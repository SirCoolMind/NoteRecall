// Updates: one shared store behind the masthead indicator and the Settings -> Updates tab.
// It reads GET /api/version, checks GET /api/update/check (quietly once a day on load),
// starts POST /api/update/apply, then follows GET /api/update/status. When the server goes
// away to restart, it polls GET /api/status until the NEW version answers, then reloads.

const POLL_MS = 1000;
const AUTO_CHECK_MS = 24 * 3600 * 1000;
const RESTART_WAIT_MS = 3 * 60 * 1000;
const CHECKED_KEY = "noterecall.update.checked";
const UPDATED_KEY = "noterecall.updated";
const RESULT_KEY = "noterecall.update.result";

// "0.10.0" -> [0, 10, 0]; null when it is not plain MAJOR.MINOR.PATCH.
function semver(text) {
  const m = /^v?(\d+)\.(\d+)\.(\d+)$/.exec(String(text || "").trim());
  return m ? m.slice(1).map(Number) : null;
}
export function isNewer(a, b) {
  const x = semver(a), y = semver(b);
  if (!x || !y) return false;
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] > y[i];
  return false;
}

function lastChecked() {
  try { return Number(localStorage.getItem(CHECKED_KEY)) || 0; } catch (e) { return 0; }
}
// The last "available" answer is kept so the quiet indicator survives reloads between daily checks.
function rememberResult(r) {
  try {
    if (r && r.available && !r.error) localStorage.setItem(RESULT_KEY, JSON.stringify(r));
    else localStorage.removeItem(RESULT_KEY);
  } catch (e) { /* storage blocked */ }
}
function storedResult() {
  try { return JSON.parse(localStorage.getItem(RESULT_KEY) || "null"); } catch (e) { return null; }
}
function rememberChecked() {
  try { localStorage.setItem(CHECKED_KEY, String(Date.now())); } catch (e) { /* storage blocked: it just checks again next load */ }
}

async function getJson(url, ms = 8000) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  try {
    const res = await fetch(url, { signal: ctl.signal, cache: "no-store" });
    if (!res.ok) throw new Error(String(res.status));
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

export function registerUpdates(Alpine) {
  Alpine.store("update", {
    version: "",            // the running version, from /api/version
    installType: "",        // git | zip-git | zip
    canUpdate: false,
    reasonCode: "",
    reason: "",
    result: null,           // the last /api/update/check answer
    phase: "idle",          // idle | checking | applying | restarting | failed | timeout
    checkFailed: false,     // the check request itself failed (the server answers errors inside result)
    applyError: "",         // why Update now was refused
    status: null,           // /api/update/status
    target: "",             // the version being installed
    justUpdated: "",        // set after the page reloads into a new version
    announcement: "",
    _timer: null,
    _since: 0,
    _probing: false,

    t(key, vars) { return Alpine.store("i18n").t(key, vars); },

    async init() {
      try {
        this.justUpdated = sessionStorage.getItem(UPDATED_KEY) || "";
        sessionStorage.removeItem(UPDATED_KEY);
      } catch (e) { /* storage blocked */ }
      window.addEventListener("settings-tab", (e) => {
        if (e.detail.tab === "updates" && this.phase === "idle") this.loadVersion();
      });
      await this.loadVersion();
      const kept = storedResult();
      if (kept && kept.available && isNewer(kept.latest, this.version)) this.result = kept;
      await this.resumeIfRunning();
      if (this.phase === "idle" && Date.now() - lastChecked() > AUTO_CHECK_MS) this.check({ quiet: true });
    },

    // ---------------------------------------------------------------- data
    async loadVersion() {
      try {
        const v = await getJson("/api/version");
        this.version = v.version;
        this.installType = v.install_type;
        this.canUpdate = !!v.can_update;
        this.reason = v.reason || "";
        this.reasonCode = v.reason_code || "";
      } catch (e) { /* the page keeps what it had */ }
    },

    // Quiet = the automatic check on load: no spinner, no error, only the masthead chip may appear.
    async check({ force = false, quiet = false } = {}) {
      if (this.phase !== "idle") return;
      if (!quiet) { this.phase = "checking"; this.checkFailed = false; this.applyError = ""; this.justUpdated = ""; }
      try {
        const r = await getJson("/api/update/check" + (force ? "?force=1" : ""), 30000);
        this.result = r;
        if (!r.error) { rememberChecked(); rememberResult(r); }
        if (!quiet) this.announcement = this.checkText;
      } catch (e) {
        if (!quiet) this.checkFailed = true;
      }
      if (!quiet) { this.phase = "idle"; await this.loadVersion(); }
    },

    async apply() {
      this.applyError = "";
      let res;
      try {
        res = await fetch("/api/update/apply", { method: "POST" });
      } catch (e) {
        this.applyError = this.t("upd.error.request");
        return;
      }
      if (!res.ok) {
        let detail = "";
        try { detail = (await res.json()).detail || ""; } catch (e) { /* no body */ }
        this.applyError = detail || this.t("upd.error.request");
        await this.loadVersion();
        return;
      }
      this.status = await res.json();
      this.target = this.status.target || this.latest;
      this.phase = "applying";
      this.announcement = this.t("upd.live.started");
      this.follow();
    },

    async resumeIfRunning() {
      try {
        const s = await getJson("/api/update/status");
        if (s.running) {
          this.status = s;
          this.target = s.target || "";
          this.phase = s.state === "restarting" ? "restarting" : "applying";
          this._since = Date.now();
          this.follow();
        }
      } catch (e) { /* nothing to resume */ }
    },

    // ---------------------------------------------------------------- following an update
    follow() {
      clearInterval(this._timer);
      this._since = this._since || Date.now();
      this._timer = setInterval(() => this.tick(), POLL_MS);
    },

    stop() { clearInterval(this._timer); this._timer = null; this._since = 0; },

    async tick() {
      if (this.phase === "restarting") return this.waitForServer();
      let s;
      try {
        s = await getJson("/api/update/status", 4000);
      } catch (e) {
        this.phase = "restarting";      // the server went away: it is restarting
        return;
      }
      if (s.state === "idle") {          // a new server process knows nothing of the run: the restart happened
        this.phase = "restarting";
        this._since = Date.now();
        return;
      }
      this.status = s;
      if (s.state === "failed") {
        this.phase = "failed";
        this.stop();
        this.announcement = this.t("upd.live.failed");
      } else if (s.state === "restarting") {
        this.phase = "restarting";
        this._since = Date.now();
        this.announcement = this.t("upd.restarting");
      }
    },

    // One probe at a time: /api/status can take a couple of seconds (it asks Ollama), so never stack them.
    async waitForServer() {
      if (this._probing) return;
      this._probing = true;
      try {
        const s = await getJson("/api/status", 10000);
        if (s.version && this.target && s.version === this.target) {
          try { sessionStorage.setItem(UPDATED_KEY, s.version); } catch (e) { /* storage blocked */ }
          this.stop();
          location.reload();
          return;
        }
      } catch (e) { /* still down */ } finally {
        this._probing = false;
      }
      if (Date.now() - this._since > RESTART_WAIT_MS) {
        this.phase = "timeout";
        this.stop();
      }
    },

    // ---------------------------------------------------------------- derived
    get available() { return !!(this.result && this.result.available && !this.result.error); },
    get latest() { return this.result ? this.result.latest || "" : ""; },
    get busy() { return this.phase !== "idle"; },
    get working() { return this.phase === "applying" || this.phase === "restarting"; },
    get offline() { return this.checkFailed || !!(this.result && this.result.error); },
    get upToDate() { return !!this.result && !this.result.error && !this.result.available; },
    get typeText() { return this.installType ? this.t("upd.type." + this.installType) : ""; },
    get reasonText() {
      if (!this.reason) return "";
      const key = "upd.reason." + this.reasonCode;
      const text = this.t(key);
      return text === key ? this.reason : text;
    },
    get checkText() {
      if (this.offline) return this.t("upd.offline");
      if (this.available) return this.t("upd.available", { version: this.latest });
      return this.upToDate ? this.t("upd.uptodate") : "";
    },
    get checkedAt() {
      const at = this.result && this.result.checked_at;
      return at ? new Date(at * 1000).toLocaleString(Alpine.store("i18n").lang, { dateStyle: "medium", timeStyle: "short" }) : "";
    },
    get steps() {
      return ((this.status && this.status.steps) || []).map((s) => ({
        id: s.id,
        state: s.state,
        message: s.state === "failed" ? s.message : "",
      }));
    },
    get failMessage() { return (this.status && this.status.message) || ""; },
    stepPill(state) {
      return { pending: "queued", running: "processing", done: "ready", failed: "failed" }[state] || "idle";
    },
  });
}
