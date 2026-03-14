from pydantic import BaseModel, ConfigDict


class JouleConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    library_paths: list[str] = ["**/vendor"]
    exclude: list[str] = ["**/.*"]
    include: list[str] = ["**"]
    suffixes: list[str] = ["jsonnet", "libsonnet"]
