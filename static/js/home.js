// Home screen: drop-to-upload and the live schedule. Registered from app.js as Alpine.data("home").
import { SPEAKER_CHOICES } from "./segmented.js";
import { addSample, secondsLeft, minutesLeft } from "./eta.js";
import { LOCALES, lengthParts } from "./format.js";
import { titleEditing } from "./title-edit.js";

const POLL_MS = 2000;
const PAGE_SIZE = 30;          // finished recordings shown per step
const VIEW_KEY = "noterecall.home.view";
const MARK_MS = 2600;          // how long the row you came back from stays marked
const STATUS_FILTERS = ["all", "ready", "progress", "failed"];
const EXTENSIONS = ["mp3", "wav", "m4a", "mp4", "ogg", "opus", "flac", "aac", "webm"];

export function statusKind(status) {
  if (status === "done") return "ready";
  if (status === "error") return "failed";
  if (status === "queued") return "queued";
  return "processing";
}

export function isSupported(file) {
  const ext = (file.name.split(".").pop() || "").toLowerCase();
  return EXTENSIONS.includes(ext) || (file.type || "").startsWith("audio/");
}

// Server-side order: the worker runs jobs first-in-first-out, so Next lists oldest first.
const byCreated = (a, b) => (a.created < b.created ? -1 : a.created > b.created ? 1 : 0);

function statusPasses(m, status) {
  if (status === "ready") return m.kind === "ready";
  if (status === "failed") return m.kind === "failed";
  if (status === "progress") return m.kind === "queued" || m.kind === "processing";
  return true;
}

export function matchesQuery(m, query) {
  const q = (query || "").trim().toLowerCase();
  if (!q) return true;
  return `${m.title || ""}\n${m.quick_summary || ""}`.toLowerCase().includes(q);
}

// The schedule model. On now / Next always list their jobs (the status filter may hide them, search never does);
// finished recordings are filtered by search and status, cut to `shown`, then grouped by month, newest first.
// `monthLabel(created)` names a month heading. Returns { groups, matched, total, left }.
export function buildSchedule(items, { status = "all", query = "", shown = PAGE_SIZE, monthLabel = (c) => c.slice(0, 7) } = {}) {
  const active = (kind) => items.filter((m) => m.kind === kind && statusPasses(m, status)).sort(byCreated);
  const on = active("processing");
  const next = active("queued");
  const finished = items
    .filter((m) => (m.kind === "ready" || m.kind === "failed") && statusPasses(m, status) && matchesQuery(m, query))
    .sort((a, b) => byCreated(b, a));
  const visible = finished.slice(0, shown);
  const months = [];
  for (const m of visible) {
    const key = "m-" + String(m.created).slice(0, 7);
    let g = months[months.length - 1];
    if (!g || g.key !== key) { g = { key, label: monthLabel(m.created), items: [] }; months.push(g); }
    g.items.push(m);
  }
  const groups = [
    { key: "on_now", items: on }, { key: "next", items: next }, ...months,
  ].filter((g) => g.items.length);
  return {
    groups,
    matched: on.length + next.length + finished.length,
    total: items.length,
    left: Math.max(0, finished.length - visible.length),
  };
}

function sendUpload(file, fields, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/meetings");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)); } catch (e) { resolve({}); }
        return;
      }
      let reason = "";
      try { reason = JSON.parse(xhr.responseText).detail || ""; } catch (e) { /* not JSON */ }
      reject(new Error(typeof reason === "string" ? reason : ""));
    };
    xhr.onerror = () => reject(Object.assign(new Error(""), { network: true }));
    const body = new FormData();
    body.append("file", file);
    body.append("language", fields.language);
    body.append("num_speakers", fields.speakers);
    xhr.send(body);
  });
}

export function registerHome(Alpine) {
  Alpine.data("home", () => ({
    ...titleEditing(),

    // upload options. Defaults come from Settings via /api/config, and follow it live.
    language: "",
    speakers: "0",
    speakerChoices: SPEAKER_CHOICES,
    accept: "audio/*,video/mp4,.m4a," + EXTENSIONS.map((e) => "." + e).join(","),

    dragging: false,
    pending: [],        // files waiting to upload, in order
    uploading: null,    // { name, percent } while a file is on its way
    uploadNote: null,   // { kind: "ok" | "error", text } shown inside the slot

    // schedule toolbar (restored per tab from sessionStorage)
    query: "",
    status: "all",
    shown: PAGE_SIZE,
    markedId: null,     // the row you just came back from

    items: [],
    loaded: false,
    offline: false,
    announcement: "",

    _timer: null,
    _samples: {},       // id -> eta samples
    _lastKind: {},      // id -> last seen status kind, for announcements
    _scrollY: 0,        // last scroll position seen while Home was showing
    _pending: null,     // { scrollY, lastId } waiting to be restored when Home is back on screen
    _markTimer: null,

    t(key, vars) { return Alpine.store("i18n").t(key, vars); },

    // Until the readiness checks pass the slot is off: nothing can be transcribed yet.
    get locked() { return Alpine.store("setup").blocked; },

    init() {
      this.loadView();
      this.loadDefaults();
      this.refresh();
      window.addEventListener("scroll", () => {
        if (!Alpine.store("route").id) this._scrollY = window.scrollY;
      }, { passive: true });
      this.$watch("$store.route.id", (id) => {
        if (id) { this.leave(id); return; }
        // Coming back from a meeting: titles or statuses may have changed meanwhile.
        this.refresh();
        this.comeBack();
      });
      this.$watch("query", () => { this.shown = PAGE_SIZE; this.saveView(); });
    },

    // ---------------------------------------------------------------- remembered view (per tab)
    loadView() {
      try {
        const v = JSON.parse(sessionStorage.getItem(VIEW_KEY) || "null");
        if (!v) return;
        this.query = typeof v.query === "string" ? v.query : "";
        this.status = STATUS_FILTERS.includes(v.status) ? v.status : "all";
        this.shown = Number.isFinite(v.shown) && v.shown >= PAGE_SIZE ? Math.floor(v.shown) : PAGE_SIZE;
        if (v.lastId) this._pending = { scrollY: Number(v.scrollY) || 0, lastId: String(v.lastId) };
      } catch (e) { /* storage blocked or malformed: start fresh */ }
    },
    saveView() {
      try {
        const v = { query: this.query, status: this.status, shown: this.shown };
        if (this._pending) Object.assign(v, this._pending);
        sessionStorage.setItem(VIEW_KEY, JSON.stringify(v));
      } catch (e) { /* storage blocked: the view just is not remembered */ }
    },
    // A meeting opens: remember where Home was and which row it was.
    leave(id) {
      this._pending = { scrollY: this._scrollY, lastId: id };
      this.saveView();
    },
    // Home is showing again: same scroll, same filters, and the row you left is marked and focused.
    async comeBack() {
      const p = this._pending;
      if (!p || !this.loaded) return;
      this._pending = null;
      this.saveView();
      // The row must be on screen: open more of the list if it lies beyond what is shown.
      const at = this.finishedIds.indexOf(p.lastId);
      if (at >= this.shown) this.shown = Math.ceil((at + 1) / PAGE_SIZE) * PAGE_SIZE;
      await this.$nextTick();
      requestAnimationFrame(() => {
        window.scrollTo(0, p.scrollY);
        const row = document.querySelector(`[data-row-id="${CSS.escape(p.lastId)}"]`);
        if (!row) return;
        this.markedId = p.lastId;
        clearTimeout(this._markTimer);
        this._markTimer = setTimeout(() => { this.markedId = null; }, MARK_MS);
        (row.querySelector(".row__open") || row.querySelector("button, a"))?.focus({ preventScroll: true });
      });
    },

    async loadDefaults() {
      try {
        const res = await fetch("/api/config");
        if (!res.ok) return;
        const cfg = await res.json();
        this.applyDefaults({ language: cfg.default_language, speakers: cfg.default_speakers });
      } catch (e) { /* keep Auto */ }
    },

    // From Settings, live: also called when a default changes in the settings modal.
    applyDefaults({ language, speakers }) {
      this.language = ["ms", "en"].includes(language) ? language : "";
      const n = Number(speakers);
      this.speakers = this.speakerChoices.includes(n) ? String(n) : "0";
    },

    // ---------------------------------------------------------------- upload
    openPicker() { this.$refs.picker.click(); },
    onSlotClick(e) {
      if (this.locked) return;
      if (e.target.closest("button, select, label, input, a, .opt")) return;
      this.openPicker();
    },
    onPick(e) {
      this.acceptFiles([...e.target.files]);
      e.target.value = "";
    },
    onDragLeave(e) {
      if (!e.currentTarget.contains(e.relatedTarget)) this.dragging = false;
    },
    onDrop(e) {
      this.dragging = false;
      this.acceptFiles([...(e.dataTransfer?.files || [])]);
    },

    acceptFiles(files) {
      if (this.locked) { this.dragging = false; return; }
      const good = files.filter(isSupported);
      const bad = files.filter((f) => !isSupported(f));
      if (bad.length) {
        this.uploadNote = {
          kind: "error",
          text: this.t("home.upload.rejected", { name: bad[0].name, types: this.t("home.upload.types") }),
        };
        this.announcement = this.uploadNote.text;
      } else if (good.length) {
        this.uploadNote = null;
      }
      if (!good.length) return;
      this.pending.push(...good);
      if (!this.uploading) this.drain();
    },

    async drain() {
      while (this.pending.length) {
        const file = this.pending.shift();
        this.uploading = { name: file.name, percent: 0 };
        this.announcement = this.t("home.upload.uploading", { name: file.name });
        try {
          await sendUpload(file, { language: this.language, speakers: this.speakers },
            (fraction) => { this.uploading.percent = Math.round(fraction * 100); });
          this.uploadNote = { kind: "ok", text: this.t("home.upload.done", { name: file.name }) };
          this.announcement = this.uploadNote.text;
          await this.refresh();
        } catch (err) {
          const reason = err.network || !err.message ? this.t("home.upload.network") : err.message;
          this.uploadNote = { kind: "error", text: this.t("home.upload.failed", { name: file.name, reason }) };
          this.announcement = this.uploadNote.text;
        }
      }
      this.uploading = null;
    },

    // ---------------------------------------------------------------- schedule
    get schedule() {
      return buildSchedule(this.items, {
        status: this.status, query: this.query, shown: this.shown,
        monthLabel: (created) => new Date(created).toLocaleDateString(this.locale(), { month: "long", year: "numeric" }),
      });
    },
    get groups() { return this.schedule.groups; },
    get finishedIds() {
      return this.items.filter((m) => m.kind === "ready" || m.kind === "failed").sort((a, b) => byCreated(b, a)).map((m) => m.id);
    },
    get filtering() { return !!this.query.trim() || this.status !== "all"; },
    get countText() {
      const { matched, total } = this.schedule;
      return this.filtering ? this.t("schedule.count.some", { n: matched, total }) : this.t("schedule.count.all", { n: total });
    },
    get statusOptions() {
      return STATUS_FILTERS.map((v) => ({ value: v, label: this.t("schedule.filter." + v) }));
    },
    groupTitle(g) { return g.label || this.t("schedule." + g.key); },
    setStatus(v) {
      this.status = STATUS_FILTERS.includes(v) ? v : "all";
      this.shown = PAGE_SIZE;
      this.saveView();
    },
    clearFilters() { this.query = ""; this.setStatus("all"); },
    showMore() { this.shown += PAGE_SIZE; this.saveView(); },

    async refresh() {
      clearTimeout(this._timer);
      try {
        const res = await fetch("/api/meetings");
        if (!res.ok) throw new Error(String(res.status));
        this.apply(await res.json());
        this.offline = false;
        const first = !this.loaded;
        this.loaded = true;
        if (first && !Alpine.store("route").id) this.comeBack();
      } catch (e) {
        this.offline = true;   // transient: keep what we have and retry
      }
      if (this.offline || this.items.some((m) => m.kind === "queued" || m.kind === "processing")) {
        this._timer = setTimeout(() => this.refresh(), POLL_MS);
      }
    },

    apply(list) {
      const now = Date.now();
      const seen = new Set();
      const next = list.map((m) => {
        const kind = statusKind(m.status);
        seen.add(m.id);
        let etaSec = null;
        if (kind === "processing") {
          this._samples[m.id] = addSample(this._samples[m.id] || [], now, m.status, m.progress || 0);
          etaSec = secondsLeft(this._samples[m.id], now);
        } else {
          delete this._samples[m.id];
        }
        this.noteChange(m, kind);
        return { ...m, kind, progress: m.progress || 0, etaSec };
      });
      for (const id of Object.keys(this._samples)) if (!seen.has(id)) delete this._samples[id];
      this.items = next;
    },

    // Announce status changes (not every progress tick) for screen readers.
    noteChange(m, kind) {
      const before = this._lastKind[m.id];
      this._lastKind[m.id] = kind;
      if (before === undefined || before === kind) return;
      const key = { queued: "live.queued", processing: "live.processing", ready: "live.ready", failed: "live.failed" }[kind];
      this.announcement = this.t(key, { title: m.title });
    },

    // ---------------------------------------------------------------- row display
    locale() { return LOCALES[Alpine.store("i18n").lang] || "en-GB"; },

    // Big slot: how long the recording is, or a muted placeholder until it is known.
    slotParts(m) { return (lengthParts(m.duration) || []).map(([n, u]) => ({ n, u: this.t("dur.unit." + u) })); },
    hasLength(m) { return !!lengthParts(m.duration); },
    // Meta line: "17 Sep 2026 · 17:31".
    startStamp(m) {
      const d = new Date(m.created);
      const date = d.toLocaleDateString(this.locale(), { day: "numeric", month: "short", year: "numeric" });
      const time = d.toLocaleTimeString(this.locale(), { hour: "2-digit", minute: "2-digit", hour12: false });
      return `${date} · ${time}`;
    },
    summaryText(m) { return (m.quick_summary || "").trim(); },
    stageName(m) {
      const key = `stage.${m.status}`;
      const text = this.t(key);
      return text === key ? this.t("stage.unknown") : text;
    },
    etaText(m) {
      const mins = minutesLeft(m.etaSec);
      if (mins === null) return this.t("eta.estimating");
      return mins === 0 ? this.t("eta.lt1") : this.t("eta.min", { n: mins });
    },
    errorText(m) { return m.error || this.t("row.error_unknown"); },

    openMeeting(m) { location.hash = `#/m/${m.id}`; },
    onRowClick(m, e) {
      if (m.kind !== "ready" || e.target.closest("button, input, a")) return;
      this.openMeeting(m);
    },

    // ---------------------------------------------------------------- title edit (see title-edit.js)
    applyTitle(id, title) {
      const row = this.items.find((x) => x.id === id);
      if (row) row.title = title;
    },
    titleSaved() { this.refresh(); },

    async retry(m) {
      try {
        const res = await fetch(`/api/meetings/${m.id}/retranscribe`, { method: "POST" });
        if (!res.ok) throw new Error(String(res.status));
      } catch (e) { /* the row stays failed; the user can press Retry again */ }
      this.refresh();
    },
  }));
}
