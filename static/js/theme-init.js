/* Aplica el tema antes de pintar la página para evitar parpadeos.
   Usa la elección guardada del usuario o, si no hay, la preferencia del sistema. */
(function () {
  var t = null;
  try { t = localStorage.getItem("portal-theme"); } catch (e) { /* almacenamiento bloqueado */ }
  if (t !== "light" && t !== "dark") {
    t = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.documentElement.setAttribute("data-theme", t);
})();
