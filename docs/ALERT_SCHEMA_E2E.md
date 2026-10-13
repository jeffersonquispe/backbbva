# E2E real del esquema de alerta

El flujo real usa Playwright contra la API y el frontend levantados. El
navegador y el contexto API apuntan al nginx publicado en el puerto 80; no
se conectan directamente al puerto 8000 de FastAPI. No intercepta `/api/v0`:
hace login, crea y gobierna las versiones del esquema,
carga cinco filas de `Muestra_total_ARIA_JUl`, inicia Testing y verifica la
separación de `input` y `labels` en la respuesta real del caso.

## Requisitos

- API, workers, DynamoDB Local y frontend disponibles.
- Dos usuarios existentes: `manager` y `release_manager`.
- Variables:

```bash
export E2E_MANAGER_EMAIL=manager@example.com
export E2E_MANAGER_PASSWORD='...'
export E2E_RELEASE_MANAGER_EMAIL=release-manager@example.com
export E2E_RELEASE_MANAGER_PASSWORD='...'
export E2E_BASE_URL=http://127.0.0.1
```

## Ejecución

`e2e-real` llama a un endpoint protegido de la API a través de nginx antes de
lanzar la suite. La API limpia los ítems de DynamoDB y conserva las tablas y
`users` para que el login siga funcionando. El runner nunca necesita
credenciales ni conexión directa a DynamoDB:

```bash
make e2e-real \
  E2E_MANAGER_EMAIL="$E2E_MANAGER_EMAIL" \
  E2E_MANAGER_PASSWORD="$E2E_MANAGER_PASSWORD" \
  E2E_RELEASE_MANAGER_EMAIL="$E2E_RELEASE_MANAGER_EMAIL" \
  E2E_RELEASE_MANAGER_PASSWORD="$E2E_RELEASE_MANAGER_PASSWORD"
```

El dataset fixture se elimina por API antes de recargarse. La suite no borra
automáticamente el resultado al terminar, para permitir inspeccionarlo.

Para limpiar después:

```bash
make e2e-clean
```

`e2e-clean` es destructivo: solicita a la API borrar todos los ítems de
DynamoDB excepto `users`; preserva tablas e índices. El endpoint sólo responde
en `GENAI_ENVIRONMENT=local` cuando `E2E_CLEANUP_ENABLED=true`, y el target no
debe ejecutarse contra una base compartida o productiva.
