// The browser tab's title: progress while a recording is being processed, so the wait can be
// watched from another tab, and a mark when it finished while this tab was in the background.
const APP = "NoteRecall";

// "62% · Weekly ops sync · NoteRecall"; parts that are missing are left out.
export function tabTitle({ name = "", progress = null, mark = "" } = {}) {
  const head = progress === null ? mark : `${Math.round(progress)}%`;
  return [head, name, APP].filter(Boolean).join(" · ");
}

let working = false;   // the last title showed a percentage
let mark = "";         // "✓" or "✗" after a job ended unseen; cleared when the tab is looked at

export function setTabTitle({ name = "", progress = null, failed = false } = {}) {
  if (progress !== null) mark = "";
  else if (working && document.hidden) mark = failed ? "✗" : "✓";
  working = progress !== null;
  document.title = tabTitle({ name, progress, mark });
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden || !mark) return;
  mark = "";
  document.title = document.title.replace(/^[✓✗] · /, "");
});
