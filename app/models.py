from pydantic import BaseModel
from typing import Optional


class Song(BaseModel):
    id: int
    title: str
    artist: str
    has_backing: bool = False  # Наличие бэка
    type: str = None
    similarity_score: Optional[float] = None
