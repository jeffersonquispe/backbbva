from functools import lru_cache

import boto3
from botocore.config import Config

from src.infrastructure.core.config import genai_config


@lru_cache
def get_dynamodb_resource():
    kwargs = {
        "region_name": genai_config.DYNAMO_REGION_NAME,
    }

    if genai_config.DYNAMO_ENDPOINT:
        # Configuración de "Fallo Rápido"
        local_config = Config(
            connect_timeout=10, # Si en 10 seg no conecta, falla
            read_timeout=30, # Si en 10 seg no lee, falla
            retries={'max_attempts': 2} # Intentos
        )
        
        kwargs.update(
            {
                "endpoint_url": genai_config.DYNAMO_ENDPOINT,
                "aws_access_key_id": genai_config.DYNAMO_ACCESS_KEY,
                "aws_secret_access_key": genai_config.DYNAMO_SECRET_KEY,
                "config": local_config
            }
        )

    return boto3.resource("dynamodb", **kwargs)
