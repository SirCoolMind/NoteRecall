// Time-left estimator. Pure functions, no DOM, no Alpine.
//
// The server only reports `stage` and `progress` (0..100). We watch how fast progress
// moves inside the CURRENT stage, over a sliding window, and extrapolate to 100.
//
// A "sample" is a progress CHANGE event: { t: ms timestamp, p: progress, stage }.
// Polling the same value again adds nothing, so a stalled job is not mistaken for a fast one.

export const WINDOW_MS = 120_000;   // only the last two minutes of change events count
export const MIN_SPAN_MS = 20_000;  // need at least this long between first and last sample...
export const MIN_GAIN = 3;          // ...and at least this many progress points gained

// Returns a new samples array. Call on every poll for a processing meeting.
// A stage change or a progress drop (a retry restarting at 0) starts a fresh window.
export function addSample(samples, now, stage, progress, windowMs = WINDOW_MS) {
  const last = samples[samples.length - 1];
  if (last && (last.stage !== stage || progress < last.p)) samples = [];
  const prev = samples[samples.length - 1];
  if (!prev || prev.p !== progress) samples = [...samples, { t: now, p: progress, stage }];
  return samples.filter((s) => s.t >= now - windowMs);
}

// Seconds until progress reaches 100, or null while there is not enough evidence.
export function secondsLeft(samples, now) {
  if (samples.length < 2) return null;
  const first = samples[0];
  const last = samples[samples.length - 1];
  const span = last.t - first.t;
  const gain = last.p - first.p;
  if (span < MIN_SPAN_MS || gain < MIN_GAIN) return null;
  const ratePerMs = gain / span;
  const sinceLast = Math.max(0, now - last.t);
  const remainingMs = (100 - last.p) / ratePerMs - sinceLast;
  return Math.max(0, remainingMs / 1000);
}

// Whole minutes to show: 0 means "under a minute".
export function minutesLeft(seconds) {
  if (seconds == null) return null;
  return seconds < 60 ? 0 : Math.round(seconds / 60);
}
