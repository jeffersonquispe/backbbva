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
