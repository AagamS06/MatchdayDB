"use strict";
(() => {
  let selected;
  try { selected = localStorage.getItem("matchday-theme"); } catch { selected = null; }
  const system = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.dataset.theme = ["light", "dark"].includes(selected) ? selected : system;
})();
