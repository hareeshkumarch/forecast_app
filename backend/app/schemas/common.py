from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
ShortStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
Percentage = Annotated[float, Field(ge=0.0, le=100.0)]
Probability = Annotated[float, Field(gt=0.0, lt=1.0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegativeFloat = Annotated[float, Field(ge=0.0)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, str_strip_whitespace=True)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ShortStr
    message: NonEmptyStr
    detail: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail


