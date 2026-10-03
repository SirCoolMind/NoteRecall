// The Download plate remembers the last export format. Storage may be blocked, so every access is guarded.
export const FORMATS = ["txt", "md", "srt"];
const KEY = "noterecall.format";

export function loadFormat() {
  try {
    const saved = localStorage.getItem(KEY);
    if (FORMATS.includes(saved)) return saved;
  } catch (e) { /* storage blocked */ }
  return "txt";
}

export function saveFormat(format) {
  try { localStorage.setItem(KEY, format); } catch (e) { /* storage blocked */ }
}
