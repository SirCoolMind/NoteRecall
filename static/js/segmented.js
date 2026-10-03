// Segmented radio group, shared by Home, the Re-detect dialog and Settings.
//
//   <div x-segmented="{ label: $t('home.opt.speakers'), options: $segOptions('speakers'),
//                       value: speakers, onChange: (v) => speakers = v, disabled: locked }"></div>
//
// The directive draws a role=radiogroup of role=radio buttons. Arrow keys move the selection (as native
// radios do), Home/End jump to the ends, and only the selected segment is in the tab order.
// Config: options [{ value, label, lang? }], value, onChange(value), disabled, label or labelledby.

export const SPEAKER_CHOICES = [2, 3, 4, 5, 6, 7, 8];

// Option lists for the groups this app uses; labels follow the interface language.
export function segOptions(kind, t) {
  if (kind === "language") {
    return [
      { value: "", label: t("home.opt.auto") },
      { value: "ms", label: t("lang.ms.short"), lang: "ms", title: t("lang.ms") },
      { value: "en", label: t("lang.en.short"), lang: "en", title: t("lang.en") },
    ];
  }
  return [{ value: "0", label: t("home.opt.auto") }, ...SPEAKER_CHOICES.map((n) => ({ value: String(n), label: String(n) }))];
}

// Index to select after an arrow/Home/End key, or -1 for a key the group ignores.
export function nextSegment(key, at, count) {
  if (key === "ArrowRight" || key === "ArrowDown") return (at + 1) % count;
  if (key === "ArrowLeft" || key === "ArrowUp") return (at - 1 + count) % count;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return -1;
}

export function registerSegmented(Alpine) {
  Alpine.magic("segOptions", () => (kind) => segOptions(kind, (k) => Alpine.store("i18n").t(k)));

  Alpine.directive("segmented", (el, { expression }, { evaluateLater, effect }) => {
    el.classList.add("pick");
    el.setAttribute("role", "radiogroup");
    const get = evaluateLater(expression);
    let cfg = { options: [], value: "" };
    let buttons = [];

    const choose = (i, focus) => {
      const opt = cfg.options[i];
      if (!opt || cfg.disabled) return;
      if (String(opt.value) !== String(cfg.value)) cfg.onChange?.(opt.value);
      if (focus) buttons[i]?.focus();
    };

    el.addEventListener("keydown", (e) => {
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      const at = buttons.indexOf(document.activeElement);
      const to = at < 0 ? -1 : nextSegment(e.key, at, buttons.length);
      if (to < 0) return;
      e.preventDefault();
      choose(to, true);
    });

    const sync = () => {
      const opts = cfg.options;
      while (buttons.length > opts.length) buttons.pop().remove();
      while (buttons.length < opts.length) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "pick__opt";
        b.setAttribute("role", "radio");
        const i = buttons.length;
        b.addEventListener("click", () => choose(i, false));
        buttons.push(b);
        el.append(b);
      }
      if (cfg.labelledby) { el.setAttribute("aria-labelledby", cfg.labelledby); el.removeAttribute("aria-label"); }
      else { el.setAttribute("aria-label", cfg.label || ""); el.removeAttribute("aria-labelledby"); }
      el.toggleAttribute("aria-disabled", !!cfg.disabled);
      const selected = opts.findIndex((o) => String(o.value) === String(cfg.value));
      opts.forEach((o, i) => {
        const b = buttons[i];
        const on = i === selected;
        if (b.textContent !== o.label) b.textContent = o.label;
        b.disabled = !!cfg.disabled;
        b.setAttribute("aria-checked", String(on));
        b.tabIndex = on || (selected < 0 && i === 0) ? 0 : -1;
        b.classList.toggle("is-on", on);
        if (o.lang) b.lang = o.lang; else b.removeAttribute("lang");
        if (o.title) b.title = o.title; else b.removeAttribute("title");
      });
    };

    effect(() => get((c) => { cfg = c || cfg; sync(); }));
  });
}
