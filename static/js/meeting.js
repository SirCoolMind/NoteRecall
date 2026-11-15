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
import { setTabTitle } from "./tabtitle.js";
import { loadSpeed, saveSpeed, stepSpeed, cycleSpeed, speedLabel, shortcutFor, elementContext } from "./keys.js";

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
    let quietQuery = null;   // a search set from a moment link: its watcher run must not jump to the first match

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
      liveLines: [],   // while processing: lines transcribed so far, without speakers
      speed: loadSpeed(),   // playback rate, remembered across meetings
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

      // corrections (see corrections.py): the server keeps the untouched transcript beside the corrected one
      corrected: false,        // an original is being kept, so "Discard corrections" is offered
      knownNames: [],          // names given to speakers in any meeting, suggested while naming
      menuLine: -1,            // transcript line whose menu is open
      editLine: -1,            // transcript line whose text is being edited
      textDraft: "",
      wholeTurn: false,        // the speaker choice in the line menu applies to the whole turn
      delArmed: false,         // "Delete line" was pressed once; the second press deletes
      popMerge: null,          // speaker being merged away, picked in the Speakers popover
      mergeInto: null,         // the speaker it will join, waiting for confirmation

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
        // The same meeting at another moment (a second search result, a pasted link).
        this.$watch("$store.route.n", () => { if (this.state === "ready" && Alpine.store("route").id === this.id) this.applyMoment(); });
        this.$watch("query", () => {
          if (quietQuery === this.query) { quietQuery = null; return; }   // applyMoment already searched
          quietQuery = null;
          this.runSearch();
        });
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
        this.liveLines = [];
        this.ranking = []; this.colors = new Map(); this.speakersOpen = false; this.speakerFilter = ""; this.popRename = null;
        this.corrected = false; this.popMerge = null; this.mergeInto = null;
        this.total = 0; this.now = 0; this.activeIdx = -1;
        this.playing = false; this.audioError = false; this.menuOpen = false; this.editing = null;
        this.resetReview();
        this.summary = ""; this.summaryBlocks = []; this.summaryBusy = false; this.actionError = ""; this.busy = false;
      },

      // Back to a clean transcript view: no search, no rename, no open menu.
      resetReview() {
        this.tab = "transcript"; this.actionsOpen = false; this.renamingLine = -1;
        this.menuLine = -1; this.editLine = -1; this.delArmed = false;
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
        this.syncTitle();
        if (this.kind !== "ready") {
          this.state = "waiting";
          if (this.kind === "processing") await this.pullLive(mine);
          else this.liveLines = [];
          return again();
        }
        if (wasReady) return;
        this.liveLines = [];
        this.showTranscript(body);
        this.state = "ready";
        this.$nextTick(() => this.mountPlayer());
      },

      // While the recording is processed: fetch the lines transcribed since the last poll.
      async pullLive(mine) {
        let body;
        try {
          const res = await fetch(`/api/meetings/${this.id}/live?after=${this.liveLines.length}`);
          if (!res.ok) return;
          body = await res.json();
        } catch (e) { return; }   // the next poll tries again
        if (mine !== ticket) return;
        // fewer lines than we hold means a new job started (re-transcribe): start over
        if (body.total < this.liveLines.length) { this.liveLines = []; return; }
        if (!body.lines.length) return;
        // keep the reading position: follow the newest line only when the reader has scrolled to the end
        const doc = document.documentElement;
        const atEnd = window.scrollY > 0 && window.innerHeight + window.scrollY >= doc.scrollHeight - 80;
        this.liveLines.push(...body.lines);
        if (atEnd && this.liveLines.length > body.lines.length) {
          this.$nextTick(() => window.scrollTo({ top: doc.scrollHeight, behavior: reducedMotion() ? "auto" : "smooth" }));
        }
      },

      // The browser tab shows the meeting, and the percentage while it is processed.
      syncTitle() {
        if (!this.meta || Alpine.store("route").id !== this.id) return;
        setTabTitle({
          name: this.meta.title || "",
          progress: this.kind === "processing" ? this.meta.progress || 0 : null,
          failed: this.kind === "failed",
        });
      },

      // Put a finished meeting's transcript on screen (first load, or after corrections were discarded).
      showTranscript(body) {
        this.meta = body.meta;
        this.segments = body.segments || [];
        this.corrected = !!body.corrected;
        this.knownNames = body.known_names || [];
        this.setSummary(body.summary);
        this.total = Math.max(this.total, this.recordingLength(body.meta.duration));
        this.rebuild();
      },

      // Everything derived from the segments: talk-time ranking, colours, turns, and the ribbon lanes.
      rebuild() {
        this.ranking = rankSpeakers(this.segments);
        this.colors = speakerColors(this.ranking);
        this.slots = buildSlots(this.segments, this.total);
        this._plotW = 0;
        this.layoutRibbon();
        if (this.query.trim()) this.runSearch(false);
      },

      recordingLength(fromAudio) {
        const lastEnd = this.segments.reduce((m, s) => Math.max(m, s.end || 0), 0);
        return Math.max(fromAudio || 0, lastEnd);
      },

      retry() { return this.reprocess(`/api/meetings/${this.id}/retranscribe`); },

      // ------------------------------------------------------------ title
      applyTitle(id, title) { if (this.meta && this.meta.id === id) { this.meta.title = title; this.syncTitle(); } },
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
        // Loading a source resets playbackRate to defaultPlaybackRate, so the remembered speed goes on both.
        audio.defaultPlaybackRate = this.speed;
        audio.playbackRate = this.speed;
        player.place();
        this.layoutRibbon();
        const plot = this.$refs.plot;
        if (plot && typeof ResizeObserver === "function") {
          plotObserver = new ResizeObserver(() => this.layoutRibbon());
          plotObserver.observe(plot);
        }
        this.applyMoment();
      },

      // '#/m/<id>?t=754&q=firewall': open at that second, with the search filled in and that line's match current.
      applyMoment() {
        const { t, q } = Alpine.store("route");
        if (!q && t === null) return;
        this.selectTab("transcript");
        if (q) {
          if (q !== this.query) quietQuery = q;
          this.query = q;
          this.runSearch(t === null);
        }
        if (t === null) return;
        const idx = segmentAt(this.segments, t + 0.01);
        const here = (this.matchLines[idx] || []).find((p) => p.n >= 0);
        if (here) this.current = here.n;
        this.seekTo(t, false);
        followUntil = performance.now() + FOLLOW_PAUSE_MS;   // the search watcher must not pull the page elsewhere
        this.$nextTick(() => this.bringIntoView(idx));
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

      // Relative seek: the back-5 button and the arrow keys.
      skip(seconds) { if (player) this.seekTo(player.time + seconds, true); },

      get speedText() { return speedLabel(this.speed); },
      setSpeed(speed) {
        if (speed === this.speed) return;
        this.speed = speed;
        saveSpeed(speed);
        const audio = this.$refs.audio;
        if (audio) { audio.defaultPlaybackRate = speed; audio.playbackRate = speed; }
      },
      nextSpeed() { this.setSpeed(cycleSpeed(this.speed)); },

      openKeys() { this.closeActions(false); this.$refs.keysDialog?.showModal(); },

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
        this.popMerge = null;
        this.mergeInto = null;
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
        this.popMerge = null; this.mergeInto = null;
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
        if (this.editLine === i) return;
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
      // Player keys that work wherever focus is, unless the user is typing or a control owns the key.
      onShortcut(e) {
        if (this.state !== "ready" || e.defaultPrevented || !player) return;
        if (document.querySelector("dialog[open]")) return;
        const action = shortcutFor(e, elementContext(e.target));
        if (!action) return;
        e.preventDefault();
        if (action === "toggle") this.toggle();
        else if (action === "back") this.skip(-SEEK_STEP);
        else if (action === "forward") this.skip(SEEK_STEP);
        else if (action === "slower") this.setSpeed(stepSpeed(this.speed, -1));
        else if (action === "faster") this.setSpeed(stepSpeed(this.speed, 1));
        else if (action === "help") this.openKeys();
        else if (action === "find") {
          this.selectTab("transcript");
          this.$nextTick(() => { this.$refs.find?.focus(); this.$refs.find?.select(); });
        }
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
          if (!this.knownNames.includes(name)) this.knownNames = [...this.knownNames, name].sort((a, b) => a.localeCompare(b));
        } catch (e) {
          if (this.meta) this.meta.speaker_names = before || {};
          this.actionError = this.t("rename.failed");
        }
      },

      // ------------------------------------------------------------ corrections
      // One request, one answer shape: { changed: { index: segment }, removed, meta, summary, corrected }.
      async correct(method, path, body) {
        if (this.busy) return false;
        this.busy = true;
        this.actionError = "";
        const mine = ticket;
        let data = null;
        try {
          const res = await fetch(`/api/meetings/${this.id}${path}`, {
            method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined,
          });
          if (res.ok) data = await res.json();
          else if (res.status === 400 || res.status === 409) this.actionError = this.t("correct.stale");
        } catch (e) { /* reported below */ }
        if (mine !== ticket) return false;
        this.busy = false;
        if (!data) { if (!this.actionError) this.actionError = this.t("action.failed"); return false; }
        if (Number.isInteger(data.removed)) {
          this.segments.splice(data.removed, 1);
          // line numbers moved up by one: the line being spoken is found again from the time
          this.activeIdx = player ? segmentAt(this.segments, player.time) : -1;
        }
        for (const [i, seg] of Object.entries(data.changed || {})) this.segments[Number(i)] = seg;
        this.meta = data.meta;
        this.corrected = !!data.corrected;
        this.setSummary(data.summary);
        this.rebuild();
        return true;
      },
      get hasCorrections() { return this.corrected || this.segments.some((s) => s.orig !== undefined); },

      // ---- the menu on each line
      get menuSpeakers() {
        return this.ranking.filter((r) => r.speaker >= 0)
          .map((r) => ({ speaker: r.speaker, name: this.speakerName(r.speaker), color: this.speakerColor(r.speaker) }));
      },
      turnLength(i) {
        const spk = this.segments[i]?.speaker;
        let lo = i, hi = i;
        while (lo > 0 && this.segments[lo - 1].speaker === spk) lo--;
        while (hi + 1 < this.segments.length && this.segments[hi + 1].speaker === spk) hi++;
        return hi - lo + 1;
      },
      toggleLineMenu(i) {
        if (this.menuLine === i) return this.closeLineMenu(true);
        this.editLine = -1;
        this.wholeTurn = false;
        this.delArmed = false;
        this.menuLine = i;
      },
      // The menu just rendered: focus its first item and make sure all of it is on screen.
      openedLineMenu(el) {
        el.querySelector("[role^=menuitem]")?.focus({ preventScroll: true });
        const over = el.getBoundingClientRect().bottom - (window.innerHeight - 16);
        if (over > 0) { this.userScrolled(); window.scrollBy({ top: over, behavior: "auto" }); }
      },
      closeLineMenu(refocus) {
        const i = this.menuLine;
        if (i < 0) return;
        this.menuLine = -1;
        this.delArmed = false;
        if (refocus) this.$nextTick(() => rootEl.querySelector(`[data-more="${i}"]`)?.focus({ preventScroll: true }));
      },
      onLineMenuKey(e, i) {
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); this.closeLineMenu(true); return; }
        const items = [...e.currentTarget.querySelectorAll("[role^=menuitem], input")].filter((el) => el.offsetParent !== null && !el.disabled);
        const at = items.indexOf(document.activeElement);
        const step = { ArrowDown: 1, ArrowUp: -1 }[e.key];
        if (e.key === "Home") items[0]?.focus();
        else if (e.key === "End") items[items.length - 1]?.focus();
        else if (step) items[(at + step + items.length) % items.length]?.focus();
        else if (e.key === "Tab") { this.closeLineMenu(false); return; }
        else return;
        e.preventDefault();
      },

      // ---- a line's text
      editText(i) {
        this.menuLine = -1;
        this.renamingLine = -1;
        this.textDraft = this.segments[i].text;
        this.editLine = i;
      },
      growBox(el) { el.style.height = "auto"; el.style.height = el.scrollHeight + 2 + "px"; },
      focusLine(i) { this.$nextTick(() => rootEl.querySelector(`[data-more="${i}"]`)?.focus({ preventScroll: true })); },
      cancelText(i) {
        this.editLine = -1;
        this.focusLine(i);
      },
      async saveText(i) {
        const seg = this.segments[i];
        const text = this.textDraft.replace(/\s+/g, " ").trim();
        if (!seg || this.editLine !== i) return;
        if (!text || text === seg.text) return this.cancelText(i);
        if (await this.correct("PATCH", `/segments/${i}`, { start: seg.start, text })) this.cancelText(i);
      },
      replayLine(i) {
        this.seekTo(this.segments[i].start, false);
        if (!this.playing) this.toggle();
      },
      async restoreLine(i) {
        const seg = this.segments[i];
        this.closeLineMenu(true);
        await this.correct("PATCH", `/segments/${i}`, { start: seg.start, restore: true });
      },
      // Deleting needs the same button pressed twice; there is no dialog to click through for every stray line.
      async deleteLine(i) {
        if (!this.delArmed) { this.delArmed = true; return; }
        const seg = this.segments[i];
        this.menuLine = -1;
        this.delArmed = false;
        if (await this.correct("DELETE", `/segments/${i}?start=${encodeURIComponent(seg.start)}`)) {
          this.focusLine(Math.min(i, this.segments.length - 1));
        }
      },

      // ---- who said a line
      async moveLine(i, speaker) {
        const seg = this.segments[i];
        const turn = this.wholeTurn && this.turnLength(i) > 1;
        this.closeLineMenu(true);
        if (speaker === seg.speaker) return;
        await this.correct("PATCH", `/segments/${i}`, { start: seg.start, speaker, turn });
      },

      // ---- merging two speakers, from the Speakers popover
      linesOf(spk) { return this.segments.reduce((n, s) => n + (s.speaker === spk ? 1 : 0), 0); },
      onSpeakerRow(spk) {
        if (this.popMerge === null) return this.pickSpeaker(spk);
        if (spk !== this.popMerge && spk >= 0) this.mergeInto = spk;
        this.$nextTick(() => this.$refs.speakersPop.querySelector(".spk__go")?.focus());
      },
      startMerge(spk) {
        this.popRename = null;
        this.mergeInto = null;
        this.popMerge = spk;
        this.$nextTick(() => this.$refs.speakersPop.querySelector(".spk__cancel")?.focus());
      },
      cancelMerge() {
        const spk = this.popMerge;
        this.popMerge = null;
        this.mergeInto = null;
        this.$nextTick(() => this.$refs.speakersPop?.querySelector(`[data-merge-spk="${spk}"]`)?.focus());
      },
      async confirmMerge() {
        const from = this.popMerge, into = this.mergeInto;
        if (from === null || into === null) return;
        const ok = await this.correct("POST", "/speakers/merge", { from, into });
        this.popMerge = null;
        this.mergeInto = null;
        if (ok) this.$nextTick(() => this.$refs.speakersPop?.querySelector(".spk__jump")?.focus());
      },

      // ---- undo everything
      openDiscard() {
        this.closeActions(false);
        this.$refs.discardDialog.showModal();
      },
      async confirmDiscard() {
        this.busy = true;
        this.actionError = "";
        const mine = ticket;
        let body = null;
        try {
          const res = await fetch(`/api/meetings/${this.id}/corrections/discard`, { method: "POST" });
          if (res.ok) body = await res.json();
        } catch (e) { /* reported below */ }
        if (mine !== ticket) return;
        this.busy = false;
        this.$refs.discardDialog.close();
        if (!body) { this.actionError = this.t("action.failed"); return; }
        this.resetReview();
        this.showTranscript(body);
      },
      // Re-transcribing throws corrections away, so it asks first when there are any.
      askRetranscribe() {
        if (!this.hasCorrections) return this.retranscribe();
        this.closeActions(false);
        this.$refs.retxDialog.showModal();
      },

      // ------------------------------------------------------------ search
      // `reveal` false keeps the page where it is: used when a correction changed the text under a search.
      runSearch(reveal = true) {
        const r = findMatches(this.segments, this.query);
        this.matchTotal = r.total;
        this.matchLines = r.lines;
        this.current = r.total ? (reveal ? 0 : Math.min(Math.max(this.current, 0), r.total - 1)) : -1;
        if (r.total && reveal) this.revealMatch();
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
        this.corrected = false;
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
        // Only meetings processed since the speaker-model choice exists say which one ran.
        if (m.diarizer) parts.push(this.t("meeting.spkby", { model: this.diarizerName(m.diarizer) }));
        return parts.join(" · ");
      },
      diarizerName(d) {
        if (d === "nemotron") return this.t("meeting.spkby.nemotron");
        if (d === "standard") return this.t("meeting.spkby.standard");
        return this.t("meeting.spkby.fellback");   // "standard (...)": Nemotron was chosen but not used
      },

      // ------------------------------------------------------------ Nemotron-3 fallback notice
      // Shown when Nemotron-3 was chosen but Standard labelled the speakers, with the reason.
      get fellBack() { return this.state === "ready" && String(this.meta?.diarizer || "").startsWith("standard ("); },
      get fallbackReason() {
        const fb = this.meta?.diarizer_fallback;
        if (!fb) return this.t("fb.reason.unknown");
        const key = "fb.reason." + fb.code;
        const text = this.t(key);
        return text === key ? this.t("fb.reason.error") : text;
      },
      get fallbackDetail() {
        const fb = this.meta?.diarizer_fallback;
        return fb && ["error", "out_of_memory"].includes(fb.code) ? fb.detail : "";
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
