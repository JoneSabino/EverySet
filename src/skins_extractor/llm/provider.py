from typing import Protocol

from pydantic import BaseModel


class LLMProvider(Protocol):
    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        cache_system: bool = True,
        max_tokens: int = 4096,
    ) -> BaseModel: ...

    def complete_vision_json(
        self,
        system: str,
        user: str,
        image_bytes: bytes,
        schema: type[BaseModel],
        max_tokens: int = 4096,
    ) -> BaseModel: ...
