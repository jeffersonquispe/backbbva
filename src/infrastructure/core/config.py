import logging
import os
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from pydantic import ConfigDict
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Config(BaseSettings):

    API_V0_STR: str

    AWS_REGION_NAME: str = "eu-west-1"

    COMPONENT_NAME: str = "aria-api"

    COMPONENT_DESCRIPTION: str = (
        "API for the novel massive fraud agent for BBVA company"
    )

    COMPONENT_VERSION: str = "0.1.0"

    DEFAULT_LOGGING_LEVEL: str = "INFO"

    ECS_CONTAINER_METADATA_URI_V4: str = "local"

    GENAI_APPLICATION: str = "aria"

    GENAI_BASE_URL: str = "http://localhost:8000"

    GENAI_ENVIRONMENT: str

    CORS_ALLOWED_ORIGINS: str = "*"

    GENAI_MIDDLEWARE_HEADERS: str = (
        "x-amzn-trace-id,x-rho-traceid,x-rho-parentspanid"
    )

    GENAI_OTEL_EXPORTER_KINESIS_STREAM: str | None = None

    GENAI_OTEL_EXPORTER_KINESIS_STREAM_OBFUSCATE_FIELDS: str | None = None

    GENAI_OTEL_EXPORTER_OTLP_STREAM_OBFUSCATE_FIELDS: str | None = None

    GENAI_PRODUCT: str = "aria"

    GENAI_NAME: str = "aria-api"

    OTEL_ENDPOINT: str = "http://localhost:4317"

    # Prompts/completions are opt-in: default off so raw LLM content never
    # leaves the process unless explicitly enabled for an environment.
    OTEL_CAPTURE_LLM_CONTENT: bool = False

    PHOENIX_ENABLED: bool = False

    PHOENIX_ENDPOINT: str | None = None

    PARAMETER_STORE_CONFIG: str = ""

    PARAMETER_STORE_S3_PROMPT_VERSION: str | None = None

    PROMPT_REPOSITORY_ROUTE: str = "./resources/templates/"

    RDS_PSQL_CREDENTIALS: str | None = None

    S3_BUCKET_PROMPT: str | None = None

    S3_LABEL_VERSION_PROMPT: str = "stable"

    S3_PATH_PROMPT: str | None = None

    # framework configurations

    SEARCH_TYPE: str = "mmr"
    SIMILITARY_ST_SEARCH_TYPE: str = "similarity_score_threshold"

    # Similitary Score Threshold params
    SIMILITARY_ST_SEARCH_K: int = (
        1  # Cantidad de documentos recuperados desde la BD Vectorial
    )
    SIMILITARY_ST_SCORE: float = (
        0.5  # Rango de similitud del vector { (0) -> menor similitud (1) -> mayor similitud }
    )

    # solo
    MMR_DIVERSITY_LAMDA: float = 1  # entre divercidad (0) y relevancia (1)
    MMR_FETCH_K: int = 20
    SEARCH_K: int = 7

    # integrations configurations
    OPENAI_ENDPOINT: str = ""

    PROXY_NG: str = ""

    OPENAI_KEY: str = ""

    OPENAI_VERSION: str = "2024-08-01-preview"

    TIKTOKEN_CACHE_DIR: str = "./"

    TIKTOKEN_ENCODING: str = (
        "cl100k_base"  # BPE encoding used by GPT-4 / text-embedding-3
    )

    RAG_EVALUATION_MODEL_NAME: str = (
        "gpt-4"  # Recomendado para las evaluaciones RAG
    )

    DEFAULT_EMBEDDING_MODEL_NAME: str = "agentepqrs-llm-live-emebed-3-large"
    DEFAULT_LLM_MODEL_NAME: str = "agentepqrs-llm-live-agent-gpt52"
    ROUTER_LLM_MODEL_NAME: str = "agentepqrs-llm-live-agent-gpt52"
    VISION_MODEL_NAME: str = "agentepqrs-llm-live-agent-gpt52"

    DYNAMO_AUTH_SESSIONS_TABLE_NAME: str = "auth_sessions"
    DYNAMO_CHAT_SESSIONS_TABLE_NAME: str = "chat_sessions"
    SESSION_COOKIE_MAX_AGE: int = 60 * 60 * 8  # 8 horas
    SECURITY_ENABLED: bool = False  # Activar en pruebas de seguridad
    ADMIN_TOKEN: str = ""  # Si está vacío, el check de /admin/* se omite (dev mode)
    SNIPPET_CHUNK_SIZE: int = (
        180  # Max characters per snippet chunk (used by preview path)
    )
    SNIPPET_CHUNK_OVERLAP: int = (
        30  # Overlap between consecutive snippet chunks (used by preview path)
    )

    SNIPPET_CHUNK_SIZE_TOKENS: int = (
        180  # Max tokens per snippet chunk (used by ingestion path)
    )
    SNIPPET_CHUNK_OVERLAP_TOKENS: int = (
        30  # Overlap in tokens between consecutive snippet chunks
    )

    INSTRUCTIONS: str = ""

    TEMPERATURE: float = 1

    MAX_TOKENS: int = 4000

    DOCUMENT_ASSESSMENT_LLM_MAX_TOKENS: int = 100000

    OPENAI_TIMEOUT: int = 60

    KNOWLEDGE_AGENT_TIMEOUT: float = 120.0

    KNOWLEDGE_AGENT_MAX_ITERATIONS: int = 6

    OPENAI_MAX_RETRIES: int = 3

    OPENSEARCH_REGION: str = "eu-west-1"

    OPENSEARCH_INDEX: str = "lupita-vector-index"

    OPENSEARCH_FAQS_INDEX: str = "faqs-vector-index"

    OPENSEARCH_ENDPOINT: str = "http://localhost:9200"

    OPENSEARCH_TIMEOUT: int = 60

    OPENSEARCH_MAX_RETRIES: int = 3

    OPENSEARCH_WAIT_EXPONENTIAL_JITTER: bool = True

    OPENSEARCH_USER: str = "admin"

    OPENSEARCH_PASSWORD: str = "admin"

    OPENSEARCH_SERVICE: str = "es"

    RDS_PSQL_USER: str = "postgress"

    RDS_PSQL_ENDPOINT: str = "rds"

    RDS_PSQL_PORT: str = "5432"

    RDS_PSQL_DB: str = "langgraph_test"

    LANGGRAPH_COMPILE_DEBUG: bool = False

    RDS_PSQL_PASSWORD: str = "genai"

    # DYNAMODB
    DYNAMO_REGION_NAME: str = "us-east-1"
    DYNAMO_ENDPOINT: str = "http://dynamodb-lupita:8000"
    DYNAMO_ACCESS_KEY: str = "dummy"
    DYNAMO_SECRET_KEY: str = "dummy"

    # QUEUE
    ASYNC_EXECUTOR_BACKEND: str = "celery"
    CELERY_BROKER_URL: str = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/1"
    CELERY_DEFAULT_QUEUE: str = "default"

    # SECURITY-NAUTILUS

    ALLOWED_ROLES: str = "lupita_admin,bbva_employee,Usuario"
    ISSUER: str = "https://preidp.work.global.platform.bbva.com/oidc/"
    JWKS_UR: str = "https://preidp.work.global.platform.bbva.com/oidc/jwk"
    AUDIENCE: str = "76ace507-d90c-49fd-a8c1-e7d0c5f55d0f"
    OIDC_TOKEN_URL: str = (
        "https://preidp.work.global.platform.bbva.com/oidc/token"
    )
    OIDC_CLIENT_ID: str = "76ace507-d90c-49fd-a8c1-e7d0c5f55d0f"
    OIDC_CLIENT_SECRET: str = "OIDC_CLIENT_SECRET"
    JWKS_CACHE_TTL: int = 300
    NAUTILUS: bool = False

    # Copilot — plataforma transversal de asistencia
    COPILOT_ENABLED: bool = True
    COPILOT_PROACTIVE: bool = True
    # ponytail: flags declarados, comportamiento diferenciado en Fase 2+
    COPILOT_SEMANTIC_SEARCH: bool = True
    COPILOT_REVIEW_MODE: bool = True

    # Concurrency limit — per Gunicorn worker process.
    # Total simultaneous LLM calls: GUNICORN_WORKERS × LLM_CONCURRENCY_QUESTION
    LLM_CONCURRENCY_QUESTION: int = 5

    # LLM API compatibility flags
    # Models in this list use max_completion_tokens instead of the legacy
    # max_tokens parameter, and do NOT accept an explicit temperature value
    # (they only operate at their default temperature).
    # Add a model's azure_deployment name here when it rejects max_tokens
    # or returns a 400 for explicit temperature.
    NEW_COMPLETION_API_MODELS: list = [
        "agentepqrs-llm-live-agent-gpt5nano",
        "agentepqrs-llm-live-agent-gpt5mini",
        "agentepqrs-llm-live-agent-gpt52",
        "agentepqrs-llm-live-agent-gpt41",
    ]

    # framework configurations

    model_config = ConfigDict(extra="ignore")

    def model_post_init(self, __context):
        parameter_store_path = self.model_dump().get(
            "PARAMETER_STORE_CONFIG", ""
        )
        parameters = {}
        if (
            parameter_store_path is not None
            and parameter_store_path.strip() != ""
        ):
            parameters = self._get_parameters_from_parameter_store(
                parameter_store_path
            )
        for attribute, value in self.model_dump().items():
            if attribute in parameters:
                attribute_type = type(getattr(self, attribute))
                value = parameters[attribute]
                setattr(self, attribute, attribute_type(value))
                logger.info(
                    f"se ha cambiado el atributo {attribute} al valor {value}"
                )
            if isinstance(value, str) and value.startswith(
                "arn:aws:secretsmanager"
            ):
                setattr(
                    self, attribute, self._get_value_from_secret_manager(value)
                )

    @staticmethod
    def _get_parameters_from_parameter_store(parameter_store_config):
        # Create a Secrets Manager client
        session = boto3.session.Session()
        client = session.client(service_name="ssm")
        parameters_result = {}
        try:
            get_parameters = client.get_parameter(
                Name=parameter_store_config, WithDecryption=False
            )
        except ClientError as e:
            # For a list of exceptions thrown, see
            # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
            raise e
        parameters = get_parameters["Parameter"]["Value"]
        lines = parameters.splitlines()
        for line in lines:
            # Ignore empty lines
            if line.strip():
                # split line caused by =
                key, value = line.split("=", 1)
                parameters_result[key] = value
        return parameters_result

    @staticmethod
    def _get_value_from_secret_manager(secret_arn):
        # Create a Secrets Manager client
        session = boto3.session.Session()
        client = session.client(service_name="secretsmanager")
        try:
            get_secret_value_response = client.get_secret_value(
                SecretId=secret_arn
            )
        except ClientError as e:
            # For a list of exceptions thrown, see
            # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
            raise e

        secret = get_secret_value_response["SecretString"]
        return secret


genai_config = Config(
    _env_file=[
        "./.env",
        os.path.expandvars("./config/$GENAI_ENVIRONMENT/config.cfg"),
    ]
)
