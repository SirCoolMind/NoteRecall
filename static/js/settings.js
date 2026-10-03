// Settings modal contents (one panel per tab). Registered from app.js as Alpine.data("settings").
// Every field autosaves through POST /api/config: choices save at once, text fields after a pause.
// Each section shows its own Saving / Saved / Not saved state; there is no Save button.

import { SPEAKER_CHOICES } from "./segmented.js";

const SECTIONS = ["engine", "device", "defaults", "speakers", "interface"];
const SAVED_VISIBLE_MS = 2500;
const TEXT_DEBOUNCE_MS = 700;
const WHISPER_MODELS = ["large-v3", "medium"];

export function checkState(check, engine) {
  if (check.ok) return "ok";
  const needed = check.req === "always" || check.req === engine;
  if (needed) return "missing";
  return check.req === "optional" ? "optional" : "not_needed";
}

export function registerSettings(Alpine) {
  Alpine.data("settings", () => ({
    loaded: false,
    loadFailed: false,

    // values (mirrors /api/config)
    engine: "local",
    device: "auto",
    whisperModel: "large-v3",
    geminiModel: "",
    defaultLanguage: "",
    defaultSpeakers: "0",
    speakerChoices: SPEAKER_CHOICES,
    hasKey: false,
    keyTail: "",
    keyDraft: "",
    keyTest: null,          // { state: "testing" | "ok" | "bad" | "info", detail }

    // per-section save state: idle | saving | saved | error
    sec: Object.fromEntries(SECTIONS.map((s) => [s, { state: "idle", inflight: 0, failed: {}, timer: null }])),

    // status from /api/status and /api/setup
    runtime: null,          // device string reported by the server
    checks: null,
    checksState: "idle",    // idle | loading | error

    _chain: Promise.resolve(),
    _statusTimer: null,

    t(key, vars) { return Alpine.store("i18n").t(key, vars); },

    async init() {
      window.addEventListener("setup-checks", (e) => {
        this.checks = e.detail.checks;
        this.checksState = "idle";
      });
      await this.loadConfig();
      this.refreshStatus();
    },

    // ---------------------------------------------------------------- load
    async loadConfig() {
      try {
        const res = await fetch("/api/config");
        if (!res.ok) throw new Error(String(res.status));
        this.applyConfig(await res.json());
        this.loaded = true;
        this.loadFailed = false;
      } catch (e) {
        this.loadFailed = true;
      }
    },

    applyConfig(cfg) {
      this.engine = cfg.engine === "gemini" ? "gemini" : "local";
      this.device = cfg.device === "cpu" ? "cpu" : "auto";
      this.whisperModel = cfg.whisper_model || "large-v3";
      this.geminiModel = cfg.gemini_model || "";
      this.defaultLanguage = ["ms", "en"].includes(cfg.default_language) ? cfg.default_language : "";
      const n = Number(cfg.default_speakers);
      this.defaultSpeakers = this.speakerChoices.includes(n) ? String(n) : "0";
      this.noteKey(cfg);
    },

    noteKey(cfg) {
      this.hasKey = !!cfg.has_key;
      const masked = cfg.gemini_api_key_masked || "";
      this.keyTail = masked.startsWith("…") ? masked : "";
    },

    // The modal just opened: read the live status again.
    onOpen() { return this.refreshStatus(); },

    // ---------------------------------------------------------------- status and checks
    refreshStatus() {
      clearTimeout(this._statusTimer);
      this.checksState = this.checks ? this.checksState : "loading";
      return Promise.all([
        fetch("/api/status").then((r) => (r.ok ? r.json() : Promise.reject(r))).then((s) => { this.runtime = s.device || ""; }).catch(() => {}),
        // The shared setup store owns /api/setup; it announces fresh checks with a "setup-checks" event.
        Alpine.store("setup").refresh().then(() => {
          if (Alpine.store("setup").error && !this.checks) this.checksState = "error";
        }),
      ]);
    },
    refreshSoon() {
      clearTimeout(this._statusTimer);
      this._statusTimer = setTimeout(() => this.refreshStatus(), 400);
    },

    get checkRows() {
      return (this.checks || []).map((c) => ({ id: c.id, state: checkState(c, this.engine) }));
    },
    get missingCount() { return this.checkRows.filter((r) => r.state === "missing").length; },
    checkName(id) {
      const key = "set.check." + id;
      const text = this.t(key);
      return text === key ? ((this.checks || []).find((c) => c.id === id) || {}).name || id : text;
    },
    checkIcon(state) { return state === "ok" ? "check" : state === "missing" ? "alert-triangle" : "minus"; },

    get runtimeText() {
      const d = this.runtime;
      if (d === null) return this.t("set.status.unknown");
      if (d.startsWith("cuda")) return this.t("set.status.gpu");
      if (d.startsWith("cpu")) return this.t("set.status.cpu");
      return this.t("set.status.idle");
    },
    // Which summary writer runs now: a local Ollama model when one is found, else the built-in extractive one.
    get summaryProvider() {
      const c = (this.checks || []).find((x) => x.id === "ollama");
      return c && c.ok ? "ollama" : "builtin";
    },
    get modelCheck() { return (this.checks || []).find((c) => c.id === "whisper_model"); },
    get modelText() {
      const c = this.modelCheck;
      if (!c) return this.t("set.status.unknown");
      return c.ok ? this.t("set.status.model_ok") : this.t("set.status.model_missing");
    },

    // ---------------------------------------------------------------- saving
    send(section, patch) {
      const s = this.sec[section];
      clearTimeout(s.timer);
      s.inflight++;
      s.state = "saving";
      const job = this._chain.then(async () => {
        try {
          const res = await fetch("/api/config", {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch),
          });
          if (!res.ok) throw new Error(String(res.status));
          const cfg = await res.json();
          this.noteKey(cfg);
          for (const k of Object.keys(patch)) delete s.failed[k];
          return true;
        } catch (e) {
          Object.assign(s.failed, patch);
          return false;
        } finally {
          s.inflight--;
          if (s.inflight === 0) this.settle(section);
        }
      });
      this._chain = job.catch(() => {});
      return job;
    },

    settle(section) {
      const s = this.sec[section];
      if (Object.keys(s.failed).length) { s.state = "error"; return; }
      s.state = "saved";
      s.timer = setTimeout(() => { if (s.state === "saved") s.state = "idle"; }, SAVED_VISIBLE_MS);
    },

    // Section changes that are not server round-trips (interface prefs live in this browser).
    flash(section) {
      const s = this.sec[section];
      clearTimeout(s.timer);
      s.state = "saved";
      s.timer = setTimeout(() => { if (s.state === "saved") s.state = "idle"; }, SAVED_VISIBLE_MS);
    },

    retry(section) { this.send(section, { ...this.sec[section].failed }).then(() => this.refreshSoon()); },

    stateText(section) {
      const key = { saving: "set.saving", saved: "set.saved", error: "set.error" }[this.sec[section].state];
      return key ? this.t(key) : "";
    },
    stateIcon(section) {
      const state = this.sec[section].state;
      return state === "saved" ? "check" : state === "error" ? "alert-triangle" : state === "saving" ? "loader" : "check";
    },

    // ---------------------------------------------------------------- engine and key
    setEngine(value) {
      this.engine = value;
      this.send("engine", { engine: value }).then(() => this.refreshSoon());
    },
    saveModel() {
      const model = this.geminiModel.trim();
      if (model) this.send("engine", { gemini_model: model });
    },
    async saveKey() {
      const key = this.keyDraft.trim();
      if (!key) return;
      const ok = await this.send("engine", { gemini_api_key: key });
      if (ok && this.keyDraft.trim() === key) this.keyDraft = "";   // never keep the key on screen
      if (ok) { this.keyTest = null; this.refreshSoon(); }
    },
    async testKey() {
      const typed = this.keyDraft.trim();
      if (!typed && !this.hasKey) { this.keyTest = { state: "info", detail: "" }; return; }
      this.keyTest = { state: "testing", detail: "" };
      try {
        const res = await fetch("/api/config/test-gemini", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(typed ? { gemini_api_key: typed } : {}),
        });
        const out = await res.json();
        this.keyTest = { state: out.ok ? "ok" : "bad", detail: out.ok ? "" : String(out.message || "") };
      } catch (e) {
        this.keyTest = { state: "net", detail: "" };
      }
    },
    get keyTestText() {
      const r = this.keyTest;
      if (!r) return "";
      return this.t({ testing: "set.key.testing", ok: "set.key.ok", bad: "set.key.bad", info: "set.key.nokey", net: "set.key.net" }[r.state]);
    },
    get keyTestIcon() {
      const r = this.keyTest;
      return r && r.state === "ok" ? "check" : r && r.state === "testing" ? "loader" : "alert-triangle";
    },

    // ---------------------------------------------------------------- device and model
    setDevice(value) {
      this.device = value;
      this.send("device", { device: value }).then(() => this.refreshSoon());
    },
    setWhisper(value) {
      this.whisperModel = value;
      this.send("device", { whisper_model: value }).then(() => this.refreshSoon());
    },
    get whisperChoices() {
      return WHISPER_MODELS.includes(this.whisperModel) ? WHISPER_MODELS : [...WHISPER_MODELS, this.whisperModel];
    },
    whisperLabel(name) {
      return WHISPER_MODELS.includes(name) ? this.t("set.whisper." + name) : this.t("set.whisper.other", { name });
    },

    // ---------------------------------------------------------------- defaults for new recordings
    setDefaults(section, patch) {
      if ("default_language" in patch) this.defaultLanguage = patch.default_language;
      if ("default_speakers" in patch) this.defaultSpeakers = String(patch.default_speakers);
      // Feed the Home drop slot right away, whether or not the save succeeds.
      window.dispatchEvent(new CustomEvent("settings-defaults", {
        detail: { language: this.defaultLanguage, speakers: this.defaultSpeakers },
      }));
      this.send(section, patch);
    },

    // ---------------------------------------------------------------- interface (kept in this browser)
    setLang(lang) { Alpine.store("i18n").set(lang); this.flash("interface"); },
    setTheme(mode) { Alpine.store("theme").set(mode); this.flash("interface"); },
  }));
}
