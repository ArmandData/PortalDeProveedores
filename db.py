"""Capa de datos: esquema SQLite, conexión y datos de ejemplo."""
import os
import random
import secrets
import sqlite3
from datetime import datetime, timedelta

from flask import g
from werkzeug.security import generate_password_hash

HASH_METHOD = "pbkdf2:sha256:600000"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("PORTAL_DB", os.path.join(BASE_DIR, "data", "portal.db"))

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    sla_hours INTEGER NOT NULL DEFAULT 48,
    color TEXT NOT NULL DEFAULT '#4f46e5'
);

CREATE TABLE IF NOT EXISTS providers (
    id INTEGER PRIMARY KEY,
    cuit TEXT UNIQUE NOT NULL,
    razon_social TEXT NOT NULL,
    nombre_fantasia TEXT,
    condicion_iva TEXT NOT NULL,
    rubro TEXT,
    email TEXT NOT NULL,
    telefono TEXT,
    sitio_web TEXT,
    domicilio TEXT,
    localidad TEXT,
    provincia TEXT,
    codigo_postal TEXT,
    contacto_nombre TEXT,
    contacto_cargo TEXT,
    contacto_email TEXT,
    contacto_telefono TEXT,
    banco TEXT,
    cbu TEXT,
    condicion_pago TEXT,
    estado TEXT NOT NULL DEFAULT 'Activo',
    avatar TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    email TEXT NOT NULL,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('provider', 'agent', 'admin')),
    provider_id INTEGER REFERENCES providers(id),
    team_id INTEGER REFERENCES teams(id),
    failed_logins INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    last_login TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contracts (
    id INTEGER PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id),
    numero TEXT UNIQUE NOT NULL,
    objeto TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('suministro', 'servicios', 'obra', 'marco')),
    fecha_inicio TEXT NOT NULL,
    fecha_fin TEXT NOT NULL,
    monto REAL NOT NULL,
    moneda TEXT NOT NULL DEFAULT 'ARS',
    estado TEXT NOT NULL DEFAULT 'vigente' CHECK (estado IN ('vigente', 'por_vencer', 'vencido', 'rescindido')),
    condicion_pago TEXT,
    responsable_interno TEXT,
    team_id INTEGER REFERENCES teams(id),
    yacimiento TEXT,
    archivo TEXT,
    created_at TEXT NOT NULL
);

-- Documentación legal, seguros y habilitaciones exigidas para operar en yacimiento
CREATE TABLE IF NOT EXISTS provider_documents (
    id INTEGER PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id),
    categoria TEXT NOT NULL,
    nombre TEXT NOT NULL,
    detalle TEXT,
    emisor TEXT,
    numero TEXT,
    vence TEXT,
    obligatorio INTEGER NOT NULL DEFAULT 1,
    bloquea_ingreso INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id),
    contract_id INTEGER REFERENCES contracts(id),
    no_contract INTEGER NOT NULL DEFAULT 0,
    provider_seen_at TEXT,
    title TEXT NOT NULL DEFAULT 'Nueva conversación',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    dup_warned TEXT
);

-- Tipos de caso: definen equipo resolutor, prioridad sugerida y plazos internos (no visibles para el proveedor)
CREATE TABLE IF NOT EXISTS case_types (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'reclamo' CHECK (kind IN ('consulta', 'reclamo')),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    priority TEXT NOT NULL DEFAULT 'media' CHECK (priority IN ('baja', 'media', 'alta', 'urgente')),
    response_hours INTEGER NOT NULL,
    resolution_hours INTEGER NOT NULL,
    keywords TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    updated_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    provider_id INTEGER NOT NULL REFERENCES providers(id),
    conversation_id INTEGER UNIQUE REFERENCES conversations(id),
    contract_id INTEGER REFERENCES contracts(id),
    team_id INTEGER NOT NULL REFERENCES teams(id),
    assignee_id INTEGER REFERENCES users(id),
    kind TEXT NOT NULL CHECK (kind IN ('consulta', 'reclamo')),
    priority TEXT NOT NULL CHECK (priority IN ('baja', 'media', 'alta', 'urgente')),
    status TEXT NOT NULL CHECK (status IN ('nuevo', 'en_curso', 'esperando_proveedor', 'resuelto', 'cerrado')),
    subject TEXT NOT NULL,
    summary TEXT NOT NULL,
    reference TEXT,
    location TEXT,
    ai_confidence REAL,
    sla_due TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    case_type_id INTEGER REFERENCES case_types(id),
    response_due TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL CHECK (role IN ('provider', 'assistant', 'agent', 'system')),
    author_id INTEGER REFERENCES users(id),
    body TEXT NOT NULL,
    internal INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    mime TEXT NOT NULL,
    size INTEGER NOT NULL,
    extracted_text TEXT,
    created_at TEXT NOT NULL,
    sha256 TEXT,
    content_hash TEXT
);

CREATE TABLE IF NOT EXISTS ticket_events (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    actor_id INTEGER REFERENCES users(id),
    event TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);

-- Scoring de proveedores: evaluaciones periódicas (solo Proveedores y Performance y el administrador)
CREATE TABLE IF NOT EXISTS provider_evaluations (
    id INTEGER PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id),
    period TEXT NOT NULL,
    calidad INTEGER NOT NULL CHECK (calidad BETWEEN 1 AND 5),
    cumplimiento INTEGER NOT NULL CHECK (cumplimiento BETWEEN 1 AND 5),
    hse INTEGER NOT NULL CHECK (hse BETWEEN 1 AND 5),
    documentacion INTEGER NOT NULL CHECK (documentacion BETWEEN 1 AND 5),
    score INTEGER NOT NULL,
    category TEXT NOT NULL,
    comment TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL
);

-- Bloqueos que impiden o restringen que el proveedor siga operando
CREATE TABLE IF NOT EXISTS provider_blocks (
    id INTEGER PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id),
    kind TEXT NOT NULL CHECK (kind IN ('suspension', 'ingreso', 'adjudicaciones')),
    reason TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    lifted_at TEXT,
    lifted_by INTEGER REFERENCES users(id),
    lift_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_evals_provider ON provider_evaluations(provider_id, created_at);
CREATE INDEX IF NOT EXISTS idx_blocks_provider ON provider_blocks(provider_id, lifted_at);
CREATE INDEX IF NOT EXISTS idx_tickets_provider ON tickets(provider_id);
CREATE INDEX IF NOT EXISTS idx_tickets_team ON tickets(team_id, status);
CREATE INDEX IF NOT EXISTS idx_conv_provider ON conversations(provider_id);
CREATE INDEX IF NOT EXISTS idx_contracts_provider ON contracts(provider_id);
CREATE INDEX IF NOT EXISTS idx_docs_provider ON provider_documents(provider_id);
CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments(message_id);
"""

TEAMS = [
    ("pagos", "Tesorería y Pagos", "Estado de pagos, fechas de cobro, órdenes de pago, transferencias, compensaciones.", 24, "#0f766e"),
    ("facturacion", "Cuentas a Pagar", "Recepción, validación y rechazo de facturas, notas de crédito y débito.", 48, "#2563eb"),
    ("certificacion", "Certificación de Servicios", "Partes diarios, actas de medición, certificados de avance y hojas de entrada de servicio (HES) previas a facturar.", 48, "#0891b2"),
    ("compras", "Compras y Contratos", "Órdenes de compra, cotizaciones, licitaciones, ajustes de tarifa (polinómica), adendas y renovaciones.", 48, "#7c3aed"),
    ("logistica", "Logística y Almacenes", "Entregas en bases y almacenes, turnos de descarga, remitos, materiales en locación y transporte.", 24, "#c2410c"),
    ("calidad", "Calidad e Inspección (QA/QC)", "Inspección de materiales, certificados de calidad (mill certificates), no conformidades y devoluciones.", 72, "#be123c"),
    ("hse", "HSE: Seguridad, Salud y Ambiente", "Incidentes y casi accidentes, eventos ambientales, permisos de trabajo, inducciones y requisitos de seguridad.", 4, "#dc2626"),
    ("impuestos", "Impuestos y Retenciones", "Retenciones, percepciones, certificados de exclusión, regímenes provinciales y constancias.", 72, "#a16207"),
    ("maestro", "Alta y Documentación de Proveedores", "Alta, datos bancarios y fiscales, seguros (ART, pólizas), habilitaciones y documentación para ingresar a yacimiento.", 72, "#475569"),
    ("general", "Mesa de Ayuda General", "Consultas que no encajan en otra categoría o requieren análisis.", 48, "#4f46e5"),
    ("performance", "Proveedores y Performance", "Evaluación de desempeño y scoring de proveedores, bloqueos y habilitación para operar.", 72, "#0e7490"),
]
PERFORMANCE_TEAM = TEAMS[-1]


# Tipos de caso iniciales: (equipo, nombre, descripción, tipo, prioridad, h 1ra respuesta, h resolución, palabras clave)
CASE_TYPES = [
    ("pagos", "Factura vencida sin pagar", "La factura ya venció según la condición de pago y no se registra el cobro.",
     "reclamo", "alta", 8, 24, "no me pagaron, no pagaron, impag, adeud, deuda, pago vencido, vencid, no cobre"),
    ("pagos", "Estado de pago o fecha de cobro", "Consulta por la fecha estimada de cobro, órdenes de pago o transferencias.",
     "consulta", "media", 8, 24, "cuando cobro, cuando pagan, estado del pago, estado de mi pago, fecha de pago, orden de pago, transferencia"),
    ("facturacion", "Factura rechazada", "Factura observada o rechazada por Cuentas a Pagar.",
     "reclamo", "alta", 12, 48, "factura rechazada, rechazaron la factura, rechazo de factura, observada"),
    ("facturacion", "Notas de crédito y débito", "Emisión, aplicación o consultas sobre notas de crédito y débito.",
     "consulta", "media", 24, 48, "nota de credito, nota de debito"),
    ("certificacion", "Certificado o HES rechazado o demorado", "Partes diarios, certificados de avance y hojas de entrada de servicio observadas o pendientes.",
     "reclamo", "alta", 12, 48, "hes, hoja de entrada, certificado de avance, parte diario, partes diarios, acta de medicion, certificado de servicio"),
    ("compras", "Orden de compra, cotización o licitación", "Consultas sobre OC emitidas, pedidos de cotización y procesos licitatorios.",
     "consulta", "media", 24, 48, "orden de compra, cotiza, licitacion, presupuesto"),
    ("compras", "Ajuste de tarifa, adenda o renovación", "Pedidos de ajuste por polinómica, adendas y renovaciones de contrato.",
     "consulta", "media", 24, 72, "polinomica, ajuste de tarifa, tarifa, adenda, renovacion del contrato, renovar el contrato"),
    ("logistica", "Entrega, turno de descarga o remito", "Coordinación de entregas en bases y almacenes, turnos y remitos.",
     "consulta", "media", 8, 24, "entrega, turno, descarga, remito, almacen, flete, envio"),
    ("logistica", "Faltante o demora en recepción", "Diferencias de cantidades, esperas o problemas al recibir materiales.",
     "reclamo", "alta", 8, 24, "faltan, faltante, incomplet, esper, demora en la descarga"),
    ("calidad", "No conformidad o material retenido", "Materiales observados, retenidos o devueltos por inspección.",
     "reclamo", "alta", 24, 72, "no conformidad, retenido, retuvieron, defect, devolucion, rosca"),
    ("calidad", "Certificado de calidad (mill certificate)", "Presentación o consultas sobre certificados de calidad de colada.",
     "consulta", "media", 24, 72, "mill cert, certificado de calidad, colada, api 5ct, inspeccion"),
    ("hse", "Incidente, accidente o evento ambiental", "Incidentes, casi accidentes, lesiones, derrames, fugas o incendios en locación.",
     "reclamo", "urgente", 1, 4, "incidente, accidente, casi accidente, derrame, fuga, incendio, lesion, herido, ambiental"),
    ("hse", "Permisos de trabajo e inducciones", "Requisitos de seguridad para operar: permisos de trabajo e inducciones HSE.",
     "consulta", "media", 4, 24, "permiso de trabajo, induccion, seguridad"),
    ("impuestos", "Retenciones y certificados fiscales", "Retenciones, percepciones, certificados de exclusión y regímenes provinciales.",
     "consulta", "media", 24, 72, "retencion, percepcion, iibb, ingresos brutos, ganancias, exclusion, convenio multilateral"),
    ("maestro", "Renovación de seguros y habilitaciones", "Pólizas, ART, habilitaciones de equipos y documentación para ingresar a yacimiento.",
     "consulta", "media", 24, 72, "poliza, seguro, art, habilitacion, documentacion, vtv, rto, ingreso a yacimiento"),
    ("maestro", "Cambio de datos bancarios o fiscales", "Actualización de CBU, domicilio fiscal o razón social con constancia.",
     "consulta", "alta", 24, 72, "cbu, datos bancarios, domicilio fiscal, razon social, alta de proveedor"),
    ("general", "Otra consulta", "Consultas que no encajan en otro tipo de caso.",
     "consulta", "media", 24, 48, ""),
    ("performance", "Evaluación de desempeño o bloqueo", "Consultas o reclamos sobre la evaluación del proveedor, una suspensión o un bloqueo para operar.",
     "consulta", "alta", 24, 72, "evaluacion, desempeno, scoring, puntaje, calificacion, suspendid, suspension, bloquead, bloqueo, inhabilitad"),
]


def now_iso():
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def get_db():
    if "db" not in g:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    conn = get_db()
    cur = conn.execute(sql, args)
    conn.commit()
    return cur.lastrowid


def init_db(seed=True):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    if seed and conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0] == 0:
        _seed(conn)
    if seed and conn.execute("SELECT COUNT(*) FROM case_types").fetchone()[0] == 0:
        _seed_case_types(conn)
    if seed:
        _ensure_performance_team(conn)
    if seed and conn.execute("SELECT COUNT(*) FROM provider_evaluations").fetchone()[0] == 0:
        _seed_scoring(conn)
    conn.commit()
    conn.close()


def _migrate(conn):
    """Agrega columnas nuevas a bases creadas con versiones anteriores."""
    new_columns = {
        "tickets": (("case_type_id", "INTEGER REFERENCES case_types(id)"), ("response_due", "TEXT")),
        "attachments": (("sha256", "TEXT"), ("content_hash", "TEXT")),
        "conversations": (("dup_warned", "TEXT"),),
    }
    for table, columns in new_columns.items():
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, ddl in columns:
            if col not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_attachments_sha ON attachments(sha256)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_attachments_content ON attachments(content_hash)")


def _seed_case_types(conn):
    """Carga los tipos de caso iniciales y clasifica los tickets existentes que no tienen tipo."""
    import ai  # import diferido: ai no depende de la base

    ts = now_iso()
    team_id = {r[0]: r[1] for r in conn.execute("SELECT slug, id FROM teams")}
    for i, (team, name, desc, kind, prio, resp_h, res_h, kws) in enumerate(CASE_TYPES):
        if team in team_id:
            conn.execute(
                """INSERT INTO case_types (name, description, kind, team_id, priority, response_hours, resolution_hours,
                   keywords, sort_order, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (name, desc, kind, team_id[team], prio, resp_h, res_h, kws, (i + 1) * 10, ts, ts))
    conn.row_factory = sqlite3.Row
    types = [dict(r) for r in conn.execute("SELECT * FROM case_types WHERE active=1 ORDER BY sort_order, id")]
    for t in conn.execute("SELECT id, team_id, subject, summary, created_at FROM tickets WHERE case_type_id IS NULL").fetchall():
        ct = ai.match_case_type(types, t["team_id"], f"{t['subject']} {t['summary']}")
        if ct:
            due = (datetime.fromisoformat(t["created_at"]) + timedelta(hours=ct["response_hours"])).isoformat(sep=" ")
            conn.execute("UPDATE tickets SET case_type_id=?, response_due=? WHERE id=?", (ct["id"], due, t["id"]))


def _ensure_performance_team(conn):
    """Bases anteriores: agrega el equipo Proveedores y Performance, su agente y su tipo de caso."""
    slug, name, desc, sla, color = PERFORMANCE_TEAM
    if conn.execute("SELECT 1 FROM teams WHERE slug=?", (slug,)).fetchone():
        return
    team_id = conn.execute("INSERT INTO teams (slug, name, description, sla_hours, color) VALUES (?,?,?,?,?)",
                           PERFORMANCE_TEAM).lastrowid
    # El agente nuevo usa la misma contraseña que los demás agentes (se copia el hash, nunca se conoce la clave).
    ref = conn.execute("SELECT password_hash FROM users WHERE role='agent' ORDER BY id LIMIT 1").fetchone()
    if ref and not conn.execute("SELECT 1 FROM users WHERE username=?", (f"agente.{slug}",)).fetchone():
        conn.execute("""INSERT INTO users (username,email,full_name,password_hash,role,team_id,created_at)
                        VALUES (?,?,?,?,?,?,?)""",
                     (f"agente.{slug}", f"{slug}@operadora.com", f"Agente {name}", ref[0], "agent", team_id, now_iso()))
    ts = now_iso()
    order = (conn.execute("SELECT COALESCE(MAX(sort_order), 0) FROM case_types").fetchone()[0] or 0) + 10
    for (team, ct_name, ct_desc, kind, prio, resp_h, res_h, kws) in CASE_TYPES:
        if team == slug:
            conn.execute("""INSERT INTO case_types (name, description, kind, team_id, priority, response_hours, resolution_hours,
                            keywords, sort_order, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                         (ct_name, ct_desc, kind, team_id, prio, resp_h, res_h, kws, order, ts, ts))


# Criterios del scoring: (clave, nombre, peso). Cada criterio se califica de 1 a 5.
SCORING_CRITERIA = [
    ("calidad", "Calidad del producto o servicio", 30),
    ("cumplimiento", "Cumplimiento de plazos y entregas", 25),
    ("hse", "Desempeño HSE", 25),
    ("documentacion", "Documentación y gestión administrativa", 20),
]


def compute_score(values):
    """Score 0-100 ponderado y categoría (A a D) a partir de calificaciones 1-5."""
    total = sum(values[k] * w for k, _, w in SCORING_CRITERIA) / sum(w for *_, w in SCORING_CRITERIA)
    score = round((total - 1) / 4 * 100)
    category = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 50 else "D"
    return score, category


def _seed_scoring(conn):
    """Evaluaciones y bloqueos de ejemplo para la demo."""
    if not conn.execute("SELECT COUNT(*) FROM providers").fetchone()[0]:
        return
    now = datetime.now().replace(microsecond=0)
    evals = [  # (proveedor, días atrás, período, calidad, cumplimiento, hse, documentación, comentario)
        (1, 190, "1er semestre 2026", 4, 4, 5, 4, "Buen desempeño en workover. Partes diarios completos y a tiempo."),
        (1, 20, "Tercer trimestre 2026", 4, 3, 4, 2, "Demoras en la presentación de certificados e inducción HSE vencida en parte de la dotación."),
        (2, 175, "1er semestre 2026", 5, 4, 5, 5, "Entregas OCTG conformes, mill certificates completos."),
        (2, 15, "Tercer trimestre 2026", 5, 5, 5, 4, "Sin no conformidades en el período."),
        (3, 160, "1er semestre 2026", 3, 3, 3, 3, "Esperas en accesos a locación y documentación de flota incompleta."),
        (3, 10, "Tercer trimestre 2026", 2, 3, 1, 2, "Derrame menor en descarga y RTO vencida en 3 unidades. Se suspende hasta regularizar."),
    ]
    for pid, days, period, cal, cum, hse, doc, comment in evals:
        score, cat = compute_score(dict(calidad=cal, cumplimiento=cum, hse=hse, documentacion=doc))
        conn.execute("""INSERT INTO provider_evaluations (provider_id, period, calidad, cumplimiento, hse, documentacion, score,
                        category, comment, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                     (pid, period, cal, cum, hse, doc, score, cat, comment, (now - timedelta(days=days)).isoformat(sep=" ")))
    conn.execute("""INSERT INTO provider_blocks (provider_id, kind, reason, created_at) VALUES (?,?,?,?)""",
                 (3, "suspension", "Derrame de agua de retorno en locación AE y RTO vencida en 3 unidades. "
                                   "Se levanta con el informe de causa raíz aprobado por HSE y la flota regularizada.",
                  (now - timedelta(days=10)).isoformat(sep=" ")))
    conn.execute("""INSERT INTO provider_blocks (provider_id, kind, reason, created_at, lifted_at, lift_reason) VALUES (?,?,?,?,?,?)""",
                 (1, "adjudicaciones", "Score C en la evaluación de 2025: sin nuevas adjudicaciones hasta la próxima evaluación.",
                  (now - timedelta(days=300)).isoformat(sep=" "), (now - timedelta(days=190)).isoformat(sep=" "),
                  "Evaluación del 1er semestre 2026 con score B."))


def _seed(conn):
    ts = now_iso()
    now = datetime.now().replace(microsecond=0)
    today = now.date()
    for t in TEAMS:
        conn.execute("INSERT INTO teams (slug, name, description, sla_hours, color) VALUES (?,?,?,?,?)", t)
    team_id = {r[0]: r[1] for r in conn.execute("SELECT slug, id FROM teams")}

    # ---------------- Proveedores (datos ficticios) ----------------
    providers = [
        dict(cuit="30-71582934-3", razon_social="Servicios Petroleros Patagónicos S.A.", nombre_fantasia="SPP Servicios",
             condicion_iva="Responsable Inscripto", rubro="Servicios de pozo: workover, pulling y cementación",
             email="facturacion@spp-servicios.com.ar", telefono="+54 299 442-1500", sitio_web="https://spp-servicios.com.ar",
             domicilio="Ruta Provincial 7 km 3, Parque Industrial", localidad="Añelo", provincia="Neuquén", codigo_postal="Q8305",
             contacto_nombre="Martín Ríos", contacto_cargo="Gerente de Cuentas y Contratos", contacto_email="mrios@spp-servicios.com.ar",
             contacto_telefono="+54 9 299 555-0142", banco="Banco Patagonia", cbu="0340040600100012345678",
             condicion_pago="45 días fecha de certificación aprobada"),
        dict(cuit="30-71466210-0", razon_social="Tubulares del Neuquén S.R.L.", nombre_fantasia="TubuNeu",
             condicion_iva="Responsable Inscripto", rubro="Suministro de tubulares OCTG (casing, tubing) y accesorios",
             email="administracion@tubuneu.com.ar", telefono="+54 299 448-7720", sitio_web="https://tubuneu.com.ar",
             domicilio="Av. Mosconi 2850", localidad="Neuquén", provincia="Neuquén", codigo_postal="Q8300",
             contacto_nombre="Lucía Fernández", contacto_cargo="Responsable Comercial", contacto_email="lfernandez@tubuneu.com.ar",
             contacto_telefono="+54 9 299 611-3388", banco="Banco Provincia del Neuquén", cbu="0970022011000098765432",
             condicion_pago="60 días fecha de recepción conforme"),
        dict(cuit="30-71709342-5", razon_social="Transportes Añelo S.A.", nombre_fantasia="TransAñelo",
             condicion_iva="Responsable Inscripto", rubro="Transporte de agua, arena de fractura y cargas generales",
             email="cuentas@transanelo.com.ar", telefono="+54 299 496-2210", sitio_web="",
             domicilio="Calle 5 N° 340, Barrio Industrial", localidad="Añelo", provincia="Neuquén", codigo_postal="Q8305",
             contacto_nombre="Diego Sepúlveda", contacto_cargo="Jefe de Operaciones", contacto_email="dsepulveda@transanelo.com.ar",
             contacto_telefono="+54 9 299 520-7711", banco="Banco Nación", cbu="0110460320046012345671",
             condicion_pago="30 días fecha de certificación aprobada"),
    ]
    for p in providers:
        cols = ",".join(p.keys()) + ",created_at"
        conn.execute(f"INSERT INTO providers ({cols}) VALUES ({','.join('?' * (len(p) + 1))})", (*p.values(), ts))

    # ---------------- Usuarios ----------------
    def user(username, email, name, pwd, role, provider_id=None, team_slug=None):
        conn.execute(
            "INSERT INTO users (username,email,full_name,password_hash,role,provider_id,team_id,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (username, email, name, generate_password_hash(pwd, method=HASH_METHOD), role, provider_id,
             team_id.get(team_slug) if team_slug else None, ts),
        )

    # Contraseñas iniciales: se toman de variables de entorno o se generan al azar.
    # Nunca se guardan en el código. Las generadas se escriben en data/credenciales_iniciales.txt (permiso 600).
    generated = []

    def initial_password(env_name, label):
        value = os.environ.get(env_name)
        if value:
            return value
        value = secrets.token_urlsafe(12)
        generated.append(f"{label}: {value}")
        return value

    prov_pwd = initial_password("PORTAL_PROVIDER_PASSWORD", "Proveedores de ejemplo (30715829343, 30714662100, 30717093425)")
    admin_pwd = initial_password("PORTAL_ADMIN_PASSWORD", "Administrador (admin)")
    agent_pwd = initial_password("PORTAL_AGENT_PASSWORD", "Agentes (agente.<equipo>)")
    user("30715829343", "mrios@spp-servicios.com.ar", "Martín Ríos", prov_pwd, "provider", provider_id=1)
    user("30714662100", "lfernandez@tubuneu.com.ar", "Lucía Fernández", prov_pwd, "provider", provider_id=2)
    user("30717093425", "dsepulveda@transanelo.com.ar", "Diego Sepúlveda", prov_pwd, "provider", provider_id=3)
    user("admin", "admin@operadora.com", "Administrador del Portal", admin_pwd, "admin")
    for slug, name, *_ in TEAMS:
        user(f"agente.{slug}", f"{slug}@operadora.com", f"Agente {name.split(':')[0]}", agent_pwd, "agent", team_slug=slug)
    if generated:
        path = os.path.join(os.path.dirname(DB_PATH), "credenciales_iniciales.txt")
        with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as fh:
            fh.write("Contraseñas iniciales generadas automáticamente. Cambialas y borrá este archivo.\n")
            fh.write("\n".join(generated) + "\n")
        print(f"[portal] Se generaron contraseñas iniciales en {path}")

    # ---------------- Contratos (fechas relativas a hoy) ----------------
    d = lambda days: today + timedelta(days=days)
    contracts = [
        (1, "CT-2025-0311", "Servicio de workover y pulling con 2 equipos y dotación completa", "servicios",
         d(-210), d(520), 4_800_000, "USD", "45 días fecha de certificación aprobada", "Ing. Laura Méndez (Contratos Upstream)",
         "compras", "Bloque Loma Negra Norte"),
        (1, "CT-2024-0198", "Alquiler de equipo de pulling con operación para mantenimiento de pozos", "servicios",
         d(-700), d(21), 1_350_000, "USD", "45 días fecha de certificación aprobada", "Ing. Pablo Ruiz (Producción)",
         "certificacion", "Bloque Sierra Azul"),
        (1, "CT-2023-0077", "Servicio de cementación de pozos, campaña de perforación 2023-2024", "servicios",
         d(-1050), d(-45), 2_100_000, "USD", "45 días fecha de certificación aprobada", "Ing. Laura Méndez (Contratos Upstream)",
         "compras", "Área Añelo Este"),
        (2, "CT-2025-0420", "Acuerdo marco de suministro de casing 9 5/8\" y tubing 2 7/8\" API 5CT con accesorios", "marco",
         d(-150), d(580), 2_350_000, "USD", "60 días fecha de recepción conforme", "Lic. Sofía Arce (Abastecimiento)",
         "compras", "Base Operativa Añelo"),
        (3, "CT-2025-0388", "Transporte de agua y arena para fractura hidráulica en locaciones del área", "servicios",
         d(-90), d(275), 980_000_000, "ARS", "30 días fecha de certificación aprobada", "Ing. Diego Paz (Completación)",
         "logistica", "Área Añelo Este"),
    ]
    for (pid, numero, objeto, tipo, ini, fin, monto, moneda, cond, resp, team_slug, yac) in contracts:
        archivo = f"{numero}.pdf"
        _write_contract_pdf(archivo, [f"CONTRATO {numero}", "", f"Objeto: {objeto}", f"Tipo: {tipo}",
                                      f"Yacimiento / area: {yac}", f"Vigencia: {ini:%d/%m/%Y} al {fin:%d/%m/%Y}",
                                      f"Monto: {moneda} {monto:,.2f}", f"Condicion de pago: {cond}",
                                      f"Responsable interno: {resp}", "",
                                      "Documento de ejemplo generado por el portal (datos ficticios)."])
        conn.execute(
            """INSERT INTO contracts (provider_id,numero,objeto,tipo,fecha_inicio,fecha_fin,monto,moneda,estado,
               condicion_pago,responsable_interno,team_id,yacimiento,archivo,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, numero, objeto, tipo, ini.isoformat(), fin.isoformat(), monto, moneda,
             "vencido" if fin < today else "vigente", cond, resp, team_id[team_slug], yac, archivo, ts))

    # ---------------- Documentación y habilitaciones ----------------
    # (proveedor, categoría, nombre, detalle, emisor, número, vence en días o None, bloquea ingreso a yacimiento)
    docs = [
        (1, "Seguros", "Seguro de ART", "Nómina de 64 personas cubierta", "Prevención ART", "ART-558120", 160, 1),
        (1, "Seguros", "Póliza de Responsabilidad Civil", "Suma asegurada USD 2.000.000", "Sancor Seguros", "RC-0099812", 12, 1),
        (1, "Seguros", "Seguro de flota y equipos", "2 equipos de pulling y 9 vehículos livianos", "La Segunda", "AUT-77120", 95, 1),
        (1, "Habilitaciones", "Inducción HSE del personal en yacimiento", "Vencida para 6 operarios de la dotación B", "HSE Operadora", "IND-2025-311", -5, 1),
        (1, "Habilitaciones", "Habilitación de equipos de izaje", "Certificación anual de mástil y aparejo", "Bureau Veritas", "BV-IZ-4410", 210, 1),
        (1, "Certificaciones", "Certificado ISO 45001", "Seguridad y salud en el trabajo", "IRAM", "SST-4501-22", 400, 0),
        (1, "Legales", "Constancia de inscripción ARCA", "Actividades 091000 / 099000", "ARCA", "30715829343", None, 0),
        (2, "Seguros", "Seguro de ART", "Nómina de 18 personas cubierta", "Experta ART", "ART-31027", 230, 1),
        (2, "Seguros", "Póliza de Responsabilidad Civil", "Suma asegurada USD 500.000", "Federación Patronal", "RC-55301", 140, 1),
        (2, "Certificaciones", "Licencia API Spec 5CT del fabricante", "Copia del certificado de la acería proveedora", "API", "5CT-1182", 25, 0),
        (2, "Certificaciones", "Certificado ISO 9001", "Gestión de la calidad", "TÜV Rheinland", "QMS-9001-845", 300, 0),
        (2, "Legales", "Constancia de inscripción ARCA", "Actividad 466932", "ARCA", "30714662100", None, 0),
        (3, "Seguros", "Seguro de ART", "Nómina de 42 choferes y operarios", "Galeno ART", "ART-90215", 75, 1),
        (3, "Seguros", "Seguro de flota (cargas peligrosas)", "28 equipos tractor-cisterna y bateas", "Rivadavia Seguros", "FLT-22891", 60, 1),
        (3, "Habilitaciones", "Revisión técnica obligatoria (RTO) de la flota", "3 unidades con RTO vencida", "Taller habilitado RTO", "RTO-NQN-2025", -12, 1),
        (3, "Habilitaciones", "Licencias de conducir de cargas peligrosas (LINTI)", "Choferes habilitados", "CNRT", "LINTI-3341", 180, 1),
        (3, "Legales", "Constancia de inscripción ARCA", "Actividad 492299", "ARCA", "30717093425", None, 0),
    ]
    for (pid, cat, nombre, detalle, emisor, numero, dias, bloquea) in docs:
        conn.execute(
            """INSERT INTO provider_documents (provider_id,categoria,nombre,detalle,emisor,numero,vence,obligatorio,bloquea_ingreso,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (pid, cat, nombre, detalle, emisor, numero, d(dias).isoformat() if dias is not None else None, 1, bloquea, ts))

    # ---------------- Tickets de ejemplo ----------------
    agent = {r[0]: r[1] for r in conn.execute("SELECT username, id FROM users WHERE role='agent'")}

    def seed_ticket(code, pid, contract_id, team, kind, prio, status, subject, summary, ref, loc, days_ago, msgs):
        created = (now - timedelta(days=days_ago)).replace(microsecond=0)
        sla = created + timedelta(hours=dict((t[0], t[3]) for t in TEAMS)[team])
        conv = conn.execute(
            "INSERT INTO conversations (provider_id,contract_id,title,created_at,updated_at,provider_seen_at) VALUES (?,?,?,?,?,?)",
            (pid, contract_id, subject, created.isoformat(sep=" "), created.isoformat(sep=" "), created.isoformat(sep=" "))).lastrowid
        last = created
        for role, body, after_hours in msgs:
            last = created + timedelta(hours=after_hours)
            conn.execute("INSERT INTO messages (conversation_id,role,author_id,body,created_at) VALUES (?,?,?,?,?)",
                         (conv, role, agent.get(f"agente.{team}") if role == "agent" else None, body, last.isoformat(sep=" ")))
        resolved = last.isoformat(sep=" ") if status in ("resuelto", "cerrado") else None
        tid = conn.execute(
            """INSERT INTO tickets (code,provider_id,conversation_id,contract_id,team_id,assignee_id,kind,priority,status,subject,
               summary,reference,location,ai_confidence,sla_due,created_at,updated_at,resolved_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (code, pid, conv, contract_id, team_id[team], agent.get(f"agente.{team}") if status != "nuevo" else None,
             kind, prio, status, subject, summary, ref, loc, 0.9, sla.isoformat(sep=" "), created.isoformat(sep=" "),
             last.isoformat(sep=" "), resolved)).lastrowid
        conn.execute("INSERT INTO ticket_events (ticket_id,event,detail,created_at) VALUES (?,?,?,?)",
                     (tid, "created", f"Clasificado por IA → {dict((t[0], t[1]) for t in TEAMS)[team]}, prioridad {prio}",
                      created.isoformat(sep=" ")))
        # el proveedor ya vio todo menos la última respuesta del equipo (para mostrar el aviso de respuesta nueva)
        conn.execute("UPDATE conversations SET updated_at=?, provider_seen_at=? WHERE id=?",
                     (last.isoformat(sep=" "), (last - timedelta(minutes=1)).isoformat(sep=" ") if msgs[-1][0] == "agent"
                      else last.isoformat(sep=" "), conv))

    # ---- Historial de ~4 meses para la analítica (determinístico) ----
    rng = random.Random(2026)
    # (proveedor, contrato, equipo, tipo, prioridad, asunto, resumen, referencia, locación)
    catalog = [
        (1, 1, "certificacion", "reclamo", "alta", "Parte diario observado por horas de stand-by",
         "El company man observó horas de stand-by del equipo de workover en el parte diario.", "Parte diario LNN-{n}", "Bloque Loma Negra Norte, pozo LNN-{n}"),
        (1, 1, "pagos", "consulta", "media", "Fecha de pago del certificado de {mes}",
         "Consulta por la fecha de pago del certificado mensual de workover.", "HES 1000{n}", "Bloque Loma Negra Norte"),
        (1, 2, "certificacion", "reclamo", "media", "Acta de medición pendiente de firma",
         "El acta de medición del equipo de pulling sigue sin firma de Producción.", "Acta AM-{n}", "Bloque Sierra Azul"),
        (1, 1, "compras", "consulta", "media", "Ajuste de tarifa por polinómica",
         "Solicitud de actualización de tarifas según la fórmula polinómica del contrato.", "CT-2025-0311", "Bloque Loma Negra Norte"),
        (1, 3, "facturacion", "reclamo", "alta", "Factura rechazada por HES incorrecta",
         "Factura de cementación rechazada por referenciar una HES de otro contrato.", "FC A 0004-000{n}", "Área Añelo Este"),
        (1, None, "maestro", "consulta", "media", "Renovación de seguro de flota",
         "Envío de la renovación del seguro de flota y equipos para validación.", "Póliza AUT-{n}", ""),
        (1, 1, "hse", "reclamo", "urgente", "Casi accidente durante maniobra de pulling",
         "Reporte de casi accidente por caída de herramienta en boca de pozo, sin lesionados.", "Reporte HSE-{n}", "Bloque Loma Negra Norte, pozo LNN-{n}"),
        (2, 4, "calidad", "reclamo", "alta", "Lote de casing retenido en inspección",
         "Lote de casing 9 5/8\" retenido por diferencias en el certificado de la colada.", "OC 45000{n}", "Base Operativa Añelo"),
        (2, 4, "logistica", "reclamo", "media", "Turno de descarga reprogramado sin aviso",
         "El camión con tubing esperó 6 horas en la base por un turno reprogramado.", "Remito 0003-000{n}", "Base Operativa Añelo"),
        (2, 4, "pagos", "consulta", "media", "Estado de pago de factura de tubing",
         "Consulta por el pago de la factura de tubing con recepción conforme.", "FC A 0003-000{n}", "Base Operativa Añelo"),
        (2, 4, "facturacion", "reclamo", "media", "Nota de crédito por material devuelto",
         "Pedido de instrucciones para emitir nota de crédito por tiros devueltos.", "NC 0003-000{n}", ""),
        (2, None, "impuestos", "consulta", "baja", "Certificado de exclusión de percepciones",
         "Carga del certificado de exclusión de percepciones de IIBB.", "", ""),
        (3, 5, "logistica", "reclamo", "alta", "Demoras en el ingreso a locación",
         "Los camiones cisterna esperan más de 3 horas en el control de acceso a la locación.", "Locación AE-{n}", "Área Añelo Este, locación AE-{n}"),
        (3, 5, "certificacion", "reclamo", "media", "Viajes no certificados en el mes",
         "Diferencia entre viajes realizados y viajes certificados de agua para fractura.", "Certificado TR-{n}", "Área Añelo Este"),
        (3, 5, "pagos", "reclamo", "alta", "Pago vencido de factura de transporte",
         "Factura de transporte de arena vencida hace más de 30 días.", "FC A 0002-0000{n}", "Área Añelo Este"),
        (3, 5, "hse", "reclamo", "urgente", "Derrame menor de agua de retorno",
         "Derrame menor de agua de retorno durante la descarga, contenido en la locación.", "Reporte HSE-{n}", "Área Añelo Este, locación AE-{n}"),
        (3, None, "maestro", "consulta", "media", "Alta de nuevas unidades en la flota",
         "Solicitud de habilitación de 4 nuevos equipos tractor-cisterna.", "", ""),
    ]
    meses = ["junio", "julio", "agosto", "septiembre", "octubre"]
    team_sla = {t[0]: t[3] for t in TEAMS}
    history = []
    for i in range(46):
        prov, contract, team, kind, prio, subject, summary, ref, loc = rng.choice(catalog)
        n = rng.randint(1000, 1999)
        days_ago = rng.uniform(11, 125)
        sla_h = team_sla[team]
        # tiempos realistas: primera respuesta entre 10% y 120% del SLA; algunos casos fuera de plazo
        first = max(0.3, rng.uniform(0.05, 0.6) * sla_h)
        # la mayoría se resuelve dentro del SLA; el resto se excede (para que la analítica muestre desvíos)
        resolve = rng.uniform(first + 0.1, sla_h * 0.95) if rng.random() < 0.86 else sla_h * rng.uniform(1.1, 2.5)
        status = "cerrado" if days_ago > 40 else rng.choice(["resuelto", "resuelto", "cerrado", "en_curso"])
        history.append((days_ago, prov, contract, team, kind, prio, status,
                        subject.format(mes=rng.choice(meses), n=n), summary, ref.format(n=n), loc.format(n=n), first, resolve))
    history.sort(key=lambda h: -h[0])

    counter = [0]

    def next_code():
        counter[0] += 1
        return f"PRV-2026-{counter[0]:05d}"

    for (days_ago, prov, contract, team, kind, prio, status, subject, summary, ref, loc, first, resolve) in history:
        msgs = [("provider", summary, 0), ("assistant", f"Registré tu {kind} y lo derivé al equipo correspondiente.", 0.02),
                ("agent", "Hola, ya estamos revisando el caso con el área responsable. Te actualizamos a la brevedad.", first)]
        if status in ("resuelto", "cerrado"):
            msgs.append(("agent", "Caso resuelto. Quedamos a disposición por cualquier otra consulta.", resolve))
        seed_ticket(next_code(), prov, contract, team, kind, prio, status, subject, summary, ref, loc, days_ago, msgs)
    # el historial ya fue leído por los proveedores (solo los casos recientes muestran "respuesta nueva")
    conn.execute("UPDATE conversations SET provider_seen_at=updated_at")

    seed_ticket(next_code(), 1, 1, "certificacion", "reclamo", "alta", "resuelto",
                "Certificado de servicios de octubre rechazado",
                "El proveedor reclama el rechazo del certificado de octubre del contrato CT-2025-0311 (workover, Loma Negra Norte). "
                "Motivo informado: partes diarios del pozo LNN-1042 sin firma del company man.",
                "CERT-OCT-2025, LNN-1042", "Bloque Loma Negra Norte, pozo LNN-1042", 9, [
                    ("provider", "Hola, nos rechazaron el certificado de servicios de octubre del contrato de workover y no sabemos el motivo.", 0),
                    ("assistant", "Gracias, Martín. Registré tu reclamo con el ID **PRV-2026-00001** y lo derivé a **Certificación de Servicios**. "
                                  "Si tenés los partes diarios firmados, podés adjuntarlos acá.", 0.02),
                    ("agent", "Hola Martín. El certificado se rechazó porque 3 partes diarios del pozo LNN-1042 no tenían la firma del company man. "
                              "Ya los recibimos firmados y aprobamos la HES 1000452. Podés facturar con esa referencia.", 30),
                ])
    seed_ticket(next_code(), 2, 4, "calidad", "reclamo", "alta", "esperando_proveedor",
                "Tubing 2 7/8\" rechazado en inspección de recepción",
                "Lote de 180 tiros de tubing 2 7/8\" J55 entregado en Base Operativa Añelo, retenido en inspección: "
                "falta el mill certificate de la colada 4471 y hay 6 tiros con daño en rosca.",
                "OC 4500087321, remito 0003-00012877", "Base Operativa Añelo", 3, [
                    ("provider", "Buenos días, nos informan que retuvieron el lote de tubing de la OC 4500087321 en la base. ¿Qué falta?", 0),
                    ("assistant", "Registré tu reclamo **PRV-2026-00002** y lo derivé a **Calidad e Inspección (QA/QC)**.", 0.02),
                    ("agent", "Hola Lucía. Para liberar el lote necesitamos el mill certificate de la colada 4471. Además, 6 tiros tienen daño en rosca "
                              "y quedan para devolución. ¿Nos enviás el certificado y nos confirmás la reposición?", 20),
                ])
    pagos_code = next_code()
    seed_ticket(pagos_code, 3, 5, "pagos", "consulta", "media", "en_curso",
                "Estado de pago de la factura A 0002-00004518",
                "El proveedor consulta la fecha de pago de la factura A 0002-00004518 (transporte de agua, septiembre), "
                "emitida con HES 1000398.", "FC A 0002-00004518, HES 1000398", "Área Añelo Este", 1, [
                    ("provider", "¿Me pueden decir cuándo se paga la factura A 0002-00004518 de septiembre?", 0),
                    ("assistant", "Registré tu consulta **PRV-2026-00003** y la derivé a **Tesorería y Pagos**.", 0.02),
                ])
    conn.execute("UPDATE tickets SET assignee_id=? WHERE code=?", (agent["agente.pagos"], pagos_code))


CONTRACT_DIR = os.path.join(os.path.dirname(DB_PATH), "contracts")


def _write_contract_pdf(filename, lines):
    """Genera un PDF de una página con texto plano (solo para datos de ejemplo)."""
    os.makedirs(CONTRACT_DIR, exist_ok=True)
    esc = lambda t: t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    text = "BT /F1 12 Tf 60 780 Td 16 TL " + " ".join(f"({esc(l)}) Tj T*" for l in lines) + " ET"
    stream = text.encode("latin-1", "replace")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    with open(os.path.join(CONTRACT_DIR, filename), "wb") as fh:
        fh.write(bytes(out))


def contract_status(c):
    """Estado efectivo: calcula 'por_vencer' (<=30 días) y 'vencido' a partir de la fecha de fin."""
    if c["estado"] == "rescindido":
        return "rescindido"
    days = (datetime.fromisoformat(c["fecha_fin"]).date() - datetime.now().date()).days
    if days < 0:
        return "vencido"
    if days <= 30:
        return "por_vencer"
    return "vigente"


def document_status(doc):
    """Estado de un documento: vigente, por_vencer (<=30 días), vencido o permanente (sin vencimiento)."""
    if not doc["vence"]:
        return "permanente", None
    days = (datetime.fromisoformat(doc["vence"]).date() - datetime.now().date()).days
    if days < 0:
        return "vencido", days
    if days <= 30:
        return "por_vencer", days
    return "vigente", days
