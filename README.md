# Portal de Proveedores · Oil&Gas

Canal único de consultas y reclamos entre una operadora de petróleo y gas y sus
contratistas y proveedores de bienes y servicios (servicios de pozo, tubulares OCTG,
transporte, etc.). Cada proveedor ingresa con su usuario y contraseña, elige el contrato al
que se refiere y habla con un asistente de IA en lenguaje natural. El asistente responde lo
que puede y, si hace falta, crea un **ticket con ID** (`PRV-2026-00001`) y lo deriva al
equipo que corresponde: certificación de servicios, QA/QC, HSE, pagos, etc.

**Demo en línea:** https://portal-proveedores-ow1e.onrender.com ·
**Instructivo de uso:** [docs/Instructivo Portal de Proveedores.docx](docs/Instructivo%20Portal%20de%20Proveedores.docx)

> Todos los proveedores, contratos, yacimientos y documentos son ficticios.

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
| Proveedor: Servicios Petroleros Patagónicos S.A. (workover y pulling) | `30715829343` |
| Proveedor: Tubulares del Neuquén S.R.L. (casing y tubing OCTG) | `30714662100` |
| Proveedor: Transportes Añelo S.A. (agua y arena de fractura) | `30717093425` |
| Administrador (ve todos los equipos) | `admin` |
| Agente de un equipo | `agente.pagos`, `agente.facturacion`, `agente.certificacion`, `agente.compras`, `agente.logistica`, `agente.calidad`, `agente.hse`, `agente.impuestos`, `agente.maestro`, `agente.general` |

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
- **Mis contratos:** contratos vigentes, por vencer y vencidos, con yacimiento o área,
  detalle, PDF, tickets asociados y un botón para iniciar una consulta sobre ese contrato.
- **Mi documentación:** ART, pólizas, seguros de flota, inducciones HSE, habilitaciones
  de equipos, RTO y certificaciones (ISO, API 5CT), con vencimientos y alertas. Marca los
  documentos que **bloquean el ingreso a yacimiento** si vencen y tiene un botón
  **Renovar** que abre el asistente con el pedido listo para adjuntar la constancia.
- **Mi perfil:** razón social, CUIT, condición de IVA, domicilio, datos bancarios
  (enmascarados), condición de pago, contacto editable, foto de perfil y cambio de
  contraseña. Los datos fiscales y bancarios solo cambian mediante ticket (antifraude).

- **Documentos duplicados:** si el proveedor adjunta un documento que ya está en otro de
  sus tickets abiertos (mismo archivo o mismo contenido con otro nombre), el asistente le
  avisa con el número de ese ticket y no abre uno nuevo salvo que confirme que es otro
  pedido. En ese caso, el equipo ve la advertencia de posible duplicado en el ticket.
- **Mis tickets:** resumen arriba con abiertos, en revisión, esperando tu respuesta y
  resueltos; el menú muestra la cantidad de tickets abiertos.

**Para los equipos internos** (`/equipo`)
- Bandeja ordenada por prioridad y vencimiento, con filtros por equipo, estado,
  prioridad y contrato.
- Detalle del ticket: resumen automático con referencias (OC, HES, remitos, pozos) y
  locación, conversación completa, respuesta al proveedor o nota interna (con adjuntos),
  cambio de estado, prioridad, equipo (re-derivación) y asignado, estado de la
  documentación del proveedor, ficha del contrato e historial de eventos.

**Analítica** (`/equipo/analitica`, solo administrador y equipos)
- Reclamos por proveedor y por contrato, tiempo de primera respuesta y de resolución de
  cada ticket, promedios y medianas, cumplimiento del SLA por equipo, filtros por
  período, equipo y proveedor, y exportación a CSV.

**Tipos de caso y SLA** (`/equipo/tipos-de-caso`)
- Tabla de tipos de consulta y reclamo con el equipo que resuelve cada uno, la prioridad
  mínima, el plazo de primera respuesta y el SLA de resolución. El asistente la usa para
  clasificar y derivar cada ticket nuevo.
- El administrador crea, edita y desactiva tipos; los agentes la ven en solo lectura.
- Los plazos son internos: el proveedor no ve plazos de respuesta, SLA ni tiempos promedio.

**Interfaz**
- Paleta corporativa (azul institucional `#005DA7`, grises neutros y tipografía tipo DIN)
  con modo claro y oscuro: botón en el menú (o arriba en el celular) que recuerda la
  elección; si no se elige, sigue la configuración del sistema.

### Específico de Oil&Gas
- **10 equipos** con plazos propios, entre ellos *Certificación de Servicios* (partes
  diarios, actas de medición, HES), *Calidad e Inspección QA/QC* (mill certificates,
  API 5CT), *HSE* (incidentes, derrames, permisos de trabajo; respuesta en 4 h) y *Alta y
  Documentación de Proveedores* (seguros y habilitaciones para ingresar a yacimiento).
- **Seguridad primero:** un mensaje que describe un incidente, derrame o lesión se deriva
  a HSE con prioridad urgente y la respuesta empieza recordando avisar en el sitio.
- **Locación:** la IA detecta yacimiento, bloque, pozo o base y lo guarda en el ticket.
- **Circuito servicio → parte diario → certificado/HES → factura** y **material → base →
  inspección → recepción conforme → factura** cargados en la base de conocimiento de la IA.

## Cómo deriva la IA

`ai.py` envía a Claude el perfil del proveedor, el contrato elegido, el historial y el
mensaje con sus adjuntos (los PDF e imágenes van como documentos nativos; Word, Excel,
HTML y texto se convierten a texto). Claude devuelve una salida estructurada
(JSON Schema) con la respuesta, el tipo (consulta/reclamo), el equipo, la prioridad, si
corresponde abrir ticket, asunto, resumen, referencias (facturas, OC, HES, remitos, pozos)
y locación. También recibe la documentación del proveedor con sus vencimientos, para
advertir cuando algo vencido impide operar en yacimiento.

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
