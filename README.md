# Lupita — Chatbot de Gobierno de Datos · BBVA Colombia

Herramienta interna para consultar campos gobernados del catálogo RCN. Permite buscar el naming técnico aprobado a partir de una descripción funcional.

---

## Requisitos previos

| Herramienta | Versión mínima | Verificar |
|---|---|---|
| Docker Desktop | 24+ | `docker --version` |
| Docker Compose | 2.20+ | `docker compose version` |
| Git | — | `git --version` |
| RAM disponible | 6 GB | OpenSearch necesita al menos 4 GB |

---

## Instalación por primera vez

### Paso 1 — Clonar el repositorio

```
git clone https://github.com/reyeserika296-boop/lupita.git
cd lupita
```

### Paso 2 — Verificar los archivos de gobierno

Confirma que la carpeta `lupita-documents/` contiene los siguientes archivos:

```
lupita-documents/
├── Consolidado MER.xlsx
├── RCN.xlsx
├── governance_embeddings.npy
└── Generacion_namings/
    └── Naming_GobiernoRCN.xlsx
```

> Estos archivos no están en el repositorio por ser datos sensibles. Solicítalos al equipo de arquitectura de datos.

### Paso 3 — Levantar los servicios

```
cd deploy
docker compose -f docker-compose.standalone.yml up -d --build
```

La primera vez tarda **5-10 minutos** mientras construye la imagen y OpenSearch indexa los datos.

### Paso 4 — Verificar

```
curl http://localhost:8000/health
```

Respuesta esperada: `{"status":"ok"}`

### Paso 5 — Abrir la aplicación

| Servicio | URL |
|---|---|
| Frontend (Gobierno de Datos) | http://localhost:8001 |
| MER (Modelado de Datos) | http://localhost:8001/mer.html |
| API Swagger | http://localhost:8000/lupita/v0/docs |
| Healthcheck | http://localhost:8000/health |

> OpenSearch indexa ~76.000 registros en background al primer inicio. El buscador queda completamente disponible en 5-10 minutos.

---

## Actualizar a la última versión

Cuando haya cambios en el repositorio, ejecutar estos comandos para asegurar que OpenSearch y DynamoDB queden con los datos actualizados:

```bash
# 1. Bajar todo y limpiar volúmenes
cd deploy
docker compose -f docker-compose.standalone.yml down -v

# 2. Actualizar código
cd ..
git pull origin lupita_data







```

> El `-v` elimina los volúmenes para que OpenSearch re-indexe con los datos actuales y DynamoDB cargue el backup más reciente automáticamente.

---

## Comandos útiles

```bash
# Ver logs de la API en tiempo real

docker logs lupita-api -f

# Reiniciar solo la API
docker restart lupita-api

# Probar el buscador de namings
curl -X POST http://localhost:8000/lupita/v0/governance/fields/search \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"Codigo del cliente\"}"

# Ver estadísticas del catálogo (opensearch_indexed debe llegar a ~76000)
curl http://localhost:8000/lupita/v0/governance/fields/stats

# Bajar todos los servicios (sin borrar datos)
cd deploy
docker compose -f docker-compose.standalone.yml down

# Bajar y borrar todos los datos (reinicio limpio)
cd deploy
docker compose -f docker-compose.standalone.yml down -v
```

---

## Solución de problemas

**OpenSearch no inicia (Linux/WSL2)**
```
sudo sysctl -w vm.max_map_count=262144
```

**El buscador no encuentra resultados**
Espera 5-10 minutos después del primer inicio para que OpenSearch termine de indexar. Verifica con:
```
curl http://localhost:8000/lupita/v0/governance/fields/stats
```
Cuando `opensearch_indexed` llegue a ~76000, el buscador está listo.

**Ver qué está fallando**
```
docker logs lupita-api --tail=50
```
