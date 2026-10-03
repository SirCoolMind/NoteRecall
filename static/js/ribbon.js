// Speaker ribbon maths. Pure functions: no DOM, no Alpine.
//
// A "run" is a stretch of consecutive transcript segments by the same speaker. Each run
// becomes one slot on the ribbon, positioned as a percentage of the whole recording.

export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

export function speakerOf(seg) {
  return Number.isInteger(seg.speaker) ? seg.speaker : -1;
}

export const NEUTRAL = "var(--ink-2)";   // unknown speakers and everyone beyond the eighth hue
export const PALETTE_SIZE = 8;           // --spk-0 .. --spk-7
export const MAX_LANES = 6;              // the top five speakers get a lane, the rest share "Others"
export const OTHERS = -2;                // pseudo speaker id of the merged lane

// Speakers ranked by total talk time, most first (ties: lower speaker number first).
// [{ speaker, seconds, share (0..1), rank }]; the unknown speaker (-1) is ranked like any other.
export function rankSpeakers(segments) {
  const secs = new Map();
  let all = 0;
  for (const seg of segments) {
    const len = Math.max(0, (seg.end || 0) - (seg.start || 0));
    const spk = speakerOf(seg);
    secs.set(spk, (secs.get(spk) || 0) + len);
    all += len;
  }
  return [...secs.entries()]
    .sort((a, b) => b[1] - a[1] || a[0] - b[0])
    .map(([speaker, seconds], rank) => ({ speaker, seconds, share: all > 0 ? seconds / all : 0, rank }));
}

// speaker -> CSS colour. The top eight by talk time take --spk-0..7 in rank order; everyone else is neutral.
// One map feeds the ribbon, the transcript, the speakers list and the summary bars.
export function speakerColors(ranking) {
  const map = new Map();
  for (const r of ranking) map.set(r.speaker, r.speaker >= 0 && r.rank < PALETTE_SIZE ? `var(--spk-${r.rank})` : NEUTRAL);
  return map;
}

// Is this many speakers implausible for a recording this long? Real meetings rarely have more than
// four voices per ten minutes, and never more than twelve here; more means diarization split voices.
export function isImplausibleSpeakerCount(count, durationSec) {
  const minutes = Math.max(0, durationSec || 0) / 60;
  const limit = Math.min(12, Math.max(4, Math.ceil(minutes / 10) * 4));
  return count > limit;
}

// "14:02 · 11%" style share text parts.
export function sharePercent(share) {
  return share > 0 && share < 0.01 ? "<1%" : `${Math.round(share * 100)}%`;
}

// Contiguous same-speaker runs: [{ speaker, first, last, start, end }] (first/last = segment indexes).
export function buildRuns(segments) {
  const runs = [];
  segments.forEach((seg, i) => {
    const spk = speakerOf(seg);
    const run = runs[runs.length - 1];
    if (run && run.speaker === spk) {
      run.last = i;
      run.end = Math.max(run.end, seg.end);
    } else {
      runs.push({ speaker: spk, first: i, last: i, start: seg.start, end: seg.end });
    }
  });
  return runs;
}

// Runs with ribbon geometry. `total` is the recording length in seconds.
export function buildSlots(segments, total) {
  if (!(total > 0)) return [];
  return buildRuns(segments).map((run) => {
    const start = clamp(run.start, 0, total);
    const end = clamp(run.end, start, total);
    return { ...run, start, end, left: (start / total) * 100, width: ((end - start) / total) * 100 };
  });
}

// ---- EPG grid: one lane per speaker -------------------------------------------------
// Everything below is pure. `width` is the rendered width of the lane area in CSS pixels.

export const LANE_MERGE_PX = 2;   // same-speaker blocks closer than this (in track pixels) join up

// Lanes by talk-time rank: at most MAX_LANES. With more speakers than that, the top MAX_LANES - 1
// keep their own lane and everyone else merges into one final "Others" lane (speaker = OTHERS).
// [{ speaker, others (count, only on the merged lane), blocks: [{ start, end, left, width }] }];
// left/width are percentages of the recording.
export function buildLanes(segments, total, width, ranking = rankSpeakers(segments)) {
  if (!(total > 0)) return [];
  const gap = width > 0 ? (LANE_MERGE_PX / width) * total : 0;   // seconds that fit in LANE_MERGE_PX
  const own = ranking.length > MAX_LANES ? ranking.slice(0, MAX_LANES - 1) : ranking;
  const laneOf = new Map(own.map((r, i) => [r.speaker, i]));
  const merged = ranking.length > MAX_LANES;
  const groups = own.map((r) => ({ speaker: r.speaker, spans: [] }));
  if (merged) groups.push({ speaker: OTHERS, others: ranking.length - own.length, spans: [] });
  for (const seg of segments) {
    const g = groups[laneOf.has(speakerOf(seg)) ? laneOf.get(speakerOf(seg)) : groups.length - 1];
    const start = clamp(seg.start, 0, total);
    g.spans.push({ start, end: clamp(seg.end, start, total) });
  }
  return groups.map(({ spans, ...lane }) => {
    spans.sort((a, b) => a.start - b.start);
    const blocks = [];
    for (const s of spans) {
      const last = blocks[blocks.length - 1];
      if (last && s.start - last.end < gap) last.end = Math.max(last.end, s.end);
      else blocks.push({ ...s });
    }
    return {
      ...lane,
      blocks: blocks.map((b) => ({ ...b, left: (b.start / total) * 100, width: ((b.end - b.start) / total) * 100 })),
    };
  });
}

// Lane height and gap (px) that fit `count` lanes in `room` px: 8-10px for a few speakers, thinner for many.
export function laneSizing(count, room) {
  const n = Math.max(1, count);
  const gap = n > 5 ? 1 : 2;
  const height = clamp(Math.floor((room - (n - 1) * gap) / n), 3, 10);
  return { height, gap, used: n * height + (n - 1) * gap };
}

const TICK_STEPS = [60, 120, 300, 600, 900, 1800, 3600, 7200];   // seconds; 10 and 15 min cover long meetings
export const TICK_MIN_PX = 60;

// Time marks: the smallest round step that keeps labels at least TICK_MIN_PX apart.
// Returns [{ t, left (percent), label }]. A mark too close to the right edge is dropped so its label fits.
export function buildTicks(total, width) {
  if (!(total > 0) || !(width > 0)) return [];
  const step = TICK_STEPS.find((s) => (s / total) * width >= TICK_MIN_PX) || TICK_STEPS[TICK_STEPS.length - 1];
  const ticks = [];
  for (let t = 0; t < total; t += step) {
    const x = (t / total) * width;
    if (t > 0 && x > width - 30) break;
    ticks.push({ t, left: (t / total) * 100, label: formatTime(t) });
  }
  return ticks;
}

// Start of the given speaker's next turn after time t, or null when they do not speak again.
export function nextTurnOf(slots, speaker, t) {
  const next = slots.find((s) => s.speaker === speaker && s.start > t + 0.05);
  return next ? next.start : null;
}

// Index of the segment being spoken at time t: the last one that has started. -1 before the first.
export function segmentAt(segments, t) {
  let lo = 0, hi = segments.length - 1, found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (segments[mid].start <= t) { found = mid; lo = mid + 1; } else { hi = mid - 1; }
  }
  return found;
}

// The slot the playhead is in, or the last one that started before it. null before the first.
export function slotAt(slots, t) {
  let found = null;
  for (const slot of slots) {
    if (slot.start <= t) found = slot; else break;
  }
  return found;
}

// Start time of the next (dir > 0) or previous (dir < 0) slot. "Previous" first restarts the
// current slot when we are more than a moment into it, like a media player's back button.
export function stepSlot(slots, t, dir) {
  if (dir > 0) {
    const next = slots.find((s) => s.start > t + 0.05);
    return next ? next.start : null;
  }
  const before = slots.filter((s) => s.start < t - 1.5);
  return before.length ? before[before.length - 1].start : 0;
}

// 83 -> "1:23", 3725 -> "1:02:05".
export function formatTime(sec) {
  const s = Math.max(0, Math.floor(Number.isFinite(sec) ? sec : 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  const p = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${p(m)}:${p(x)}` : `${m}:${p(x)}`;
}
