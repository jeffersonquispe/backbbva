# Event API

Servicio de entrada para alertas que FRM ya filtró. No realiza homologación ni
validación de esquema del evento: requiere JSON válido con `alert_id` y
`event_id`, autentica al emisor con OIDC y publica el mensaje en la cola
productiva `production_events`.

## HTTP

- `POST /api/event/events`
- Autenticación: `Authorization: Bearer <OIDC access token>`; se valida firma
  RS256, issuer, audience, `exp`, `iat`, `sub` y el client ID autorizado
  (`azp`/`client_id`) contra el JWKS configurado.
- Cuerpo mínimo: `{"alert_id":"…","event_id":"…"}`.
- `alert_id` identifica la alerta resumida en el sistema fuente; `event_id`
  identifica esta entrega y es la clave de idempotencia. Son los únicos campos
  que Event API conserva y publica. Puede recibir atributos adicionales del
  resumen de FRM, pero los ignora: la consulta y el enriquecimiento pertenecen
  al preproceso de producción (#22).
- `202`: evento aceptado; `receipt_id` es `event_id`. Reintentar el mismo
  `event_id` para el mismo `alert_id` retorna `202` con `duplicate: true`.
- `400`: JSON inválido o faltan los IDs.
- `401`: token ausente/inválido.
- `409`: `event_id` ya asociado a otro `alert_id`.
- `413`: cuerpo supera `EVENT_API_MAX_BODY_BYTES`.
- `503`: issuer OIDC o cola productiva no disponible; el emisor puede reintentar.

La idempotencia usa Redis, separada de la base de resultados Celery, con TTL
configurable (30 días por defecto). Si el envío a Celery falla, se elimina la
reserva de idempotencia para permitir reintentar. Los consumidores downstream
deben seguir siendo idempotentes para cubrir un corte de conexión después de
que el broker acepte el mensaje.

El servicio publica en la cola durable `production_events`. El worker de
producción aún debe incorporar el consumidor y conectar el enriquecimiento
por `alert_id` de #22 antes de habilitar el procesamiento integral.

## Configuración

`EVENT_API_OIDC_ISSUER`, `EVENT_API_OIDC_AUDIENCE` y
`EVENT_API_OIDC_JWKS_URL` se inyectan por ambiente. En OKD el issuer/JWKS del
proveedor OIDC corporativo deben configurarse en `aria-event-api-config` antes
de habilitar FRM. En local, el perfil `event-api-e2e` levanta Keycloak con un
realm/client exclusivamente de desarrollo.

El servicio local escucha en `http://localhost:8001`; OKD publica una Route
TLS al servicio `event-api`. E2E local (no ejecutar sin autorización expresa):
`make e2e-event-api-local`.
