/* Vista de ticket para equipos internos. */
(() => {
  "use strict";
  const thread = document.getElementById("thread");
  if (thread) thread.scrollTop = thread.scrollHeight;
  const text = document.getElementById("reply-text");
  const status = document.getElementById("reply-status");
  document.querySelectorAll('input[name="internal"]').forEach((r) => r.addEventListener("change", () => {
    const internal = r.value === "1" && r.checked;
    if (!r.checked) return;
    text.placeholder = internal ? "Nota visible solo para el equipo…" : "Escribí la respuesta…";
    status.disabled = internal;
    text.focus();
  }));
})();
