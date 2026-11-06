"""Routes HTTP privées de messagerie et de notifications."""
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.database import get_db
from app.core.rate_limit import rate_limit
from app.modules.auth.api.routes import current_user
from app.modules.auth.models.entities import User
from app.modules.auth.services.logic import fail
from app.modules.psychologists.storage import validate_content
from . import notifications, services
from .schemas import ConversationCreate, MessageCreate, MessageEdit, PreferencesUpdate

router = APIRouter()
conversations = APIRouter(prefix='/api/conversations', tags=['Messagerie'])
notifications_router = APIRouter(prefix='/api/notifications', tags=['Notifications'])
Db = Annotated[Session, Depends(get_db)]
ConnectedUser = Annotated[User, Depends(current_user)]
Page = Annotated[int, Query(ge=1)]
Limit = Annotated[int, Query(ge=1, le=100)]


@conversations.get('')
def get_conversations(user: ConnectedUser, db: Db, page: Page = 1, limit: Limit = 20):
    return services.list_conversations(db, user, page, limit)


@conversations.post('', status_code=201)
def open_conversation(body: ConversationCreate, user: ConnectedUser, db: Db):
    return services.create_conversation(db, user, body.participant_id, body.initial_message)


@conversations.get('/{conversation_id}/messages')
def get_messages(conversation_id: str, user: ConnectedUser, db: Db,
                 before_id: int | None = Query(default=None, gt=0),
                 page: Page = 1, limit: Limit = 50):
    return services.list_messages(db, user, conversation_id, before_id, page, limit)


@conversations.post('/{conversation_id}/messages', status_code=201)
def post_message(conversation_id: str, body: MessageCreate, user: ConnectedUser,
                 db: Db, request: Request):
    rate_limit(request, 'send-message', user.id, 60, 60)
    return services.create_message(db, user, conversation_id, body.content)


@conversations.put('/{conversation_id}/messages/{message_id}')
def update_message(conversation_id: str, message_id: int, body: MessageEdit,
                   user: ConnectedUser, db: Db):
    return services.edit_message(db, user, conversation_id, message_id, body.content)


@conversations.delete('/{conversation_id}/messages/{message_id}')
def remove_message(conversation_id: str, message_id: int, user: ConnectedUser, db: Db):
    return services.delete_message(db, user, conversation_id, message_id)


@conversations.post('/{conversation_id}/messages/attachment', status_code=201)
async def upload_message_attachment(conversation_id: str, user: ConnectedUser, db: Db,
                                    file: UploadFile = File(...),
                                    caption: str | None = Form(default=None, max_length=1000)):
    maximum = get_settings().message_attachment_max_bytes
    try:
        raw = await file.read(maximum + 1)
    finally:
        await file.close()
    if not raw:
        fail(400, 'EMPTY_FILE')
    if len(raw) > maximum:
        fail(413, 'FILE_TOO_LARGE')
    content, mime, extension = await run_in_threadpool(validate_content, raw, avatar=False)
    if extension not in {'.jpg', '.png', '.pdf'}:
        fail(415, 'FILE_TYPE_NOT_ALLOWED')
    if len(content) > maximum:
        fail(413, 'FILE_TOO_LARGE')
    filename = (file.filename or 'piece-jointe').replace('\\', '/').rsplit('/', 1)[-1]
    filename = ''.join(ch for ch in filename if ch.isprintable()).strip()[:255] or 'piece-jointe'
    return await run_in_threadpool(services.save_attachment, db, user, conversation_id,
        content=content, mime_type=mime, extension=extension, filename=filename, caption=caption)


@conversations.get('/{conversation_id}/attachments/{attachment_id}')
def download_message_attachment(conversation_id: str, attachment_id: str,
                                user: ConnectedUser, db: Db):
    attachment, path = services.attachment_path(db, user, conversation_id, attachment_id)
    return FileResponse(path, media_type=attachment.mime_type, filename=attachment.original_filename,
        headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@notifications_router.get('')
def get_notifications(user: ConnectedUser, db: Db, page: Page = 1, limit: Limit = 20):
    return services.list_notifications(db, user, page, limit)


@notifications_router.get('/unread')
def get_unread_notifications(user: ConnectedUser, db: Db, page: Page = 1, limit: Limit = 20):
    return services.list_notifications(db, user, page, limit, unread_only=True)


@notifications_router.get('/preferences')
def get_notification_preferences(user: ConnectedUser, db: Db):
    return services.preferences_view(db, user)


@notifications_router.put('/preferences')
def update_notification_preferences(body: PreferencesUpdate, user: ConnectedUser, db: Db):
    return notifications.set_preferences(db, user, body)


@notifications_router.post('/{notification_id}/read')
def mark_notification_read(notification_id: str, user: ConnectedUser, db: Db):
    return notifications.mutate_notification(db, user, notification_id)


@notifications_router.post('/read-all')
def mark_all_notifications_read(user: ConnectedUser, db: Db):
    return notifications.read_all(db, user)


@notifications_router.delete('/{notification_id}')
def delete_notification(notification_id: str, user: ConnectedUser, db: Db):
    return notifications.mutate_notification(db, user, notification_id, remove=True)


router.include_router(conversations)
router.include_router(notifications_router)
