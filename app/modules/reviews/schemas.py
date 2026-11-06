from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ReviewWrite(StrictBody):
    appointment_id: str = Field(min_length=1, max_length=36)
    rating: int = Field(ge=1, le=5)
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=3000)]


class ReviewDecision(StrictBody):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)] | None = None
