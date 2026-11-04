# Portal de Proveedores

Canal único de consultas y reclamos entre los proveedores y la empresa. Cada proveedor
ingresa con su usuario y contraseña, elige el contrato al que se refiere y habla con un
asistente de IA en lenguaje natural. El asistente responde lo que puede y, si hace falta,
crea un **ticket con ID** (`PRV-2026-00001`) y lo deriva al equipo que corresponde.

## Cómo ejecutarlo

```bash
cp .env.example .env      # completar ANTHROPIC_API_KEY para usar Claude
./run.sh                  # crea el entorno la primera vez y levanta http://127.0.0.1:5050
```

Requiere Python 3.9 o superior. La base SQLite y los archivos se guardan en `data/`
(se crea con datos de ejemplo la primera vez; borrar la carpeta para empezar de cero).

### Usuarios de ejemplo

| Rol | Usuario |
|---|---|
| Proveedor (Distribuidora Andina S.A.) | `30712345671` |
| Proveedor (Juan Pérez, monotributista) | `20287654325` |
| Administrador (ve todos los equipos) | `admin` |
| Agente de un equipo | `agente.pagos`, `agente.facturacion`, `agente.compras`, `agente.logistica`, `agente.calidad`, `agente.impuestos`, `agente.maestro`, `agente.general` |

Las contraseñas **no están en el código**. Al crear la base se toman de las variables
`PORTAL_PROVIDER_PASSWORD`, `PORTAL_ADMIN_PASSWORD` y `PORTAL_AGENT_PASSWORD`; si no
están definidas se generan al azar y se guardan en `data/credenciales_iniciales.txt`
(solo legible por tu usuario). Cambialas al ingresar por primera vez.

## Publicarlo en la web (Render)

GitHub guarda el código, pero no puede ejecutar un sistema con servidor y base de datos
(GitHub Pages solo sirve páginas estáticas). Para abrir el portal desde cualquier
dispositivo se publica en un hosting; el repositorio ya incluye `render.yaml`:

1. Crear una cuenta en [render.com](https://render.com) y conectar tu cuenta de GitHub.
2. **New → Blueprint**, elegir este repositorio y confirmar.
3. Cuando lo pida, pegar tu `ANTHROPIC_API_KEY`.
4. Render genera solo la clave de sesión y las contraseñas iniciales. Para verlas:
   servicio `portal-proveedores` → **Environment** → `PORTAL_ADMIN_PASSWORD`, etc.
5. La URL pública queda como `https://portal-proveedores-xxxx.onrender.com`.

El blueprint usa el plan **Starter** con un disco de 1 GB (servicio pago), porque en el
plan gratuito los tickets y archivos se borran cada vez que el servicio se reinicia.

## Qué incluye

**Para el proveedor**
- **Asistente (pantalla principal):** chat en lenguaje natural. Antes de escribir, el
  proveedor elige el contrato (o indica que no está relacionado con uno). Puede adjuntar
  hasta 10 archivos por mensaje (PDF, Word, Excel, TXT, CSV, HTML, XML, JSON e imágenes,
  15 MB c/u) con clic, arrastrando o pegando. Panel lateral con el ticket, su progreso,
  equipo, prioridad y plazo.
- **Mis tickets:** listado con filtros (abiertos / resueltos / todos), búsqueda por ID,
  factura, OC o contrato, y aviso de respuestas nuevas.
- **Mis contratos:** contratos vigentes, por vencer y vencidos, con detalle, PDF, tickets
  asociados y un botón para iniciar una consulta sobre ese contrato.
- **Mi perfil:** razón social, CUIT, condición de IVA, domicilio, datos bancarios
  (enmascarados), condición de pago, contacto editable, foto de perfil y cambio de
  contraseña. Los datos fiscales y bancarios solo cambian mediante ticket (antifraude).

**Para los equipos internos** (`/equipo`)
- Bandeja ordenada por prioridad y vencimiento, con filtros por equipo, estado,
  prioridad y contrato.
- Detalle del ticket: resumen automático, conversación completa, respuesta al proveedor o
  nota interna (con adjuntos), cambio de estado, prioridad, equipo (re-derivación) y
  asignado, ficha del proveedor y del contrato, e historial de eventos.

## Cómo deriva la IA

`ai.py` envía a Claude el perfil del proveedor, el contrato elegido, el historial y el
mensaje con sus adjuntos (los PDF e imágenes van como documentos nativos; Word, Excel,
HTML y texto se convierten a texto). Claude devuelve una salida estructurada
(JSON Schema) con la respuesta, el tipo (consulta/reclamo), el equipo, la prioridad, si
corresponde abrir ticket, asunto, resumen y referencias (facturas, OC, remitos).

- Modelo: `claude-opus-5-5`, esfuerzo `low` para que el chat responda rápido
  (configurable con `PORTAL_AI_MODEL` y `PORTAL_AI_EFFORT`).
- Se activó el **fallback del lado del servidor** (`fallbacks: "default"`): si el modelo
  declina una solicitud, la API la reintenta automáticamente con otro modelo.
- El prompt del sistema se cachea (prompt caching) para bajar costo y latencia.
- **Sin `ANTHROPIC_API_KEY`** (o si la API falla), el portal sigue funcionando con un
  clasificador local por palabras clave ("modo básico"), que siempre registra el ticket.

Equipos y plazos (SLA) se definen en `db.py` (`TEAMS`); la base de conocimiento que la IA
puede responder sin derivar está en `ai.py` (`KNOWLEDGE_BASE`). Ajustalas a tus políticas.

## Seguridad aplicada

- Contraseñas con PBKDF2-SHA256 (600.000 iteraciones); bloqueo de 15 min tras 5 intentos
  fallidos; mensajes de error que no revelan si el usuario existe.
- Cookies de sesión `HttpOnly` + `SameSite=Lax` (y `Secure` con `PORTAL_HTTPS=1`),
  token CSRF en todos los `POST`.
- Cabeceras CSP, `X-Frame-Options`, `nosniff`, `Referrer-Policy`.
- Control de acceso por proveedor en conversaciones, tickets, archivos y contratos
  (un proveedor no puede ver datos de otro).
- Adjuntos: lista blanca de extensiones, verificación de firma del archivo, límites de
  tamaño y cantidad, nombres aleatorios en disco y descarga solo autenticada.
- El texto de los mensajes se escapa siempre antes de mostrarlo; el contenido de los
  adjuntos se le indica a la IA como dato, no como instrucción (mitiga prompt injection).

## Antes de producción

- Fuera de Render: servir con `gunicorn` detrás de HTTPS y definir
  `PORTAL_SECRET_KEY` y `PORTAL_HTTPS=1`.
- Migrar a PostgreSQL y a un almacenamiento de archivos (S3 o similar) con antivirus.
- Integrar alta de usuarios / recuperación de contraseña por e-mail, notificaciones por
  correo y, si corresponde, SSO para los equipos internos.
- Conectar la IA con el ERP (estado de pagos, facturas) mediante herramientas para que
  pueda responder más casos sin derivar.

## Estructura

```
app.py            rutas, autenticación, tickets, contratos, perfil, panel interno
ai.py             asistente (Claude + clasificador local de respaldo)
db.py             esquema SQLite y datos de ejemplo
extract.py        validación de adjuntos y extracción de texto (PDF, Word, Excel, HTML…)
templates/        vistas (Jinja2)
static/css/app.css  sistema de diseño (tokens, modo claro/oscuro, responsive)
static/js/        chat.js (asistente), app.js (comunes), staff.js (panel interno)
```
