from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]


class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ConversationCreate(StrictBody):
    participant_id: str = Field(min_length=1, max_length=36)
    initial_message: Text | None = None


class MessageCreate(StrictBody):
    content: Text
    message_type: Literal['text'] = 'text'


class MessageEdit(StrictBody):
    content: Text


class MessagesRead(StrictBody):
    message_ids: list[Annotated[int, Field(gt=0)]] = Field(min_length=1, max_length=200)


class PreferencesUpdate(StrictBody):
    email_notifications: bool
    message_email_notifications: bool
    appointment_reminders: bool
    push_notifications: bool
