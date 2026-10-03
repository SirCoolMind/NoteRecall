// Display helpers shared by Home and the meeting view.
export const LOCALES = { en: "en-GB", ms: "ms-MY" };

// "12 min", "1 h 5 min", "<1 min", or a dash when unknown. `t` is the i18n lookup.
export function durationLabel(seconds, t) {
  if (!seconds) return "—";
  const mins = Math.round(seconds / 60);
  if (mins < 1) return t("dur.lt1");
  if (mins < 60) return t("dur.min", { m: mins });
  return t("dur.hm", { h: Math.floor(mins / 60), m: mins % 60 });
}

// Slot face parts, e.g. [[1,"h"],["52","m"]] or [[11,"m"],["14","s"]]; null while unknown.
// Units are spelled out so the length can't be mistaken for a clock time.
export function lengthParts(seconds) {
  const total = Math.round(Number(seconds));
  if (!total || total < 0) return null;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  if (h) return [[h, "h"], [pad(m), "m"]];
  if (m) return [[m, "m"], [pad(s), "s"]];
  return [[s, "s"]];
}
