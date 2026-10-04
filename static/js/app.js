// App entry. Loaded before Alpine (document order), so it registers on alpine:init.
import { detectLanguage, saveLanguage, loadDictionaries, translate } from "./i18n.js";
import { registerIcons } from "./icons.js";
import { registerSegmented } from "./segmented.js";
import { createThemeStore } from "./theme.js";
import { registerHome } from "./home.js";
import { registerMeeting } from "./meeting.js";
import { registerSettings } from "./settings.js";
import { registerSetup } from "./setup.js";
import { registerUpdates } from "./updates.js";

document.addEventListener("alpine:init", () => {
  const Alpine = window.Alpine;

  registerIcons(Alpine);
  registerSegmented(Alpine);

  Alpine.store("i18n", {
    lang: "en",
    dicts: {},
    ready: false,
    async init() {
      this.dicts = await loadDictionaries();
      this.set(detectLanguage(), false);
      this.ready = true;
    },
    set(lang, persist = true) {
      this.lang = lang;
      document.documentElement.lang = lang;
      if (persist) saveLanguage(lang);
    },
    t(key, vars) { return translate(this.dicts, this.lang, key, vars); },
  });

  Alpine.store("theme", createThemeStore());

  // $t('key', {var: 1}) in templates; reactive to language changes.
  Alpine.magic("t", () => (key, vars) => Alpine.store("i18n").t(key, vars));

  // Which screen is showing: '#/m/<id>' opens a meeting, anything else is Home.
  const routeFromHash = () => (location.hash.match(/^#\/m\/([\w-]+)$/) || [])[1] || null;
  Alpine.store("route", { id: routeFromHash() });
  window.addEventListener("hashchange", () => { Alpine.store("route").id = routeFromHash(); });

  registerSetup(Alpine);
  registerUpdates(Alpine);
  registerHome(Alpine);
  registerMeeting(Alpine);
  registerSettings(Alpine);

  // '#settings' opens the settings modal on the last-used tab (General by default); '#settings/<tab>' opens that tab.
  // The old /setup and /about pages redirect here, and the older section names still work (checks -> Setup).
  // Closing the modal puts the route that was showing before it back.
  const SETTINGS_HASH = /^#settings(?:\/([\w-]+))?$/;
  const TAB_IDS = ["general", "transcription", "speakers", "summary", "setup", "updates", "about"];
  const TAB_ALIASES = { checks: "setup", engine: "transcription", device: "transcription", defaults: "general", interface: "general" };
  const TAB_KEY = "noterecall.settings.tab";

  const normaliseTab = (name) => {
    const id = TAB_ALIASES[name] || name;
    return TAB_IDS.includes(id) ? id : null;
  };
  const rememberedTab = () => {
    try { return normaliseTab(sessionStorage.getItem(TAB_KEY)); } catch (e) { return null; }
  };

  Alpine.data("shell", () => ({
    modalOpen: false,
    tab: "general",
    tabIds: TAB_IDS,
    _before: "",          // the hash that was showing when the modal opened

    init() {
      const fromHash = (e) => {
        const m = location.hash.match(SETTINGS_HASH);
        if (m) {
          if (!this.modalOpen) this._before = e && e.oldURL ? hashOf(e.oldURL) : "";
          this.openModal(m[1] ? normaliseTab(m[1]) : null, { fromHash: true });
        } else if (this.modalOpen) {
          // The user navigated away (browser Back, another link): just close.
          this.modalOpen = false;
          this.$refs.modal.close();
        }
      };
      window.addEventListener("hashchange", fromHash);
      this.$nextTick(() => fromHash());   // refs and the settings component exist by then
    },

    openModal(tab = null, { fromHash = false } = {}) {
      const wanted = tab || rememberedTab() || "general";
      if (!this.modalOpen) {
        if (!fromHash) this._before = location.hash;
        this.modalOpen = true;
        if (!this.$refs.modal.open) this.$refs.modal.showModal();
        window.dispatchEvent(new CustomEvent("settings-open", { detail: { tab: wanted } }));
      }
      this.selectTab(wanted, { focus: false });
      this.$nextTick(() => {
        if (!fromHash) this.$refs.modalClose.focus();
        else this.activeTabButton()?.focus();
      });
    },

    closeModal() {
      if (this.$refs.modal.open) this.$refs.modal.close();
      else this.onModalClosed();
    },

    // The dialog closed (Esc, close button, backdrop): restore the earlier route and give focus back to the gear.
    onModalClosed() {
      if (!this.modalOpen) return;
      this.modalOpen = false;
      if (SETTINGS_HASH.test(location.hash)) {
        history.replaceState(null, "", location.pathname + location.search + (SETTINGS_HASH.test(this._before) ? "" : this._before));
        Alpine.store("route").id = routeFromHash();
      }
      this.$nextTick(() => this.$refs.gear.focus());
    },

    // A click on the backdrop lands on the dialog element itself.
    onBackdrop(e) { if (e.target === this.$refs.modal) this.closeModal(); },

    // ---- tabs
    activeTabButton() { return this.$refs.tablist.querySelector(`[data-tab="${this.tab}"]`); },
    selectTab(id, { focus = false } = {}) {
      const next = normaliseTab(id) || "general";
      this.tab = next;
      window.dispatchEvent(new CustomEvent("settings-tab", { detail: { tab: next } }));
      try { sessionStorage.setItem(TAB_KEY, next); } catch (e) { /* storage blocked: the tab is just not remembered */ }
      if (this.modalOpen && location.hash !== "#settings/" + next) {
        history.replaceState(null, "", location.pathname + location.search + "#settings/" + next);
      }
      this.$nextTick(() => {
        const btn = this.activeTabButton();
        if (btn) {
          if (focus) btn.focus();
          btn.scrollIntoView({ inline: "nearest", block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
        }
        this.syncFades();
      });
    },
    onTabKey(e) {
      const keys = { ArrowRight: 1, ArrowLeft: -1, Home: "first", End: "last" };
      if (!(e.key in keys) || e.altKey || e.ctrlKey || e.metaKey) return;
      e.preventDefault();
      const at = TAB_IDS.indexOf(this.tab);
      const to = keys[e.key] === "first" ? 0 : keys[e.key] === "last" ? TAB_IDS.length - 1
        : (at + keys[e.key] + TAB_IDS.length) % TAB_IDS.length;
      this.selectTab(TAB_IDS[to], { focus: true });
    },
    // Fade the tab bar's edges only where more tabs are hidden.
    syncFades() {
      const el = this.$refs.tablist;
      const wrap = this.$refs.tabsWrap;
      if (!el || !wrap) return;
      wrap.classList.toggle("has-left", el.scrollLeft > 4);
      wrap.classList.toggle("has-right", el.scrollLeft + el.clientWidth < el.scrollWidth - 4);
    },
  }));

  function hashOf(url) {
    const i = url.indexOf("#");
    return i < 0 ? "" : url.slice(i);
  }
});
