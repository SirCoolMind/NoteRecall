// The hash route. Pure functions: no DOM, no Alpine.
//   #/m/<id>                  a meeting
//   #/m/<id>?t=754&q=firewall the same meeting at 12:34, with "firewall" in its search box
// Anything else is Home.

export function parseRoute(hash) {
  const m = String(hash || "").match(/^#\/m\/([\w-]+)(?:\?(.*))?$/);
  if (!m) return { id: null, t: null, q: "" };
  const params = new URLSearchParams(m[2] || "");
  const t = Number(params.get("t"));
  return {
    id: m[1],
    t: params.has("t") && Number.isFinite(t) && t >= 0 ? t : null,
    q: (params.get("q") || "").trim(),
  };
}

// Link to a meeting, optionally at a moment (seconds) and with a transcript search.
export function meetingHref(id, { t = null, q = "" } = {}) {
  const params = new URLSearchParams();
  if (t !== null && Number.isFinite(t)) params.set("t", String(Math.max(0, Math.round(t * 100) / 100)));   // exact enough to land on the line itself
  if (q) params.set("q", q);
  const tail = params.toString();
  return `#/m/${id}${tail ? "?" + tail : ""}`;
}

// Cut `text` into [{ text, hit }] around every case-insensitive occurrence of `query`.
export function markQuery(text, query) {
  const src = String(text || "");
  const needle = String(query || "").trim().toLocaleLowerCase();
  const hay = src.toLocaleLowerCase();
  if (!needle || hay.length !== src.length) return [{ text: src, hit: false }];
  const parts = [];
  let from = 0;
  for (let at = hay.indexOf(needle); at !== -1; at = hay.indexOf(needle, from)) {
    if (at > from) parts.push({ text: src.slice(from, at), hit: false });
    parts.push({ text: src.slice(at, at + needle.length), hit: true });
    from = at + needle.length;
  }
  if (from < src.length) parts.push({ text: src.slice(from), hit: false });
  return parts.length ? parts : [{ text: src, hit: false }];
}
