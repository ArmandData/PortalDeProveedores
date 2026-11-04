/* Asistente del portal: conversación, adjuntos, selección de contrato y panel del caso. */
(() => {
  "use strict";
  const app = document.getElementById("chat-app");
  if (!app) return;

  const $ = (sel, root = document) => root.querySelector(sel);
  const csrf = $('meta[name="csrf-token"]').content;
  const els = {
    list: $("#conv-list"), search: $("#conv-search"), noResults: $("#conv-noresults"),
    title: $("#chat-title"), meta: $("#chat-meta"), pinSlot: $("#contract-pin-slot"),
    messages: $("#messages"), inner: $("#messages-inner"), caseStrip: $("#case-strip"), casePane: $("#case-pane"),
    form: $("#composer"), input: $("#msg-input"), fileInput: $("#file-input"), attach: $("#attach-btn"),
    send: $("#send-btn"), pending: $("#pending-files"), error: $("#composer-error"), hint: $("#composer-hint"),
    drop: $("#drop-overlay"), pane: $("#chat-pane"), back: $("#back-to-list"),
    dialog: $("#contract-dialog"), dialogBody: $("#contract-dialog-body"), tpl: $("#contract-picker-tpl"),
  };
  const ACCEPT = app.dataset.accept.split(",").map((e) => e.replace(".", "").toLowerCase());
  const MAX_MB = Number(app.dataset.maxMb);
  const MAX_FILES = Number(app.dataset.maxFiles);
  const firstName = app.dataset.contact || "";

  const state = {
    convId: app.dataset.conversation ? Number(app.dataset.conversation) : null,
    contract: undefined, // undefined = sin elegir · null = "no relacionado" · objeto = contrato
    lastId: 0,
    files: [],
    sending: false,
    ticket: null,
  };

  const SUGGESTIONS = [
    "¿Cuándo me pagan una factura?",
    "Me rechazaron una factura",
    "Tengo un problema con una entrega",
    "Necesito cambiar mis datos bancarios",
    "Necesito un certificado de retención",
  ];

  // ---------- utilidades ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icon = (name, cls = "") => `<svg class="icon ${cls}" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
  const extOf = (name) => (name.includes(".") ? name.split(".").pop().toLowerCase() : "");
  const human = (n) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`);

  function md(text) {
    let html = esc(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    const out = [];
    let inList = false;
    for (const line of html.split("\n")) {
      if (/^\s*[-•]\s+/.test(line)) {
        if (!inList) { out.push("<ul>"); inList = true; }
        out.push(`<li>${line.replace(/^\s*[-•]\s+/, "")}</li>`);
      } else {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push(line.trim() ? `${line}<br>` : "<br>");
      }
    }
    if (inList) out.push("</ul>");
    return out.join("").replace(/(<br>)+$/, "");
  }

  async function api(url, opts = {}) {
    const res = await fetch(url, { credentials: "same-origin", ...opts, headers: { "X-CSRF-Token": csrf, ...(opts.headers || {}) } });
    let data = null;
    try { data = await res.json(); } catch (_) { /* sin cuerpo */ }
    if (!res.ok) throw new Error((data && data.error) || "No pudimos conectar con el servidor. Revisá tu conexión e intentá de nuevo.");
    return data;
  }

  const scrollToBottom = (smooth = true) => {
    els.messages.scrollTo({ top: els.messages.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  };
  const nearBottom = () => els.messages.scrollHeight - els.messages.scrollTop - els.messages.clientHeight < 120;

  function showError(msg) {
    if (!msg) { els.error.hidden = true; els.error.innerHTML = ""; return; }
    els.error.innerHTML = `<div class="alert alert-error" role="alert">${icon("alert")}<span>${esc(msg)}</span></div>`;
    els.error.hidden = false;
  }

  // ---------- render de mensajes ----------
  function fileCard(a) {
    const ext = a.ext || extOf(a.name);
    return `<a class="file-card" href="${esc(a.url)}" target="_blank" rel="noopener" title="Abrir ${esc(a.name)}">
      <span class="ext ext-${esc(ext)}">${esc(ext.slice(0, 4))}</span>
      <span class="ftxt"><span class="fname">${esc(a.name)}</span><span class="fsize">${esc(a.size)}</span></span></a>`;
  }

  function messageEl(m) {
    const el = document.createElement("div");
    el.dataset.id = m.id || "";
    if (m.role === "system") {
      el.className = "msg msg-system";
      el.innerHTML = `<div class="bubble">${md(m.body)}</div>`;
      return el;
    }
    const files = (m.attachments || []).length ? `<div class="files">${m.attachments.map(fileCard).join("")}</div>` : "";
    const body = m.body ? `<div class="bubble">${md(m.body)}</div>` : "";
    if (m.role === "provider") {
      el.className = "msg msg-me";
      el.innerHTML = `<div class="msg-body"><div class="msg-meta"><time>${esc(m.time || "")}</time></div>${body}${files}</div>`;
    } else if (m.role === "agent") {
      el.className = "msg msg-agent";
      el.innerHTML = `<span class="avatar avatar-team" aria-hidden="true">${icon("users", "icon-sm")}</span>
        <div class="msg-body"><div class="msg-meta"><strong>${esc(m.author || "Equipo")}</strong>${m.team ? `· ${esc(m.team)}` : ""}<time>· ${esc(m.time || "")}</time></div>${body}${files}</div>`;
    } else {
      el.className = "msg msg-bot";
      el.innerHTML = `<span class="avatar avatar-bot" aria-hidden="true">${icon("sparkles", "icon-sm")}</span>
        <div class="msg-body"><div class="msg-meta"><strong>Asistente</strong><time>· ${esc(m.time || "")}</time></div>${body}${files}</div>`;
    }
    return el;
  }

  function appendMessages(list) {
    const stick = nearBottom();
    for (const m of list) {
      if (m.id && els.inner.querySelector(`[data-id="${m.id}"]`)) continue;
      els.inner.appendChild(messageEl(m));
      if (m.id) state.lastId = Math.max(state.lastId, m.id);
    }
    if (stick || list.some((m) => m.role === "provider")) scrollToBottom();
  }

  function typingEl() {
    const el = document.createElement("div");
    el.className = "msg msg-bot";
    el.id = "typing";
    el.innerHTML = `<span class="avatar avatar-bot" aria-hidden="true">${icon("sparkles", "icon-sm")}</span>
      <div class="msg-body"><div class="msg-meta"><strong>Asistente</strong> · analizando tu mensaje…</div>
      <div class="bubble"><span class="typing" aria-label="El asistente está escribiendo"><i></i><i></i><i></i></span></div></div>`;
    return el;
  }

  // ---------- contrato ----------
  function buildPicker(container, onPick, selected) {
    container.innerHTML = "";
    container.appendChild(els.tpl.content.cloneNode(true));
    const search = $("[data-contract-search]", container);
    const empty = $("[data-picker-empty]", container);
    const options = [...container.querySelectorAll(".contract-option")];
    options.forEach((btn) => {
      const raw = btn.dataset.contract;
      const value = raw === "none" ? null : JSON.parse(raw);
      const isSel = selected === undefined ? false : (selected === null ? value === null : value && value.id === selected.id);
      btn.setAttribute("aria-pressed", String(!!isSel));
      btn.addEventListener("click", () => onPick(value));
    });
    if (search) {
      search.addEventListener("input", () => {
        const q = search.value.trim().toLowerCase();
        let shown = 0;
        options.forEach((btn) => {
          const ok = !q || btn.dataset.search.includes(q) || btn.classList.contains("none");
          btn.parentElement.hidden = !ok;
          if (ok && !btn.classList.contains("none")) shown++;
        });
        empty.hidden = shown > 0 || !q;
      });
    }
    return container;
  }

  function renderPin() {
    const c = state.contract;
    if (c === undefined) { els.pinSlot.innerHTML = ""; return; }
    const label = c ? `<strong>${esc(c.numero)}</strong><span class="obj">${esc(c.objeto)}</span>` : `<span>Sin contrato asociado</span>`;
    els.pinSlot.innerHTML = `<span class="contract-pin" title="${c ? esc(c.numero + " · " + c.objeto) : "Consulta no relacionada con un contrato"}">
      ${icon("contract", "icon-sm")}${label}<button type="button" id="change-contract">Cambiar</button></span>`;
    $("#change-contract").addEventListener("click", openContractDialog);
  }

  function openContractDialog() {
    buildPicker(els.dialogBody, async (value) => {
      els.dialog.close();
      if (state.convId) {
        try {
          const fd = new FormData();
          fd.append("contract_id", value ? value.id : "none");
          const data = await api(`/api/conversations/${state.convId}/contract`, { method: "POST", body: fd });
          state.contract = data.contract || null;
          renderPin();
          appendMessages(data.messages.filter((m) => m.id > state.lastId));
          renderCase(data.ticket);
          refreshList();
        } catch (e) { showError(e.message); }
      } else {
        state.contract = value;
        renderPin();
        renderWelcome();
      }
    }, state.contract);
    els.dialog.showModal();
    const first = els.dialogBody.querySelector("[data-contract-search]:not([hidden]), .contract-option");
    if (first) first.focus();
  }
  els.dialog.addEventListener("click", (e) => {
    if (e.target === els.dialog || e.target.closest("[data-close-dialog]")) els.dialog.close();
  });

  // ---------- estados de la vista ----------
  function setComposerEnabled(on, hint) {
    els.input.disabled = !on;
    els.attach.disabled = !on;
    els.form.classList.toggle("is-disabled", !on);
    els.input.placeholder = on ? "Escribí tu consulta o reclamo…" : "Elegí primero el contrato de tu consulta";
    if (hint) els.hint.textContent = hint;
    updateSendState();
  }

  function renderPickerStep() {
    els.title.textContent = "Nueva consulta";
    els.inner.innerHTML = `<div class="picker">
      <div class="picker-hero">
        <span class="avatar avatar-bot" aria-hidden="true">${icon("sparkles")}</span>
        <span class="step-pill">Paso 1 de 2</span>
        <h2>${firstName ? `Hola, ${esc(firstName)}. ` : ""}¿Sobre qué contrato es tu consulta o reclamo?</h2>
        <p>Elegí el contrato para que podamos responderte con sus datos y derivarte al equipo correcto.</p>
      </div><div id="picker-slot"></div></div>`;
    buildPicker($("#picker-slot"), (value) => {
      state.contract = value;
      renderPin();
      renderWelcome();
    }, state.contract);
    setComposerEnabled(false, "Elegí un contrato para empezar");
    renderCase(null);
  }

  function renderWelcome() {
    const c = state.contract;
    const ctx = c ? `sobre el contrato **${c.numero}** (${c.objeto}).` : "que no está relacionada con un contrato.";
    els.inner.innerHTML = "";
    const intro = messageEl({ role: "assistant", body: `¡Perfecto! Contame tu consulta o reclamo ${ctx}\n\nPodés escribir con tus palabras y adjuntar facturas, remitos u otros documentos. Si hace falta, lo derivo al equipo indicado y te doy un número de ticket para el seguimiento.`, time: "ahora" });
    els.inner.appendChild(intro);
    const sug = document.createElement("div");
    sug.className = "welcome";
    sug.innerHTML = `<div class="suggestions" aria-label="Sugerencias">${SUGGESTIONS.map((s) => `<button type="button" class="suggestion">${esc(s)}</button>`).join("")}</div>`;
    sug.addEventListener("click", (e) => {
      const b = e.target.closest(".suggestion");
      if (!b) return;
      els.input.value = b.textContent;
      autosize();
      updateSendState();
      els.input.focus();
    });
    els.inner.appendChild(sug);
    setComposerEnabled(true, `PDF, Word, Excel, TXT, HTML o imágenes · hasta ${MAX_MB} MB c/u`);
    renderCase(null);
    els.input.focus();
  }

  // ---------- panel del caso ----------
  const STEPS = [["nuevo", "Recibido"], ["en_curso", "En revisión del equipo"], ["esperando_proveedor", "Esperando tu respuesta"], ["resuelto", "Resuelto"]];

  function progressHtml(status) {
    const order = { nuevo: 0, en_curso: 1, esperando_proveedor: 2, resuelto: 3, cerrado: 3 };
    const cur = order[status];
    return `<ol class="progress">${STEPS.filter(([s]) => s !== "esperando_proveedor" || status === "esperando_proveedor")
      .map(([s, label]) => {
        const i = order[s];
        const cls = i < cur || (i === cur && i === 3) ? "done" : i === cur ? "current" : "";
        return `<li class="${cls}"><span class="dot"></span>${label}</li>`;
      }).join("")}</ol>`;
  }

  function contractBlock(c) {
    if (c === undefined) return "";
    if (!c) return `<section><h2>Contrato</h2><p class="case-empty">Consulta no relacionada con un contrato.</p></section>`;
    return `<section><h2>Contrato</h2><dl class="dl">
      <dt>Número</dt><dd class="mono"><a href="/contratos/${encodeURIComponent(c.numero)}">${esc(c.numero)}</a></dd>
      <dt>Estado</dt><dd><span class="badge badge-${esc(c.status)}">${esc(c.status_label)}</span></dd>
      <dt>Objeto</dt><dd>${esc(c.objeto)}</dd>
      <dt>Vigencia</dt><dd>${esc(c.vigencia)}</dd>
      <dt>Pago</dt><dd>${esc(c.condicion_pago || "—")}</dd></dl></section>`;
  }

  function renderCase(ticket) {
    state.ticket = ticket;
    const c = state.contract;
    if (ticket) {
      els.casePane.innerHTML = `
        <section><h2>Tu ticket</h2>
          <div class="case-code">${esc(ticket.code)}<button class="copy-btn" type="button" data-copy="${esc(ticket.code)}" aria-label="Copiar número de ticket" title="Copiar">${icon("copy", "icon-sm")}</button></div>
          <p class="muted" style="font-size:14px;margin-top:4px">${esc(ticket.subject)}</p></section>
        <section><h2>Estado</h2>${progressHtml(ticket.status)}</section>
        <section><h2>Detalle</h2><dl class="dl">
          <dt>Tipo</dt><dd>${ticket.kind === "reclamo" ? "Reclamo" : "Consulta"}</dd>
          <dt>Equipo</dt><dd><span class="team-tag"><span class="dot" style="background:${esc(ticket.team_color)}"></span>${esc(ticket.team)}</span></dd>
          <dt>Prioridad</dt><dd><span class="prio prio-${esc(ticket.priority)}"><span class="bars"><i></i><i></i><i></i></span>${esc(ticket.priority_label)}</span></dd>
          <dt>Plazo</dt><dd><span class="sla sla-${esc(ticket.sla_state)}">${esc(ticket.sla_label)}</span></dd>
          ${ticket.reference ? `<dt>Referencia</dt><dd class="mono">${esc(ticket.reference)}</dd>` : ""}
          <dt>Creado</dt><dd>${esc(ticket.created_at)}</dd></dl></section>
        ${contractBlock(c)}`;
      els.caseStrip.innerHTML = `${icon("ticket", "icon-sm")}<span class="mono">${esc(ticket.code)}</span>
        <span class="badge badge-${esc(ticket.status)}">${esc(ticket.status_label)}</span>
        <span class="team-tag"><span class="dot" style="background:${esc(ticket.team_color)}"></span>${esc(ticket.team)}</span>
        <span class="sla sla-${esc(ticket.sla_state)}">${esc(ticket.sla_label)}</span>`;
      els.caseStrip.hidden = false;
      els.meta.innerHTML = "";
    } else {
      els.casePane.innerHTML = `<section class="case-empty"><div class="icon-wrap">${icon("ticket")}</div>
        <h2 style="margin-bottom:6px">Sin ticket todavía</h2>
        <p>Si tu consulta necesita la intervención de un equipo, el asistente va a crear un ticket con su número de seguimiento y lo vas a ver acá.</p></section>
        ${contractBlock(c)}`;
      els.caseStrip.hidden = true;
      els.meta.innerHTML = state.contract === undefined ? `<span>Asistente del portal</span>` : "";
    }
  }

  els.casePane.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-copy]");
    if (!b) return;
    try { await navigator.clipboard.writeText(b.dataset.copy); b.innerHTML = icon("check", "icon-sm"); setTimeout(() => (b.innerHTML = icon("copy", "icon-sm")), 1500); } catch (_) { /* sin permiso */ }
  });

  // ---------- carga de conversación ----------
  async function loadConversation(id) {
    els.inner.innerHTML = `<p class="muted" style="text-align:center">Cargando conversación…</p>`;
    try {
      const data = await api(`/api/conversations/${id}`);
      state.convId = id;
      state.lastId = 0;
      state.contract = data.contract ? data.contract : (data.no_contract ? null : undefined);
      els.title.textContent = data.title;
      els.inner.innerHTML = "";
      appendMessages(data.messages);
      renderPin();
      renderCase(data.ticket);
      setComposerEnabled(true, `PDF, Word, Excel, TXT, HTML o imágenes · hasta ${MAX_MB} MB c/u`);
      scrollToBottom(false);
      markListRead(id);
    } catch (e) {
      els.inner.innerHTML = "";
      showError(e.message);
    }
  }

  async function poll() {
    if (!state.convId || state.sending || document.hidden) return;
    try {
      const data = await api(`/api/conversations/${state.convId}?after=${state.lastId}`);
      if (data.messages.length) appendMessages(data.messages);
      renderCase(data.ticket);
    } catch (_) { /* reintenta en el próximo ciclo */ }
  }
  setInterval(poll, 12000);
  setInterval(() => { if (!document.hidden) refreshList(); }, 30000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });

  // ---------- lista de conversaciones ----------
  function markListRead(id) {
    els.list.querySelectorAll("a[data-conv]").forEach((a) => {
      const on = Number(a.dataset.conv) === id;
      a.toggleAttribute("aria-current", on);
      if (on) a.setAttribute("aria-current", "true");
      if (on) a.parentElement.classList.remove("unread");
    });
  }

  async function refreshList() {
    try {
      const items = await api("/api/conversations");
      if (!items.length) return;
      els.list.innerHTML = items.map((c) => `
        <li class="conv-item ${c.unread ? "unread" : ""}" data-search="${esc((c.title + " " + (c.code || "") + " " + (c.contract || "")).toLowerCase())}">
          <a href="/asistente?c=${c.id}" data-conv="${c.id}" ${c.id === state.convId ? 'aria-current="true"' : ""}>
            <span class="t"><strong>${esc(c.title)}</strong><time>${esc(c.updated)}</time></span>
            <span class="p">${esc(c.preview)}</span>
            ${c.code || c.contract ? `<span class="m">${c.code ? `<span class="badge badge-${esc(c.status)}">${esc(c.status_label)}</span><span class="mono">${esc(c.code)}</span>` : ""}${c.contract ? `<span class="chip-contract">${esc(c.contract)}</span>` : ""}</span>` : ""}
          </a></li>`).join("") + `<li class="conv-empty" id="conv-noresults" hidden>No hay conversaciones que coincidan.</li>`;
      els.noResults = $("#conv-noresults");
      filterList();
    } catch (_) { /* silencioso */ }
  }

  function filterList() {
    const q = els.search.value.trim().toLowerCase();
    let shown = 0;
    els.list.querySelectorAll(".conv-item").forEach((li) => {
      const ok = !q || (li.dataset.search || "").includes(q);
      li.hidden = !ok;
      if (ok) shown++;
    });
    if (els.noResults) els.noResults.hidden = shown > 0 || !q;
  }
  els.search.addEventListener("input", filterList);

  els.list.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-conv]");
    if (!a || e.metaKey || e.ctrlKey) return;
    e.preventDefault();
    const id = Number(a.dataset.conv);
    history.pushState({ c: id }, "", `/asistente?c=${id}`);
    app.classList.remove("show-list");
    clearFiles();
    showError("");
    loadConversation(id);
  });
  window.addEventListener("popstate", () => {
    const id = Number(new URLSearchParams(location.search).get("c"));
    if (id) loadConversation(id); else location.reload();
  });
  els.back.addEventListener("click", () => app.classList.add("show-list"));

  // ---------- adjuntos ----------
  function addFiles(fileList) {
    showError("");
    const problems = [];
    for (const f of fileList) {
      const ext = extOf(f.name);
      if (state.files.length >= MAX_FILES) { problems.push(`Podés adjuntar hasta ${MAX_FILES} archivos por mensaje.`); break; }
      if (!ACCEPT.includes(ext)) { problems.push(`«${f.name}»: el formato .${ext || "?"} no está permitido.`); continue; }
      if (f.size > MAX_MB * 1048576) { problems.push(`«${f.name}»: supera el máximo de ${MAX_MB} MB.`); continue; }
      if (f.size === 0) { problems.push(`«${f.name}»: el archivo está vacío.`); continue; }
      if (state.files.some((x) => x.name === f.name && x.size === f.size)) continue;
      state.files.push(f);
    }
    if (problems.length) showError(problems.join(" "));
    renderFiles();
  }

  function renderFiles() {
    els.pending.hidden = state.files.length === 0;
    els.pending.innerHTML = state.files.map((f, i) => {
      const ext = extOf(f.name);
      return `<span class="pending-file"><span class="ext ext-${esc(ext)}">${esc(ext.slice(0, 4))}</span>
        <span class="ftxt"><span class="fname" title="${esc(f.name)}">${esc(f.name)}</span><span class="fsize">${human(f.size)}</span></span>
        <button type="button" data-remove="${i}" aria-label="Quitar ${esc(f.name)}">${icon("x", "icon-sm")}</button></span>`;
    }).join("");
    updateSendState();
  }
  function clearFiles() { state.files = []; renderFiles(); }

  els.pending.addEventListener("click", (e) => {
    const b = e.target.closest("[data-remove]");
    if (!b) return;
    state.files.splice(Number(b.dataset.remove), 1);
    renderFiles();
    els.input.focus();
  });
  els.attach.addEventListener("click", () => els.fileInput.click());
  els.fileInput.addEventListener("change", () => { addFiles(els.fileInput.files); els.fileInput.value = ""; });

  let dragDepth = 0;
  const canDrop = () => !els.input.disabled;
  els.pane.addEventListener("dragenter", (e) => {
    if (!canDrop() || !e.dataTransfer.types.includes("Files")) return;
    e.preventDefault(); dragDepth++; els.drop.hidden = false;
  });
  els.pane.addEventListener("dragover", (e) => { if (canDrop()) e.preventDefault(); });
  els.pane.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) els.drop.hidden = true; });
  els.pane.addEventListener("drop", (e) => {
    e.preventDefault(); dragDepth = 0; els.drop.hidden = true;
    if (canDrop() && e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  });
  els.input.addEventListener("paste", (e) => {
    if (e.clipboardData && e.clipboardData.files.length) { e.preventDefault(); addFiles(e.clipboardData.files); }
  });

  // ---------- composer ----------
  function autosize() {
    els.input.style.height = "auto";
    els.input.style.height = Math.min(els.input.scrollHeight, 200) + "px";
  }
  function updateSendState() {
    const has = els.input.value.trim().length > 0 || state.files.length > 0;
    els.send.disabled = els.input.disabled || state.sending || !has;
  }
  els.input.addEventListener("input", () => { autosize(); updateSendState(); });
  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!els.send.disabled) els.form.requestSubmit(); }
  });

  els.form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (els.send.disabled) return;
    const text = els.input.value.trim();
    const files = state.files.slice();
    els.input.value = "";
    autosize();
    clearFiles();
    sendMessage(text, files);
  });

  async function sendMessage(text, files, retryEl) {
    showError("");
    state.sending = true;
    updateSendState();
    const welcome = els.inner.querySelector(".welcome");
    if (welcome) welcome.remove();

    const pending = retryEl || messageEl({ role: "provider", body: text, time: "Enviando…",
      attachments: files.map((f) => ({ name: f.name, size: human(f.size), ext: extOf(f.name), url: "#" })) });
    pending.classList.add("pending");
    pending.classList.remove("failed");
    const oldErr = pending.querySelector(".msg-error");
    if (oldErr) oldErr.remove();
    if (!retryEl) els.inner.appendChild(pending);
    const typing = typingEl();
    els.inner.appendChild(typing);
    scrollToBottom();

    const fd = new FormData();
    fd.append("text", text);
    files.forEach((f) => fd.append("files", f, f.name));
    if (!state.convId) fd.append("contract_id", state.contract ? state.contract.id : "none");
    const url = state.convId ? `/api/conversations/${state.convId}/messages` : "/api/conversations/new/messages";

    try {
      const data = await api(url, { method: "POST", body: fd });
      pending.remove();
      typing.remove();
      const isNew = !state.convId;
      state.convId = data.conversation_id;
      if (isNew) history.replaceState({ c: state.convId }, "", `/asistente?c=${state.convId}`);
      els.title.textContent = data.title;
      state.contract = data.contract ? data.contract : (data.no_contract ? null : state.contract);
      renderPin();
      appendMessages(data.messages);
      renderCase(data.ticket);
      refreshList();
    } catch (err) {
      typing.remove();
      pending.classList.remove("pending");
      pending.classList.add("failed");
      const meta = pending.querySelector(".msg-meta time");
      if (meta) meta.textContent = "No enviado";
      const errEl = document.createElement("div");
      errEl.className = "msg-error";
      errEl.innerHTML = `${icon("alert", "icon-sm")}<span>${esc(err.message)}</span><button type="button">Reintentar</button>`;
      errEl.querySelector("button").addEventListener("click", () => sendMessage(text, files, pending));
      pending.querySelector(".msg-body").appendChild(errEl);
    } finally {
      state.sending = false;
      updateSendState();
      els.input.focus();
    }
  }

  // ---------- inicio ----------
  if (state.convId) {
    loadConversation(state.convId);
  } else {
    const pre = app.dataset.preselect;
    if (pre) {
      state.contract = JSON.parse(pre);
      renderPin();
      renderWelcome();
    } else {
      renderPickerStep();
    }
  }
})();
