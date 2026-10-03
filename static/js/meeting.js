// Meeting view: the speaker ribbon (which is the audio player), the Download plate and the
// transcript. Registered from app.js as Alpine.data("meeting").
import { statusKind } from "./home.js";
import { LOCALES, durationLabel } from "./format.js";
import { titleEditing } from "./title-edit.js";
import { createPlayer } from "./player.js";
import { FORMATS, loadFormat, saveFormat } from "./download.js";
import {
  buildSlots, buildLanes, buildTicks, laneSizing, nextTurnOf, segmentAt, slotAt, stepSlot, formatTime, clamp,
  rankSpeakers, speakerColors, isImplausibleSpeakerCount, sharePercent, OTHERS, NEUTRAL,
} from "./ribbon.js";
import { SPEAKER_CHOICES } from "./segmented.js";
import { findMatches, lineOfMatch } from "./search.js";
import { parseSummary, withTalkBlocks, speakerIndexByName } from "./summary.js";

const POLL_MS = 2000;
const FOLLOW_PAUSE_MS = 4000;   // after the user scrolls, playback stops pulling the transcript for this long
const SEEK_STEP = 5;
const SEEK_JUMP = 30;
const LANE_ROOM = 36;   // px of the track given to the speaker lanes; the time marks sit below
const SCROLL_KEYS = ["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "];

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function registerMeeting(Alpine) {
  Alpine.data("meeting", () => {
    // Not reactive on purpose: the player and timers must not be wrapped in proxies.
    let player = null;
    let pollTimer = 0;
    let followUntil = 0;
    let ticket = 0;      // invalidates responses that arrive after the route changed
    let plotObserver = null;   // keeps the lanes and time marks in step with the track width
    let rootEl = null;   // the component element; $root is only valid inside the synchronous handler

    return {
      ...titleEditing(),

      id: null,
      state: "idle",   // idle | loading | missing | offline | waiting | ready
      meta: null,
      kind: "",        // queued | processing | ready | failed
      segments: [],
      ranking: [],     // speakers by talk time: [{ speaker, seconds, share, rank }]
      colors: new Map(),   // speaker -> colour, assigned by rank
      slots: [],       // speaker turns (runs), for Alt+arrow jumps and the slider text
      lanes: [],       // EPG lanes: one per speaker, same-speaker blocks merged to the track width
      ticks: [],
      laneSize: { height: 10, gap: 2, used: 0 },
      total: 0,        // seconds, the ribbon's full width
      now: 0,          // whole seconds played, for the clock and slider value
      activeIdx: -1,   // transcript line being spoken
      playing: false,
      audioError: false,
      format: loadFormat(),
      menuOpen: false,

      tab: "transcript",       // transcript | summary
      summary: "",
      summaryBlocks: [],
      summaryBusy: false,
      actionsOpen: false,
      actionError: "",
      busy: false,             // a menu action is on its way to the server
      redoCount: "0",
      speakerChoices: SPEAKER_CHOICES,

      speakersOpen: false,     // the Speakers popover in the ribbon
      speakerFilter: "",
      popRename: null,         // speaker being renamed inside the popover
      popDraft: "",

      renamingLine: -1,        // transcript line whose speaker name is being edited
      nameDraft: "",

      query: "",
      matchTotal: 0,
      matchLines: {},          // line index -> [{ text, n }] parts, only for lines that hold a match
      current: -1,             // match being shown

      t(key, vars) { return Alpine.store("i18n").t(key, vars); },
      fmt: formatTime,
      formats: FORMATS,

      init() {
        rootEl = this.$root;
        this.$watch("$store.route.id", (id) => this.open(id));
        this.$watch("query", () => this.runSearch());
        this.open(Alpine.store("route").id);
      },

      // ------------------------------------------------------------ loading
      open(id) {
        this.teardown();
        this.id = id;
        if (!id) { this.state = "idle"; return; }
        this.state = "loading";
        window.scrollTo(0, 0);
        this.load();
      },

      teardown() {
        ticket++;
        if (plotObserver) { plotObserver.disconnect(); plotObserver = null; }
        clearTimeout(pollTimer);
        if (player) { player.destroy(); player = null; }
        this.meta = null; this.kind = ""; this.segments = []; this.slots = []; this.lanes = []; this.ticks = []; this._plotW = 0;
        this.ranking = []; this.colors = new Map(); this.speakersOpen = false; this.speakerFilter = ""; this.popRename = null;
        this.total = 0; this.now = 0; this.activeIdx = -1;
        this.playing = false; this.audioError = false; this.menuOpen = false; this.editing = null;
        this.resetReview();
        this.summary = ""; this.summaryBlocks = []; this.summaryBusy = false; this.actionError = ""; this.busy = false;
      },

      // Back to a clean transcript view: no search, no rename, no open menu.
      resetReview() {
        this.tab = "transcript"; this.actionsOpen = false; this.renamingLine = -1;
        this.query = ""; this.matchTotal = 0; this.matchLines = {}; this.current = -1;
      },

      async load() {
        const mine = ticket;
        const again = () => { if (mine === ticket) pollTimer = setTimeout(() => this.load(), POLL_MS); };
        let res;
        try {
          res = await fetch(`/api/meetings/${this.id}`);
        } catch (e) {
          if (mine === ticket && !this.meta) this.state = "offline";
          return again();
        }
        if (mine !== ticket) return;
        if (res.status === 404) { this.state = "missing"; return; }
        if (!res.ok) { if (!this.meta) this.state = "offline"; return again(); }
        const body = await res.json();
        if (mine !== ticket) return;

        // Keep a title the user is editing or just saved; everything else comes from the server.
        const wasReady = this.state === "ready";
        this.meta = body.meta;
        this.kind = statusKind(body.meta.status);
        if (this.kind !== "ready") {
          this.state = "waiting";
          return again();
        }
        if (wasReady) return;
        this.segments = body.segments || [];
        this.ranking = rankSpeakers(this.segments);
        this.colors = speakerColors(this.ranking);
        this.setSummary(body.summary);
        this.total = this.recordingLength(body.meta.duration);
        this.slots = buildSlots(this.segments, this.total);
        this.state = "ready";
        this.$nextTick(() => this.mountPlayer());
      },

      recordingLength(fromAudio) {
        const lastEnd = this.segments.reduce((m, s) => Math.max(m, s.end || 0), 0);
        return Math.max(fromAudio || 0, lastEnd);
      },

      retry() { return this.reprocess(`/api/meetings/${this.id}/retranscribe`); },

      // ------------------------------------------------------------ title
      applyTitle(id, title) { if (this.meta && this.meta.id === id) this.meta.title = title; },
      titleSaved() {},

      // ------------------------------------------------------------ player
      mountPlayer() {
        const audio = this.$refs.audio;
        const playhead = this.$refs.playhead;
        if (!audio || !playhead) return;
        audio.addEventListener("loadedmetadata", () => {
          if (Number.isFinite(audio.duration) && audio.duration > 0) {
            this.total = Math.max(audio.duration, this.recordingLength(0));
            this.slots = buildSlots(this.segments, this.total);
            this._plotW = 0;   // the length changed, so the lanes must be rebuilt at the same width
            this.layoutRibbon();
            player?.place();
          }
        });
        audio.addEventListener("error", () => { this.audioError = true; });
        player = createPlayer({
          audio, playhead,
          total: () => this.total,
          onTick: (t) => this.tick(t),
          onState: (playing) => { this.playing = playing; },
        });
        audio.src = `/api/meetings/${this.id}/audio`;
        player.place();
        this.layoutRibbon();
        const plot = this.$refs.plot;
        if (plot && typeof ResizeObserver === "function") {
          plotObserver = new ResizeObserver(() => this.layoutRibbon());
          plotObserver.observe(plot);
        }
      },

      // Lanes merge blocks closer than ~2 track pixels, so they depend on the rendered width.
      layoutRibbon() {
        const width = this.$refs.plot?.getBoundingClientRect().width || 0;
        if (!width || width === this._plotW && this.lanes.length) return;
        this._plotW = width;
        this.lanes = buildLanes(this.segments, this.total, width, this.ranking);
        this.ticks = buildTicks(this.total, width);
        this.laneSize = laneSizing(this.lanes.length, LANE_ROOM);
      },

      tick(t) {
        const whole = Math.floor(t);
        if (whole !== this.now) this.now = whole;
        const idx = segmentAt(this.segments, t);
        if (idx === this.activeIdx) return;
        this.activeIdx = idx;
        if (this.playing && performance.now() >= followUntil) this.bringIntoView(idx);
      },

      toggle() { player?.toggle(); },

      // Seek from anywhere (ribbon, slot, line, key). `reveal` scrolls the transcript to that moment.
      seekTo(t, reveal) {
        if (!player) return;
        followUntil = 0;
        player.seek(t);
        this.tick(t);
        if (reveal) this.bringIntoView(this.activeIdx);
      },

      // ------------------------------------------------------------ ribbon input
      onTrackClick(e) {
        const rect = this.$refs.plot.getBoundingClientRect();
        if (!rect.width) return;
        this.seekTo(clamp((e.clientX - rect.left) / rect.width, 0, 1) * this.total, true);
        this.$refs.track.focus({ preventScroll: true });
      },

      onTrackKey(e) {
        const key = e.key;
        const now = player ? player.time : 0;
        let target = null;
        if (e.altKey && (key === "ArrowLeft" || key === "ArrowRight")) {
          target = stepSlot(this.slots, now, key === "ArrowRight" ? 1 : -1);
          if (target === null) { e.preventDefault(); return; }
        } else if (key === "ArrowLeft" || key === "ArrowDown") target = now - SEEK_STEP;
        else if (key === "ArrowRight" || key === "ArrowUp") target = now + SEEK_STEP;
        else if (key === "PageDown") target = now - SEEK_JUMP;
        else if (key === "PageUp") target = now + SEEK_JUMP;
        else if (key === "Home") target = 0;
        else if (key === "End") target = this.total;
        else if (key === " " || key === "Enter") { e.preventDefault(); this.toggle(); return; }
        else return;
        e.preventDefault();
        this.seekTo(target, true);
      },

      get valueText() {
        const slot = slotAt(this.slots, this.now);
        return this.t("ribbon.valuetext", {
          now: formatTime(this.now), total: formatTime(this.total),
          speaker: slot ? this.speakerName(slot.speaker) : this.t("meeting.speaker_unknown"),
        });
      },

      laneStyle(n) {
        const { height, gap, used } = this.laneSize;
        return { top: Math.round((LANE_ROOM - used) / 2) + n * (height + gap) + "px", height: height + "px" };
      },
      blockStyle(l, b) {
        return { left: b.left + "%", width: b.width + "%", background: this.laneColor(l) };
      },
      // Colour of a speaker by talk-time rank; the same lookup feeds ribbon, transcript, list and summary.
      speakerColor(spk) { return this.colors.get(spk) || NEUTRAL; },
      laneColor(l) {
        return l.speaker === OTHERS ? "color-mix(in srgb, var(--ink-2) 55%, transparent)" : this.speakerColor(l.speaker);
      },
      laneTitle(l) {
        return l.speaker === OTHERS ? this.t("ribbon.others", { n: l.others }) : this.speakerName(l.speaker);
      },
      // Jump to that speaker's next turn after the current time, or their first when they do not speak again.
      jumpToSpeaker(spk) {
        const now = player ? player.time : 0;
        const t = nextTurnOf(this.slots, spk, now) ?? nextTurnOf(this.slots, spk, -1);
        if (t !== null) this.seekTo(t, true);
      },

      // ------------------------------------------------------------ speakers popover
      get speakerCount() { return this.ranking.filter((r) => r.speaker >= 0).length || this.ranking.length; },
      get showSpeakerFilter() { return this.ranking.length > 10; },
      // Rows for the popover: every speaker by talk time, narrowed by the filter.
      get speakerRows() {
        const q = this.speakerFilter.trim().toLocaleLowerCase();
        return this.ranking
          .map((r) => ({ ...r, name: this.speakerName(r.speaker), color: this.speakerColor(r.speaker),
                         meta: `${formatTime(r.seconds)} \u00b7 ${sharePercent(r.share)}` }))
          .filter((r) => !q || r.name.toLocaleLowerCase().includes(q));
      },
      toggleSpeakers() {
        if (this.speakersOpen) return this.closeSpeakers(true);
        this.speakersOpen = true;
        this.speakerFilter = "";
        this.$nextTick(() => {
          const pop = this.$refs.speakersPop;
          (pop?.querySelector(".spk__filter") || pop?.querySelector(".spk__jump"))?.focus({ preventScroll: true });
          // Make room: scroll the page until the whole popover is on screen (the ribbon sticks, so it always fits).
          const over = pop.getBoundingClientRect().bottom - (window.innerHeight - 16);
          if (over > 0) window.scrollBy({ top: over, behavior: "auto" });
        });
      },
      closeSpeakers(refocus) {
        if (!this.speakersOpen) return;
        this.speakersOpen = false;
        this.popRename = null;
        if (refocus) this.$refs.speakersBtn?.focus();
      },
      // Focus leaving the popover (Tab away) closes it, unless it went to the button that toggles it.
      onSpeakersFocusOut(e) {
        const to = e.relatedTarget;
        if (!this.speakersOpen || !to) return;
        if (this.$refs.speakersPop.contains(to) || this.$refs.speakersBtn.contains(to)) return;
        this.closeSpeakers(false);
      },
      pickSpeaker(spk) {
        this.closeSpeakers(false);
        this.jumpToSpeaker(spk);
        this.$refs.track?.focus({ preventScroll: true });
      },
      startPopRename(spk) {
        this.popDraft = this.speakerName(spk);
        this.popRename = spk;
        this.$nextTick(() => this.$refs.speakersPop.querySelector(".spk__input")?.focus());
      },
      cancelPopRename(spk) {
        this.popRename = null;
        this.$nextTick(() => this.$refs.speakersPop.querySelector(`[data-rename-spk="${spk}"]`)?.focus());
      },
      commitPopRename(spk, viaKey = false) {
        if (this.popRename !== spk) return;
        this.popRename = null;
        if (viaKey) this.$nextTick(() => this.$refs.speakersPop.querySelector(`[data-rename-spk="${spk}"]`)?.focus());
        return this.saveSpeakerName(spk, this.popDraft);
      },

      // ------------------------------------------------------------ diarization sanity
      get suspectSpeakers() {
        return this.state === "ready" && isImplausibleSpeakerCount(this.speakerCount, this.total);
      },

      slotTitle(s) {
        return this.t("ribbon.slot_title", { speaker: this.speakerName(s.speaker), from: formatTime(s.start), to: formatTime(s.end) });
      },

      // ------------------------------------------------------------ transcript
      speakerName(spk) {
        if (spk < 0) return this.t("meeting.speaker_unknown");
        return this.meta?.speaker_names?.[spk] || this.t("meeting.speaker_n", { n: spk + 1 });
      },
      startsRun(i) { return i === 0 || this.segments[i].speaker !== this.segments[i - 1].speaker; },

      onLineClick(i) {
        if (String(window.getSelection())) return;   // the user is selecting text to copy, not seeking
        this.seekTo(this.segments[i].start, false);
      },

      // Scroll the transcript so line `idx` is comfortably visible under the sticky bars.
      bringIntoView(idx) {
        const el = rootEl.querySelector(`[data-line="${idx}"]`);
        const ribbon = this.$refs.ribbon;
        if (!el || !ribbon || this.tab !== "transcript") return;
        const rect = el.getBoundingClientRect();
        const top = ribbon.getBoundingClientRect().bottom + 24;
        const bottom = window.innerHeight - 24;
        if (rect.top >= top && rect.bottom <= bottom) return;
        const y = window.scrollY + rect.top - (top + (bottom - top) * 0.3);
        // Short hops glide; a long jump (clicking far along the ribbon) lands at once.
        const far = Math.abs(y - window.scrollY) > window.innerHeight * 1.5;
        window.scrollTo({ top: Math.max(0, y), behavior: reducedMotion() || far ? "auto" : "smooth" });
      },

      // The user is scrolling by hand: stop following playback for a moment.
      userScrolled() { if (this.state === "ready") followUntil = performance.now() + FOLLOW_PAUSE_MS; },
      onWindowKey(e) {
        if (this.state !== "ready" || e.defaultPrevented || !SCROLL_KEYS.includes(e.key)) return;
        if (e.target.closest?.("input, select, textarea, dialog, [role=slider], [role=menu], [role=tab]")) return;
        this.userScrolled();
      },
      onWindowPointer(e) {
        // A press on the page's own scrollbar (drag to scroll) lands outside the client area.
        if (e.clientX >= document.documentElement.clientWidth) this.userScrolled();
      },

      // ------------------------------------------------------------ rename a speaker
      startRename(i) {
        const spk = this.segments[i].speaker;
        if (!(spk >= 0)) return;
        this.nameDraft = this.speakerName(spk);
        this.renamingLine = i;
      },
      focusName(i) {
        this.$nextTick(() => rootEl.querySelector(`[data-line="${i}"] [data-rename]`)?.focus());
      },
      cancelRename(i) {
        this.renamingLine = -1;
        this.focusName(i);
      },
      async commitRename(i, viaKey = false) {
        if (this.renamingLine !== i) return;   // Esc or Enter already settled this edit
        this.renamingLine = -1;
        if (viaKey) this.focusName(i);
        await this.saveSpeakerName(this.segments[i].speaker, this.nameDraft);
      },
      // Optimistic rename: ribbon, list and transcript follow at once; PATCH speaker_names, roll back on failure.
      async saveSpeakerName(spk, draft) {
        const name = draft.trim();
        if (!name || name === this.speakerName(spk)) return;
        const before = this.meta.speaker_names;
        this.actionError = "";
        this.meta.speaker_names = { ...(before || {}), [spk]: name };
        try {
          const res = await fetch(`/api/meetings/${this.id}`, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ speaker_names: { [spk]: name } }),
          });
          if (!res.ok) throw new Error(String(res.status));
        } catch (e) {
          if (this.meta) this.meta.speaker_names = before || {};
          this.actionError = this.t("rename.failed");
        }
      },

      // ------------------------------------------------------------ search
      runSearch() {
        const r = findMatches(this.segments, this.query);
        this.matchTotal = r.total;
        this.matchLines = r.lines;
        this.current = r.total ? 0 : -1;
        if (r.total) this.revealMatch();
      },
      stepMatch(dir) {
        if (!this.matchTotal) return;
        this.current = (this.current + dir + this.matchTotal) % this.matchTotal;
        this.revealMatch();
      },
      // Show the current match. Playback stops pulling the transcript for a moment, like a manual scroll,
      // and follows the current line again once that pause ends.
      revealMatch() {
        const line = lineOfMatch(this.matchLines, this.current);
        if (line < 0) return;
        followUntil = performance.now() + FOLLOW_PAUSE_MS;
        this.$nextTick(() => this.bringIntoView(line));
      },
      get countText() {
        return this.matchTotal
          ? this.t("find.count", { n: this.current + 1, total: this.matchTotal })
          : this.t("find.none");
      },
      onFindKey(e) {
        if (e.key === "Enter") { e.preventDefault(); this.stepMatch(e.shiftKey ? -1 : 1); }
        else if (e.key === "Escape" && this.query) { e.preventDefault(); e.stopPropagation(); this.query = ""; }
      },
      clearSearch() {
        this.query = "";
        this.$refs.find?.focus();
      },

      // ------------------------------------------------------------ tabs
      selectTab(name, focus = false) {
        this.tab = name;
        if (focus) this.$nextTick(() => rootEl.querySelector(`#tab-${name}`)?.focus());
      },
      onTabKey(e) {
        const names = ["transcript", "summary"];
        const at = names.indexOf(this.tab);
        let to = null;
        if (e.key === "ArrowRight") to = names[(at + 1) % names.length];
        else if (e.key === "ArrowLeft") to = names[(at + names.length - 1) % names.length];
        else if (e.key === "Home") to = names[0];
        else if (e.key === "End") to = names[names.length - 1];
        else return;
        e.preventDefault();
        this.selectTab(to, true);
      },

      // ------------------------------------------------------------ summary
      setSummary(md) {
        this.summary = md || "";
        this.summaryBlocks = withTalkBlocks(parseSummary(this.summary));
      },
      // Speaking-time rows with the speaker's colour and current name.
      talkRows(block) {
        const names = this.meta?.speaker_names;
        const lang = LOCALES[Alpine.store("i18n").lang] || "en-GB";
        const one = { maximumFractionDigits: 1, minimumFractionDigits: 1 };
        return block.rows.map((r) => {
          const idx = speakerIndexByName(r.name, names, (n) => this.t("meeting.speaker_n", { n: n + 1 }));
          return {
            name: idx >= 0 ? this.speakerName(idx) : r.name,
            color: idx >= 0 ? this.speakerColor(idx) : NEUTRAL,
            percent: r.percent,
            minutes: this.t("summary.min", { n: r.minutes.toLocaleString(lang, one) }),
          };
        });
      },

      // ------------------------------------------------------------ overflow menu
      get canRework() { return this.kind === "ready" && this.segments.length > 0; },
      toggleActions() {
        this.actionsOpen = !this.actionsOpen;
        if (this.actionsOpen) this.$nextTick(() => this.actionItems()[0]?.focus());
      },
      closeActions(refocus) {
        if (!this.actionsOpen) return;
        this.actionsOpen = false;
        if (refocus) this.$refs.actionsBtn.focus();
      },
      actionItems() { return [...this.$refs.actionsMenu.querySelectorAll("[role=menuitem]")].filter((el) => el.offsetParent !== null); },
      onActionsKey(e) {
        const items = this.actionItems();
        const at = items.indexOf(document.activeElement);
        const step = { ArrowDown: 1, ArrowUp: -1 }[e.key];
        if (e.key === "Home") items[0].focus();
        else if (e.key === "End") items[items.length - 1].focus();
        else if (step) items[(at + step + items.length) % items.length].focus();
        else if (e.key === "Tab") { this.closeActions(false); return; }
        else return;
        e.preventDefault();
      },
      afterDialog() { this.$refs.actionsBtn?.focus(); },

      // Re-queued jobs send the meeting back to processing: drop the reading view and poll until it is ready again.
      async reprocess(url) {
        this.actionError = "";
        let ok = false;
        try { ok = (await fetch(url, { method: "POST" })).ok; } catch (e) { /* reported below */ }
        if (!ok) { this.actionError = this.t("action.failed"); return false; }
        ticket++;
        clearTimeout(pollTimer);
        if (player) { player.destroy(); player = null; }
        this.segments = []; this.slots = []; this.lanes = []; this.ticks = []; this.ranking = []; this.colors = new Map(); this.now = 0; this.activeIdx = -1; this.playing = false; this.audioError = false;
        this.resetReview();
        this.setSummary("");
        if (this.meta) { this.meta.status = "queued"; this.meta.progress = 0; }
        this.kind = "queued";
        this.state = "waiting";
        this.load();
        return true;
      },
      retranscribe() {
        this.closeActions(false);
        return this.reprocess(`/api/meetings/${this.id}/retranscribe`);
      },
      openRedetect() {
        this.closeActions(false);
        // Preselect the current count when a fixed number can express it, otherwise Auto.
        const n = this.speakerCount;
        this.redoCount = SPEAKER_CHOICES.includes(n) ? String(n) : "0";
        this.$refs.redoDialog.showModal();
      },
      async confirmRedetect() {
        this.$refs.redoDialog.close();
        await this.reprocess(`/api/meetings/${this.id}/rediarize?num_speakers=${Number(this.redoCount) || 0}`);
      },
      // Regenerating the summary runs inside one request, so the Summary tab shows the wait itself.
      async resummarize() {
        this.closeActions(false);
        this.actionError = "";
        this.selectTab("summary");
        this.summaryBusy = true;
        const mine = ticket;
        try {
          const res = await fetch(`/api/meetings/${this.id}/resummarize`, { method: "POST" });
          if (!res.ok) throw new Error(String(res.status));
          const body = await res.json();
          if (mine === ticket) this.setSummary(body.summary);
        } catch (e) {
          if (mine === ticket) this.actionError = this.t("action.failed");
        }
        if (mine === ticket) this.summaryBusy = false;
      },
      openDelete() {
        this.closeActions(false);
        this.$refs.delDialog.showModal();
      },
      async confirmDelete() {
        this.busy = true;
        this.actionError = "";
        let ok = false;
        try { ok = (await fetch(`/api/meetings/${this.id}`, { method: "DELETE" })).ok; } catch (e) { /* reported below */ }
        this.busy = false;
        this.$refs.delDialog.close();
        if (!ok) { this.actionError = this.t("action.failed"); return; }
        ticket++;
        clearTimeout(pollTimer);
        location.hash = "#/";    // back to the schedule; Home reloads the list
        document.getElementById("view")?.focus();
      },

      // ------------------------------------------------------------ meta line
      get metaLine() {
        const m = this.meta;
        if (!m) return "";
        const lang = LOCALES[Alpine.store("i18n").lang] || "en-GB";
        const when = new Date(m.created);
        const parts = [
          when.toLocaleDateString(lang, { weekday: "short", day: "numeric", month: "short" }) + " " +
            when.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit", hour12: false }),
        ];
        if (m.duration) parts.push(durationLabel(m.duration, (k, v) => this.t(k, v)));
        const n = m.num_speakers_found;
        if (n) parts.push(this.t(n === 1 ? "meeting.speakers.one" : "meeting.speakers.other", { n }));
        if (m.detected_language) {
          const known = ["ms", "en"].includes(m.detected_language);
          parts.push(this.t("meeting.lang", { lang: known ? this.t("lang." + m.detected_language) : m.detected_language.toUpperCase() }));
        }
        return parts.join(" · ");
      },

      stageName() {
        const key = `stage.${this.meta?.status}`;
        const text = this.t(key);
        return text === key ? this.t("stage.unknown") : text;
      },
      errorText() { return this.meta?.error || this.t("row.error_unknown"); },

      // ------------------------------------------------------------ download
      get exportHref() { return `/api/meetings/${this.id}/export?format=${this.format}`; },
      toggleMenu() {
        this.menuOpen = !this.menuOpen;
        if (this.menuOpen) this.$nextTick(() => this.$refs.menu.querySelector("[aria-checked=true]")?.focus());
      },
      closeMenu(refocus) {
        if (!this.menuOpen) return;
        this.menuOpen = false;
        if (refocus) this.$refs.menuBtn.focus();
      },
      chooseFormat(f) {
        this.format = f;
        saveFormat(f);
        this.closeMenu(true);
      },
      onMenuKey(e) {
        const items = [...this.$refs.menu.querySelectorAll("[role=menuitemradio]")];
        const at = items.indexOf(document.activeElement);
        const step = { ArrowDown: 1, ArrowUp: -1 }[e.key];
        if (e.key === "Home") items[0].focus();
        else if (e.key === "End") items[items.length - 1].focus();
        else if (step) items[(at + step + items.length) % items.length].focus();
        else if (e.key === "Tab") { this.closeMenu(false); return; }
        else return;
        e.preventDefault();
      },
    };
  });
}
