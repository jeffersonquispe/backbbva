# Despliegue de la app Streamlit en AWS App Runner

Esto despliega **solo** `app/app.py` (el simulador del pipeline). El pipeline
de agentes en sí sigue viviendo en AWS Lambda — ver `scripts/package_lambda.py`
en la raíz del proyecto.

Hay dos formas de desplegar. Para un PoC rápido, usa la **Opción A (sin Docker)**.

Reemplaza `ACCOUNT_ID`, `REGION` y `CONNECTION_ID` por tus valores reales en
todos los comandos y archivos JSON de esta carpeta antes de ejecutar nada.

---

## Opción A: Deploy desde GitHub, sin Docker (recomendado para PoC)

App Runner construye la app directamente desde el repo usando `apprunner.yaml`
(ya está en la raíz del proyecto) — no necesitas Docker instalado ni correr
nada local.

> ⚠️ No pude verificar en vivo el identificador exacto de runtime
> (`runtime: python311` en `apprunner.yaml`) contra la documentación actual de
> AWS. Si `create-service`/el build falla quejándose del runtime, revisa los
> valores válidos vigentes en la consola de App Runner (al crear un servicio
> "Source code" te los lista en un dropdown) y ajusta ese campo.

### A.1 Autorizar la conexión de App Runner a GitHub (una sola vez, manual)

Este paso **no se puede hacer por CLI** — requiere el flujo OAuth de GitHub:

1. Ve a la consola de AWS → **App Runner → GitHub connections → Create connection**.
2. Autoriza la app "AWS Connector for GitHub" sobre tu cuenta/repo `cdrojasm/iara`.
3. Copia el **Connection ARN** que queda creado (algo como
   `arn:aws:apprunner:REGION:ACCOUNT_ID:connection/nombre/ID`).
4. Pégalo en `deploy/apprunner-service-source.json`, campo `ConnectionArn`.

### A.2 Crear el rol de instancia (para que la app llame a Bedrock)

Igual que en la Opción B — aquí **no** hace falta el rol de acceso a ECR,
porque no hay imagen que descargar:

```bash
aws iam create-role \
  --role-name AriaAppRunnerInstanceRole \
  --assume-role-policy-document file://deploy/iam/instance-role-trust-policy.json

aws iam put-role-policy \
  --role-name AriaAppRunnerInstanceRole \
  --policy-name AriaBedrockInvoke \
  --policy-document file://deploy/iam/instance-role-permissions-policy.json
```

### A.3 Crear el servicio

Edita `deploy/apprunner-service-source.json`: reemplaza `REGION`, `ACCOUNT_ID`
y `CONNECTION_ID`. Confirma que `SourceCodeVersion.Value` sea la rama que
quieres desplegar (`pocv1` por defecto).

```bash
aws apprunner create-service \
  --cli-input-json file://deploy/apprunner-service-source.json \
  --region REGION
```

Sigue el estado con:

```bash
aws apprunner describe-service \
  --service-arn $(aws apprunner list-services --region REGION --query "ServiceSummaryList[?ServiceName=='aria-streamlit-app'].ServiceArn" --output text) \
  --region REGION \
  --query "Service.{Status:Status,URL:ServiceUrl}"
```

### A.4 Deploys posteriores

Con `AutoDeploymentsEnabled: true`, cada `git push` a la rama configurada
redespliega solo. También puedes forzarlo manualmente:

```bash
aws apprunner start-deployment --service-arn <tu-service-arn> --region REGION
```

---

## Opción B: Deploy con Docker + ECR (más control sobre la imagen)

Usa esto si necesitas fijar exactamente qué va en la imagen, o si el deploy
desde GitHub no es viable en tu cuenta.

### B.0 Probar la imagen localmente (recomendado antes de subirla)

```bash
docker build -t aria-streamlit-app .
docker run --rm -p 8080:8080 --env-file .env aria-streamlit-app
```

Abre `http://localhost:8080`. El `--env-file .env` es solo para la prueba
local — la imagen en sí **nunca** contiene el `.env` (ver `.dockerignore`).

### B.1 Crear el repositorio ECR y subir la imagen

```bash
aws ecr create-repository --repository-name aria-streamlit-app --region REGION

aws ecr get-login-password --region REGION \
  | docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com

docker build -t aria-streamlit-app .
docker tag aria-streamlit-app:latest ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/aria-streamlit-app:latest
docker push ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/aria-streamlit-app:latest
```

### B.2 Crear los roles IAM

**Rol de acceso a ECR** (usado por App Runner solo para *descargar* la imagen
— no tiene permisos de Bedrock):

```bash
aws iam create-role \
  --role-name AppRunnerECRAccessRole \
  --assume-role-policy-document file://deploy/iam/ecr-access-role-trust-policy.json

aws iam attach-role-policy \
  --role-name AppRunnerECRAccessRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess
```

**Rol de instancia** (mismo que en la Opción A — el que usa la app *en
ejecución* para llamar a Bedrock):

```bash
aws iam create-role \
  --role-name AriaAppRunnerInstanceRole \
  --assume-role-policy-document file://deploy/iam/instance-role-trust-policy.json

aws iam put-role-policy \
  --role-name AriaAppRunnerInstanceRole \
  --policy-name AriaBedrockInvoke \
  --policy-document file://deploy/iam/instance-role-permissions-policy.json
```

### B.3 Crear el servicio de App Runner

Edita `deploy/apprunner-service.json`: reemplaza `ACCOUNT_ID` y `REGION` en
`ImageIdentifier` y en los dos ARN de rol.

```bash
aws apprunner create-service \
  --cli-input-json file://deploy/apprunner-service.json \
  --region REGION
```

### B.4 Deploys posteriores

Con `AutoDeploymentsEnabled: true`, basta con volver a construir y subir la
imagen con el mismo tag `:latest` — App Runner detecta el nuevo digest y
redespliega solo:

```bash
docker build -t aria-streamlit-app .
docker tag aria-streamlit-app:latest ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/aria-streamlit-app:latest
docker push ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/aria-streamlit-app:latest
```

---

## Notas (aplican a ambas opciones)

- **No hay `.env` en el deploy.** `BEDROCK_MODEL_ID` y `AWS_DEFAULT_REGION` se
  configuran como variables de entorno del servicio (`apprunner.yaml` en la
  Opción A, `RuntimeEnvironmentVariables` en la Opción B); las credenciales de
  AWS las provee `InstanceRoleArn` automáticamente (boto3/langchain-aws las
  detectan solas vía el rol de instancia, sin código adicional).
- El `Resource` de `instance-role-permissions-policy.json` está simplificado
  para el PoC: cubre cualquier ARN (foundation model o inference profile) que
  contenga `anthropic.claude-sonnet-4-6`, en cualquier cuenta/región. Es más
  permisivo de lo necesario a propósito — antes de un uso real, acótalo al
  ARN exacto de tu inference profile (`aws bedrock list-inference-profiles`).
- Este servicio es una **consola interna** con acceso a Bedrock y datos de
  fraude — no la expongas sin autenticación delante (ej. AWS WAF + Cognito,
  o un ALB con auth, o restringir por VPC/IP si App Runner queda detrás de un
  VPC connector). App Runner por sí solo no trae autenticación.
- `docs/` (incluido el Excel de casos sintéticos) **no se despliega** a
  propósito (ver `.dockerignore` / ausencia en `apprunner.yaml`), para no
  subir datos de prueba fuera del repo controlado. Sin ese archivo, el
  selector de "Caso sintético del Excel" queda vacío y la app usa
  automáticamente el caso de ejemplo hardcodeado (`app/app.py`, fallback de
  `sel_data`) — no rompe, solo pierde esa comodidad.
