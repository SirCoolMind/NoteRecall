// Summary markdown -> a small block model that the page renders with text bindings only.
// Nothing here produces HTML: links and `code` spans are modelled as { href } / { code } and the page
// builds real <a> and <code> nodes from them, with every piece of text reaching the DOM through
// x-text, so untrusted summary text (it can come from an LLM) cannot inject markup. Pure, no DOM.

// A link is only kept when it is plain http(s) or mailto.
export function safeHref(url) {
  return /^(https?:\/\/|mailto:)[^\s<>"']+$/i.test(url) ? url : null;
}

const INLINE = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)|(?<![\w])_([^_]+)_(?![\w])|(?<![\w*])\*([^*\s][^*]*)\*(?![\w*])/g;

// "a **b** c" -> [{ text: "a " }, { text: "b", bold: true }, { text: " c" }]
export function parseInline(src) {
  const out = [];
  let last = 0;
  for (const m of src.matchAll(INLINE)) {
    if (m.index > last) out.push({ text: src.slice(last, m.index) });
    if (m[1] !== undefined) out.push({ text: m[1], bold: true });
    else if (m[2] !== undefined) out.push({ text: m[2], code: true });
    else if (m[3] !== undefined) {
      const href = safeHref(m[4]);
      out.push(href ? { text: m[3], href } : { text: m[3] });
    } else out.push({ text: m[5] ?? m[6], italic: true });
    last = m.index + m[0].length;
  }
  if (last < src.length) out.push({ text: src.slice(last) });
  return out.length ? out : [{ text: "" }];
}

// Blocks: { type: "h", raw, inline } | { type: "p"|"quote", ... } | { type: "ul"|"ol", items: [{ raw, inline }] }
export function parseSummary(md) {
  const blocks = [];
  let list = null;
  let para = null;
  const flush = () => { list = null; para = null; };
  const item = (raw) => ({ raw, inline: parseInline(raw) });

  for (const line of String(md || "").split(/\r?\n/)) {
    const text = line.trim();
    if (!text) { flush(); continue; }
    let m;
    if ((m = text.match(/^#{1,6}\s+(.*)$/))) {
      flush();
      blocks.push({ type: "h", ...item(m[1].replace(/\s*#+$/, "")) });
    } else if ((m = text.match(/^[-*+]\s+(.*)$/))) {
      if (!list || list.type !== "ul") { list = { type: "ul", items: [] }; blocks.push(list); para = null; }
      list.items.push(item(m[1]));
    } else if ((m = text.match(/^\d+[.)]\s+(.*)$/))) {
      if (!list || list.type !== "ol") { list = { type: "ol", items: [] }; blocks.push(list); para = null; }
      list.items.push(item(m[1]));
    } else if ((m = text.match(/^>\s?(.*)$/))) {
      list = null;
      if (para && para.type === "quote") { para.raw += " " + m[1]; para.inline = parseInline(para.raw); }
      else { para = { type: "quote", ...item(m[1]) }; blocks.push(para); }
    } else if (/^(-{3,}|\*{3,})$/.test(text)) {
      flush();
    } else {
      list = null;
      if (para && para.type === "p") { para.raw += " " + text; para.inline = parseInline(para.raw); }
      else { para = { type: "p", ...item(text) }; blocks.push(para); }
    }
  }
  return blocks;
}

// "**Aisyah**: 4.5 min (62%)" -> { name, minutes, percent }, or null when the line is something else.
const TALK_LINE = /^\*\*(.+?)\*\*:?\s*:?\s*([\d.,]+)\s*min\w*\s*\((\d+(?:[.,]\d+)?)%\)\s*$/i;
export function parseTalkLine(raw) {
  const m = raw.trim().match(TALK_LINE);
  if (!m) return null;
  return { name: m[1].trim(), minutes: parseFloat(m[2].replace(",", ".")), percent: parseFloat(m[3].replace(",", ".")) };
}

// Turn a bullet list whose every item is a speaking-time line into a "talk" block.
export function withTalkBlocks(blocks) {
  return blocks.map((b) => {
    if (b.type !== "ul" || !b.items.length) return b;
    const rows = b.items.map((i) => parseTalkLine(i.raw));
    return rows.every(Boolean) ? { type: "talk", rows } : b;
  });
}

// Match a name printed in the summary to a speaker index: the current custom name, or "Speaker N".
// Returns -1 when it cannot be matched (the bar then uses neutral ink).
export function speakerIndexByName(name, speakerNames, defaultLabel) {
  const wanted = name.trim().toLowerCase();
  for (const [k, v] of Object.entries(speakerNames || {})) {
    if (String(v).trim().toLowerCase() === wanted) return Number(k);
  }
  const m = wanted.match(/^(?:speaker|penutur|pembicara)\s+(\d+)$/);
  if (m) return Number(m[1]) - 1;
  for (let n = 0; n < 16; n++) if (defaultLabel(n).toLowerCase() === wanted) return n;
  return -1;
}
