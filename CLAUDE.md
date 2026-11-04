# Mesa de Proveedores: reglas del negocio

Nombre del portal: **Mesa de Proveedores**. Nombre del asistente del chat: **MiProveedor** (se presenta como asistente virtual).

## Derivación de casos

- **Toda modificación de contrato va a Administración de Contratos** (`contratos`): adendas,
  cambios de alcance, monto, plazo o condiciones, prórrogas, renovaciones, ajustes de tarifa
  por polinómica, redeterminación de precios, cesiones y rescisiones. Vale aunque el contrato
  pertenezca a otro equipo.
  - La regla se aplica en tres lugares: el prompt del asistente (`ai.py`, regla 7), el
    clasificador sin IA (`ai.is_contract_modification`) y una garantía en el servidor al
    crear el ticket (`app.api_send`), que corrige la decisión de la IA.
  - Compras (`compras`) solo atiende órdenes de compra, cotizaciones y licitaciones.
  - Las pólizas y seguros no son contratos: van a Alta y Documentación (`maestro`).
  - Un incidente HSE en curso va siempre a HSE, aunque mencione el contrato.

## Lo que nunca ve el proveedor

- Plazos de respuesta, SLA ni tiempos promedio de atención.
- Score, evaluaciones ni el motivo de un bloqueo (solo ve que tiene la operación suspendida o
  restringida).

## Permisos

- Tipos de caso y SLA: los edita el administrador; los equipos solo los ven.
- Scoring y bloqueos: Proveedores y Performance (`performance`) y el administrador.
- Revisión de requisitos: administrador, Alta y Documentación (`maestro`) y Proveedores y
  Performance.

## Requisitos y alarmas

- Cada requisito se presenta N días antes o después del inicio de operaciones del proveedor.
  Los «antes» son obligatorios para operar: si faltan, `provider_standing` restringe la operación.
- El catálogo define los valores por defecto; `provider_requirement_settings` guarda solo lo que
  el administrador cambia para un proveedor.
- Las alarmas (`provider_alerts`) se recalculan al navegar (cada 5 minutos por sesión) y en un
  hilo que revisa a todos una vez por hora y manda los e-mails si hay SMTP configurado.

## Base de datos

- Las bases existentes (Render) se actualizan solas al iniciar, en `db.init_db()`: cada cambio
  de esquema o de equipos necesita su migración (`_migrate`, `_ensure_*`) y una prueba que
  parta de una base creada con la versión publicada.
