from pathlib import Path

from pydantic import BaseModel, ConfigDict


class SourcesConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    jpaths: list[Path] = []
    extensions: list[str] = ["jsonnet", "libsonnet", "jsonnet.TEMPLATE"]
    exclude: list[str] = [".*", ".*/"]


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    sources: SourcesConfig = SourcesConfig()
