# Pruebas

Las pruebas se organizan por nivel. La regla práctica es ejecutar el nivel más
pequeño que cubra el cambio; antes de integrar cambios de Vector Store, ejecutar
los tres comandos de esta sección.

## Suite completa

```bash
make test
```

Ejecuta toda la suite disponible en el entorno local. Las pruebas que requieren
servicios Docker se omiten si no se configuró `DYNAMO_ENDPOINT`.

## Contratos y propiedades

- `make test-api-contracts` extrae métodos/rutas de todos los módulos API del
  frontend y los compara con el OpenAPI generado por la aplicación backend.
  Requiere ambos repositorios hermanos y las dependencias npm del frontend.
  Comprueba cobertura de rutas/métodos; la comparación automática de tipos de
  request/response está pendiente.
- `python scripts/report_api_endpoint_usage.py --from-day YYYY-MM-DD
  --to-day YYYY-MM-DD --include-unused` cruza operaciones OpenAPI con las
  referencias estáticas del frontend y las peticiones auditadas en `audit_log`
  (GSI `TipoIdx`). Es de solo lectura; una ruta sin referencias ni tráfico solo
  es un candidato a revisar, no evidencia suficiente para borrarla.
- `test_celery_task_signature_contracts.py` comprueba registro, serializador
  JSON y anotaciones de entrada/salida de las 27 tasks Celery actuales.
  `test_reconcile_async_operations_properties.py` genera resultados y comprueba
  que reconciliar una task exitosa preserva su resultado y no la procesa de
  nuevo tras el cierre terminal.
- `test_infrastructure/test_entrypoint/test_alert_api_contract.py` verifica
  que el sobre de respuesta de alertas permanece estable y que `input` y
  `labels` admiten campos definidos por cada versión del esquema. El frontend
  verifica sus tipos y los campos dinámicos en
  `../frontend_mockup/src/test/alert-contract.test.ts`.
- Los tests `test_*_properties.py` usan Hypothesis para generar muchos valores
  y comprobar invariantes de dominio además de los ejemplos unitarios.
  Hypothesis se declara como dependencia de desarrollo del proyecto API.

### Estado medido (2026-10-25)

- El OpenAPI publica **226 operaciones método/ruta**. El cliente frontend
  referencia **180/226 (79,6%)**; las 180/180 referencias frontend encuentran
  correspondencia en OpenAPI. Las otras **46 (20,4%)** no aparecen en esos
  módulos frontend; eso no significa que estén sin pruebas ni que estén
  obsoletas.
- Las **27/27 tasks Celery** actuales tienen comprobación de firma anotada y
  configuración de serialización JSON. Esto no valida todavía el payload de
  entrada/salida de cada task contra un schema de mensaje independiente.
- Hay **9 propiedades Hypothesis** en reglas, historial, muestreo/partición,
  rollups y reconciliación async. No hay un porcentaje global de propiedades
  para workflows: sus módulos y comportamientos no tienen una unidad común
  comparable, y la mayoría tiene tests convencionales.
- No se consultó `audit_log` en esta medición, así que aún no sabemos cuántas
  de las 46 operaciones recibieron tráfico real en una ventana concreta.

## Vector Store

### Unitarias

```bash
make test-unit-vector-store
```

Ejecuta reglas de negocio y casos de uso en aislamiento: creación idempotente de
instancias, expansión del grafo de activos, propagación y desvinculación
recursiva. Usa dobles en memoria; no requiere Docker ni DynamoDB.

### API

```bash
make test-api-vector-store
```

Ejecuta los contratos HTTP de la API mediante `TestClient`: autorización,
auditoría del usuario autenticado, previsualización del impacto y alta de
relaciones. No abre puertos ni requiere servicios Docker.

### Integración con Docker

```bash
make test-integration-docker-vector-store
```

Construye la imagen de pruebas, inicia el stack local requerido y ejecuta las
pruebas de integración contra DynamoDB Local dentro de Docker. Verifica la
persistencia real de las relaciones entre instancias de Vector Store y activos,
la propagación y el borrado recursivo de relaciones.

Requiere Docker Desktop o un daemon Docker en ejecución. Este comando crea o
reutiliza los contenedores del stack `lupita-data`; para detenerlos al terminar:

```bash
make local-docker-stop
```

## Convención para nuevos grupos

Los targets usan el formato `test-<nivel>-<dominio>`:

- `test-unit-<dominio>`: lógica aislada y rápida.
- `test-api-<dominio>`: contratos de rutas HTTP sin infraestructura externa.
- `test-integration-docker-<dominio>`: integración con dependencias reales en
  Docker.

Mantén los tests unitarios bajo `tests/test_application`, los de API bajo
`tests/test_infrastructure/test_entrypoint` y los de integración bajo
`tests/test_integration`.
