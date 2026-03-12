from pydantic import BaseModel, ConfigDict


class JouleConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    library_search_paths: list[str] = ["**/vendor"]
    exclude_folders: list[str] = ["**/.*"]
    include_folders: list[str] = ["**"]
    include_files: list[str] = ["*.jsonnet", "*.libsonnet"]
