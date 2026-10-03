// i18n core: dictionaries, language detection, lookup with {var} interpolation and en fallback.
// Pure functions; the Alpine store in app.js owns the reactive state.

export const LANGS = ["en", "ms"];
export const FALLBACK = "en";
const STORAGE_KEY = "noterecall.lang";

export function detectLanguage() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (LANGS.includes(saved)) return saved;
  } catch (e) { /* storage blocked */ }
  const nav = (navigator.language || "").toLowerCase();
  return nav.startsWith("ms") ? "ms" : "en";
}

export function saveLanguage(lang) {
  try { localStorage.setItem(STORAGE_KEY, lang); } catch (e) { /* storage blocked */ }
}

export async function loadDictionaries() {
  const entries = await Promise.all(LANGS.map(async (lang) => {
    const res = await fetch(`/static/i18n/${lang}.json`);
    if (!res.ok) throw new Error(`Missing dictionary: ${lang}`);
    return [lang, await res.json()];
  }));
  return Object.fromEntries(entries);
}

// t(key, vars): current language, then English, then the key itself.
export function translate(dicts, lang, key, vars) {
  let text = dicts?.[lang]?.[key] ?? dicts?.[FALLBACK]?.[key] ?? key;
  if (vars) text = text.replace(/\{(\w+)\}/g, (m, name) => (name in vars ? String(vars[name]) : m));
  return text;
}
