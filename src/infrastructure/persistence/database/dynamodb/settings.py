import os
from pydantic import BaseModel


class DynamoSettings(BaseModel):

    region_name: str = os.getenv("DYNAMO_REGION_NAME", "us-east-1")

    endpoint_url: str | None = os.getenv("DYNAMO_ENDPOINT")

    access_key: str | None = os.getenv("DYNAMO_ACCESS_KEY")
    secret_key: str | None = os.getenv("DYNAMO_SECRET_KEY")


dynamo_settings = DynamoSettings()
