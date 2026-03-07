from pydantic import BaseModel


class JouleConfig(BaseModel):
    include: list[str] = ["**/vendor"]
    exclude: list[str] = ["**/.*"]
    sources: list[str] = ["*.jsonnet", "*.libsonnet"]
