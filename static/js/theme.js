// Theme: follows the OS; a remembered override sets data-theme on <html>.
const STORAGE_KEY = "noterecall.theme";

export function createThemeStore() {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  let override = null;
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "light" || saved === "dark") override = saved;
  } catch (e) { /* storage blocked */ }

  return {
    override,
    systemDark: media.matches,
    init() { media.addEventListener("change", (e) => { this.systemDark = e.matches; }); },
    get effective() { return this.override ?? (this.systemDark ? "dark" : "light"); },
    // "system" follows the OS; "light" and "dark" are remembered overrides.
    get mode() { return this.override ?? "system"; },
    set(mode) {
      if (mode === "light" || mode === "dark") {
        this.override = mode;
        document.documentElement.dataset.theme = mode;
        try { localStorage.setItem(STORAGE_KEY, mode); } catch (e) { /* storage blocked */ }
      } else {
        this.override = null;
        delete document.documentElement.dataset.theme;
        try { localStorage.removeItem(STORAGE_KEY); } catch (e) { /* storage blocked */ }
      }
    },
    toggle() {
      this.set(this.effective === "dark" ? "light" : "dark");
    },
  };
}
