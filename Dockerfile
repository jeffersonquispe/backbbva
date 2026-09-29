FROM artifactory.globaldevtools.bbva.com:443/public.ecr.aws-remote/docker/library/python:3.11-slim

ARG GENAI_ENVIRONMENT
ARG ARTIFACTORY_USER
ARG ARTIFACTORY_PASSWORD

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
COPY deploy/requirements/pyproject.toml ./pyproject.toml
RUN pip install --no-cache-dir --index-url https://${ARTIFACTORY_USER}:${ARTIFACTORY_PASSWORD}@artifactory.globaldevtools.bbva.com/artifactory/api/pypi/gl-ai-genai-python-virtual/simple poetry==${POETRY_VERSION} 
RUN poetry config http-basic.BBVARepo ${ARTIFACTORY_USER} ${ARTIFACTORY_PASSWORD} 
RUN poetry install --without dev --no-root 

RUN rm -rf /root/.cache/* && \
    rm -rf /usr/local/lib/python*/site-packages/pip* /usr/local/lib/python*/site-packages/setuptools* /usr/local/bin/pip*
RUN apt-get update && apt-get install -y --no-install-recommends \                                                                                                                                         
    make \                                                                                                                                                                                                   
    && rm -rf /var/lib/apt/lists/*

RUN poetry install --only main --no-root

COPY src ./src

RUN chown -R www-data:www-data ${APP_DIR} && chmod -R 755 ${APP_DIR}
USER www-data

EXPOSE 8000

CMD ["uvicorn", "src.infrastructure.entrypoint.api.fastapi_app:app", "--host", "0.0.0.0", "--port", "8000"]
