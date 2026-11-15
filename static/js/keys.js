// Keys that work anywhere on a meeting page, and the playback speed. No Alpine in here.
//
// The rule for "anywhere": a key acts on the player unless the user is typing, or focus is inside
// a control that already uses that key (a menu, the tabs, the ribbon slider, a dialog).

export const SPEEDS = [0.75, 1, 1.25, 1.5, 1.75, 2];
const SPEED_KEY = "noterecall.speed";

export function loadSpeed() {
  try {
    const saved = Number(localStorage.getItem(SPEED_KEY));
    if (SPEEDS.includes(saved)) return saved;
  } catch (e) { /* storage blocked */ }
  return 1;
}

export function saveSpeed(speed) {
  try { localStorage.setItem(SPEED_KEY, String(speed)); } catch (e) { /* storage blocked */ }
}

// One step slower (-1) or faster (+1); stays at the ends.
export function stepSpeed(speed, dir) {
  const at = SPEEDS.indexOf(speed);
  const from = at < 0 ? SPEEDS.indexOf(1) : at;
  return SPEEDS[Math.min(SPEEDS.length - 1, Math.max(0, from + dir))];
}

// The button cycles upward and wraps: 1 -> 1.25 -> ... -> 2 -> 0.75 -> 1.
export function cycleSpeed(speed) {
  const at = SPEEDS.indexOf(speed);
  return SPEEDS[(at + 1) % SPEEDS.length];
}

export function speedLabel(speed) {
  return String(speed) + "×";
}

const TYPING = "input, textarea, select, [contenteditable]:not([contenteditable='false'])";
const OWN_KEYS = "[role='menu'], [role='tablist'], [role='slider'], [role='radiogroup'], dialog, [role='dialog']";
const PRESSABLE = "button, a[href], summary";

// Which player action a keydown means, or null. `where` describes the focused element:
// { typing, ownKeys, pressable }, as elementContext() returns it.
export function shortcutFor(e, where) {
  if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return null;
  if (where.typing || where.ownKeys) return null;
  switch (e.key) {
    case " ": return where.pressable ? null : "toggle";   // Space on a button presses that button
    case "k": case "K": return "toggle";
    case "ArrowLeft": case "j": case "J": return "back";
    case "ArrowRight": case "l": case "L": return "forward";
    case "[": case "<": case ",": return "slower";
    case "]": case ">": case ".": return "faster";
    case "/": return "find";
    case "?": return "help";
    default: return null;
  }
}

export function elementContext(el) {
  const at = el && typeof el.closest === "function" ? el : null;
  return {
    typing: !!at?.closest(TYPING),
    ownKeys: !!at?.closest(OWN_KEYS),
    pressable: !!at?.closest(PRESSABLE),
  };
}
