# Lineamientos de seguridad para métricas y revisión de fraude

Este documento recoge los controles y recomendaciones de seguridad de la
revisión de dashboards y métricas. Las decisiones y verificaciones aún
pendientes están en `PENDIENTES.md`.

## Permisos y datos

- Mantener `/metrics/overview` bajo `dashboard`, y `/metrics/agent` y
  `/metrics/technical` bajo `monitor`.
- Restringir el historial y las revisiones de fraude a `fraud_history` y
  `fraud_review`, según corresponda. El historial autorizado contiene
  `customer_id`, importes y etiquetas de fraude. `fraud_review` solo lo
  tienen `fraud_reviewer` (equipo de fraude) y `manager` de respaldo; nunca
  `channel_manager`, que lanza el optimizador evaluado con esas etiquetas.
- La retención del historial (`fraud_history.retention`) es el único proceso
  que borra filas de `alerts` y `fraud_label_reviews`, y solo después de
  releer el archivo frío y verificar su SHA-256.
- Tratar la nota libre de revisión como dato de negocio sensible. No copiarla
  a logs genéricos ni registrar cuerpos, tokens, query strings o atributos de
  los ítems en la auditoría.

## Auditoría e integridad

- Las revisiones se insertan condicionalmente; el puerto de aplicación no
  expone operaciones de actualización o borrado.
- La auditoría de DynamoDB y objetos registra identificadores de entidad sin
  copiar datos de negocio. La auditoría HTTP registra método, plantilla de
  ruta y resultado, con actor y correlation id cuando están disponibles.
- Las restricciones de la aplicación no hacen el registro invulnerable a una
  identidad de despliegue con permisos de modificación o borrado. En OKD,
  aplicar mínimo privilegio y denegar esas operaciones para `fraud_label_reviews`
  y `audit_log`. Evaluar almacenamiento de auditoría separado e inmutable si
  el modelo de amenazas requiere resistencia ante administradores del servicio.

## Métricas y telemetría

- No incluir `customer_id` ni el importe exacto como atributos de métricas o
  spans; preferir dimensiones agregadas y de baja cardinalidad.
- Mantener la captura de prompts y respuestas desactivada por defecto. Su
  activación debe seguir siendo explícita y acotada.

## Retención y cifrado

- Aplicar la política corporativa aprobada para notas de fraude y eventos de
  auditoría, incluyendo cifrado en reposo con KMS cuando lo requiera la
  plataforma.
- La política, la retención configurada y la verificación de su aplicación en
  OKD se siguen en `PENDIENTES.md`.
