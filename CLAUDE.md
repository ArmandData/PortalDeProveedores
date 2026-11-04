# Portal de Proveedores: reglas del negocio

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

## Base de datos

- Las bases existentes (Render) se actualizan solas al iniciar, en `db.init_db()`: cada cambio
  de esquema o de equipos necesita su migración (`_migrate`, `_ensure_*`) y una prueba que
  parta de una base creada con la versión publicada.
