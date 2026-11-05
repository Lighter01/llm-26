"""Shared data contracts; importing this module never loads a model."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class RagError(Exception):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict:
        result = {'code': self.code, 'message': self.message}
        if self.details is not None:
            result['details'] = self.details
        return result


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
