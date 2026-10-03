// The ribbon's player: drives one <audio> element and the On Air playhead.
// While playing, the playhead moves every animation frame, interpolated between the
// browser's coarse currentTime updates, so it glides. With reduced motion it only steps
// on timeupdate. No Alpine in here.
import { clamp } from "./ribbon.js";

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const GLIDE_MS = 260;   // how long a seek's eased jump may run (--t-ui plus slack)

export function createPlayer({ audio, playhead, total, onTick, onState }) {
  let raf = 0, lastTime = -1, lastWall = 0, glideTimer = 0;

  function place(shown, actual) {
    const length = total();
    playhead.style.left = (length > 0 ? clamp(shown / length, 0, 1) * 100 : 0) + "%";
    onTick(actual);
  }

  function frame(now) {
    if (audio.paused) { raf = 0; return; }
    const t = audio.currentTime;
    if (t !== lastTime) { lastTime = t; lastWall = now; }
    const ahead = Math.min((now - lastWall) / 1000, 0.25) * audio.playbackRate;
    place(Math.min(t + ahead, total() || t + ahead), t);
    raf = requestAnimationFrame(frame);
  }

  // The playhead is moved by animation frames while playing; the clock and current line also follow
  // timeupdate, so they stay right when frames are not delivered (hidden tab).
  const sync = () => {
    if (audio.paused || reducedMotion()) place(audio.currentTime, audio.currentTime);
    else onTick(audio.currentTime);
  };
  const onPlay = () => {
    onState(true);
    if (!raf && !reducedMotion()) raf = requestAnimationFrame(frame);
  };
  const onPause = () => { onState(false); sync(); };
  const on = { play: onPlay, pause: onPause, ended: onPause, seeked: sync, timeupdate: sync, loadedmetadata: sync };
  for (const [name, fn] of Object.entries(on)) audio.addEventListener(name, fn);

  return {
    seek(t) {
      const target = clamp(t, 0, total() || t);
      audio.currentTime = target;
      lastTime = -1;
      if (!reducedMotion()) {
        playhead.classList.add("is-glide");
        clearTimeout(glideTimer);
        glideTimer = setTimeout(() => playhead.classList.remove("is-glide"), GLIDE_MS);
      }
      place(target, target);
    },
    toggle() {
      if (audio.paused) audio.play().catch(() => { /* blocked or unsupported: stays paused */ });
      else audio.pause();
    },
    get time() { return audio.currentTime; },
    place() { place(audio.currentTime, audio.currentTime); },
    destroy() {
      cancelAnimationFrame(raf);
      raf = 0;
      clearTimeout(glideTimer);
      for (const [name, fn] of Object.entries(on)) audio.removeEventListener(name, fn);
      audio.pause();
    },
  };
}
