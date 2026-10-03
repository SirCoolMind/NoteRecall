// Inline Lucide icons so they inherit currentColor. Files live in static/icons/.
const cache = new Map();

function load(name) {
  if (!cache.has(name)) {
    cache.set(name, fetch(`/static/icons/${name}.svg`)
      .then((res) => { if (!res.ok) throw new Error(`Missing icon: ${name}`); return res.text(); })
      .then((text) => {
        const svg = new DOMParser().parseFromString(text, "image/svg+xml").documentElement;
        ["width", "height", "class"].forEach((attr) => svg.removeAttribute(attr));
        svg.setAttribute("aria-hidden", "true");
        svg.setAttribute("focusable", "false");
        return svg;
      }));
  }
  return cache.get(name);
}

// <span x-icon="'upload'"></span>; the expression may be reactive.
export function registerIcons(Alpine) {
  Alpine.directive("icon", (el, { expression }, { evaluateLater, effect }) => {
    el.classList.add("icon");
    el.setAttribute("aria-hidden", "true");
    const get = evaluateLater(expression);
    let latest = 0;
    effect(() => get(async (name) => {
      const ticket = ++latest;
      const svg = await load(name);
      if (ticket === latest) el.replaceChildren(svg.cloneNode(true));
    }));
  });
}
