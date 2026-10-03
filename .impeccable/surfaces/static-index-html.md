---
version: 1
slug: "static-index-html"
primary_target: "static/index.html"
related_targets: ["static/setup.html","static/about.html"]
---

## Scope

The whole NoteRecall app shell: Home (upload + schedule of meetings), Meeting (transcript, player, download), Settings (a tabbed modal reachable from every screen), and First-run readiness. `/about` becomes a short help view inside Settings. Mode: **Operate**.

## Audience and task

One user on their own desktop, in daylight or a dim room (light and dark themes follow the OS). The job is: drop a recording → wait → download the transcript. Everything else is secondary and must not cost clicks on that path.

## Constraints

- Offline: self-hosted fonts and icons, no CDN.
- Bilingual: every string in `static/i18n/en.json` + `ms.json`; first language follows the browser, with a remembered toggle in the masthead.
- No text below 14px; transcript at 18px; clickable targets at least 44px tall.
- Keep: speaker colours with click-to-rename, the audio player synced to the transcript, honest setup checks.
- Avoid: generic SaaS dashboard (sidebar + stat cards), developer-tool feel (monospace only for real commands), playful decoration, an unfinished look.
- Icons come from one vendored SVG set (Lucide, copied into `static/icons/`); no emoji or Unicode glyphs as icons.

## Direction contract

THESIS: Every meeting is a programme on your broadcast schedule (who is on, when, and what is next). It refuses the category default of a sidebar meeting list beside a white transcript canvas.

OWN-WORLD: Broadcast-navy masthead over a cool listing-paper ground; square-cut programme slots with hairline rules; big tabular slot-face times (Barlow Semi Condensed) beside Barlow body text; an On Air red lamp as the only hot colour; eight speaker hues that act as programme colours. Status is shown by form as well as colour: outlined amber = queued, striped navy = processing, solid = ready, struck red = failed.

STORY: The user sees at once where to drop a recording, watches it move from Next to On Now to Ready with the stage and time left, opens it, and downloads in one click. When they review, they find any moment by its speaker slot.

FIRST VIEWPORT: Masthead (64px, navy): NoteRecall wordmark left; BM/EN toggle, theme, and Settings gear right. Below it, the full-width drop slot "Next recording", 44px headline with the language and speaker defaults shown as editable text; this is the screen's one reversed plate. Under it is the schedule: one row per meeting (big start time at left in the slot face; title; duration right-aligned in tabular figures; status slot). The active job row expands to show its stage and time remaining. Meeting view: a sticky ribbon under the masthead draws the whole meeting as speaker-coloured slots, the red On Air playhead glides along it with play/pause and time beside it, and Download is the reversed plate at the right end; the transcript sits below in a time | speaker | text listing rhythm at a 72ch measure.

FORM: Jadual Siaran, a broadcast programme schedule (RTM-era printed listings), position 5 on my ordered list of seven; seed key c92d98ef. Raises kept from declined challengers: status by form as well as colour (Emission-Line Rail); one reversed plate per screen for the single next action (Timetable Slide Rack); the item in focus expands to show detail (Streaming Title Wall); times right-aligned in tabular figures (Cassette J-Card).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Memorable moment

The speaker ribbon with the gliding On Air playhead: the whole meeting visible as a schedule, and clicking any slot jumps the audio and transcript there.

## Shaped decisions (confirmed 2026-10-04)

- **Main path:** drop a file → it uploads immediately → the schedule row → open → Download. That is two clicks after the drop. Each screen has one reversed plate: the drop slot on Home, Download on a meeting, "Set up everything" on the readiness panel.
- **First run:** a readiness panel sits **above** a disabled drop slot. It lists the failed checks with a "Set up everything" plate and live install progress, and each check can expand to show its manual steps for this OS. Once everything passes, it collapses to one line and the drop slot turns on.
- **Time left:** the stage name plus "about N min left", estimated in the browser from the rate at which progress changes. It shows "estimating…" until there are enough samples. The backend already exposes `stage` and `progress`.
- **Title while waiting:** the meeting title can be edited in place on its schedule row and in the meeting header at every status, including queued and processing. It saves on Enter or blur, and Esc cancels. **Backend fix required:** the worker currently holds a stale `meta` copy and its progress writes overwrite edits made during processing. Before every write, the worker must re-read the user-editable fields (`title`, `speaker_names`) from disk and merge them, or else serialise meta writes under a per-meeting lock.
- **Download:** a split plate, e.g. "Download .txt", with a small format menu (txt / md / srt). The last format used is remembered and becomes the default.
- **Meeting view:**
  - The sticky ribbon is the audio player: play/pause, time, speaker slots you can click to jump to, the playhead, and the Download plate. There is no separate floating player.
  - The transcript reads as time | speaker | text. Clicking a line seeks there. Clicking a speaker name renames that speaker everywhere.
  - Search sits in the transcript header. Summary is a tab next to Transcript and shows the existing content only.
- **Rare actions:** these live in one overflow menu per meeting: Re-transcribe, Re-detect speakers (with a count), Regenerate summary, and Delete. Delete asks for confirmation and names what will be removed.
- **Settings modal:** a centred dialog (about 880px) with scrollable tabs (General, Transcription, Speakers, Summary, Setup, About), opened from the masthead gear on any screen. It holds:
  - Engine: local or Gemini, with the plain upload warning.
  - Device, model and its status, and the Gemini key with a Test button.
  - Default language and speaker count.
  - Setup checks.
  - Interface language and theme.
  - About/help.

  Every change saves immediately; there is no Save button. `/setup` and `/about` redirect into the modal.
- **Home:** the schedule is the only meeting list. Opening a meeting replaces the view, and a back link appears in the masthead. When there are no meetings, the page shows only the drop slot and one line saying audio stays on this machine.
- **Upload options:** language (Auto/BM/EN) and speaker count (Auto/N) appear as editable text inside the drop slot, defaulting from Settings.
- **Failed meetings:** shown struck through in red, with an icon, the error message, and a Retry action.
- **Layout:** desktop-first, solid down to 1024px, still usable when narrower.
- **Builders must not invent:** new export formats, any cloud default, marketing copy, or samples built from `data/`.
