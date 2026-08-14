# Imagen para desplegar app/app.py (simulador del pipeline ARIA) en AWS App Runner.
# El pipeline de agentes (lambda_function.py) sigue viviendo en AWS Lambda por
# separado — ver scripts/package_lambda.py. Esta imagen es solo para la consola
# Streamlit.

FROM python:3.13-slim

WORKDIR /app

# Capa de dependencias separada del código para aprovechar la cache de Docker
# en rebuilds (el código cambia mucho más seguido que las dependencias).
COPY requirements-app.txt .
RUN pip install --no-cache-dir -r requirements-app.txt

# Solo se copia lo que la app necesita para correr: el núcleo del pipeline
# (para invocar lambda_handler in-process, sin pasar por AWS Lambda) y la app
# en sí. NUNCA se copia .env, scripts/, tests/, docs/ ni output/ — las
# credenciales de AWS las provee el Rol de Instancia de App Runner, no un
# archivo horneado en la imagen (ver deploy/apprunner-service.json).
COPY schemas.py lambda_function.py aria_rules.yaml ./
COPY agents/ ./agents/
COPY app/ ./app/

# Usuario sin privilegios: buena práctica para un contenedor expuesto públicamente.
RUN useradd --create-home --shell /bin/bash ariauser \
    && chown -R ariauser:ariauser /app
USER ariauser

# Streamlit debe escuchar en 0.0.0.0 (no localhost) para que el health checker
# de App Runner pueda alcanzarlo desde fuera del contenedor.
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8080 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# Health check local (docker run / ECS). App Runner usa su propia configuración
# de health check (ver HealthCheckConfiguration en deploy/apprunner-service.json),
# pero esto sirve para probar la imagen antes de desplegarla.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/_stcore/health', timeout=3)" || exit 1

CMD ["streamlit", "run", "app/app.py"]
