// Setup readiness: one shared store behind the Home readiness panel and the Settings modal.
// It reads GET /api/setup (checks + install state), starts installs with POST /api/setup/install,
// and while a run is active polls GET /api/setup/install once a second.
import { checkState } from "./settings.js";

const POLL_MS = 1000;
const COPIED_MS = 2000;
const WORKING = ["pending", "running"];

export function registerSetup(Alpine) {
  Alpine.store("setup", {
    loaded: false,        // a first /api/setup answer has arrived
    error: false,         // the last refresh failed; Home never locks on a failed check
    checks: [],
    engine: "local",
    os: "linux",
    compute: "cpu",
    install: { running: false, items: {} },
    startError: false,
    announcement: "",     // polite live region: item changes, not every progress tick
    expanded: {},         // check id -> manual steps open
    copied: "",           // "<id>:<n>" of the command just copied
    _timer: null,
    _copyTimer: null,

    t(key, vars) { return Alpine.store("i18n").t(key, vars); },

    init() { this.refresh(); },

    // ---------------------------------------------------------------- data
    async refresh() {
      try {
        const res = await fetch("/api/setup");
        if (!res.ok) throw new Error(String(res.status));
        const s = await res.json();
        this.checks = s.checks;
        this.engine = s.engine;
        this.os = s.os === "windows" ? "windows" : "linux";
        this.compute = s.compute;
        this.appDir = s.app_dir || "";
        this.noteInstall(s.install);
        this.loaded = true;
        this.error = false;
        window.dispatchEvent(new CustomEvent("setup-checks", { detail: { checks: s.checks, engine: s.engine, os: s.os } }));
      } catch (e) {
        this.error = true;
      }
      this.syncPolling();
    },

    async start(ids) {
      this.startError = false;
      try {
        const res = await fetch("/api/setup/install", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(ids ? { ids } : {}),
        });
        if (!res.ok) throw new Error(String(res.status));
        this.noteInstall((await res.json()).install);
      } catch (e) {
        this.startError = true;
        this.announcement = this.t("setup.error.start");
      }
      this.syncPolling();
    },

    retry(id) { return this.start([id]); },

    syncPolling() {
      if (this.install.running && !this._timer) this._timer = setInterval(() => this.poll(), POLL_MS);
      if (!this.install.running && this._timer) { clearInterval(this._timer); this._timer = null; }
    },

    async poll() {
      let snap;
      try {
        const res = await fetch("/api/setup/install");
        if (!res.ok) return;
        snap = await res.json();
      } catch (e) { return; }   // a hiccup: the next tick tries again
      this.noteInstall(snap);
      if (!snap.running) {
        this.syncPolling();
        await this.refresh();   // the run is over: re-read the real checks
        this.announceFinish();
      }
    },

    // Store the new snapshot and announce items that just finished or failed.
    noteInstall(snap) {
      const before = this.install.items || {};
      for (const [id, it] of Object.entries(snap.items || {})) {
        const was = (before[id] || {}).state;
        if (was === it.state || was === undefined) continue;
        const name = this.nameOf(id);
        if (it.state === "done") this.announcement = this.t("setup.live.done", { name });
        if (it.state === "failed") this.announcement = this.t("setup.live.failed", { name, reason: it.message });
      }
      this.install = snap;
    },

    announceFinish() {
      this.announcement = this.missing.length
        ? this.t("setup.live.incomplete", { n: this.missing.length })
        : this.t("setup.live.finished");
    },

    // ---------------------------------------------------------------- derived
    nameOf(id) {
      const key = "set.check." + id;
      const text = this.t(key);
      return text === key ? ((this.checks.find((c) => c.id === id)) || {}).name || id : text;
    },

    get rows() {
      return this.checks.map((c) => ({
        id: c.id,
        name: this.nameOf(c.id),
        state: checkState(c, this.engine),            // ok | missing | optional | not_needed
        auto: !!c.auto,
        item: this.install.items[c.id] || null,       // { state, message, progress } from this run
        steps: ((c.fix || {})[this.os]) || [],
      }));
    },
    // Required and not satisfied. Done items stay listed until the run ends and the checks are re-read.
    get missing() { return this.rows.filter((r) => r.state === "missing"); },
    // The drawer also lists optional items, so their manual steps are one tap away.
    get attention() { return this.rows.filter((r) => r.state === "missing" || r.state === "optional"); },
    get blocked() { return this.loaded && this.missing.length > 0; },
    get ready() { return this.loaded && this.missing.length === 0; },
    get running() { return !!this.install.running; },
    // Something the installer can do that is not already queued or running.
    get canInstall() {
      return !this.running && this.missing.some((r) => r.auto && !(r.item && r.item.state === "done"));
    },
    get readyText() {
      if (this.engine === "gemini") return this.t("setup.ready.cloud");
      return this.t(this.compute === "gpu" ? "setup.ready.gpu" : "setup.ready.cpu");
    },
    get countText() {
      const n = this.missing.length;
      return this.t(n === 1 ? "setup.count.one" : "setup.count.other", { n });
    },

    // What the row shows on the right. manual = the user has to act; plain missing = nothing started yet.
    kind(r) {
      const s = r.item && r.item.state;
      if (s) return s;                                 // pending | running | done | failed
      if (r.state === "optional") return "optional";
      return r.auto ? "missing" : "manual";
    },
    progressPct(r) {
      const p = r.item && r.item.progress;
      return typeof p === "number" ? Math.round(p * 100) : null;
    },
    detailText(r) {
      const it = r.item;
      if (!it) return "";
      if (it.state === "failed") return it.message;
      if (it.state === "running") return it.message || "";
      return "";
    },
    // The command that moves a terminal into the NoteRecall folder (cd /d also switches drive on Windows).
    cdCmd() {
      if (!this.appDir) return "";
      return this.os === "windows" ? `cd /d "${this.appDir}"` : `cd "${this.appDir}"`;
    },
    stepText(r, i, step) {
      const key = `setup.fix.${this.os}.${r.id}.${i}`;
      const text = this.t(key);
      return text === key ? step.do : text;
    },

    // ---------------------------------------------------------------- manual steps
    toggle(id) { this.expanded[id] = !this.expanded[id]; },

    async copy(id, n, cmd) {
      let ok = false;
      try { await navigator.clipboard.writeText(cmd); ok = true; } catch (e) { /* fall back below */ }
      if (!ok) {
        const ta = Object.assign(document.createElement("textarea"), { value: cmd });
        ta.style.cssText = "position:fixed;opacity:0";
        document.body.append(ta);
        ta.select();
        try { ok = document.execCommand("copy"); } catch (e) { /* nothing more to try */ }
        ta.remove();
      }
      if (!ok) return;
      this.copied = `${id}:${n}`;
      clearTimeout(this._copyTimer);
      this._copyTimer = setTimeout(() => { this.copied = ""; }, COPIED_MS);
    },
  });
}
