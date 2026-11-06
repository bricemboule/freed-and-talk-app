from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    appointment_id: str = Field(min_length=1, max_length=36)
    provider: Literal['orange_money', 'mtn_momo', 'mobile_money', 'card']
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r'^[A-Za-z0-9._:-]+$')
