// Transcript search. Pure functions: no DOM, no Alpine.

// All case-insensitive matches of `query` in the segments' text, in reading order, plus for each
// matching line the text cut into parts: [{ text, n }] where n is the match number or -1.
export function findMatches(segments, query) {
  const needle = query.trim().toLocaleLowerCase();
  const count = { total: 0 };
  const lines = {};
  if (!needle) return { total: 0, lines };
  segments.forEach((seg, i) => {
    const hay = String(seg.text || "").toLocaleLowerCase();
    // A few characters change length when lowercased; then offsets would drift, so skip highlighting that line.
    if (hay.length !== String(seg.text || "").length) return;
    const parts = [];
    let from = 0;
    for (let at = hay.indexOf(needle); at !== -1; at = hay.indexOf(needle, from)) {
      if (at > from) parts.push({ text: seg.text.slice(from, at), n: -1 });
      parts.push({ text: seg.text.slice(at, at + needle.length), n: count.total++ });
      from = at + needle.length;
    }
    if (parts.length) {
      if (from < seg.text.length) parts.push({ text: seg.text.slice(from), n: -1 });
      lines[i] = parts;
    }
  });
  return { total: count.total, lines };
}

// Line index that holds match number n.
export function lineOfMatch(lines, n) {
  for (const [i, parts] of Object.entries(lines)) {
    if (parts.some((p) => p.n === n)) return Number(i);
  }
  return -1;
}
