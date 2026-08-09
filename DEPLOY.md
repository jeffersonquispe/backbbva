# Lupita — Guía de Despliegue Standalone

Guía completa para levantar Lupita en cualquier ambiente sin acceso a los registros internos de BBVA (Artifactory / Quay).

---

## Requisitos previos

| Herramienta | Versión mínima | Verificar |
|---|---|---|
| Docker | 24+ | `docker --version` |
| Docker Compose | 2.20+ | `docker compose version` |
| Git | — | `git --version` |
| RAM disponible | 6 GB | OpenSearch necesita al menos 4 GB |
| Espacio en disco | 10 GB | Imágenes + datos |

> **Linux / WSL2:** OpenSearch requiere ajuste del kernel antes de iniciar:
> ```bash
> sudo sysctl -w vm.max_map_count=262144
> # Para que sea permanente:
> echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.conf
> ```

---

## Estructura del proyecto (archivos clave)

```
lupita/
├── deploy/
│   ├── Dockerfile.api         ← imagen sin dependencias BBVA
│   ├── docker-compose.yml ← stack completo
│   ├── gunicorn.standalone.py        ← config de workers
│   └── requirements.standalone.txt  ← dependencias PyPI
├── frontend/
│   ├── dist/                         ← HTML del chatbot (gobierno, admin, mer)
│   └── nginx.conf                    ← proxy inverso
├── lupita-documents/                 ← ⚠ NO está en git — copiar manualmente
│   ├── Consolidado MER.xlsx          ← catálogo MER (obligatorio)
│   └── RCN.xlsx                      ← catálogo RCN (obligatorio)
├── src/                              ← código fuente Python
├── scripts/                          ← scripts de inicio
└── DEPLOY.md                         ← esta guía
```

---

## Inicio rápido

### Paso 1 — Clonar el repositorio

```bash
git clone https://github.com/reyeserika296-boop/lupita.git
cd lupita
```

### Paso 2 — Ajustar límites del kernel (solo Linux / WSL2)

```bash
sudo sysctl -w vm.max_map_count=262144
```

### Paso 3 — Crear el directorio de documentos y copiar los archivos Excel

> **Importante:** Los archivos Excel de gobierno **no están en el repositorio** por ser datos sensibles.
> Debes obtenerlos del equipo de gobierno de datos y copiarlos manualmente.

```bash
# Crear el directorio si no existe
mkdir -p lupita-documents

# Copiar los archivos Excel al directorio
cp /ruta/donde/tienes/los/archivos/Consolidado\ MER.xlsx lupita-documents/
cp /ruta/donde/tienes/los/archivos/RCN.xlsx lupita-documents/

# Verificar que están los dos archivos
ls lupita-documents/
# Debe mostrar: Consolidado MER.xlsx  RCN.xlsx
```

### Paso 4 — Construir e iniciar todos los servicios

```bash
cd deploy
docker compose -f docker-compose.yml up -d --build
```

La primera vez tarda **5-10 minutos** mientras descarga las imágenes base y construye la imagen de la API.

> **WSL2:** Si el build da timeout al descargar paquetes de PyPI, cancela con `Ctrl+C` y usa:
> ```bash
> docker build --network=host -f Dockerfile.api -t lupita-api:local ..
> docker compose -f docker-compose.yml up -d
> ```

### Paso 5 — Verificar que todo esté corriendo

```bash
docker compose -f docker-compose.yml ps
```

Todos los servicios deben estar en estado `running`. Luego comprueba el healthcheck:

```bash
curl http://localhost:8000/health
# Respuesta esperada: {"status":"ok"}
```

### Paso 6 — Cargar los datos iniciales de DynamoDB

> **Solo la primera vez.** Los datos incluyen proyectos MER de ejemplo y el catálogo base.

```bash
docker exec lupita-api python3 /code/scripts/dynamo_import.py
```

Salida esperada:
```
  auth_sessions: vacía, omitida
  chat_sessions: vacía, omitida
  frequently_questions: vacía, omitida
  glosary: vacía, omitida
  mer_projects: 2 items importados, 0 errores
  user_feedback: vacía, omitida

Importación completada.
```

> Si ves `2 items importados` en `mer_projects`, los datos están cargados correctamente.

---

## URLs disponibles

| Servicio | URL | Descripción |
|---|---|---|
| **Frontend** | http://localhost:8001 | Chatbot de gobierno de datos |
| **Swagger UI** | http://localhost:8000/lupita/v0/docs | Documentación interactiva de la API |
| **API Healthcheck** | http://localhost:8000/health | Estado de la API |
| **DynamoDB Admin** | http://localhost:8003 | UI para inspeccionar tablas DynamoDB |
| **OpenSearch** | http://localhost:9200 | Motor de búsqueda (uso interno) |

---

## Módulos del frontend

| URL | Módulo |
|---|---|
| http://localhost:8001/gobierno.html | Carga y envío de MER a revisión |
| http://localhost:8001/admin.html | Panel de administración y aprobaciones |
| http://localhost:8001/mer.html | Búsqueda de campos en el catálogo |

---

## Endpoints principales de la API

```bash
# Búsqueda de un campo por descripción funcional
curl -s -X POST http://localhost:8000/lupita/v0/governance/fields/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Codigo del cliente"}' | python3 -m json.tool

# Búsqueda de múltiples campos en lote
curl -s -X POST http://localhost:8000/lupita/v0/governance/fields/batch-search \
  -H "Content-Type: application/json" \
  -d '{"queries": ["Codigo del cliente", "Fecha de nacimiento", "Numero de cuenta"]}' | python3 -m json.tool

# Estadísticas del catálogo (cuántos campos cargados)
curl -s http://localhost:8000/lupita/v0/governance/fields/stats | python3 -m json.tool

# Sugerencia de naming TC-015
curl -s -X POST http://localhost:8000/lupita/v0/governance/naming/suggest \
  -H "Content-Type: application/json" \
  -d '{"description": "identificador de clientes", "suffix": "IDENTIFICADOR"}' | python3 -m json.tool
```

---

## Comandos de gestión del stack

### Ver estado de los contenedores

```bash
cd deploy
docker compose -f docker-compose.yml ps
```

### Ver logs en tiempo real

```bash
# Todos los servicios
cd deploy
docker compose -f docker-compose.yml logs -f

# Solo la API
docker logs lupita-api -f

# Solo el frontend
docker logs lupita-frontend -f
```

### Reiniciar un servicio

```bash
# Reiniciar la API (aplica cambios en src/)
docker restart lupita-api

# Reconstruir la imagen de la API (si cambia requirements.standalone.txt o el Dockerfile)
cd deploy
docker compose -f docker-compose.yml build api
docker compose -f docker-compose.yml up -d api
```

### Detener todos los servicios

```bash
cd deploy
docker compose -f docker-compose.yml down
```

### Detener y eliminar volúmenes (limpieza total — borra datos DynamoDB y OpenSearch)

```bash
cd deploy
docker compose -f docker-compose.yml down -v
```

---

## Actualizar los archivos Excel de gobierno

Los archivos se montan como volumen, por lo que **no es necesario reconstruir la imagen**:

1. Reemplaza los archivos en `lupita-documents/`
2. Reinicia la API para que recargue los catálogos:

```bash
docker restart lupita-api
```

---

## Configuración de variables de entorno

El `docker-compose.yml` incluye todas las variables con valores predeterminados para local. Para personalizar, crea `deploy/.env` (no commitear):

```ini
# deploy/.env
DEFAULT_LOGGING_LEVEL=DEBUG
GUNICORN_WORKERS=2
```

### Variables importantes

| Variable | Valor predeterminado | Descripción |
|---|---|---|
| `GENAI_ENVIRONMENT` | `local` | Entorno de ejecución |
| `API_V0_STR` | `/lupita/v0` | Prefijo de todas las rutas |
| `DEFAULT_LOGGING_LEVEL` | `INFO` | Nivel de logs (`DEBUG`, `INFO`, `WARNING`) |
| `GUNICORN_WORKERS` | auto (CPU+1, máx 4) | Número de workers del servidor |
| `API_DEBUG` | `false` | Activar debugpy en puerto 5678 |
| `DYNAMO_ENDPOINT` | `http://dynamodb-lupita:8000` | Endpoint DynamoDB |
| `OPENSEARCH_ENDPOINT` | `http://opensearch-node:9200` | Endpoint OpenSearch |

---

## Modo desarrollo vs producción

El compose monta `../src:/code/src` para que los cambios de código se apliquen sin reconstruir la imagen. Para un despliegue de producción, elimina esa línea del compose:

```yaml
# Quitar este volumen en producción:
# - ../src:/code/src
```

Luego reconstruye la imagen:

```bash
cd deploy
docker compose -f docker-compose.yml build api
docker compose -f docker-compose.yml up -d
```

---

## Servicios opcionales

DynamoDB Admin, OpenSearch y Redis son opcionales para el chatbot de gobierno. Stack mínimo:

```bash
cd deploy
docker compose -f docker-compose.yml up -d dynamodb api frontend
```

---

## Solución de problemas

### La API no inicia — espera OpenSearch

OpenSearch tarda ~30-40 segundos en arrancar. Si falla:

```bash
# Ver estado de OpenSearch
curl http://localhost:9200/_cluster/health

# Ver logs
docker logs opensearch-node --tail=50
```

Si OpenSearch no inicia por memoria virtual:
```bash
sudo sysctl -w vm.max_map_count=262144
```

### La API inicia pero no encuentra los archivos Excel

```bash
# Verificar que el volumen está montado y los archivos existen
docker exec lupita-api ls /code/lupita-documents/
# Debe mostrar: Consolidado MER.xlsx  RCN.xlsx
```

### Puerto ya en uso

Cambia el mapeo en el compose:

```yaml
# Ejemplo: cambiar el frontend al puerto 9001
ports:
  - "9001:80"
```

### Ver logs de inicio de la API

```bash
docker logs lupita-api --tail=100
```

Busca líneas como:
```
[Startup] Tablas DynamoDB verificadas.
[Startup] GovernanceCatalog listo: 1234 registros MER, 567 RCN.
```

### Reconstrucción completa (estado limpio)

```bash
cd deploy
docker compose -f docker-compose.yml down -v
docker rmi lupita-api:local 2>/dev/null || true
docker compose -f docker-compose.yml up -d --build
```

---

## Diferencias con el despliegue interno BBVA

| Aspecto | Interno BBVA | Standalone |
|---|---|---|
| Imagen base | `artifactory.globaldevtools.bbva.com/.../python:3.11-slim` | `python:3.11-slim` (Docker Hub) |
| Dependencias | Instaladas desde Artifactory | Instaladas desde PyPI |
| Imagen API | `quay.io/bbva-co/lupita-api-preproduccion:vXX` | Construida localmente |
| Observabilidad | `genai.libs.observability` (BBVA) | `logging` estándar de Python |
| Configuración | `config/local/config.cfg` | Variables en `docker-compose.yml` |
| Documentos Excel | En servidor compartido | Copiar manualmente a `lupita-documents/` |
