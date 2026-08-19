from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class WireModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ApiResponse(WireModel, Generic[T]):
    code: int
    message: str
    data: T | None = None

    @classmethod
    def ok(cls, data: T | None = None, message: str = "success") -> "ApiResponse[T]":
        return cls(code=200, message=message, data=data)

    @classmethod
    def fail(cls, message: str, code: int = 500) -> "ApiResponse[None]":
        return cls(code=code, message=message, data=None)