from pydantic import BaseModel, ConfigDict


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    jpaths: list[str] = []
    exclude: list[str] | None = None
    extensions: list[str] = ["jsonnet", "libsonnet", "jsonnet.TEMPLATE"]
