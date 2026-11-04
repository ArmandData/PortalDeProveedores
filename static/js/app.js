/* Comportamientos comunes del portal (sin dependencias). */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  document.addEventListener("DOMContentLoaded", () => {
    // Menú lateral en mobile
    const shell = $("#shell"), toggle = $("#nav-toggle"), scrim = $("#nav-scrim");
    const setNav = (open) => {
      if (!shell) return;
      shell.classList.toggle("nav-open", open);
      if (toggle) { toggle.setAttribute("aria-expanded", String(open)); toggle.setAttribute("aria-label", open ? "Cerrar menú" : "Abrir menú"); }
      if (scrim) scrim.hidden = !open;
    };
    if (toggle) toggle.addEventListener("click", () => setNav(!shell.classList.contains("nav-open")));
    if (scrim) scrim.addEventListener("click", () => setNav(false));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") setNav(false); });

    // Avisos: cerrar y ocultar solos los de éxito
    $$(".flash").forEach((f) => {
      const close = () => { f.style.opacity = "0"; setTimeout(() => f.remove(), 200); };
      const b = $("[data-dismiss]", f);
      if (b) b.addEventListener("click", close);
      if (f.classList.contains("flash-success")) setTimeout(close, 5000);
    });

    // Mostrar/ocultar contraseña
    $$("[data-toggle-password]").forEach((b) => {
      b.addEventListener("click", () => {
        const input = document.getElementById(b.dataset.togglePassword);
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        b.setAttribute("aria-pressed", String(show));
        b.setAttribute("aria-label", show ? "Ocultar contraseña" : "Mostrar contraseña");
      });
    });

    // Botón con estado de carga (evita doble envío)
    $$("form").forEach((form) => {
      form.addEventListener("submit", (e) => {
        if (e.defaultPrevented) return;
        const btn = $("[data-loading-text]", form);
        if (btn) { btn.disabled = true; btn.textContent = btn.dataset.loadingText; }
      });
    });

    // Filas clickeables (el enlace principal sigue siendo accesible por teclado)
    $$("tr[data-href]").forEach((tr) => {
      tr.addEventListener("click", (e) => {
        if (e.target.closest("a, button, input, select")) return;
        window.location.href = tr.dataset.href;
      });
    });

    // Filtros que se aplican al cambiar
    $$("[data-autosubmit]").forEach((el) => el.addEventListener("change", () => el.form.requestSubmit()));

    // Foto de perfil: enviar al elegir
    $$("[data-upload-on-change]").forEach((input) => input.addEventListener("change", () => { if (input.files.length) input.form.submit(); }));

    // Confirmaciones
    $$("[data-confirm]").forEach((el) => el.addEventListener("click", (e) => { if (!confirm(el.dataset.confirm)) e.preventDefault(); }));

    // Nombre de archivos elegidos en formularios clásicos
    $$("[data-file-names]").forEach((input) => {
      const out = document.getElementById(input.dataset.fileNames);
      input.addEventListener("change", () => { out.textContent = [...input.files].map((f) => f.name).join(", "); });
    });
  });
})();
