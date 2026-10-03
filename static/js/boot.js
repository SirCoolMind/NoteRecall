// Runs before first paint: apply the remembered theme override so there is no flash.
// With no override, tokens.css follows the OS via prefers-color-scheme.
(function () {
  try {
    var theme = localStorage.getItem("noterecall.theme");
    if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  } catch (e) { /* storage blocked: follow the OS */ }
})();
