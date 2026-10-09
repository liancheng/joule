from pathlib import Path

from pydantic import BaseModel, ConfigDict


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    jpaths: list[Path] = []
    exclude: list[str] | None = None
    extensions: list[str] = ["jsonnet", "libsonnet", "jsonnet.TEMPLATE"]
