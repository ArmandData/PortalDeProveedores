"""Capa de datos: esquema SQLite, conexión y datos de ejemplo."""
import os
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
    archivo TEXT,
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
    ai_confidence REAL,
    sla_due TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT
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
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket_events (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    actor_id INTEGER REFERENCES users(id),
    event TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_tickets_provider ON tickets(provider_id);
CREATE INDEX IF NOT EXISTS idx_tickets_team ON tickets(team_id, status);
CREATE INDEX IF NOT EXISTS idx_conv_provider ON conversations(provider_id);
CREATE INDEX IF NOT EXISTS idx_contracts_provider ON contracts(provider_id);
"""

TEAMS = [
    ("pagos", "Tesorería y Pagos", "Estado de pagos, fechas de cobro, órdenes de pago, transferencias y cheques.", 24, "#0f766e"),
    ("facturacion", "Cuentas a Pagar", "Recepción, validación y rechazo de facturas, notas de crédito y débito.", 48, "#2563eb"),
    ("compras", "Compras", "Órdenes de compra, cotizaciones, precios, licitaciones y condiciones comerciales.", 48, "#7c3aed"),
    ("logistica", "Logística y Recepción", "Entregas, turnos de descarga, remitos y recepción de mercadería.", 24, "#c2410c"),
    ("calidad", "Calidad y Devoluciones", "Rechazos de calidad, devoluciones, no conformidades y garantías.", 72, "#be123c"),
    ("impuestos", "Impuestos y Retenciones", "Retenciones, percepciones, certificados de exclusión y constancias.", 72, "#a16207"),
    ("maestro", "Alta y Datos de Proveedor", "Alta, modificación de datos bancarios, fiscales o de contacto, documentación.", 72, "#475569"),
    ("general", "Mesa de Ayuda General", "Consultas que no encajan en otra categoría o requieren análisis.", 48, "#4f46e5"),
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
    if seed and conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0] == 0:
        _seed(conn)
    conn.commit()
    conn.close()


def _seed(conn):
    ts = now_iso()
    for t in TEAMS:
        conn.execute("INSERT INTO teams (slug, name, description, sla_hours, color) VALUES (?,?,?,?,?)", t)

    providers = [
        dict(cuit="30-71234567-1", razon_social="Distribuidora Andina S.A.", nombre_fantasia="Andina Insumos",
             condicion_iva="Responsable Inscripto", rubro="Insumos industriales", email="facturacion@andina.com.ar",
             telefono="+54 11 4321-5678", sitio_web="https://andina.com.ar", domicilio="Av. Corrientes 1234, Piso 5",
             localidad="CABA", provincia="Buenos Aires", codigo_postal="C1043", contacto_nombre="María González",
             contacto_cargo="Responsable de Cuentas", contacto_email="mgonzalez@andina.com.ar",
             contacto_telefono="+54 9 11 5555-1234", banco="Banco Nación", cbu="0110599520000012345678",
             condicion_pago="30 días fecha factura"),
        dict(cuit="20-28765432-5", razon_social="Juan Pérez", nombre_fantasia="Pérez Servicios Técnicos",
             condicion_iva="Monotributista", rubro="Mantenimiento eléctrico", email="juan@perezservicios.com",
             telefono="+54 351 422-1100", sitio_web="", domicilio="Bv. San Juan 455", localidad="Córdoba",
             provincia="Córdoba", codigo_postal="X5000", contacto_nombre="Juan Pérez", contacto_cargo="Titular",
             contacto_email="juan@perezservicios.com", contacto_telefono="+54 9 351 600-7788", banco="Banco Galicia",
             cbu="0070999830004123456789", condicion_pago="15 días fecha factura"),
    ]
    for p in providers:
        cols = ",".join(p.keys()) + ",created_at"
        conn.execute(f"INSERT INTO providers ({cols}) VALUES ({','.join('?' * (len(p) + 1))})", (*p.values(), ts))

    def user(username, email, name, pwd, role, provider_id=None, team_slug=None):
        team_id = None
        if team_slug:
            team_id = conn.execute("SELECT id FROM teams WHERE slug=?", (team_slug,)).fetchone()[0]
        conn.execute(
            "INSERT INTO users (username,email,full_name,password_hash,role,provider_id,team_id,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (username, email, name, generate_password_hash(pwd, method=HASH_METHOD), role, provider_id, team_id, ts),
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

    prov_pwd = initial_password("PORTAL_PROVIDER_PASSWORD", "Proveedores de ejemplo (30712345671, 20287654325)")
    admin_pwd = initial_password("PORTAL_ADMIN_PASSWORD", "Administrador (admin)")
    agent_pwd = initial_password("PORTAL_AGENT_PASSWORD", "Agentes (agente.<equipo>)")
    user("30712345671", "mgonzalez@andina.com.ar", "María González", prov_pwd, "provider", provider_id=1)
    user("20287654325", "juan@perezservicios.com", "Juan Pérez", prov_pwd, "provider", provider_id=2)
    user("admin", "admin@empresa.com", "Administrador del Portal", admin_pwd, "admin")
    for slug, *_ in TEAMS:
        user(f"agente.{slug}", f"{slug}@empresa.com", f"Agente {slug.capitalize()}", agent_pwd, "agent", team_slug=slug)
    if generated:
        path = os.path.join(os.path.dirname(DB_PATH), "credenciales_iniciales.txt")
        with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as fh:
            fh.write("Contraseñas iniciales generadas automáticamente. Cambialas y borrá este archivo.\n")
            fh.write("\n".join(generated) + "\n")
        print(f"[portal] Se generaron contraseñas iniciales en {path}")

    # Contratos de ejemplo (fechas relativas a hoy para que los estados sean coherentes)
    today = datetime.now().date()
    contracts = [
        (1, "CT-2025-0142", "Provisión de insumos industriales (guantes, EPP y consumibles de planta)", "suministro",
         today - timedelta(days=300), today + timedelta(days=430), 48_500_000, "ARS", "vigente",
         "30 días fecha factura", "Laura Méndez (Compras)", "compras"),
        (1, "CT-2024-0087", "Servicio de abastecimiento just-in-time para línea de envasado", "servicios",
         today - timedelta(days=700), today + timedelta(days=18), 12_300_000, "ARS", "vigente",
         "45 días fecha factura", "Diego Sosa (Logística)", "logistica"),
        (1, "CT-2023-0031", "Acuerdo marco de precios para repuestos mecánicos", "marco",
         today - timedelta(days=1100), today - timedelta(days=40), 85_000, "USD", "vencido",
         "60 días fecha factura", "Laura Méndez (Compras)", "compras"),
        (2, "CT-2025-0219", "Mantenimiento eléctrico preventivo y correctivo de planta Córdoba", "servicios",
         today - timedelta(days=120), today + timedelta(days=245), 9_600_000, "ARS", "vigente",
         "15 días fecha factura", "Ing. Pablo Ruiz (Mantenimiento)", "compras"),
    ]
    for (pid, numero, objeto, tipo, ini, fin, monto, moneda, estado, cond, resp, team_slug) in contracts:
        tid = conn.execute("SELECT id FROM teams WHERE slug=?", (team_slug,)).fetchone()[0]
        archivo = f"{numero}.pdf"
        _write_contract_pdf(archivo, [f"CONTRATO {numero}", "", f"Objeto: {objeto}", f"Tipo: {tipo}",
                                      f"Vigencia: {ini:%d/%m/%Y} al {fin:%d/%m/%Y}",
                                      f"Monto: {moneda} {monto:,.2f}", f"Condicion de pago: {cond}",
                                      f"Responsable interno: {resp}", "", "Documento de ejemplo generado por el portal."])
        conn.execute(
            """INSERT INTO contracts (provider_id,numero,objeto,tipo,fecha_inicio,fecha_fin,monto,moneda,estado,
               condicion_pago,responsable_interno,team_id,archivo,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, numero, objeto, tipo, ini.isoformat(), fin.isoformat(), monto, moneda, estado, cond, resp, tid, archivo, ts))

    # Un ticket histórico para que el proveedor demo vea el listado poblado
    created = (datetime.now() - timedelta(days=6)).replace(microsecond=0)
    c = conn.execute(
        "INSERT INTO conversations (provider_id,contract_id,title,created_at,updated_at,provider_seen_at) VALUES (1,1,?,?,?,?)",
        ("Factura A 0003-00001245 rechazada", created.isoformat(sep=" "), created.isoformat(sep=" "),
         created.isoformat(sep=" ")),
    )
    conv_id = c.lastrowid
    team_id = conn.execute("SELECT id FROM teams WHERE slug='facturacion'").fetchone()[0]
    conn.execute(
        """INSERT INTO tickets (code,provider_id,conversation_id,contract_id,team_id,kind,priority,status,subject,summary,reference,
           ai_confidence,sla_due,created_at,updated_at,resolved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("PRV-2026-00001", 1, conv_id, 1, team_id, "reclamo", "media", "resuelto",
         "Factura A 0003-00001245 rechazada",
         "El proveedor reclama el rechazo de la factura A 0003-00001245 por falta de número de OC.",
         "FC A 0003-00001245", 0.92, (created + timedelta(hours=48)).isoformat(sep=" "),
         created.isoformat(sep=" "), (created + timedelta(days=1)).isoformat(sep=" "),
         (created + timedelta(days=1)).isoformat(sep=" ")),
    )
    msgs = [
        ("provider", "Hola, me rechazaron la factura A 0003-00001245 y no entiendo por qué.", 0),
        ("assistant", "Gracias, María. Registré tu reclamo con el ID **PRV-2026-00001** y lo derivé a **Cuentas a Pagar**. "
                      "Te avisamos por acá cuando haya novedades.", 0),
        ("agent", "Hola María, la factura fue rechazada porque no indicaba el N° de OC. Ya la reprocesamos con la OC 4500012345; "
                  "se paga en la próxima corrida del viernes.", 1),
    ]
    for i, (role, body, offset) in enumerate(msgs):
        when = (created + timedelta(days=offset, minutes=i)).isoformat(sep=" ")
        author = None
        if role == "agent":
            author = conn.execute("SELECT id FROM users WHERE username='agente.facturacion'").fetchone()[0]
        conn.execute("INSERT INTO messages (conversation_id,role,author_id,body,created_at) VALUES (?,?,?,?,?)",
                     (conv_id, role, author, body, when))


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
