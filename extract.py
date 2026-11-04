"""Validación de archivos adjuntos y extracción de texto para que la IA pueda leerlos."""
import csv
import html
import io
import re

# extensión -> (mime canónico, categoría)
ALLOWED = {
    "pdf": ("application/pdf", "pdf"),
    "txt": ("text/plain", "text"),
    "csv": ("text/csv", "text"),
    "md": ("text/markdown", "text"),
    "json": ("application/json", "text"),
    "xml": ("application/xml", "text"),
    "html": ("text/html", "html"),
    "htm": ("text/html", "html"),
    "doc": ("application/msword", "binary"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "xls": ("application/vnd.ms-excel", "binary"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "png": ("image/png", "image"),
    "jpg": ("image/jpeg", "image"),
    "jpeg": ("image/jpeg", "image"),
    "webp": ("image/webp", "image"),
    "gif": ("image/gif", "image"),
}

MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_FILES_PER_MESSAGE = 10
MAX_TEXT_CHARS = 60_000

# Firmas mágicas para evitar que se suba un ejecutable renombrado
_MAGIC = {
    "pdf": [b"%PDF"],
    "png": [b"\x89PNG"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "gif": [b"GIF8"],
    "webp": [b"RIFF"],
    "docx": [b"PK\x03\x04"],
    "xlsx": [b"PK\x03\x04"],
    "doc": [b"\xd0\xcf\x11\xe0"],
    "xls": [b"\xd0\xcf\x11\xe0"],
}


def extension(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def validate(filename, data):
    """Devuelve (ok, mensaje_error)."""
    ext = extension(filename)
    if ext not in ALLOWED:
        return False, f"El formato .{ext or '?'} no está permitido."
    if len(data) == 0:
        return False, "El archivo está vacío."
    if len(data) > MAX_FILE_BYTES:
        return False, f"Supera el máximo de {MAX_FILE_BYTES // (1024 * 1024)} MB."
    sigs = _MAGIC.get(ext)
    if sigs and not any(data.startswith(s) for s in sigs):
        return False, "El contenido no coincide con la extensión del archivo."
    if ALLOWED[ext][1] in ("text", "html") and b"\x00" in data[:4096]:
        return False, "El archivo de texto parece ser binario."
    return True, ""


def _decode(data):
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _html_to_text(raw):
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(raw)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()


def extract_text(filename, data):
    """Texto plano legible del archivo (o None si no aplica, p. ej. imágenes)."""
    ext = extension(filename)
    kind = ALLOWED.get(ext, ("", ""))[1]
    try:
        if kind == "text":
            text = _decode(data)
            if ext == "csv":
                rows = list(csv.reader(io.StringIO(text)))
                text = "\n".join(" | ".join(r) for r in rows[:500])
        elif kind == "html":
            text = _html_to_text(_decode(data))
        elif kind == "pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            text = "\n\n".join((p.extract_text() or "") for p in reader.pages[:60])
        elif kind == "docx":
            import docx
            d = docx.Document(io.BytesIO(data))
            parts = [p.text for p in d.paragraphs if p.text.strip()]
            for table in d.tables:
                for row in table.rows:
                    parts.append(" | ".join(c.text.strip() for c in row.cells))
            text = "\n".join(parts)
        elif kind == "xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            parts = []
            for ws in wb.worksheets[:10]:
                parts.append(f"## Hoja: {ws.title}")
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i >= 500:
                        parts.append("… (filas truncadas)")
                        break
                    if any(v is not None for v in row):
                        parts.append(" | ".join("" if v is None else str(v) for v in row))
            text = "\n".join(parts)
        elif kind == "binary":
            return "(Formato Office antiguo: el equipo lo revisará manualmente; no se pudo leer automáticamente.)"
        else:
            return None
    except Exception as exc:  # archivo corrupto o protegido
        return f"(No se pudo leer el contenido: {type(exc).__name__})"
    text = (text or "").strip()
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n… (contenido truncado)"
    return text or "(Sin texto extraíble; puede ser un documento escaneado.)"


def human_size(n):
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
