import logging
import os

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

    GENAI_APPLICATION: str = "aria"

    GENAI_ENVIRONMENT: str

    CORS_ALLOWED_ORIGINS: str = "*"

    GENAI_PRODUCT: str = "aria"

    GENAI_NAME: str = "aria-api"

    OTEL_ENDPOINT: str = "http://localhost:4317"

    # Prompts/completions are opt-in: default off so raw LLM content never
    # leaves the process unless explicitly enabled for an environment.
    OTEL_CAPTURE_LLM_CONTENT: bool = False

    PARAMETER_STORE_CONFIG: str = ""

    # LLM backend selection - which adapter get_llm_unit_of_work_factory()
    # builds. Add a new value here + a branch in
    # infrastructure/llm/langchain/__init__.py when adding another
    # provider; step use cases and ports never see this switch, they only
    # ever depend on LLMUnitOfWorkFactory.
    LLM_BACKEND: str = "azure"

    # "llm" (ProfileAlertUseCase) or "deterministic"
    # (DeterministicProfileAlertUseCase) - see
    # infrastructure/workflows/celery/factories.py's
    # get_profile_alert_use_case(). None of profiling's 3 output fields
    # involve judgment, only description of already-fetched data, so the
    # deterministic path is a straight swap, not a quality tradeoff.
    PROFILING_BACKEND: str = "llm"

    # integrations configurations
    OPENAI_ENDPOINT: str = ""

    OPENAI_KEY: str = ""

    OPENAI_VERSION: str = "2024-08-01-preview"

    PROFILING_LLM_MODEL: str = ""

    CLASSIFICATION_LLM_MODEL: str = ""

    ADVERSARIAL_LLM_MODEL: str = ""

    ANALYST_LLM_MODEL: str = ""

    REPORT_LLM_MODEL: str = ""

    # DYNAMODB
    DYNAMO_REGION_NAME: str = "us-east-1"
    DYNAMO_ENDPOINT: str = "http://dynamodb-lupita:8000"
    DYNAMO_ACCESS_KEY: str = "dummy"
    DYNAMO_SECRET_KEY: str = "dummy"

    # OBJECT STORAGE (MinIO, S3-compatible)
    OBJECT_STORAGE_ENDPOINT: str = "http://minio:9000"
    OBJECT_STORAGE_REGION: str = "us-east-1"
    OBJECT_STORAGE_ACCESS_KEY: str = "dummy"
    OBJECT_STORAGE_SECRET_KEY: str = "dummy"
    OBJECT_STORAGE_BUCKET: str = "aria-reports"

    # OPENSEARCH (fraud knowledge vector store)
    OPENSEARCH_ENDPOINT: str = "http://opensearch:9200"
    OPENSEARCH_REGION: str = "eu-west-1"
    OPENSEARCH_AUTH_MODE: str = "basic"
    OPENSEARCH_USERNAME: str = "admin"
    OPENSEARCH_PASSWORD: str = "dummy"
    OPENSEARCH_VERIFY_CERTS: bool = False
    OPENSEARCH_INDEX: str = "fraud_knowledge"

    EMBEDDING_MODEL: str = ""
    EMBEDDING_DIMENSIONS: int = 1536

    # QUEUE
    ASYNC_EXECUTOR_BACKEND: str = "celery"
    CELERY_BROKER_URL: str = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/1"
    CELERY_DEFAULT_QUEUE: str = "default"

    # TEST RUNS - CSV datasets dropped on disk, listed via plain fs scan
    DATASETS_DIR: str = "./datasets"

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
