import logging
import os
from typing import Literal

import boto3
from botocore.exceptions import ClientError
from pydantic import ConfigDict, Field
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

    GENAI_ENVIRONMENT: str

    # Selects infrastructure-specific capacity behavior. Docker Compose uses
    # operator-managed replicas; OKD delegates queue scaling to KEDA.
    DEPLOYMENT_TYPE: Literal["docker", "okd"] = "docker"

    CORS_ALLOWED_ORIGINS: str = "*"

    # Local authentication.  Set a long, unique value per environment; the
    # development default exists only to make the local stack usable.
    AUTH_JWT_SECRET: str = "change-me-in-production"
    AUTH_JWT_TTL_SECONDS: int = 3600
    # Required only for POST /auth/users. Keep empty to disable provisioning
    # through the API after the initial local users have been created.
    AUTH_BOOTSTRAP_TOKEN: str = ""

    # Destructive E2E cleanup is exposed only by a local API instance. The
    # endpoint remains disabled unless explicitly enabled in local config.
    E2E_CLEANUP_ENABLED: bool = False

    # Preserve local optimizer replay records for post-run debugging only when
    # an E2E explicitly opts in. Production and ordinary tests keep cleanup on.
    E2E_PRESERVE_DATA: bool = False

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

    # Per-request cap for Azure OpenAI calls. The SDK default (600 s, retried
    # twice) let one hung call hold a worker for ~15 min while its queue aged
    # past CELERY_STUCK_TASK_TIMEOUT_SECONDS.
    OPENAI_REQUEST_TIMEOUT_SECONDS: float = Field(default=120, gt=0)

    PROFILING_LLM_MODEL: str = ""

    DETECTOR_LLM_MODEL: str = ""

    DETECTOR_ADVERSARIAL_LLM_MODEL: str = ""

    CLASSIFICATION_LLM_MODEL: str = ""

    ADVERSARIAL_LLM_MODEL: str = ""

    ANALYST_LLM_MODEL: str = ""

    # Executor step's free-text generators (ARIC marking comment,
    # Documentador's "agent" strategy - see GenerateAgentTextUseCase). Not
    # REPORT_LLM_MODEL, a different consumer (DocumentAnalystDecisionUseCase,
    # the fire-and-forget audit-trail report written to object storage).
    EXECUTOR_LLM_MODEL: str = ""

    REPORT_LLM_MODEL: str = ""

    # Sampled reasoning LLM-judge (EvaluateAlertReasoning, D6). Empty falls
    # back to REPORT_LLM_MODEL (see workflows/celery/factories.py).
    JUDGE_LLM_MODEL: str = ""

    # MCP model-serving service
    MCP_PORT: int = 8100
    MCP_BASE_URL: str = "http://mcp:8100"
    MCP_TIMEOUT_SECONDS: float = 15.0

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
    # Age-based retention sweep (daily, Celery Beat). Deletes are permanent,
    # so it is off by default and, once enabled, dry-runs until
    # OBJECT_STORAGE_RETENTION_DRY_RUN=false. RULES is a JSON list of
    # {"store": "reports"|"datasets"|"models", "prefix": "...",
    #  "max_age_days": N}; an empty prefix is rejected.
    OBJECT_STORAGE_RETENTION_ENABLED: bool = False
    OBJECT_STORAGE_RETENTION_DRY_RUN: bool = True
    OBJECT_STORAGE_RETENTION_RULES: str = "[]"

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

    CELERY_AGENT_QUEUE: str = "agent"
    AGENT_STUB_DELAY_SECONDS: float = 0.0
    # Test runs use a dedicated queue and worker so batch CSV work cannot
    # consume production workflow capacity.
    CELERY_TEST_QUEUE: str = "test"
    # Simulator alerts use the production pipeline/configuration, but consume
    # isolated worker capacity so test traffic cannot delay production.
    CELERY_SIMULATOR_ALERT_QUEUE: str = "simulator_alerts"
    # Celery Beat is deliberately a standalone process (never co-located
    # with a worker).  This is the first global maintenance schedule; future
    # retention and cleanup jobs use the same scheduler.
    CELERY_RECONCILE_INTERVAL_SECONDS: int = Field(default=60, ge=10)
    CELERY_RECONCILE_LIMIT: int = Field(default=100, ge=1, le=1000)
    # A running task is stuck after this long without workflow step progress;
    # time spent waiting in the queue has its own, longer, limit.
    CELERY_STUCK_TASK_TIMEOUT_SECONDS: int = Field(default=900, ge=60)
    CELERY_STUCK_QUEUE_TIMEOUT_SECONDS: int = Field(default=3600, ge=60)
    CELERY_TEST_RUN_CLEANUP_INTERVAL_SECONDS: int = Field(default=3600, ge=60)

    # TEST RUNS - CSV datasets dropped on disk, listed via plain fs scan
    DATASETS_DIR: str = "./datasets"

    # "filesystem" (default, reads DATASETS_DIR above) or "minio" (reads/writes
    # the DATASET_STORAGE_BUCKET below - what the testing page's dataset
    # upload button targets). See dataset_factory.py's get_dataset_repository().
    DATASET_STORAGE_BACKEND: str = "filesystem"
    DATASET_STORAGE_BUCKET: str = "datasets"
    # Analysis currently builds row/sample collections in memory. Larger
    # uploads remain stored safely, but are not automatically profiled until
    # the analysis pipeline is made fully streaming.
    DATASET_ANALYSIS_MAX_BYTES: int = 268435456
    # Reproducible splits run synchronously in the API and hold every row in
    # memory; larger sources must be sampled first (POST /datasets/extract).
    DATASET_SPLIT_MAX_ROWS: int = 200000

    # MODELS - versioned XGBoost training artifacts (joblib bundles), see
    # infrastructure/persistence/object_storage/minio/__init__.py's
    # get_model_object_storage().
    MODEL_STORAGE_BUCKET: str = "models"

    # EVENT SIMULATOR - independent microservice
    # (src/infrastructure/entrypoint/simulator/), never imported by aria-api
    # or aria-worker.
    # How often the self-rescheduling tick task wakes up per RUNNING
    # scenario - trades rate-curve precision against Celery/LLM load.
    EVENT_SIMULATOR_TICK_SECONDS: int = 10
    # Hard ceiling per tick regardless of what a scenario's rate curve
    # computes - guards against a misconfigured curve fork-bombing the
    # simulator's own Celery queue or the LLM backend.
    EVENT_SIMULATOR_MAX_EVENTS_PER_TICK: int = 200
    # Reuses the same Redis container as aria-worker (see CELERY_BROKER_URL
    # above) but a distinct logical DB + queue name, so the simulator's own
    # worker pool never competes with aria-worker's for capacity.
    EVENT_SIMULATOR_CELERY_BROKER_URL: str = "redis://redis:6379/2"
    EVENT_SIMULATOR_CELERY_RESULT_BACKEND: str = "redis://redis:6379/3"
    EVENT_SIMULATOR_CELERY_QUEUE: str = "event_simulation"
    # Where the simulator's HTTP gateways (AlertDispatchGateway/EventSink/
    # DatasetReaderGateway) reach aria-api - POST /alerts/test and
    # POST|GET /datasets/{name}/rows. No auth token today: neither endpoint
    # is behind an auth dependency in aria-api as of this writing (see
    # HttpAlertDispatchGateway's docstring) - EVENT_SIMULATOR_ARIA_API_TOKEN
    # is read and sent as a Bearer header only if non-empty, ready for
    # whenever that changes.
    EVENT_SIMULATOR_ARIA_API_BASE_URL: str = "http://api:8000"
    EVENT_SIMULATOR_ARIA_API_TOKEN: str = ""

    # Local clock the analyst staffing matrix (OperationalSettings.
    # analyst_capacity, one value per hour of the day) is read against.
    OPERATIONS_TIMEZONE: str = "America/Bogota"
    # Shared secret the voicebot provider sends as a Bearer token on
    # POST /voicebot/callbacks. Checked only when non-empty (same opt-in
    # pattern as EVENT_SIMULATOR_ARIA_API_TOKEN) - set it in every
    # non-local environment, otherwise anyone can release voicebot slots.
    VOICEBOT_CALLBACK_TOKEN: str = ""

    model_config = ConfigDict(extra="ignore")

    def model_post_init(self, __context):
        parameter_store_path = self.model_dump().get("PARAMETER_STORE_CONFIG", "")
        parameters = {}
        if parameter_store_path is not None and parameter_store_path.strip() != "":
            parameters = self._get_parameters_from_parameter_store(parameter_store_path)
        for attribute, value in self.model_dump().items():
            if attribute in parameters:
                attribute_type = type(getattr(self, attribute))
                value = parameters[attribute]
                setattr(self, attribute, attribute_type(value))
                logger.info(f"se ha cambiado el atributo {attribute} al valor {value}")
            if isinstance(value, str) and value.startswith("arn:aws:secretsmanager"):
                setattr(self, attribute, self._get_value_from_secret_manager(value))

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
            get_secret_value_response = client.get_secret_value(SecretId=secret_arn)
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
