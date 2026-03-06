from pydantic import BaseModel


class JouleConfig(BaseModel):
    include: list[str] = []
    exclude: list[str] = []
