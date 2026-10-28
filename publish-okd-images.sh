#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
AUTH_FILE="${1:-$ROOT/../credsartippub.json}"

if [[ $# -gt 1 ]]; then
  echo "Uso: ./publish-okd-images.sh [ruta/al/auth.json]" >&2
  exit 2
fi

if [[ "$AUTH_FILE" != /* ]]; then
  AUTH_FILE="$(cd -- "$(dirname -- "$AUTH_FILE")" && pwd)/$(basename -- "$AUTH_FILE")"
fi

if [[ ! -r "$AUTH_FILE" ]]; then
  echo "No se puede leer el archivo de credenciales: $AUTH_FILE" >&2
  exit 2
fi

if ! command -v skopeo >/dev/null 2>&1 && ! command -v podman >/dev/null 2>&1; then
  echo "Se necesita podman o skopeo en PATH; no se inició ninguna publicación." >&2
  exit 2
fi

if ! command -v skopeo >/dev/null 2>&1; then
  echo "Skopeo no está instalado; se usará Podman como publicador."
fi
TLS_VERIFY_VALUE="${ARTIFACTORY_TLS_VERIFY:-true}"
if [[ "${TLS_VERIFY_VALUE,,}" == "false" || "${TLS_VERIFY_VALUE,,}" == "0" ]]; then
  echo "ADVERTENCIA: ARTIFACTORY_TLS_VERIFY está desactivado para esta ejecución." >&2
fi
echo "Publicando únicamente artefactos AMD64 verificados desde staging."
echo "Las imágenes ya publicadas con el digest esperado se omitirán."
exec "$ROOT/deploy.sh" publish \
  --auth-file "$AUTH_FILE" \
  --push-concurrency 1 \
  --attempts 3
