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
CREATE INDEX IF NOT EXISTS idx_docs_provider ON provider_documents(provider_id);
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
        created = now - timedelta(days=days_ago)
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

    seed_ticket("PRV-2026-00001", 1, 1, "certificacion", "reclamo", "alta", "resuelto",
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
    seed_ticket("PRV-2026-00002", 2, 4, "calidad", "reclamo", "alta", "esperando_proveedor",
                "Tubing 2 7/8\" rechazado en inspección de recepción",
                "Lote de 180 tiros de tubing 2 7/8\" J55 entregado en Base Operativa Añelo, retenido en inspección: "
                "falta el mill certificate de la colada 4471 y hay 6 tiros con daño en rosca.",
                "OC 4500087321, remito 0003-00012877", "Base Operativa Añelo", 3, [
                    ("provider", "Buenos días, nos informan que retuvieron el lote de tubing de la OC 4500087321 en la base. ¿Qué falta?", 0),
                    ("assistant", "Registré tu reclamo **PRV-2026-00002** y lo derivé a **Calidad e Inspección (QA/QC)**.", 0.02),
                    ("agent", "Hola Lucía. Para liberar el lote necesitamos el mill certificate de la colada 4471. Además, 6 tiros tienen daño en rosca "
                              "y quedan para devolución. ¿Nos enviás el certificado y nos confirmás la reposición?", 20),
                ])
    seed_ticket("PRV-2026-00003", 3, 5, "pagos", "consulta", "media", "en_curso",
                "Estado de pago de la factura A 0002-00004518",
                "El proveedor consulta la fecha de pago de la factura A 0002-00004518 (transporte de agua, septiembre), "
                "emitida con HES 1000398.", "FC A 0002-00004518, HES 1000398", "Área Añelo Este", 1, [
                    ("provider", "¿Me pueden decir cuándo se paga la factura A 0002-00004518 de septiembre?", 0),
                    ("assistant", "Registré tu consulta **PRV-2026-00003** y la derivé a **Tesorería y Pagos**.", 0.02),
                ])
    conn.execute("UPDATE tickets SET assignee_id=? WHERE code='PRV-2026-00003'", (agent["agente.pagos"],))


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
