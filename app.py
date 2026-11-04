"""Portal de Proveedores — consultas y reclamos con asistente IA y ticketera."""
import functools
import hashlib
import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from markupsafe import Markup, escape
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import ai
import db
import extract

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.environ.get("PORTAL_UPLOADS", os.path.join(BASE_DIR, "data", "uploads"))
AVATAR_DIR = os.path.join(UPLOAD_DIR, "avatars")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

def _secret_key():
    """Clave de sesión: variable de entorno o archivo local persistente (no versionado)."""
    if os.environ.get("PORTAL_SECRET_KEY"):
        return os.environ["PORTAL_SECRET_KEY"]
    path = os.path.join(os.path.dirname(db.DB_PATH), "secret_key")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600), "w") as fh:
            fh.write(secrets.token_hex(32))
    with open(path) as fh:
        return fh.read().strip()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("PORTAL_HTTPS") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=(extract.MAX_FILE_BYTES * extract.MAX_FILES_PER_MESSAGE) + 1024 * 1024,
)
app.teardown_appcontext(db.close_db)
if os.environ.get("PORTAL_HTTPS") == "1":
    # Detrás de un proxy HTTPS (Render, Nginx, etc.): respetar X-Forwarded-Proto/Host
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

STATUS_LABELS = {
    "nuevo": "Nuevo",
    "en_curso": "En curso",
    "esperando_proveedor": "Esperando tu respuesta",
    "resuelto": "Resuelto",
    "cerrado": "Cerrado",
}
STATUS_LABELS_STAFF = dict(STATUS_LABELS, esperando_proveedor="Esperando proveedor")
PRIORITY_LABELS = {"baja": "Baja", "media": "Media", "alta": "Alta", "urgente": "Urgente"}
PRIORITY_ORDER = list(PRIORITY_LABELS)
KIND_LABELS = {"reclamo": "Reclamo", "consulta": "Consulta"}
CONTRACT_STATUS_LABELS = {"vigente": "Vigente", "por_vencer": "Por vencer", "vencido": "Vencido", "rescindido": "Rescindido"}
CONTRACT_TYPE_LABELS = {"suministro": "Suministro", "servicios": "Servicios", "obra": "Obra", "marco": "Acuerdo marco"}
CONTRACT_ORDER = {"vigente": 0, "por_vencer": 1, "vencido": 2, "rescindido": 3}
OPEN_STATUSES = ("nuevo", "en_curso", "esperando_proveedor")
MAX_LOGIN_ATTEMPTS = 5
LOCK_MINUTES = 15


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def valid_cuit(cuit):
    digits = re.sub(r"\D", "", cuit or "")
    if len(digits) != 11:
        return False
    weights = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    total = sum(int(d) * w for d, w in zip(digits[:10], weights))
    check = 11 - (total % 11)
    check = 0 if check == 11 else (9 if check == 10 else check)
    return check == int(digits[10])


def parse_dt(value):
    return datetime.fromisoformat(value) if value else None


@app.template_filter("fecha")
def fmt_fecha(value, with_time=True):
    dt = parse_dt(value) if isinstance(value, str) else value
    if not dt:
        return "—"
    return dt.strftime("%d/%m/%Y %H:%M" if with_time else "%d/%m/%Y")


@app.template_filter("relativa")
def fmt_relativa(value):
    dt = parse_dt(value) if isinstance(value, str) else value
    if not dt:
        return ""
    secs = (datetime.now() - dt).total_seconds()
    if secs < 60:
        return "recién"
    if secs < 3600:
        return f"hace {int(secs // 60)} min"
    if secs < 86400:
        return f"hace {int(secs // 3600)} h"
    if secs < 86400 * 7:
        d = int(secs // 86400)
        return f"hace {d} día{'s' if d > 1 else ''}"
    return dt.strftime("%d/%m/%Y")


@app.template_filter("horas")
def fmt_horas(h):
    """Plazo en horas, legible: 4 h, 24 h, 3 días."""
    if h is None:
        return "—"
    if h >= 48 and h % 24 == 0:
        return f"{h // 24} días"
    return f"{h} h"


@app.template_filter("tamano")
def fmt_tamano(n):
    return extract.human_size(n)


@app.template_filter("iniciales")
def iniciales(name):
    parts = [p for p in re.split(r"\s+", (name or "").strip()) if p and p[0].isalnum()]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


@app.template_filter("cbu_mask")
def cbu_mask(cbu):
    return f"•••• •••• {cbu[-4:]}" if cbu and len(cbu) >= 4 else "—"


def sla_state(ticket):
    if ticket["status"] in ("resuelto", "cerrado"):
        return "ok", "Cumplido" if ticket["resolved_at"] and ticket["resolved_at"] <= ticket["sla_due"] else "Fuera de plazo"
    remaining = (parse_dt(ticket["sla_due"]) - datetime.now()).total_seconds() / 3600
    if remaining < 0:
        return "late", f"Vencido hace {abs(int(remaining))} h"
    if remaining < 8:
        return "warn", f"Vence en {int(remaining)} h"
    return "ok", f"Vence {fmt_fecha(ticket['sla_due'])}"


def fmt_money(amount, currency="ARS"):
    s = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'US$' if currency == 'USD' else '$'} {s}"


def contract_view(c):
    """Contrato como dict con estado efectivo y textos listos para mostrar."""
    if c is None:
        return None
    d = dict(c)
    d["status"] = db.contract_status(c)
    d["status_label"] = CONTRACT_STATUS_LABELS[d["status"]]
    d["tipo_label"] = CONTRACT_TYPE_LABELS.get(d["tipo"], d["tipo"])
    d["vigencia"] = f"{fmt_fecha(d['fecha_inicio'] + ' 00:00:00', False)} – {fmt_fecha(d['fecha_fin'] + ' 00:00:00', False)}"
    d["monto_fmt"] = fmt_money(d["monto"], d["moneda"])
    d["days_left"] = (datetime.fromisoformat(d["fecha_fin"]).date() - datetime.now().date()).days
    start, end = datetime.fromisoformat(d["fecha_inicio"]).date(), datetime.fromisoformat(d["fecha_fin"]).date()
    span = max((end - start).days, 1)
    d["progress"] = max(0, min(100, round((datetime.now().date() - start).days * 100 / span)))
    return d


def provider_contracts(provider_id):
    rows = db.query("""SELECT c.*, tm.name AS team_name, tm.slug AS team_slug FROM contracts c LEFT JOIN teams tm ON tm.id=c.team_id
                       WHERE c.provider_id=?""", (provider_id,))
    items = [contract_view(r) for r in rows]
    return sorted(items, key=lambda c: (CONTRACT_ORDER[c["status"]], c["fecha_fin"] if c["status"] in ("vigente", "por_vencer") else "", c["numero"]))


def own_contract(contract_id, provider_id):
    row = db.query("""SELECT c.*, tm.name AS team_name, tm.slug AS team_slug FROM contracts c LEFT JOIN teams tm ON tm.id=c.team_id
                      WHERE c.id=? AND c.provider_id=?""", (contract_id, provider_id), one=True)
    return contract_view(row)


def serialize_contract(c):
    if not c:
        return None
    return {k: c[k] for k in ("id", "numero", "objeto", "tipo_label", "vigencia", "status", "status_label",
                              "monto_fmt", "condicion_pago", "team_name", "days_left", "yacimiento")}


DOC_STATUS_LABELS = {"vigente": "Vigente", "por_vencer": "Por vencer", "vencido": "Vencido", "permanente": "Sin vencimiento"}
DOC_ORDER = {"vencido": 0, "por_vencer": 1, "vigente": 2, "permanente": 3}


def provider_documents(provider_id):
    """Documentación del proveedor con estado calculado, ordenada por urgencia."""
    items = []
    for r in db.query("SELECT * FROM provider_documents WHERE provider_id=? ORDER BY categoria, nombre", (provider_id,)):
        d = dict(r)
        d["status"], d["days_left"] = db.document_status(r)
        d["status_label"] = DOC_STATUS_LABELS[d["status"]]
        d["vence_fmt"] = fmt_fecha(d["vence"] + " 00:00:00", False) if d["vence"] else "—"
        items.append(d)
    items.sort(key=lambda d: (DOC_ORDER[d["status"]], d["days_left"] if d["days_left"] is not None else 99999))
    summary = {k: sum(1 for d in items if d["status"] == k) for k in DOC_STATUS_LABELS}
    summary["bloqueantes"] = sum(1 for d in items if d["status"] == "vencido" and d["bloquea_ingreso"])
    return items, summary


app.jinja_env.globals.update(STATUS_LABELS=STATUS_LABELS, STATUS_LABELS_STAFF=STATUS_LABELS_STAFF,
                             PRIORITY_LABELS=PRIORITY_LABELS, KIND_LABELS=KIND_LABELS, sla_state=sla_state, ai_enabled=ai.ai_enabled,
                             company=ai.COMPANY, CONTRACT_STATUS_LABELS=CONTRACT_STATUS_LABELS,
                             DOC_STATUS_LABELS=DOC_STATUS_LABELS)


# ---------------------------------------------------------------------------
# Seguridad: CSRF, cabeceras, autenticación
# ---------------------------------------------------------------------------
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def load_user_and_check_csrf():
    g.user = None
    uid = session.get("uid")
    if uid:
        g.user = db.query("SELECT * FROM users WHERE id=?", (uid,), one=True)
        if g.user is None:
            session.clear()
    if request.method == "POST":
        token = request.headers.get("X-CSRF-Token") or request.form.get("_csrf")
        if not token or not secrets.compare_digest(token, session.get("_csrf", "")):
            if request.path.startswith("/api/"):
                return jsonify(error="La sesión expiró. Recargá la página."), 400
            flash("La sesión expiró. Volvé a intentarlo.", "error")
            return redirect(request.referrer or url_for("login"))


@app.after_request
def security_headers(resp):
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "frame-ancestors 'none'; form-action 'self'; base-uri 'self'")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["X-Frame-Options"] = "DENY"
    return resp


def login_required(*roles):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            if g.user is None:
                if request.path.startswith("/api/"):
                    return jsonify(error="No autenticado"), 401
                return redirect(url_for("login", next=request.path))
            if roles and g.user["role"] not in roles:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


def current_provider():
    return db.query("SELECT * FROM providers WHERE id=?", (g.user["provider_id"],), one=True)


@app.context_processor
def inject_nav():
    ctx = {}
    if g.get("user") and g.user["role"] == "provider":
        ctx["nav_provider"] = current_provider()
        ctx["nav_unread"] = db.query(
            """SELECT COUNT(*) AS n FROM messages m JOIN conversations c ON c.id=m.conversation_id
               WHERE c.provider_id=? AND m.role='agent' AND m.internal=0
               AND m.created_at > COALESCE(c.provider_seen_at, '')""",
            (g.user["provider_id"],), one=True)["n"]
        ctx["nav_open"] = db.query(
            f"SELECT COUNT(*) AS n FROM tickets WHERE provider_id=? AND status IN ({','.join('?' * len(OPEN_STATUSES))})",
            (g.user["provider_id"], *OPEN_STATUSES), one=True)["n"]
        _, docs_summary = provider_documents(g.user["provider_id"])
        ctx["nav_docs_alert"] = docs_summary["vencido"] + docs_summary["por_vencer"]
        ctx["nav_docs_summary"] = docs_summary
    elif g.get("user"):
        ctx["nav_team"] = db.query("SELECT * FROM teams WHERE id=?", (g.user["team_id"],), one=True) if g.user["team_id"] else None
        ctx["nav_open"] = db.query(
            f"SELECT COUNT(*) AS n FROM tickets WHERE status IN ({','.join('?' * len(OPEN_STATUSES))})"
            + (" AND team_id=?" if g.user["team_id"] else ""),
            (*OPEN_STATUSES, *([g.user["team_id"]] if g.user["team_id"] else [])), one=True)["n"]
    return ctx


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("home"))
    error = None
    username = ""
    if request.method == "POST":
        username = re.sub(r"[\s\-]", "", request.form.get("username", "")).lower()
        password = request.form.get("password", "")
        user = db.query("SELECT * FROM users WHERE lower(username)=? OR lower(email)=?", (username, username), one=True)
        if user and user["locked_until"] and parse_dt(user["locked_until"]) > datetime.now():
            error = f"Por seguridad, la cuenta quedó bloqueada temporalmente. Probá de nuevo en {LOCK_MINUTES} minutos."
        elif user and check_password_hash(user["password_hash"], password):
            db.execute("UPDATE users SET failed_logins=0, locked_until=NULL, last_login=? WHERE id=?", (db.now_iso(), user["id"]))
            session.clear()
            session.permanent = request.form.get("remember") == "on"
            session["uid"] = user["id"]
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("home"))
        else:
            if user:
                fails = user["failed_logins"] + 1
                lock = (datetime.now() + timedelta(minutes=LOCK_MINUTES)).isoformat(sep=" ") if fails >= MAX_LOGIN_ATTEMPTS else None
                db.execute("UPDATE users SET failed_logins=?, locked_until=? WHERE id=?", (0 if lock else fails, lock, user["id"]))
            error = "El usuario o la contraseña no son correctos."
    return render_template("login.html", error=error, username=username)


@app.post("/logout")
def logout():
    session.clear()
    flash("Cerraste sesión correctamente.", "success")
    return redirect(url_for("login"))


@app.route("/")
@login_required()
def home():
    return redirect(url_for("assistant") if g.user["role"] == "provider" else url_for("staff_inbox"))


# ---------------------------------------------------------------------------
# Proveedor: asistente (chat)
# ---------------------------------------------------------------------------
def own_conversation(conv_id):
    conv = db.query("SELECT * FROM conversations WHERE id=?", (conv_id,), one=True)
    if conv is None or (g.user["role"] == "provider" and conv["provider_id"] != g.user["provider_id"]):
        abort(404)
    return conv


def ticket_for_conversation(conv_id):
    return db.query("""SELECT t.*, tm.name AS team_name, tm.color AS team_color, tm.sla_hours,
                       u.full_name AS assignee_name, ct.numero AS contract_numero
                       FROM tickets t JOIN teams tm ON tm.id=t.team_id LEFT JOIN users u ON u.id=t.assignee_id
                       LEFT JOIN contracts ct ON ct.id=t.contract_id
                       WHERE t.conversation_id=?""", (conv_id,), one=True)


def serialize_ticket(t):
    if not t:
        return None
    # El plazo (SLA) es interno: no se envía al proveedor.
    return dict(code=t["code"], subject=t["subject"], status=t["status"], status_label=STATUS_LABELS[t["status"]],
                priority=t["priority"], priority_label=PRIORITY_LABELS[t["priority"]], kind=t["kind"],
                team=t["team_name"], team_color=t["team_color"],
                reference=t["reference"] or "", created_at=fmt_fecha(t["created_at"]),
                contract=t["contract_numero"] or "", location=t["location"] or "",
                assignee=t["assignee_name"] or "Sin asignar", summary=t["summary"])


# Mensajes de tickets creados antes de ocultar el plazo al proveedor.
_SLA_LINE = re.compile(r"^- Plazo de respuesta:.*\n?", re.M)


def serialize_messages(conv_id, include_internal=False, after_id=0):
    rows = db.query(
        f"""SELECT m.*, u.full_name AS author_name, tm.name AS author_team FROM messages m
            LEFT JOIN users u ON u.id=m.author_id LEFT JOIN teams tm ON tm.id=u.team_id
            WHERE m.conversation_id=? AND m.id>? {'' if include_internal else 'AND m.internal=0'} ORDER BY m.id""",
        (conv_id, after_id))
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    atts = db.query(f"SELECT * FROM attachments WHERE message_id IN ({','.join('?' * len(ids))})", ids)
    by_msg = {}
    for a in atts:
        by_msg.setdefault(a["message_id"], []).append(dict(
            id=a["id"], name=a["original_name"], size=extract.human_size(a["size"]),
            ext=extract.extension(a["original_name"]), url=url_for("download", att_id=a["id"]),
            is_image=a["mime"].startswith("image/")))
    return [dict(id=r["id"], role=r["role"],
                 body=_SLA_LINE.sub("", r["body"]) if r["role"] == "assistant" else r["body"], internal=bool(r["internal"]),
                 author=r["author_name"], team=r["author_team"], time=fmt_fecha(r["created_at"]),
                 iso=r["created_at"], attachments=by_msg.get(r["id"], [])) for r in rows]


def list_conversations(provider_id):
    return db.query(
        """SELECT c.id, c.title, c.updated_at, t.code, t.status, ct.numero AS contract_numero,
           (SELECT body FROM messages WHERE conversation_id=c.id AND internal=0 ORDER BY id DESC LIMIT 1) AS last_body,
           (SELECT COUNT(*) FROM messages WHERE conversation_id=c.id AND role='agent' AND internal=0
              AND created_at > COALESCE(c.provider_seen_at,'')) AS unread
           FROM conversations c LEFT JOIN tickets t ON t.conversation_id=c.id
           LEFT JOIN contracts ct ON ct.id=c.contract_id
           WHERE c.provider_id=? ORDER BY c.updated_at DESC LIMIT 100""", (provider_id,))


@app.route("/asistente")
@login_required("provider")
def assistant():
    conv_id = request.args.get("c", type=int)
    conv = own_conversation(conv_id) if conv_id else None
    preselect, no_contract = None, False
    if not conv and request.args.get("contrato", type=int):
        preselect = own_contract(request.args.get("contrato", type=int), g.user["provider_id"])
    elif not conv and request.args.get("sin_contrato") == "1":
        no_contract = True
    prefill = (request.args.get("texto") or "")[:500] if not conv else ""
    return render_template("assistant.html", conversations=list_conversations(g.user["provider_id"]),
                           active=conv, contracts=provider_contracts(g.user["provider_id"]),
                           preselect=serialize_contract(preselect), preselect_none=no_contract, prefill=prefill,
                           accept=",".join("." + e for e in extract.ALLOWED),
                           max_mb=extract.MAX_FILE_BYTES // (1024 * 1024), max_files=extract.MAX_FILES_PER_MESSAGE)


@app.get("/api/conversations")
@login_required("provider")
def api_conversations():
    return jsonify([dict(id=c["id"], title=c["title"], code=c["code"], status=c["status"],
                         contract=c["contract_numero"] or "",
                         status_label=STATUS_LABELS.get(c["status"], ""), updated=fmt_relativa(c["updated_at"]),
                         preview=(c["last_body"] or "").replace("**", "")[:90], unread=c["unread"])
                    for c in list_conversations(g.user["provider_id"])])


@app.get("/api/conversations/<int:conv_id>")
@login_required("provider")
def api_conversation(conv_id):
    conv = own_conversation(conv_id)
    db.execute("UPDATE conversations SET provider_seen_at=? WHERE id=?", (db.now_iso(), conv_id))
    contract = own_contract(conv["contract_id"], conv["provider_id"]) if conv["contract_id"] else None
    return jsonify(id=conv["id"], title=conv["title"], contract=serialize_contract(contract),
                   no_contract=bool(conv["no_contract"]),
                   messages=serialize_messages(conv_id, after_id=request.args.get("after", 0, type=int)),
                   ticket=serialize_ticket(ticket_for_conversation(conv_id)))


def parse_contract_choice(value):
    """'none' = sin contrato; id numérico = contrato propio. Devuelve (contract|None, no_contract, error)."""
    value = (value or "").strip()
    if value == "none":
        return None, True, None
    if not value.isdigit():
        return None, False, "Elegí el contrato al que se refiere tu consulta o indicá que no está relacionada con uno."
    contract = own_contract(int(value), g.user["provider_id"])
    if contract is None:
        return None, False, "El contrato elegido no existe o no pertenece a tu empresa."
    return contract, False, None


@app.post("/api/conversations/<int:conv_id>/contract")
@login_required("provider")
def api_change_contract(conv_id):
    conv = own_conversation(conv_id)
    contract, no_contract, err = parse_contract_choice(request.form.get("contract_id"))
    if err:
        return jsonify(error=err), 400
    new_id = contract["id"] if contract else None
    if new_id != conv["contract_id"] or no_contract != bool(conv["no_contract"]):
        ts = db.now_iso()
        db.execute("UPDATE conversations SET contract_id=?, no_contract=?, updated_at=? WHERE id=?",
                   (new_id, 1 if no_contract else 0, ts, conv_id))
        label = f"el contrato **{contract['numero']}**" if contract else "**ningún contrato**"
        db.execute("INSERT INTO messages (conversation_id, role, body, created_at) VALUES (?,?,?,?)",
                   (conv_id, "system", f"Cambiaste la referencia de esta conversación a {label}.", ts))
        ticket = ticket_for_conversation(conv_id)
        if ticket:
            db.execute("UPDATE tickets SET contract_id=?, updated_at=? WHERE id=?", (new_id, ts, ticket["id"]))
            log_event(ticket["id"], "contract", f"Contrato cambiado por el proveedor a {contract['numero'] if contract else 'ninguno'}")
    return api_conversation(conv_id)


def next_ticket_code():
    year = datetime.now().year
    row = db.query("SELECT code FROM tickets WHERE code LIKE ? ORDER BY id DESC LIMIT 1", (f"PRV-{year}-%",), one=True)
    n = int(row["code"].rsplit("-", 1)[1]) + 1 if row else 1
    return f"PRV-{year}-{n:05d}"


def log_event(ticket_id, event, detail=None):
    db.execute("INSERT INTO ticket_events (ticket_id, actor_id, event, detail, created_at) VALUES (?,?,?,?,?)",
               (ticket_id, g.user["id"] if g.get("user") else None, event, detail, db.now_iso()))


def file_fingerprints(data, extracted_text):
    """Huella del archivo (bytes exactos) y de su contenido (texto normalizado).
    La segunda detecta el mismo documento guardado o exportado de nuevo con otro nombre."""
    sha = hashlib.sha256(data).hexdigest()
    norm = re.sub(r"\s+", " ", (extracted_text or "")).strip().lower()
    content = hashlib.sha256(norm.encode()).hexdigest() if len(norm) >= 200 else None
    return sha, content


def save_attachments(message_id, files):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    for f in files:
        stored = f"{uuid.uuid4().hex}.{extract.extension(f['original_name'])}"
        with open(os.path.join(UPLOAD_DIR, stored), "wb") as fh:
            fh.write(f["data"])
        sha, content = file_fingerprints(f["data"], f["extracted_text"])
        db.execute("""INSERT INTO attachments (message_id, original_name, stored_name, mime, size, extracted_text, created_at,
                      sha256, content_hash) VALUES (?,?,?,?,?,?,?,?,?)""",
                   (message_id, f["original_name"], stored, f["mime"], f["size"], f["extracted_text"], db.now_iso(), sha, content))


def find_duplicate_attachments(provider_id, files, exclude_conv_id):
    """Adjuntos nuevos que ya están en otro ticket ABIERTO del mismo proveedor.
    Devuelve una lista de dict(name, code, status, subject), uno por archivo y ticket."""
    if not files:
        return []
    found, seen = [], set()
    for f in files:
        sha, content = file_fingerprints(f["data"], f["extracted_text"])
        rows = db.query(
            f"""SELECT DISTINCT t.code, t.status, t.subject, a.original_name AS prev_name FROM attachments a
                JOIN messages m ON m.id=a.message_id JOIN conversations c ON c.id=m.conversation_id
                JOIN tickets t ON t.conversation_id=c.id
                WHERE c.provider_id=? AND c.id<>? AND t.status IN ({','.join('?' * len(OPEN_STATUSES))})
                AND (a.sha256=? OR (? IS NOT NULL AND a.content_hash=?))
                ORDER BY t.created_at DESC""",
            (provider_id, exclude_conv_id or 0, *OPEN_STATUSES, sha, content, content))
        for r in rows:
            if (f["original_name"], r["code"]) not in seen:
                seen.add((f["original_name"], r["code"]))
                found.append(dict(name=f["original_name"], prev_name=r["prev_name"], code=r["code"],
                                  status=STATUS_LABELS[r["status"]], subject=r["subject"]))
    return found


def duplicate_notice(dups):
    lines = [f"- «{d['name']}» ya está en el ticket **{d['code']}** ({d['subject']}), estado: {d['status']}." for d in dups]
    return "\n".join(lines)


# El proveedor confirma que, aunque el documento se repita, es un pedido distinto.
_DUP_CONFIRM = re.compile(r"\b(distint|diferente|otro (pedido|reclamo|caso|tema|ticket)|otra (consulta|solicitud|factura)|nuevo ticket|"
                          r"abr[ií] (uno|otro|un nuevo)|s[ií],? (abr|cre|registr)|igual (abr|cre|registr)|no es el mismo)", re.I)


def backfill_attachment_hashes():
    """Calcula las huellas de adjuntos guardados antes de esta versión (se ejecuta una vez al iniciar)."""
    with app.app_context():
        rows = db.query("SELECT id, stored_name, extracted_text FROM attachments WHERE sha256 IS NULL")
        for r in rows:
            path = os.path.join(UPLOAD_DIR, r["stored_name"])
            if os.path.exists(path):
                with open(path, "rb") as fh:
                    sha, content = file_fingerprints(fh.read(), r["extracted_text"])
                db.execute("UPDATE attachments SET sha256=?, content_hash=? WHERE id=?", (sha, content, r["id"]))


def read_uploads():
    """Valida y lee los archivos del request. Devuelve (lista, error)."""
    files = [f for f in request.files.getlist("files") if f and f.filename]
    if len(files) > extract.MAX_FILES_PER_MESSAGE:
        return None, f"Podés adjuntar hasta {extract.MAX_FILES_PER_MESSAGE} archivos por mensaje."
    out = []
    for f in files:
        name = secure_filename(f.filename) or "archivo"
        # secure_filename elimina acentos; conservamos el nombre visible original saneado
        display = re.sub(r"[^\w\s.\-()áéíóúñÁÉÍÓÚÑüÜ]", "_", f.filename)[:150]
        data = f.read()
        ok, err = extract.validate(name, data)
        if not ok:
            return None, f"«{display}»: {err}"
        mime, kind = extract.ALLOWED[extract.extension(name)]
        out.append(dict(original_name=display, data=data, mime=mime, kind=kind, size=len(data),
                        extracted_text=extract.extract_text(name, data)))
    return out, None


@app.post("/api/conversations/<int:conv_id>/messages")
@app.post("/api/conversations/new/messages", defaults={"conv_id": None})
@login_required("provider")
def api_send(conv_id):
    text = (request.form.get("text") or "").strip()[:8000]
    files, err = read_uploads()
    if err:
        return jsonify(error=err), 400
    if not text and not files:
        return jsonify(error="Escribí un mensaje o adjuntá al menos un archivo."), 400

    provider = current_provider()
    ts = db.now_iso()
    if conv_id is None:
        contract, no_contract, err = parse_contract_choice(request.form.get("contract_id"))
        if err:
            return jsonify(error=err), 400
        title = (text.split("\n")[0][:70] if text else f"Envío de {files[0]['original_name']}")
        conv_id = db.execute(
            """INSERT INTO conversations (provider_id, contract_id, no_contract, title, created_at, updated_at, provider_seen_at)
               VALUES (?,?,?,?,?,?,?)""",
            (provider["id"], contract["id"] if contract else None, 1 if no_contract else 0, title, ts, ts, ts))
    conv = own_conversation(conv_id)
    contract = own_contract(conv["contract_id"], provider["id"]) if conv["contract_id"] else None
    ticket = ticket_for_conversation(conv_id)

    history = serialize_messages(conv_id)
    for m in history:
        m["attachments"] = [dict(original_name=a["name"], extracted_text=(
            db.query("SELECT extracted_text FROM attachments WHERE id=?", (a["id"],), one=True)["extracted_text"]))
            for a in m["attachments"]]
    last_id = history[-1]["id"] if history else 0

    dups = find_duplicate_attachments(provider["id"], files, conv_id)
    msg_id = db.execute("INSERT INTO messages (conversation_id, role, author_id, body, created_at) VALUES (?,?,?,?,?)",
                        (conv_id, "provider", g.user["id"], text, ts))
    save_attachments(msg_id, files)

    if dups and not ticket and not conv["dup_warned"]:
        # Antes de abrir otro ticket, avisar que el documento ya está en una solicitud abierta.
        codes = sorted({d["code"] for d in dups})
        reply = ("Antes de registrar un nuevo pedido, te aviso que ya recibimos este documento en una solicitud que sigue abierta:\n"
                 + duplicate_notice(dups)
                 + f"\n\nPara no duplicar la solicitud, seguí el caso desde **{codes[0]}** (lo encontrás en **Mis tickets**): "
                   "ahí podés sumar información o preguntar por el estado. "
                   "Si se trata de un pedido distinto, contame qué necesitás y lo registro como uno nuevo.")
        db.execute("UPDATE conversations SET dup_warned=? WHERE id=?", (",".join(codes), conv_id))
        db.execute("INSERT INTO messages (conversation_id, role, body, created_at) VALUES (?,?,?,?)",
                   (conv_id, "assistant", reply, db.now_iso()))
        db.execute("UPDATE conversations SET updated_at=?, provider_seen_at=? WHERE id=?", (db.now_iso(), db.now_iso(), conv_id))
        return jsonify(conversation_id=conv_id, title=db.query("SELECT title FROM conversations WHERE id=?", (conv_id,), one=True)["title"],
                       messages=serialize_messages(conv_id, after_id=last_id), ticket=None,
                       contract=serialize_contract(contract), no_contract=bool(conv["no_contract"]),
                       duplicates=[d["code"] for d in dups])

    teams = [dict(t) for t in db.query("SELECT * FROM teams ORDER BY id")]
    case_types = active_case_types()
    documents, _ = provider_documents(provider["id"])
    result = ai.analyze(provider, teams, history, text, files, ticket=dict(ticket) if ticket else None,
                        contract=contract, documents=documents, case_types=case_types)
    location = (result.get("location") or "").strip() or (contract["yacimiento"] if contract and contract.get("yacimiento") else "")
    reply = result["reply"].strip()
    warned = (conv["dup_warned"] or "").split(",") if conv["dup_warned"] else []
    if warned and not ticket and result.get("create_ticket") and result.get("engine") == "local" and not _DUP_CONFIRM.search(text or ""):
        # Sin IA no podemos interpretar la respuesta: solo abrimos un ticket nuevo si el proveedor lo confirma.
        result["create_ticket"] = False
        reply = (f"Perfecto. Seguimos el caso en **{warned[0]}**: podés abrirlo desde **Mis tickets** para sumar información. "
                 "Si en cambio es un pedido distinto, escribime «es otro pedido» y contame qué necesitás.")
    if ticket and dups:
        reply += "\n\nTe aviso que este documento también está en otra solicitud abierta:\n" + duplicate_notice(dups)

    if ticket:
        updates = {"updated_at": ts}
        if ticket["status"] in ("esperando_proveedor", "resuelto"):
            updates["status"] = "en_curso"
            log_event(ticket["id"], "status", f"{ticket['status']} → en_curso (respuesta del proveedor)")
        db.execute(f"UPDATE tickets SET {', '.join(k + '=?' for k in updates)} WHERE id=?", (*updates.values(), ticket["id"]))
    elif result.get("create_ticket"):
        team = next(t for t in teams if t["slug"] == result["team"])
        # El tipo de caso define equipo, tipo, prioridad mínima y plazos (internos).
        ctype = next((c for c in case_types if c["id"] == result.get("case_type")), None) \
            or ai.match_case_type(case_types, team["id"], f"{text} {result.get('summary', '')}")
        kind = result["kind"] if result["kind"] in ("consulta", "reclamo") else "consulta"
        priority = result["priority"]
        now = datetime.now().replace(microsecond=0)
        if ctype:
            team = next((t for t in teams if t["id"] == ctype["team_id"]), team)
            kind = ctype["kind"]
            priority = max(priority, ctype["priority"], key=PRIORITY_ORDER.index)
            sla_due, response_due = now + timedelta(hours=ctype["resolution_hours"]), now + timedelta(hours=ctype["response_hours"])
        else:
            sla_due, response_due = now + timedelta(hours=team["sla_hours"]), None
        code = next_ticket_code()
        tid = db.execute(
            """INSERT INTO tickets (code, provider_id, conversation_id, contract_id, team_id, kind, priority, status, subject,
               summary, reference, location, ai_confidence, sla_due, created_at, updated_at, case_type_id, response_due)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (code, provider["id"], conv_id, contract["id"] if contract else None, team["id"], kind, priority, "nuevo",
             result["subject"], result["summary"], result.get("reference") or "", location[:150], result.get("confidence"),
             sla_due.isoformat(sep=" "), ts, ts, ctype["id"] if ctype else None,
             response_due.isoformat(sep=" ") if response_due else None))
        prev_dups = sorted({d["code"] for d in dups} | set(warned))
        if prev_dups:
            # Aviso para el equipo: el proveedor confirmó que es un pedido distinto pese al documento repetido.
            note = f"Posible duplicado: el documento adjunto ya está en {', '.join(prev_dups)} (abierto). El proveedor indicó que es un pedido distinto."
            db.execute("UPDATE tickets SET summary=summary || ? WHERE id=?", ("\n\n" + note, tid))
            log_event(tid, "duplicate", note)
        log_event(tid, "created", f"Clasificado por IA ({result['engine']}) → {team['name']}"
                                  + (f", tipo «{ctype['name']}»" if ctype else "") + f", prioridad {priority}, "
                                  f"confianza {int((result.get('confidence') or 0) * 100)}%")
        db.execute("UPDATE conversations SET title=? WHERE id=?", (result["subject"][:90], conv_id))
        reply += (f"\n\n**{'Reclamo registrado' if kind == 'reclamo' else 'Consulta registrada'}: {code}**\n"
                  f"- Equipo asignado: {team['name']}\n"
                  + (f"- Contrato: {contract['numero']}\n" if contract else "")
                  + (f"- Locación: {location}\n" if location else "")
                  + f"Te avisamos en esta conversación cuando el equipo responda.")
        ticket = ticket_for_conversation(conv_id)

    db.execute("INSERT INTO messages (conversation_id, role, body, created_at) VALUES (?,?,?,?)",
               (conv_id, "assistant", reply, db.now_iso()))
    db.execute("UPDATE conversations SET updated_at=?, provider_seen_at=? WHERE id=?", (db.now_iso(), db.now_iso(), conv_id))
    return jsonify(conversation_id=conv_id, title=db.query("SELECT title FROM conversations WHERE id=?", (conv_id,), one=True)["title"],
                   messages=serialize_messages(conv_id, after_id=last_id), ticket=serialize_ticket(ticket),
                   contract=serialize_contract(contract), no_contract=bool(conv["no_contract"]),
                   engine=result["engine"])


# ---------------------------------------------------------------------------
# Proveedor: contratos
# ---------------------------------------------------------------------------
@app.route("/contratos")
@login_required("provider")
def contracts():
    status = request.args.get("estado", "")
    q = request.args.get("q", "").strip().lower()
    items = provider_contracts(g.user["provider_id"])
    counts = {s: sum(1 for c in items if c["status"] == s) for s in CONTRACT_STATUS_LABELS}
    counts["todos"] = len(items)
    if status in CONTRACT_STATUS_LABELS:
        items = [c for c in items if c["status"] == status]
    if q:
        items = [c for c in items if q in c["numero"].lower() or q in c["objeto"].lower() or q in (c["yacimiento"] or "").lower()]
    open_by_contract = {r["contract_id"]: r["n"] for r in db.query(
        f"""SELECT contract_id, COUNT(*) AS n FROM tickets WHERE provider_id=? AND contract_id IS NOT NULL
            AND status IN ({','.join('?' * len(OPEN_STATUSES))}) GROUP BY contract_id""",
        (g.user["provider_id"], *OPEN_STATUSES))}
    return render_template("contracts.html", contracts=items, status=status, q=request.args.get("q", ""),
                           counts=counts, open_by_contract=open_by_contract)


@app.route("/contratos/<numero>")
@login_required("provider")
def contract_detail(numero):
    row = db.query("SELECT id FROM contracts WHERE numero=? AND provider_id=?", (numero, g.user["provider_id"]), one=True)
    if not row:
        abort(404)
    c = own_contract(row["id"], g.user["provider_id"])
    tks = db.query("""SELECT t.*, tm.name AS team_name, tm.color AS team_color FROM tickets t JOIN teams tm ON tm.id=t.team_id
                      WHERE t.contract_id=? AND t.provider_id=? ORDER BY t.updated_at DESC""", (c["id"], g.user["provider_id"]))
    return render_template("contract_detail.html", c=c, tickets=tks)


@app.get("/contratos/<numero>/pdf")
@login_required()
def contract_pdf(numero):
    c = db.query("SELECT * FROM contracts WHERE numero=?", (numero,), one=True)
    if not c or not c["archivo"] or (g.user["role"] == "provider" and c["provider_id"] != g.user["provider_id"]):
        abort(404)
    return send_from_directory(db.CONTRACT_DIR, c["archivo"], mimetype="application/pdf",
                               download_name=f"{c['numero']}.pdf")


# ---------------------------------------------------------------------------
# Proveedor: tickets
# ---------------------------------------------------------------------------
@app.route("/tickets")
@login_required("provider")
def tickets():
    status = request.args.get("estado", "abiertos")
    q = request.args.get("q", "").strip()
    sql = """SELECT t.*, tm.name AS team_name, tm.color AS team_color, ct.numero AS contract_numero,
             (SELECT COUNT(*) FROM messages m JOIN conversations c ON c.id=m.conversation_id
               WHERE m.conversation_id=t.conversation_id AND m.role='agent' AND m.internal=0
               AND m.created_at > COALESCE(c.provider_seen_at,'')) AS unread
             FROM tickets t JOIN teams tm ON tm.id=t.team_id LEFT JOIN contracts ct ON ct.id=t.contract_id
             WHERE t.provider_id=?"""
    args = [g.user["provider_id"]]
    if status == "abiertos":
        sql += f" AND t.status IN ({','.join('?' * len(OPEN_STATUSES))})"
        args += OPEN_STATUSES
    elif status == "cerrados":
        sql += " AND t.status IN ('resuelto','cerrado')"
    if q:
        sql += " AND (t.code LIKE ? OR t.subject LIKE ? OR t.reference LIKE ? OR ct.numero LIKE ?)"
        args += [f"%{q}%"] * 4
    rows = db.query(sql + " ORDER BY t.updated_at DESC", args)
    counts = db.query("""SELECT SUM(status IN ('nuevo','en_curso','esperando_proveedor')) AS abiertos,
                         SUM(status IN ('nuevo','en_curso')) AS revision, SUM(status='esperando_proveedor') AS esperando, SUM(status IN ('resuelto','cerrado')) AS cerrados,
                         COUNT(*) AS todos FROM tickets WHERE provider_id=?""", (g.user["provider_id"],), one=True)
    return render_template("tickets.html", tickets=rows, status=status, q=q, counts=counts)


@app.route("/tickets/<code>")
@login_required("provider")
def ticket_detail(code):
    t = db.query("SELECT * FROM tickets WHERE code=? AND provider_id=?", (code, g.user["provider_id"]), one=True)
    if not t:
        abort(404)
    return redirect(url_for("assistant", c=t["conversation_id"]))


# ---------------------------------------------------------------------------
# Proveedor: documentación y habilitaciones
# ---------------------------------------------------------------------------
@app.route("/documentacion")
@login_required("provider")
def documents():
    items, summary = provider_documents(g.user["provider_id"])
    status = request.args.get("estado", "")
    shown = [d for d in items if d["status"] == status] if status in DOC_STATUS_LABELS else items
    return render_template("documents.html", docs=shown, summary=summary, total=len(items), status=status)


# ---------------------------------------------------------------------------
# Proveedor: perfil
# ---------------------------------------------------------------------------
EDITABLE_FIELDS = {
    "nombre_fantasia": ("Nombre de fantasía", 120), "telefono": ("Teléfono", 40), "sitio_web": ("Sitio web", 200),
    "contacto_nombre": ("Nombre del contacto", 120), "contacto_cargo": ("Cargo", 80),
    "contacto_email": ("E-mail del contacto", 160), "contacto_telefono": ("Teléfono del contacto", 40),
}


@app.route("/perfil", methods=["GET", "POST"])
@login_required("provider")
def profile():
    provider = current_provider()
    errors = {}
    if request.method == "POST":
        values = {k: (request.form.get(k) or "").strip()[:maxlen] for k, (_, maxlen) in EDITABLE_FIELDS.items()}
        email_re = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        if values["contacto_email"] and not re.match(email_re, values["contacto_email"]):
            errors["contacto_email"] = "Ingresá un e-mail válido, por ejemplo nombre@empresa.com."
        if not values["contacto_nombre"]:
            errors["contacto_nombre"] = "Indicá quién es la persona de contacto."
        if values["sitio_web"] and not re.match(r"^https?://", values["sitio_web"]):
            values["sitio_web"] = "https://" + values["sitio_web"]
        for k in ("telefono", "contacto_telefono"):
            if values[k] and not re.match(r"^[\d\s+()\-]{6,}$", values[k]):
                errors[k] = "Usá solo números, espacios, + o guiones."
        if not errors:
            db.execute(f"UPDATE providers SET {', '.join(k + '=?' for k in values)} WHERE id=?", (*values.values(), provider["id"]))
            flash("Guardamos los cambios de tu perfil.", "success")
            return redirect(url_for("profile"))
        provider = dict(provider, **values)
    stats = db.query("""SELECT COUNT(*) AS total, SUM(status IN ('nuevo','en_curso','esperando_proveedor')) AS abiertos,
                        SUM(status IN ('resuelto','cerrado')) AS resueltos FROM tickets WHERE provider_id=?""",
                     (provider["id"],), one=True)
    return render_template("profile.html", p=provider, errors=errors, fields=EDITABLE_FIELDS, stats=stats)


@app.post("/perfil/avatar")
@login_required("provider")
def profile_avatar():
    f = request.files.get("avatar")
    if request.form.get("remove") == "1":
        db.execute("UPDATE providers SET avatar=NULL WHERE id=?", (g.user["provider_id"],))
        flash("Quitamos la foto de perfil.", "success")
        return redirect(url_for("profile"))
    if not f or not f.filename:
        flash("Elegí una imagen para subir.", "error")
        return redirect(url_for("profile"))
    name = secure_filename(f.filename)
    data = f.read()
    ext = extract.extension(name)
    ok, err = extract.validate(name, data)
    if ext not in ("png", "jpg", "jpeg", "webp") or not ok:
        flash(err or "La foto debe ser PNG, JPG o WEBP.", "error")
    elif len(data) > 2 * 1024 * 1024:
        flash("La foto no puede superar los 2 MB.", "error")
    else:
        os.makedirs(AVATAR_DIR, exist_ok=True)
        stored = f"{uuid.uuid4().hex}.{ext}"
        with open(os.path.join(AVATAR_DIR, stored), "wb") as fh:
            fh.write(data)
        db.execute("UPDATE providers SET avatar=? WHERE id=?", (stored, g.user["provider_id"]))
        flash("Actualizamos tu foto de perfil.", "success")
    return redirect(url_for("profile"))


@app.get("/avatar/<int:provider_id>")
@login_required()
def avatar(provider_id):
    if g.user["role"] == "provider" and g.user["provider_id"] != provider_id:
        abort(404)
    p = db.query("SELECT avatar FROM providers WHERE id=?", (provider_id,), one=True)
    if not p or not p["avatar"]:
        abort(404)
    return send_from_directory(AVATAR_DIR, p["avatar"], max_age=3600)


@app.post("/perfil/password")
@login_required()
def change_password():
    current = request.form.get("current", "")
    new = request.form.get("new", "")
    confirm = request.form.get("confirm", "")
    back = url_for("profile") if g.user["role"] == "provider" else url_for("staff_inbox")
    if not check_password_hash(g.user["password_hash"], current):
        flash("La contraseña actual no es correcta.", "error")
    elif new != confirm:
        flash("La nueva contraseña y su confirmación no coinciden.", "error")
    elif len(new) < 10 or not re.search(r"[A-Za-z]", new) or not re.search(r"\d", new):
        flash("La nueva contraseña debe tener al menos 10 caracteres, con letras y números.", "error")
    else:
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new, method=db.HASH_METHOD), g.user["id"]))
        flash("Actualizamos tu contraseña.", "success")
    return redirect(back + "#seguridad")


# ---------------------------------------------------------------------------
# Archivos
# ---------------------------------------------------------------------------
@app.get("/archivos/<int:att_id>")
@login_required()
def download(att_id):
    a = db.query("""SELECT a.*, c.provider_id FROM attachments a JOIN messages m ON m.id=a.message_id
                    JOIN conversations c ON c.id=m.conversation_id WHERE a.id=?""", (att_id,), one=True)
    if not a or (g.user["role"] == "provider" and a["provider_id"] != g.user["provider_id"]):
        abort(404)
    inline = a["mime"].startswith("image/") or a["mime"] == "application/pdf"
    return send_from_directory(UPLOAD_DIR, a["stored_name"], mimetype=a["mime"], as_attachment=not inline,
                               download_name=a["original_name"])


# ---------------------------------------------------------------------------
# Equipos internos (mesa de ayuda)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Analítica de desempeño (admin y equipos internos)
# ---------------------------------------------------------------------------
PERIODS = {"30": ("Últimos 30 días", 30), "90": ("Últimos 90 días", 90), "180": ("Últimos 180 días", 180), "todo": ("Todo el historial", None)}


def fmt_duration(hours):
    """Duración legible: minutos, horas o días."""
    if hours is None:
        return "—"
    if hours < 1:
        return f"{max(1, round(hours * 60))} min"
    if hours < 48:
        return f"{hours:.1f} h".replace(".", ",")
    return f"{hours / 24:.1f} d".replace(".", ",")


app.jinja_env.filters["duracion"] = fmt_duration


def _hours_between(a, b):
    if not a or not b:
        return None
    return max(0.0, (parse_dt(b) - parse_dt(a)).total_seconds() / 3600)


def _avg(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def analytics_data(period, team_id, provider_id):
    sql = """SELECT t.*, tm.name AS team_name, tm.color AS team_color, tm.sla_hours, p.razon_social, p.nombre_fantasia,
             ct.numero AS contract_numero, ct.objeto AS contract_objeto,
             (SELECT MIN(m.created_at) FROM messages m WHERE m.conversation_id=t.conversation_id
                AND m.role='agent' AND m.internal=0) AS first_response_at
             FROM tickets t JOIN teams tm ON tm.id=t.team_id JOIN providers p ON p.id=t.provider_id
             LEFT JOIN contracts ct ON ct.id=t.contract_id WHERE 1=1"""
    args = []
    days = PERIODS.get(period, PERIODS["90"])[1]
    if days:
        sql += " AND t.created_at >= ?"
        args.append((datetime.now() - timedelta(days=days)).replace(microsecond=0).isoformat(sep=" "))
    if team_id:
        sql += " AND t.team_id=?"
        args.append(team_id)
    if provider_id:
        sql += " AND t.provider_id=?"
        args.append(provider_id)
    rows = db.query(sql + " ORDER BY t.created_at DESC", args)

    now_s = db.now_iso()
    tickets = []
    for r in rows:
        resolved = r["status"] in ("resuelto", "cerrado") and r["resolved_at"]
        resp_h = _hours_between(r["created_at"], r["first_response_at"])
        res_h = _hours_between(r["created_at"], r["resolved_at"]) if resolved else None
        if resolved:
            sla = "cumplido" if r["resolved_at"] <= r["sla_due"] else "incumplido"
        else:
            sla = "en_plazo" if now_s <= r["sla_due"] else "vencido"
        tickets.append(dict(code=r["code"], subject=r["subject"], provider=r["nombre_fantasia"] or r["razon_social"],
                            provider_id=r["provider_id"], contract=r["contract_numero"] or "Sin contrato",
                            contract_objeto=r["contract_objeto"] or "", team=r["team_name"], team_color=r["team_color"],
                            kind=r["kind"], priority=r["priority"], status=r["status"], created_at=r["created_at"],
                            response_h=resp_h, resolution_h=res_h, sla=sla, resolved=bool(resolved)))

    def group(key, label_fn):
        groups = {}
        for t in tickets:
            g = groups.setdefault(key(t), {"label": label_fn(t), "total": 0, "reclamos": 0, "abiertos": 0,
                                           "resp": [], "res": [], "sla_ok": 0, "sla_eval": 0})
            g["total"] += 1
            g["reclamos"] += t["kind"] == "reclamo"
            g["abiertos"] += not t["resolved"]
            g["resp"].append(t["response_h"])
            g["res"].append(t["resolution_h"])
            if t["resolved"]:
                g["sla_eval"] += 1
                g["sla_ok"] += t["sla"] == "cumplido"
        out = []
        for g in groups.values():
            out.append(dict(label=g["label"], total=g["total"], reclamos=g["reclamos"], abiertos=g["abiertos"],
                            avg_resp=_avg(g["resp"]), avg_res=_avg(g["res"]),
                            sla_pct=round(100 * g["sla_ok"] / g["sla_eval"]) if g["sla_eval"] else None))
        return out

    by_provider = sorted(group(lambda t: t["provider_id"], lambda t: t["provider"]), key=lambda g: (-g["reclamos"], -g["total"]))
    by_contract = sorted(group(lambda t: t["contract"], lambda t: t["contract"] + (f" · {t['contract_objeto'][:48]}" if t["contract_objeto"] else "")),
                         key=lambda g: (-g["reclamos"], -g["total"]))
    by_team = sorted(group(lambda t: t["team"], lambda t: t["team"]), key=lambda g: -(g["avg_res"] or 0))

    resolved_t = [t for t in tickets if t["resolved"]]
    kpis = dict(
        total=len(tickets), reclamos=sum(t["kind"] == "reclamo" for t in tickets),
        abiertos=sum(not t["resolved"] for t in tickets),
        vencidos=sum(t["sla"] == "vencido" for t in tickets),
        avg_resp=_avg([t["response_h"] for t in tickets]), med_resp=_median([t["response_h"] for t in tickets]),
        avg_res=_avg([t["resolution_h"] for t in resolved_t]), med_res=_median([t["resolution_h"] for t in resolved_t]),
        sla_pct=round(100 * sum(t["sla"] == "cumplido" for t in resolved_t) / len(resolved_t)) if resolved_t else None,
        resueltos=len(resolved_t),
    )
    return kpis, by_provider, by_contract, by_team, tickets


def _analytics_filters():
    period = request.args.get("periodo", "90")
    if period not in PERIODS:
        period = "90"
    team = request.args.get("equipo", type=int)
    provider = request.args.get("proveedor", type=int)
    return period, team, provider


@app.route("/equipo/analitica")
@login_required("agent", "admin")
def staff_analytics():
    period, team, provider = _analytics_filters()
    kpis, by_provider, by_contract, by_team, tickets = analytics_data(period, team, provider)
    sort = request.args.get("orden", "reciente")
    if sort == "resolucion":
        tickets = sorted(tickets, key=lambda t: -(t["resolution_h"] if t["resolution_h"] is not None else -1))
    elif sort == "respuesta":
        tickets = sorted(tickets, key=lambda t: -(t["response_h"] if t["response_h"] is not None else -1))
    max_reclamos_p = max([g["reclamos"] for g in by_provider] + [1])
    max_reclamos_c = max([g["reclamos"] for g in by_contract] + [1])
    max_res_team = max([g["avg_res"] or 0 for g in by_team] + [1])
    return render_template("analytics.html", kpis=kpis, by_provider=by_provider, by_contract=by_contract, by_team=by_team,
                           tickets=tickets, periods=PERIODS, period=period, team=team, provider=provider, sort=sort,
                           teams=db.query("SELECT * FROM teams ORDER BY name"),
                           providers=db.query("SELECT id, razon_social FROM providers ORDER BY razon_social"),
                           max_reclamos_p=max_reclamos_p, max_reclamos_c=max_reclamos_c, max_res_team=max_res_team,
                           SLA_LABELS={"cumplido": "Cumplido", "incumplido": "Fuera de plazo", "en_plazo": "En plazo", "vencido": "Vencido"})


@app.route("/equipo/analitica.csv")
@login_required("agent", "admin")
def staff_analytics_csv():
    import csv
    import io
    period, team, provider = _analytics_filters()
    _, _, _, _, tickets = analytics_data(period, team, provider)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Ticket", "Asunto", "Proveedor", "Contrato", "Equipo", "Tipo", "Prioridad", "Estado", "Creado",
                "Primera respuesta (h)", "Resolución (h)", "SLA"])
    for t in tickets:
        f = lambda v: "" if v is None else f"{v:.2f}".replace(".", ",")
        w.writerow([t["code"], t["subject"], t["provider"], t["contract"], t["team"], t["kind"], t["priority"], t["status"],
                    t["created_at"], f(t["response_h"]), f(t["resolution_h"]), t["sla"]])
    from flask import Response
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=analitica-tickets-{period}.csv"})


@app.route("/equipo")
@login_required("agent", "admin")
def staff_inbox():
    teams = db.query("SELECT * FROM teams ORDER BY id")
    team = request.args.get("equipo", "" if g.user["role"] == "admin" else str(g.user["team_id"] or ""))
    status = request.args.get("estado", "abiertos")
    priority = request.args.get("prioridad", "")
    q = request.args.get("q", "").strip()
    contract = request.args.get("contrato", "").strip()
    sql = """SELECT t.*, tm.name AS team_name, tm.color AS team_color, p.razon_social, p.cuit, u.full_name AS assignee_name,
             ct.numero AS contract_numero, cty.name AS case_type_name
             FROM tickets t JOIN teams tm ON tm.id=t.team_id JOIN providers p ON p.id=t.provider_id
             LEFT JOIN users u ON u.id=t.assignee_id LEFT JOIN contracts ct ON ct.id=t.contract_id
             LEFT JOIN case_types cty ON cty.id=t.case_type_id WHERE 1=1"""
    args = []
    if contract == "sin":
        sql += " AND t.contract_id IS NULL"
    elif contract:
        sql += " AND ct.numero=?"
        args.append(contract)
    if team:
        sql += " AND t.team_id=?"
        args.append(team)
    if status == "abiertos":
        sql += f" AND t.status IN ({','.join('?' * len(OPEN_STATUSES))})"
        args += OPEN_STATUSES
    elif status == "mios":
        sql += " AND t.assignee_id=? AND t.status NOT IN ('resuelto','cerrado')"
        args.append(g.user["id"])
    elif status in STATUS_LABELS:
        sql += " AND t.status=?"
        args.append(status)
    if priority in PRIORITY_LABELS:
        sql += " AND t.priority=?"
        args.append(priority)
    if q:
        sql += """ AND (t.code LIKE ? OR t.subject LIKE ? OR p.razon_social LIKE ? OR p.cuit LIKE ? OR t.reference LIKE ?
                  OR ct.numero LIKE ?)"""
        args += [f"%{q}%"] * 6
    sql += " ORDER BY CASE t.priority WHEN 'urgente' THEN 0 WHEN 'alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END, t.sla_due"
    rows = db.query(sql, args)
    contracts_all = db.query("""SELECT c.numero, p.razon_social FROM contracts c JOIN providers p ON p.id=c.provider_id
                                ORDER BY c.numero DESC""")
    return render_template("staff_inbox.html", tickets=rows, teams=teams, team=str(team), status=status,
                           priority=priority, q=q, contract=contract, contracts=contracts_all)


def staff_ticket(code):
    t = db.query("""SELECT t.*, tm.name AS team_name, tm.color AS team_color, tm.sla_hours, u.full_name AS assignee_name,
                    ct.name AS case_type_name,
                    CAST(ROUND((julianday(t.sla_due) - julianday(t.created_at)) * 24) AS INTEGER) AS sla_total_hours,
                    (SELECT MIN(m.created_at) FROM messages m WHERE m.conversation_id=t.conversation_id
                     AND m.role='agent' AND m.internal=0) AS first_response_at
                    FROM tickets t JOIN teams tm ON tm.id=t.team_id LEFT JOIN users u ON u.id=t.assignee_id
                    LEFT JOIN case_types ct ON ct.id=t.case_type_id
                    WHERE t.code=?""", (code,), one=True)
    if not t:
        abort(404)
    return t


@app.route("/equipo/tickets/<code>")
@login_required("agent", "admin")
def staff_ticket_detail(code):
    t = staff_ticket(code)
    provider = db.query("SELECT * FROM providers WHERE id=?", (t["provider_id"],), one=True)
    messages = serialize_messages(t["conversation_id"], include_internal=True)
    events = db.query("""SELECT e.*, u.full_name FROM ticket_events e LEFT JOIN users u ON u.id=e.actor_id
                         WHERE ticket_id=? ORDER BY e.id DESC""", (t["id"],))
    agents = db.query("SELECT id, full_name FROM users WHERE role IN ('agent','admin') AND (team_id=? OR role='admin') ORDER BY full_name",
                      (t["team_id"],))
    teams = db.query("SELECT * FROM teams ORDER BY id")
    contract = own_contract(t["contract_id"], t["provider_id"]) if t["contract_id"] else None
    docs, docs_summary = provider_documents(t["provider_id"])
    return render_template("staff_ticket.html", t=t, p=provider, messages=messages, events=events, agents=agents,
                           teams=teams, contract=contract, docs=docs, docs_summary=docs_summary,
                           accept=",".join("." + e for e in extract.ALLOWED))


@app.post("/equipo/tickets/<code>/responder")
@login_required("agent", "admin")
def staff_reply(code):
    t = staff_ticket(code)
    text = (request.form.get("text") or "").strip()[:8000]
    internal = request.form.get("internal") == "1"
    files, err = read_uploads()
    if err:
        flash(err, "error")
        return redirect(url_for("staff_ticket_detail", code=code))
    if not text and not files:
        flash("Escribí una respuesta o adjuntá un archivo.", "error")
        return redirect(url_for("staff_ticket_detail", code=code))
    ts = db.now_iso()
    mid = db.execute("INSERT INTO messages (conversation_id, role, author_id, body, internal, created_at) VALUES (?,?,?,?,?,?)",
                     (t["conversation_id"], "agent", g.user["id"], text, 1 if internal else 0, ts))
    save_attachments(mid, files)
    new_status = request.form.get("status") or t["status"]
    if new_status not in STATUS_LABELS:
        new_status = t["status"]
    if not internal and new_status == "nuevo":
        new_status = "en_curso"
    resolved = ts if new_status in ("resuelto", "cerrado") and not t["resolved_at"] else t["resolved_at"]
    assignee = t["assignee_id"] or g.user["id"]
    db.execute("UPDATE tickets SET status=?, updated_at=?, resolved_at=?, assignee_id=? WHERE id=?",
               (new_status, ts, resolved, assignee, t["id"]))
    if not internal:
        db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (ts, t["conversation_id"]))
    log_event(t["id"], "note" if internal else "reply", "Nota interna" if internal else "Respuesta al proveedor")
    if new_status != t["status"]:
        log_event(t["id"], "status", f"{STATUS_LABELS_STAFF[t['status']]} → {STATUS_LABELS_STAFF[new_status]}")
    flash("Nota interna guardada." if internal else "Respuesta enviada al proveedor.", "success")
    return redirect(url_for("staff_ticket_detail", code=code))


@app.post("/equipo/tickets/<code>/actualizar")
@login_required("agent", "admin")
def staff_update(code):
    t = staff_ticket(code)
    changes = []
    status = request.form.get("status")
    priority = request.form.get("priority")
    team_id = request.form.get("team_id", type=int)
    assignee = request.form.get("assignee_id", type=int)
    ts = db.now_iso()
    if status in STATUS_LABELS and status != t["status"]:
        resolved = ts if status in ("resuelto", "cerrado") else None
        db.execute("UPDATE tickets SET status=?, resolved_at=? WHERE id=?", (status, resolved, t["id"]))
        changes.append(("status", f"{STATUS_LABELS_STAFF[t['status']]} → {STATUS_LABELS_STAFF[status]}"))
    if priority in PRIORITY_LABELS and priority != t["priority"]:
        db.execute("UPDATE tickets SET priority=? WHERE id=?", (priority, t["id"]))
        changes.append(("priority", f"{PRIORITY_LABELS[t['priority']]} → {PRIORITY_LABELS[priority]}"))
    if team_id and team_id != t["team_id"]:
        new_team = db.query("SELECT * FROM teams WHERE id=?", (team_id,), one=True)
        if new_team:
            db.execute("UPDATE tickets SET team_id=?, assignee_id=NULL WHERE id=?", (team_id, t["id"]))
            changes.append(("team", f"Derivado de {t['team_name']} a {new_team['name']}"))
            db.execute("INSERT INTO messages (conversation_id, role, body, created_at) VALUES (?,?,?,?)",
                       (t["conversation_id"], "system", f"Tu caso fue derivado al equipo **{new_team['name']}**.", ts))
    elif assignee is not None and assignee != (t["assignee_id"] or 0):
        db.execute("UPDATE tickets SET assignee_id=? WHERE id=?", (assignee or None, t["id"]))
        name = db.query("SELECT full_name FROM users WHERE id=?", (assignee,), one=True)
        changes.append(("assign", f"Asignado a {name['full_name'] if name else 'nadie'}"))
    if changes:
        db.execute("UPDATE tickets SET updated_at=? WHERE id=?", (ts, t["id"]))
        for ev, detail in changes:
            log_event(t["id"], ev, detail)
        flash("Ticket actualizado.", "success")
    return redirect(url_for("staff_ticket_detail", code=code))


# ---------------------------------------------------------------------------
# Tipos de caso y SLA: el administrador los define, los equipos solo los consultan.
# El proveedor nunca ve estos plazos.
# ---------------------------------------------------------------------------
CASE_TYPE_LIMITS = dict(name=80, description=300, keywords=500)
MAX_RESPONSE_HOURS = 24 * 30
MAX_RESOLUTION_HOURS = 24 * 90


def active_case_types():
    return [dict(c) for c in db.query("SELECT * FROM case_types WHERE active=1 ORDER BY sort_order, id")]


def case_type_form(values=None):
    """Valida el formulario de tipo de caso. Devuelve (datos, errores)."""
    f = request.form
    data = {k: (f.get(k) or "").strip()[:n] for k, n in CASE_TYPE_LIMITS.items()}
    data["keywords"] = ", ".join(k.strip() for k in data["keywords"].split(",") if k.strip())
    data["kind"] = f.get("kind") if f.get("kind") in KIND_LABELS else ""
    data["priority"] = f.get("priority") if f.get("priority") in PRIORITY_LABELS else ""
    data["team_id"] = f.get("team_id", type=int)
    data["response_hours"] = f.get("response_hours", type=int)
    data["resolution_hours"] = f.get("resolution_hours", type=int)
    data["active"] = 1 if f.get("active") == "1" else 0
    errors = {}
    if not data["name"]:
        errors["name"] = "Ingresá un nombre."
    if not data["kind"]:
        errors["kind"] = "Elegí si es reclamo o consulta."
    if not data["priority"]:
        errors["priority"] = "Elegí una prioridad."
    if not data["team_id"] or not db.query("SELECT 1 FROM teams WHERE id=?", (data["team_id"],), one=True):
        errors["team_id"] = "Elegí el equipo que resuelve este tipo de caso."
    if not data["response_hours"] or not 1 <= data["response_hours"] <= MAX_RESPONSE_HOURS:
        errors["response_hours"] = f"Ingresá un número de horas entre 1 y {MAX_RESPONSE_HOURS}."
    if not data["resolution_hours"] or not 1 <= data["resolution_hours"] <= MAX_RESOLUTION_HOURS:
        errors["resolution_hours"] = f"Ingresá un número de horas entre 1 y {MAX_RESOLUTION_HOURS}."
    elif data["response_hours"] and data["response_hours"] > data["resolution_hours"]:
        errors["resolution_hours"] = "El SLA de resolución no puede ser menor que el plazo de primera respuesta."
    if values is not None and not data["active"] and values["active"]:
        remaining = db.query("SELECT COUNT(*) AS n FROM case_types WHERE active=1 AND id<>?", (values["id"],), one=True)["n"]
        if remaining == 0:
            errors["active"] = "Tiene que quedar al menos un tipo de caso activo."
    return data, errors


@app.route("/equipo/tipos-de-caso")
@login_required("agent", "admin")
def case_types():
    rows = db.query("""SELECT c.*, tm.name AS team_name, tm.color AS team_color, u.full_name AS updated_by_name,
                       (SELECT COUNT(*) FROM tickets t WHERE t.case_type_id=c.id) AS tickets
                       FROM case_types c JOIN teams tm ON tm.id=c.team_id LEFT JOIN users u ON u.id=c.updated_by
                       ORDER BY c.active DESC, tm.id, c.sort_order, c.id""")
    team = request.args.get("equipo", type=int)
    if team:
        rows = [r for r in rows if r["team_id"] == team]
    teams = db.query("SELECT * FROM teams ORDER BY id")
    return render_template("case_types.html", types=rows, teams=teams, team=team,
                           can_edit=g.user["role"] == "admin")


@app.route("/equipo/tipos-de-caso/nuevo", methods=["GET", "POST"])
@login_required("admin")
def case_type_new():
    values, errors = dict(kind="reclamo", priority="media", active=1, team_id=None, response_hours=24, resolution_hours=48,
                          name="", description="", keywords=""), {}
    if request.method == "POST":
        values, errors = case_type_form()
        if not errors:
            ts = db.now_iso()
            order = db.query("SELECT COALESCE(MAX(sort_order), 0) + 10 AS n FROM case_types", one=True)["n"]
            db.execute("""INSERT INTO case_types (name, description, kind, team_id, priority, response_hours, resolution_hours,
                          keywords, active, sort_order, updated_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (values["name"], values["description"], values["kind"], values["team_id"], values["priority"],
                        values["response_hours"], values["resolution_hours"], values["keywords"], values["active"], order,
                        g.user["id"], ts, ts))
            flash(f"Tipo de caso «{values['name']}» creado.", "success")
            return redirect(url_for("case_types"))
    return render_template("case_type_form.html", c=values, errors=errors, is_new=True,
                           teams=db.query("SELECT * FROM teams ORDER BY id"))


@app.route("/equipo/tipos-de-caso/<int:type_id>", methods=["GET", "POST"])
@login_required("admin")
def case_type_edit(type_id):
    current = db.query("SELECT * FROM case_types WHERE id=?", (type_id,), one=True)
    if not current:
        abort(404)
    values, errors = dict(current), {}
    if request.method == "POST":
        values, errors = case_type_form(current)
        values["id"] = type_id
        if not errors:
            db.execute("""UPDATE case_types SET name=?, description=?, kind=?, team_id=?, priority=?, response_hours=?,
                          resolution_hours=?, keywords=?, active=?, updated_by=?, updated_at=? WHERE id=?""",
                       (values["name"], values["description"], values["kind"], values["team_id"], values["priority"],
                        values["response_hours"], values["resolution_hours"], values["keywords"], values["active"],
                        g.user["id"], db.now_iso(), type_id))
            flash(f"Tipo de caso «{values['name']}» actualizado. Los cambios aplican a los tickets nuevos.", "success")
            return redirect(url_for("case_types"))
    used = db.query("SELECT COUNT(*) AS n FROM tickets WHERE case_type_id=?", (type_id,), one=True)["n"]
    return render_template("case_type_form.html", c=values, errors=errors, is_new=False, used=used,
                           teams=db.query("SELECT * FROM teams ORDER BY id"))


# ---------------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------------
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(413)
def http_error(err):
    messages = {403: "No tenés permiso para ver esta página.", 404: "No encontramos lo que buscabas.",
                413: f"Los archivos superan el tamaño máximo permitido ({extract.MAX_FILE_BYTES // (1024 * 1024)} MB por archivo)."}
    if request.path.startswith("/api/"):
        return jsonify(error=messages[err.code]), err.code
    return render_template("error.html", code=err.code, message=messages[err.code]), err.code


@app.template_filter("md")
def simple_markdown(text):
    """Markdown mínimo y seguro: escapa primero, luego negritas, listas y saltos."""
    html = str(escape(text or ""))
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    lines, out, in_list = html.split("\n"), [], False
    for line in lines:
        if re.match(r"^\s*[-•]\s+", line):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>" + re.sub(r"^\s*[-•]\s+", "", line) + "</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(line + "<br>" if line.strip() else "<br>")
    if in_list:
        out.append("</ul>")
    return Markup("".join(out).rstrip("<br>"))


db.init_db()
backfill_attachment_hashes()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="127.0.0.1", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
