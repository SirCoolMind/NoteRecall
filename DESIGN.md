---
name: NoteRecall
description: Local-first Malay/English meeting transcription, laid out as a broadcast programme schedule (Jadual Siaran).
colors:
  paper: "#f4f5f7"
  sheet: "#ffffff"
  rule: "#d3d8e2"
  rule-strong: "#aeb7c8"
  ink: "#111a2e"
  ink-2: "#4a5670"
  masthead: "#12306b"
  on-masthead: "#ffffff"
  on-masthead-2: "#c3cfeb"
  action: "#12306b"
  on-action: "#ffffff"
  action-hover: "#1b3f86"
  on-air: "#c81e24"
  on-air-soft: "#fbe6e6"
  next: "#8a5a00"
  next-fill: "#f2b632"
  processing: "#12306b"
  processing-soft: "#dfe6f5"
  focus: "#f2b632"
  selection: "#c9d6f2"
  hit: "#fff1c2"
  spk-0: "#1f5fd1"
  spk-1: "#0b7a5c"
  spk-2: "#a34a06"
  spk-3: "#a8238f"
  spk-4: "#0b6f86"
  spk-5: "#6a3bd0"
  spk-6: "#b93a0a"
  spk-7: "#4b7a0c"
  paper-dark: "#0b1730"
  sheet-dark: "#11203f"
  rule-dark: "#2a3d68"
  rule-strong-dark: "#3d5590"
  ink-dark: "#eef2fb"
  ink-2-dark: "#a9b6d3"
  masthead-dark: "#060f24"
  action-dark: "#c9d6f2"
  on-action-dark: "#0b1730"
  action-hover-dark: "#dbe4f7"
  on-air-dark: "#ff5a5c"
  on-air-soft-dark: "#3a1426"
  next-dark: "#f2b632"
  processing-dark: "#79a7ff"
  processing-soft-dark: "#18305e"
  selection-dark: "#2a4a8a"
  hit-dark: "#4a3c0e"
  spk-0-dark: "#79a7ff"
  spk-1-dark: "#3fd0a4"
  spk-2-dark: "#f0a840"
  spk-3-dark: "#f080dc"
  spk-4-dark: "#5ccfe0"
  spk-5-dark: "#b79bff"
  spk-6-dark: "#ff8f66"
  spk-7-dark: "#a8d860"
typography:
  display:
    fontFamily: "Barlow Semi Condensed, Arial Narrow, Segoe UI, sans-serif"
    fontSize: "clamp(1.875rem, 4.5vw, 2.75rem)"
    fontWeight: 700
    lineHeight: 1.15
    fontFeature: "tnum"
  time:
    fontFamily: "Barlow Semi Condensed, Arial Narrow, Segoe UI, sans-serif"
    fontSize: "2.25rem"
    fontWeight: 700
    lineHeight: 1
    fontFeature: "tnum"
  headline:
    fontFamily: "Barlow Semi Condensed, Arial Narrow, Segoe UI, sans-serif"
    fontSize: "1.875rem"
    fontWeight: 700
    lineHeight: 1.15
  title:
    fontFamily: "Barlow Semi Condensed, Arial Narrow, Segoe UI, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 700
    lineHeight: 1.15
  row-title:
    fontFamily: "Barlow, Segoe UI, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.15
  transcript:
    fontFamily: "Barlow, Segoe UI, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 400
    lineHeight: 1.65
  body:
    fontFamily: "Barlow, Segoe UI, system-ui, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.55
  small:
    fontFamily: "Barlow, Segoe UI, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Barlow Semi Condensed, Arial Narrow, Segoe UI, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.02em"
  label-small:
    fontFamily: "Barlow Semi Condensed, Arial Narrow, Segoe UI, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "0.02em"
  status:
    fontFamily: "Barlow Semi Condensed, Arial Narrow, Segoe UI, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.03em"
  meta:
    fontFamily: "Barlow Semi Condensed, Arial Narrow, Segoe UI, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 600
    lineHeight: 1
    fontFeature: "tnum"
  code:
    fontFamily: "Cascadia Code, Consolas, DejaVu Sans Mono, monospace"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  slot: "3px"
  control: "6px"
  panel: "8px"
spacing:
  sp-1: "4px"
  sp-2: "8px"
  sp-3: "12px"
  sp-4: "16px"
  sp-5: "24px"
  sp-6: "32px"
  sp-7: "48px"
  sp-8: "64px"
  target: "44px"
  masthead-h: "64px"
  page-max: "1200px"
  measure: "72ch"
components:
  masthead:
    backgroundColor: "{colors.masthead}"
    textColor: "{colors.on-masthead}"
    height: "{spacing.masthead-h}"
    padding: "0 24px"
  masthead-icon-button:
    backgroundColor: "transparent"
    textColor: "{colors.on-masthead}"
    rounded: "{rounded.control}"
    size: "{spacing.target}"
  drop-slot-plate:
    backgroundColor: "{colors.action}"
    textColor: "{colors.on-action}"
    typography: "{typography.display}"
    rounded: "{rounded.slot}"
    padding: "32px 48px"
  plate-inverse-button:
    backgroundColor: "{colors.on-action}"
    textColor: "{colors.action}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    height: "{spacing.target}"
    padding: "0 24px"
  button-plate:
    backgroundColor: "{colors.action}"
    textColor: "{colors.on-action}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    height: "{spacing.target}"
    padding: "0 16px"
  button-plate-hover:
    backgroundColor: "{colors.action-hover}"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.label-small}"
    rounded: "{rounded.control}"
    height: "{spacing.target}"
    padding: "0 16px"
  button-outline-hover:
    backgroundColor: "{colors.paper}"
  button-danger:
    backgroundColor: "{colors.on-air-soft}"
    textColor: "{colors.on-air}"
    typography: "{typography.label-small}"
    rounded: "{rounded.control}"
    height: "{spacing.target}"
    padding: "0 16px"
  button-danger-hover:
    backgroundColor: "{colors.on-air}"
    textColor: "{colors.sheet}"
  input:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    height: "{spacing.target}"
    padding: "0 12px"
  search-box:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    height: "{spacing.target}"
    width: "20rem"
  tab:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    typography: "{typography.label}"
    height: "{spacing.target}"
    padding: "0 16px"
  tab-selected:
    textColor: "{colors.ink}"
  status-queued:
    backgroundColor: "transparent"
    textColor: "{colors.next}"
    typography: "{typography.status}"
    rounded: "{rounded.slot}"
    height: "32px"
    padding: "0 12px"
  status-processing:
    backgroundColor: "{colors.processing}"
    textColor: "{colors.paper}"
    typography: "{typography.status}"
    rounded: "{rounded.slot}"
    height: "32px"
    padding: "0 12px"
  status-ready:
    backgroundColor: "{colors.processing-soft}"
    textColor: "{colors.ink}"
    typography: "{typography.status}"
    rounded: "{rounded.slot}"
    height: "32px"
    padding: "0 12px"
  status-failed:
    backgroundColor: "{colors.on-air-soft}"
    textColor: "{colors.on-air}"
    typography: "{typography.status}"
    rounded: "{rounded.slot}"
    height: "32px"
    padding: "0 12px"
  schedule-row:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    height: "80px"
    padding: "12px 16px"
  schedule-row-hover:
    backgroundColor: "{colors.paper}"
  speakers-button:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    height: "{spacing.target}"
    padding: "0 12px"
  segmented-option:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    height: "{spacing.target}"
    padding: "0 12px"
  segmented-option-selected:
    backgroundColor: "{colors.selection}"
  ribbon-track:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.slot}"
    height: "56px"
    padding: "0 12px"
  transcript-line:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.transcript}"
    padding: "0 16px"
  settings-modal:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    width: "880px"
    padding: "24px"
---

# Design System: NoteRecall

## Overview

**Creative North Star: "Jadual Siaran"**

Every meeting is a programme on the user's own broadcast schedule: who is on, when, and what comes next. The model is an RTM-era printed programme listing. A broadcast-navy masthead sits over a cool listing-paper ground. Programmes sit in square-cut slots divided by hairline rules, and big condensed times are set in tabular figures. One hot colour, the On Air red, marks what is live and what has failed. Eight speaker hues act as programme colours, in the speaker ribbon, on speaker names, and in the speaking-time split.

The system is in Operate mode. The task is to drop a recording, wait, and download the transcript, so the world comes through in precise details rather than decoration: the slot grid, the times, the EPG lane ribbon with its gliding playhead, and status shown by form as well as colour. Density is that of a listing. Rows are at least 80px tall and every control is at least 44px. Reading surfaces hold a 72ch measure. Light and dark themes follow the OS, and the masthead lets the user override the choice. Dark mode is a night broadcast: navy ground, a near-black masthead and a pale-blue action plate.

Provenance: the UI ships no rasters. Everything is drawn in CSS and inline SVG. The icons are Lucide (lucide-static, ISC licence), vendored as SVG in `static/icons/` with `LICENSE.txt`. Barlow and Barlow Semi Condensed are self-hosted woff2 files in `static/fonts/` under the SIL OFL (`OFL.txt`). Alpine.js is vendored in `static/vendor/`. Nothing loads from a CDN.

**Key Characteristics:**
- A broadcast-navy masthead over a cool paper ground, with white sheets for work surfaces.
- Square-cut listing slots separated by 1px hairlines rather than cards with shadows.
- Barlow Semi Condensed in tabular figures for every time, label, heading and number.
- One reversed plate per screen for the single next action.
- On Air red only for the live moment and for failure.
- Status shown by form as well as colour: outlined, striped, solid, struck.
- Eight speaker programme colours, tuned separately for each theme.

## Colors

The palette is a cool listing paper with navy structure, one red signal lamp, an amber for waiting, and eight programme colours for speakers. The light values are the defaults. The `-dark` keys hold the dark-theme overrides of the same roles, and `static/css/tokens.css` is the source of truth.

### Primary
- **Broadcast Navy** (`masthead`, `action`, `processing`): the shell, and the same navy for the reversed action plate and for processing stripes. In dark mode they separate: the masthead becomes Night Navy (`masthead-dark`), the plate becomes Pale Plate Blue (`action-dark`) with navy text, and processing becomes Signal Blue (`processing-dark`).
- **Plate Hover Navy** (`action-hover`): the hover state of the plate, and only that.

### Secondary
- **On Air Red** (`on-air`): the playhead and its lamp, the On Now lamp, the current transcript line, failure text and failed status, and destructive actions. Its pale tint (`on-air-soft`) fills failed pills, error bands and the danger button at rest.

### Tertiary
- **Queue Amber** (`next-fill`): the outline of queued pills, the plain cloud-upload warning (an amber 2px outline over a 22% amber fill), and the focus ring (`focus`). **Queue Amber Text** (`next`) is the darker amber for the queued label in light mode, where `next-fill` does not reach text contrast.
- **Speaker programme colours** (`spk-0` to `spk-7`): blue, green, burnt orange, magenta, teal, violet, rust and olive. In light mode each is text-safe (at least 4.5:1) on both sheet and paper, and the dark set is lifted to stay legible on navy. They colour the ribbon lane blocks, the Speakers list, speaker names in the transcript, and the speaking-time bars. Hues go to speakers by talk-time rank, so the top eight keep `spk-0` to `spk-7` in every place they appear. Everyone beyond the eighth, and the unknown speaker, take `ink-2`.

### Neutral
- **Listing Paper** (`paper`): the page ground, and the hover fill for rows, tabs and quiet buttons.
- **Sheet White** (`sheet`): work surfaces such as the schedule, transcript, summary, settings modal, menus and dialogs.
- **Hairline** (`rule`) and **Strong Hairline** (`rule-strong`): slot dividers and outlines. Use `rule-strong` for control strokes, the ribbon frame and the edge under the tabs.
- **Ink** (`ink`) and **Ink Two** (`ink-2`): primary and secondary text. Secondary covers meta lines, durations, tick labels and placeholders.
- **Search Hit** (`hit`) and **Selection** (`selection`): the search-match highlight and text selection.

### Named Rules
**The One Plate Rule.** Each screen has exactly one reversed plate (`action` fill with `on-action` text), and it carries the single next action. That is the drop slot on Home, the Download split button on a meeting, and "Set up everything" while the readiness panel is open, in which case the drop slot is switched off into a dashed paper outline. Everything else is an outline, plain text, or a low-value status chip.

**The On Air Rule.** Red means live or failed, and nothing else. The live uses are the playhead, the lamps and the current transcript line. Failure is always also struck through and carries an icon, so the colour never carries the meaning alone.

**The Status-By-Form Rule.** Each status has its own form as well as its colour. Queued is an amber outline, processing is drifting navy stripes, ready is a solid low-value fill, and failed is a red outline with a warning icon plus struck-through red time and title. A new status needs a new form, not just a new hue.

## Typography

**Display Font:** Barlow Semi Condensed 600/700 (falling back to Arial Narrow and Segoe UI)
**Body Font:** Barlow 400/500/600 (falling back to Segoe UI and system-ui)
**Label/Mono Font:** Cascadia Code, then Consolas and DejaVu Sans Mono, for shell commands, paths and inline code only

**Character:** a condensed grotesque used as the slot face, the way a printed listing sets its times, next to its own wider sibling for reading. They come from one family, so the pair reads as a single voice at two widths.

### Hierarchy
- **Display** (700, clamp 30px to 44px, line-height 1.15): only the drop-slot headline, "Next recording".
- **Time** (700, 36px, line-height 1, tabular figures): the recording length in each schedule row's slot (`1:52:07`, `42:10`; a muted `--:--` until known), the biggest numbers on screen.
- **Headline** (700, 30px, line-height 1.15): the meeting title and the readiness panel title.
- **Title** (700, 22px, line-height 1.15): the wordmark, the schedule group titles (On now, Next, month headings such as September 2026), and the titles of settings sections, dialogs and summary blocks.
- **Row Title** (Barlow 600, 20px, line-height 1.15): meeting titles on schedule rows, cut with an ellipsis on one line.
- **Transcript** (Barlow 400, 18px, line-height 1.65, max 72ch): the text of transcript lines.
- **Body** (Barlow 400, 17px, line-height 1.55): UI body copy and inputs.
- **Small** (Barlow 400, 15px): secondary lines, hints and meta.
- **Label** (700, 17px, 0.02em): text on plates, tabs, the ribbon clock and speaker names. **Label Small** (600, 15px) is for outline buttons, the language toggle and the back link.
- **Status** (700, 15px, 0.03em, uppercase): status pills only, plus check states at 14px.
- **Meta** (600, 14px, tabular figures): ribbon tick labels and speaker chips.

### Named Rules
**The Slot Face Rule.** Times, durations, counts, labels and headings use Barlow Semi Condensed, and any number uses tabular figures. Durations and percentages are right-aligned so their digits line up down the listing. Running text never uses the slot face.

**The 14px Floor Rule.** Nothing is smaller than 14px (`0.875rem`), anywhere, including tick labels and chips.

**The Real-Code Rule.** Monospace appears only where the user would copy or recognise literal code: install steps, file paths, and inline code in summaries.

## Layout

The layout is a single centred column up to 1200px wide, with 24px side padding (16px below 720px) under a sticky 64px masthead. Spacing sits on a 4px base: 4, 8, 12, 16, 24, 32, 48 and 64px. Home stacks a one-line readiness status (or the full readiness panel), then the full-width drop slot, a privacy line, and the schedule groups.

A schedule row is a three-column grid: the length slot (8.75rem), title with a date-and-time meta line and the quick-summary area, and the status cell (pill, plus the eye button on ready rows). The row in focus expands beneath, indented to the title column, to show the stage, the time left and the striped progress bar. Below 900px the slot face sits above the title and the status cell drops beside the body. Above the schedule sits a toolbar (search, All / Ready / In progress / Failed segmented filter, result count); finished rows load 30 at a time under month headings with a "Show more (N left)" button.

On the meeting view, the ribbon is sticky directly under the masthead. It holds play/pause, the clock, the EPG track (which takes the remaining width), and the Download split button at the right end. The transcript is a three-column listing: time (5.5rem), speaker (11rem) and text (72ch max). Below 900px the ribbon wraps the track onto its own full-width row. Below 720px the transcript text drops under the time and speaker.

The design target is desktop down to 1024px. Narrower widths stay usable and never scroll sideways.

**The 44 Rule.** Anything clickable is at least 44px in its smaller dimension (`--target`). Inline edit, search and stepping controls, chips that act as links, and select-as-text options all meet this.

## Elevation & Depth

The system is flat. Resting surfaces get their depth from tone (sheet on paper) and 1px hairlines, never from shadow. Shadows exist only on layers that float above the page, and they are tight and neutral (ink-tinted in light, black in dark), tokenised as `--shadow-pop` and `--shadow-modal`. Inset 1px strokes, done with `box-shadow: inset`, are used as borders for selected choices, the search box and the current transcript line. They are strokes, not elevation.

### Shadow Vocabulary
- **Menu lift** (`--shadow-pop`: `0 2px 6px`, ink at 16% / black at 45% in dark): the download format menu and the overflow menu.
- **Dialog lift** (`--shadow-modal`: `0 4px 10px`, ink at 22% / black at 55% in dark): confirmation dialogs, over a backdrop of 62% navy.


### Named Rules
**The Hairline Rule.** Use a 1px rule in `rule` or `rule-strong` to separate listings, rows, sections and the tab header. If a resting surface seems to need a shadow, it needs a hairline.

## Shapes

Listings are square-cut, and only things you operate soften. Slots, rows, the transcript sheet, pills, chips, progress bars and the ribbon track use a 3px radius (`rounded.slot`). Buttons, inputs, choice tiles and the search box use 6px (`rounded.control`). Floating panels (menus and dialogs) use 8px (`rounded.panel`). The only circles are the signal lamps: the On Now lamp (12px) and the playhead lamp (13px).

Borders carry state. A 1px `rule-strong` stroke marks a quiet control at rest. A 2px ink stroke marks a field being edited in place, such as a title or speaker name. A 2px amber stroke marks queued status and the cloud warning. A 2px red stroke marks failure and danger. A 2px dashed stroke marks a switched-off drop slot. Editable text (the drop-slot options and speaker names) is marked with a dashed underline that turns solid on hover.

## Components

### Buttons
Buttons are plain, firm and labelled in the slot face.
- **Shape:** gently softened corners (6px), at least 44px tall.
- **Plate:** `action` fill with `on-action` text in Label type, 16px to 24px side padding, hover to `action-hover`. Use it for one action per screen only (see The One Plate Rule).
- **Plate inverse:** the button on the drop slot. It reverses the plate, with an `on-action` fill and `action` text, fades to 0.88 opacity on hover, and gets a double focus ring (2px plate colour, then 5px `on-action`).
- **Outline:** transparent with a 1px `rule-strong` stroke and ink text in Label Small. It fills with paper on hover. Icons sit to the left at 20px.
- **Danger:** a red-tint fill with a 2px red stroke and red text. On hover it inverts to a solid red fill with sheet-coloured text.
- **Icon buttons:** 44px squares. On the masthead they use a 1px `on-masthead-2` stroke and a 16% white wash on hover. On the page they use the plain variant with a `rule-strong` stroke and paper on hover.
- **Download split:** a plate split into the action ("Download .txt") and a 44px chevron, divided by a 38% `on-action` hairline. The chevron opens the format menu, and the last format used becomes the default.

### Chips
- **Status pills:** 32px tall, 3px radius, uppercase Status type, with an optional 18px icon. Queued, processing, ready and failed each take their own form (see The Status-By-Form Rule). In setup rows an idle pill uses a 2px `rule-strong` outline.
- **Speakers button and list:** one 44px outlined button, "Speakers · N", sits left of the ribbon track and opens a popover (dialog, Esc closes) listing every speaker by talk time with colour swatch, name, time and share, a rename action and a jump to their next turn. A filter field appears above 10 speakers. The ribbon draws at most six lanes: the top five speakers and one neutral "Others (N)" lane.
- **Segmented radio groups:** language and speaker count are `role=radiogroup` bars of 44px segments with arrow-key selection. On sheets the chosen segment is filled with `selection`, set bold and ringed in `ink`; on the drop plate it reverses to `on-action` fill with `action` text and the rest outlined.
- **Diarization note:** when the speaker count is implausible for the recording length, a plain note under the meeting header (alert-triangle icon in `next`, never a plate) offers to re-detect with a fixed number.

### Cards / Containers
- **Corner Style:** 3px for listings, 8px for floating panels.
- **Background:** sheet on paper. The readiness head is a plain sheet, not a plate.
- **Shadow Strategy:** none at rest (see Elevation & Depth).
- **Border:** a 1px `rule` frame, with `rule` hairlines between rows.
- **Internal Padding:** schedule rows 12px by 16px. The summary and setup rows use 24px. The readiness head uses 32px by 48px.

### Inputs / Fields
- **Style:** a sheet fill, 1px `rule-strong` stroke, 6px radius, 44px tall, in Body type. Selects hide the native arrow and draw a Lucide chevron.
- **Focus:** a 3px amber outline at 2px offset, plus a 2px ink ring so it holds on white, paper and navy. The search box applies this to the whole box through `:focus-within`.
- **In-place edit:** title and speaker inputs switch to a 2px ink stroke in the slot face. Enter or blur saves, and Esc cancels.
- **Choice tiles:** a native radio inside a full-tile label. When selected, the tile gets an ink stroke plus a 1px ink inset.
- **Error / Disabled:** errors are red text with a warning icon. Disabled controls drop to 0.45 to 0.6 opacity, and the locked drop slot goes to paper with a dashed outline.

### Navigation
- **Masthead:** a sticky 64px navy bar. The NoteRecall wordmark (Title type) is on the left, with a "Back to schedule" outline link once a meeting is open. On the right are the BM/EN segmented toggle (pressed state inverts to white with navy text), the theme toggle and the Settings gear.
- **Update indicator:** when a newer version exists, a quiet 44px outlined chip (download icon in amber, "Update available") sits left of the language toggle and links to `#settings/updates`; its accessible name carries the version ("Update available: version 0.2.0"). Below 720px it is icon-only. It is never a modal or a badge that nags, and it disappears once the app is current.
- **Tabs:** Transcript and Summary share one hairline header with the search box. A tab is 44px tall in Label type with `ink-2` text, and the selected tab gets ink text and a 3px ink bottom bar.
- **Settings modal:** a centred native dialog, 880px wide and at most 85vh, full-screen below 720px, over a 62% navy backdrop. A tab bar (General, Transcription, Speakers, Summary, Setup, Updates, About) is a `tablist` with roving tabindex and Left/Right/Home/End keys; it never wraps, scrolls sideways with scroll-snap when tabs overflow, scrolls the active tab into view and fades the edge that hides more. Only the panel scrolls. Sections inside a panel are divided by hairlines; every field autosaves and shows a saved/saving/not-saved state beside its section title. Hashes `#settings` and `#settings/<tab>` deep-link; closing restores the earlier route and returns focus to the gear. Speaker detection and Summary are lists of providers (name, description, Active / Not found / Standby pill) so a new model or key slots in as another row.

### Updates tab
The Updates tab is a settings section like the others, with no new components. It lists the current version and how the app was installed in a facts list, then one line of reassurance ("Your meetings, settings and downloaded models are kept."). A 44px outline "Check for updates" button reports "You're up to date" on a paper note, or, when a release exists, a sheet panel with a 2px `action` stroke: the heading "Version X is available", the single Plate button "Update now" (disabled and paper-toned with the reason beside it when an update cannot run), and the release notes as plain pre-wrapped text, never HTML. Applying swaps the panel for the same setup rows used by Setup (pending, processing, ready and failed pills) (get the new version, update packages, restart), then a spinner line "Restarting NoteRecall…" until the new version answers and the page reloads itself. Spinners stop under `prefers-reduced-motion`.

### Speaker Ribbon (signature)
The sticky ribbon is the audio player, drawn as an EPG lane grid. A 56px paper track with a `rule-strong` frame holds one lane per speaker. Lanes are 3 to 10px tall, a 70% hairline fill carrying blocks in the speaker colour. Faint vertical ticks with tabular Meta labels sit at round steps (1 to 120 min), at least 60px apart. A 3px On Air playhead with a 13px lamp crosses every lane and glides 220ms on the exponential ease-out. Clicking anywhere on the track seeks the audio and scrolls the transcript there. The current transcript line takes an 8% red wash with a 45% red inset stroke, and its time turns red.

### Schedule Row (signature)
The recording length in Time type, a Row Title with an inline 44px pencil edit, a meta line with date and time (`17 Sep 2026 · 17:31`), a quick-summary area (small slot-face label "Quick summary", then the gist clamped to two lines, or a muted "Not available yet" so every row has the same shape), and a status pill with, on ready rows, a 44px eye button that opens the meeting. The title of a ready row is its link, stretched over the whole row, and focus draws a 3px amber outline inset around the row. The processing row expands to show its stage, "about N min left" and a 10px striped bar. The stripes drift at 900ms, and the On Now group title carries a pulsing red lamp (1600ms). A failed row is struck through in red and shows its error message and a Retry outline button.

### Motion
Motion is quiet and functional. Hover and press changes take 140ms and UI movement 220ms, all on `cubic-bezier(0.16, 1, 0.3, 1)`. The only authored moment is the gliding playhead. Under `prefers-reduced-motion`, the stripes, lamps, spinners and transitions stop.

## Do's and Don'ts

### Do:
- **Do** take every colour, size, space and duration from the custom properties in `static/css/tokens.css`, and define each new colour for both themes.
- **Do** give each screen exactly one reversed plate, and switch competing plates off (as the locked drop slot does) rather than letting two coexist.
- **Do** set times, durations and counts in Barlow Semi Condensed with tabular figures, right-aligned in columns.
- **Do** show status by form as well as colour, and give failure a struck-through form plus a warning icon.
- **Do** separate listings with 1px hairlines and keep slots at a 3px radius.
- **Do** use vendored Lucide SVGs from `static/icons/` for every icon, at 18px to 24px.
- **Do** keep every clickable target at least 44px and every text size at least 14px.
- **Do** put every string in both `static/i18n/en.json` and `ms.json`.

### Don't:
- **Don't** use On Air red for decoration, emphasis or brand. It means live or failed.
- **Don't** add a sidebar meeting list beside a white canvas, or SaaS stat cards. The schedule is the only meeting list.
- **Don't** use monospace for UI text, numbers or labels. It is for commands, paths and code only.
- **Don't** put eyebrow labels above headings, gradient text, or thick coloured side borders on callouts. The warning is an amber fill with a full outline.
- **Don't** use emoji or Unicode glyphs as icons.
- **Don't** shadow resting surfaces. Shadows belong only to menus and dialogs.
- **Don't** load fonts, icons or scripts from a CDN.
