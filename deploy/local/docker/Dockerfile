FROM python:3.11-slim

ARG GENAI_ENVIRONMENT=local

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GENAI_ENVIRONMENT=${GENAI_ENVIRONMENT} \
    APP_DIR=/code \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_VERSION=2.2.1 \
    POETRY_NO_INTERACTION=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR ${APP_DIR}

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry==${POETRY_VERSION}
COPY deploy/requirements/pyproject.toml ./pyproject.toml
RUN poetry install --only main --no-root

COPY src ./src
RUN chown -R www-data:www-data ${APP_DIR} && chmod -R 755 ${APP_DIR}
USER www-data

EXPOSE 8000

CMD ["uvicorn", "src.infrastructure.entrypoint.api.fastapi_app:app", "--host", "0.0.0.0", "--port", "8000"]
