# Automatización de imágenes OKD

`services.json` registra los Dockerfiles propios y apunta a los Deployments como
fuente de verdad para el contenedor y la imagen destino. Solo incluye las
imágenes de la aplicación; imágenes de terceros en `deploy/okd/iac_celery` no
se construyen. Incluye seis imágenes backend y el frontend; sus repositorios,
Dockerfiles, contextos e imágenes están configurados desde los remotos y
Deployments existentes.

## Uso local

Requiere Python 3, Podman (preferido) o Docker, y `skopeo` para publicación.
El staging persistente por defecto está en `~/.cache/aria-okd/images`; puede
cambiarse con `ARIA_IMAGE_STAGING`. Se guardan artefactos OCI y metadatos con
SHA-256. Los artefactos se escriben en temporal y se confirman mediante rename.

```sh
./deploy.sh                         # cambios desde el último publish conocido
./deploy.sh all                     # construir todas las imágenes configuradas
./deploy.sh services --services api,mcp
./deploy.sh changed --backend-branch feature/V0_0_7 --frontend-branch main
./deploy.sh publish                 # publicar artifacts pendientes, no build
./deploy.sh resume                  # alias operativo de publish/reintento
./deploy.sh deploy                  # muestra cambios de manifiestos verificados
./deploy.sh deploy --allow-manifest-write  # edita manifiestos locales solamente
./deploy.sh dry-run
```

`changed`, `all` y `services` construyen y luego publican; si falla la
publicación, el artefacto queda pendiente y `resume` no reconstruye. El CLI
reutiliza una sesión existente de Podman/Docker para Artifactory si está
disponible; si no, pide usuario y contraseña/token de forma oculta. También
acepta `ARTIFACTORY_USER` y `ARTIFACTORY_PASSWORD` desde el gestor de secretos
del shell/CI. No se admiten como argumentos.
La autenticación temporal de Skopeo usa un archivo modo 0600 eliminado al salir.
Git usa `GIT_ASKPASS` temporal y no construye URLs con tokens.

Los tags por defecto son el SHA fuente completo. Un tag personalizado se
valida; no se fuerza el overwrite. Si un destino existe, la publicación falla
de forma cerrada salvo que haya un digest previamente registrado que coincida.
Para ejecutar un flujo de extremo a extremo se necesita que el tag sea nuevo.
No se hace push Git ni `oc apply`; `deploy --allow-manifest-write` solo modifica
los manifiestos del checkout local después de publicar y verificar.

El CLI clona/actualiza los remotos ya definidos en el proyecto: `free/aria-agente-
prevencion-fraude-backend` y `free/aria-agente-prevencion-fraude-frontend`.
Las ramas predeterminadas son `main` y se pueden cambiar con las opciones de
arriba o `ARIA_BACKEND_BRANCH`/`ARIA_FRONTEND_BRANCH`. Los checkouts se guardan
en `sources/` dentro del staging; no se modifican los checkouts del usuario.
Los cambios locales del checkout frontend no entran en la imagen.

Git consulta el helper del sistema y pide el token de GHE de forma oculta solo
si no encuentra uno utilizable. En este equipo está configurado `osxkeychain`,
así que el token se puede guardar en el llavero y reutilizar. Si vence, se
solicita uno nuevo. Para automatización sin TTY, inyecte `GITHUB_TOKEN` desde un
gestor de secretos; no lo pase como argumento. `dry-run` no clona ni hace fetch:
describe los checkouts locales y avisa si su rama difiere de la predeterminada.
El tag personalizado aplica a los servicios seleccionados; sin él, cada
repositorio usa su propio commit.

## Pipeline existente y seguridad

El YAML histórico `clone-and-build-pipeline-with-hashedcommit-tag` se conserva
para compatibilidad. Tiene defectos que explican fallos y riesgo: default Git
URL con credenciales, TLS desactivado (`GIT_SSL_NO_VERIFY`, `http.sslVerify=false`,
`--skip-tls-verify`), limpieza destructiva del workspace compartido, y build
combinado con push. Además pasa usuario/password como build args y genera
`.netrc` dentro del contexto; esos secretos pueden aparecer en historial/capas.
La solución nueva no hereda esos patrones. Los Dockerfiles `*.secure.okd`
reciben credenciales mediante `RUN --mount=type=secret`; los Dockerfiles OKD
históricos siguen intactos para mantener compatibilidad con el Kaniko anterior.
Los Tasks release nuevos usan Kaniko/Skopeo sin privilegios ni user namespaces,
con TLS verificado, y están en
`tekton/tasks/`, un archivo por Task. El bundle `tekton/tasks.release.yaml`
permite instalarlas todas juntas. Las Pipelines generadas están en
`tekton/pipeline-build.release.yaml` y `tekton/pipeline-publish.release.yaml`
(un manifiesto por Pipeline para cargarlos desde la consola). El bundle
`tekton/pipelines.release.yaml` contiene ambos documentos para `oc apply`. El
Pipeline histórico se conserva, pero no se debe usar para el flujo nuevo.

En OKD, la Pipeline solicita `github-user` y `github-token` como campos separados.
Tekton guarda el token en PipelineRun y TaskRun; limita quién puede leer esos
recursos. Los PVC y Secrets disponibles no se pueden verificar desde este
checkout. Antes de habilitar Tasks de build paralelas, verificar nombre,
capacidad, accessModes y persistencia del PVC. Con `ReadWriteOnce`, no distribuir
Tasks entre nodos salvo que el storage y scheduling permitan compartirlo.
Configurar un timeout PipelineRun máximo de `50m`; dividir build/publicación y
volver a ejecutar `publish` desde estado persistente.

### Flujo OKD nuevo

La ejecución tiene dos PipelineRuns independientes:

1. `aria-build-images-v1` clona los dos repos configurados con las ramas
   predeterminadas, compara por servicio con la última imagen publicada y hace
   builds en grupos de hasta tres. Acepta `changed` (predeterminado), `all` y
   `services`; `image-tag` es opcional. Los servicios no seleccionados terminan
   como no-op exitoso para que no bloqueen los grupos siguientes. El frontend
   usa su propio commit y el Dockerfile seguro que viaja en el checkout backend.
2. `aria-publish-images-v1` recorre las imágenes pendientes en serie, verifica
   el destino/digest, aplica retries y finalmente deja
   `deployment-manifests.patch` en staging con los cambios de imagen publicados.
   No hace commit, push ni `oc apply`.

Para arrancar desde la consola, abre `aria-build-images-v1`, completa `github-user`
y `github-token` con tu usuario y GitHub classic token, deja `mode=changed` y
las ramas/tag vacíos o predeterminados, y pulsa **Start**. Después del éxito,
abre `aria-publish-images-v1` y pulsa **Start** para publicar los artefactos
confirmados. Para recuperar un fallo de push, ejecuta solo esa segunda Pipeline.
El script no imprime el token ni lo pone en la URL Git. Tekton sí persiste los
parámetros en PipelineRun y TaskRun, así que quienes puedan leer esos recursos
podrán verlo; limita esos permisos y elimina los runs según la retención interna.

Para crear los PipelineRuns desde CLI, copia
`tekton/pipelineruns.release.yaml.tmpl`, establece el PVC real en
`ARIA_STAGING_PVC` y el ServiceAccount autorizado en
`ARIA_TEKTON_SERVICE_ACCOUNT`, revisa el resultado de `envsubst` y crea el
PipelineRun. El template usa el Secret de pull `artifactory-auth` que ya está
referenciado por los Deployments. Los campos de GitHub se llenan en el formulario
de `aria-build-images-v1`; no se requieren URLs de repositorio.

Antes de ejecutar builds paralelos, revisar `oc get pvc "$ARIA_STAGING_PVC"`
y confirmar capacidad/persistencia y `accessModes`. Para tres TaskRuns que
montan ese PVC simultáneamente, se necesita `ReadWriteMany` o que la instalación
Tekton tenga co-scheduling de PVC RWO habilitado; no se presupone ese ajuste.
Si solo se dispone de RWO sin co-scheduling, no ejecutar el Pipeline paralelo
hasta habilitar una forma segura de compartirlo. Los builds escriben en rutas
únicas y no limpian staging.

El PipelineRun de build fija `50m` total/`45m` de Tasks; el de publicación fija
`50m` total/`45m` de Tasks y reserva `3m` para preparar el parche. Si build
agota el timeout, los archivos completados quedan confirmados; volver a correr
`changed` reutiliza artefactos con checksum válido. Si falla Artifactory, correr
solo `aria-publish-images-v1`; no reconstruye.

`generate_release_pipelines.py` regenera las Pipelines desde `services.json` y
los Deployments reales. `generate_release_tasks.py` recompone el bundle desde
los archivos individuales de `tekton/tasks/`.

Para cargar desde la consola, importa cada uno de los cinco archivos dentro de
`tekton/tasks/` por separado, luego
`tekton/pipeline-build.release.yaml` y `tekton/pipeline-publish.release.yaml`.
Para instalar con CLI, un administrador autorizado puede aplicar
`tekton/tasks.release.yaml` y `tekton/pipelines.release.yaml` en `aria-genai-dev`, una vez
verificados que las imágenes `ghcr.io/osscontainertools/kaniko:v1.28.5-debug` y
`quay.io/skopeo/stable:v1.18.0` son permitidas en el cluster. No se incluye un
PipelineRun aplicado ni se ha conectado al cluster. La publicación se serializa
para no saturar Artifactory. El parche de manifiestos queda en staging; crear un
commit, PR o aplicar al cluster es un paso deliberado y separado.

## Extensión y límite incremental

Agregue servicios a `services.json` apuntando al Deployment real y al
Dockerfile real. La detección recorre fuentes Docker `COPY`: un cambio en
`src/` reconstruye todas las imágenes backend que copian ese árbol; cambios de
Dockerfile/dependencias específicos reconstruyen solo la imagen correspondiente.
Cambios exclusivos bajo
`deploy/okd/iac_celery` y `deploy/okd/automation` se excluyen. El primer uso sin
baseline publicado reconstruye conservadoramente todos los servicios con
fuente disponible. El estado de publicación queda en `state.json`; cada
artefacto tiene metadata individual e integridad comprobada antes de publicar.
La limpieza de staging debe ser manual y controlada (no se elimina al iniciar).
