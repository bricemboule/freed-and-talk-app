"""Logique métier des conversations privées et notifications personnelles."""
from datetime import timedelta
from pathlib import Path
import os
import re

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.auth.models.entities import User, now
from app.modules.auth.services.logic import fail, utc
from app.modules.psychologists.models import PsychologistProfile
from app.modules.auth.models.entities import uid
from . import notifications
from .models import (Conversation, ConversationParticipant, Message, MessageAttachment,
                     MessageRead, MessageQuota, MessageRevision, Notification,
                     NotificationPreferences, RealtimeEvent)


def _active_user(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if not user or not user.is_active or not user.email_verified or not user.role.is_active:
        fail(404, 'USER_NOT_FOUND')
    return user


def _approved_psychologist(db: Session, user: User) -> PsychologistProfile:
    profile = db.scalar(select(PsychologistProfile).where(
        PsychologistProfile.user_id == user.id,
        PsychologistProfile.verification_status == 'approved'))
    if not profile:
        fail(403, 'PSYCHOLOGIST_NOT_APPROVED')
    return profile


def _member(db: Session, conversation_id: str, user_id: str, *, lock=False):
    query = select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conversation_id,
        ConversationParticipant.user_id == user_id,
        ConversationParticipant.is_active.is_(True))
    participant = db.scalar(query.with_for_update() if lock else query)
    if not participant:
        fail(404, 'CONVERSATION_NOT_FOUND')
    return participant


def _message_view(db: Session, item: Message, viewer_id: str):
    read = db.scalar(select(MessageRead.id).where(
        MessageRead.message_id == item.id, MessageRead.user_id == viewer_id)) if item.sender_id != viewer_id else None
    attachment = db.scalar(select(MessageAttachment).where(
        MessageAttachment.message_id == item.id, MessageAttachment.deleted_at.is_(None)))
    return {'id': item.id, 'conversation_id': item.conversation_id,
            'sender_id': item.sender_id,
            'content': '[message supprimé]' if item.deleted_at else item.content,
            'message_type': item.message_type, 'created_at': utc(item.created_at),
            'edited_at': utc(item.edited_at), 'deleted_at': utc(item.deleted_at),
            'is_read': bool(read),
            'attachment': ({'id': attachment.id, 'filename': attachment.original_filename,
                           'mime_type': attachment.mime_type, 'file_size': attachment.file_size,
                           'download_url': f'/api/conversations/{item.conversation_id}/attachments/{attachment.id}'}
                          if attachment else None)}


def conversation_view(db: Session, item: Conversation, user_id: str):
    members = list(db.scalars(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == item.id,
        ConversationParticipant.is_active.is_(True))))
    other_id = next((m.user_id for m in members if m.user_id != user_id), None)
    other = _active_user(db, other_id) if other_id else None
    last = db.scalar(select(Message).where(Message.conversation_id == item.id)
                     .order_by(Message.id.desc()).limit(1))
    unread = db.scalar(select(func.count()).select_from(Message).where(
        Message.conversation_id == item.id, Message.sender_id != user_id,
        Message.deleted_at.is_(None), ~select(MessageRead.id).where(
            MessageRead.message_id == Message.id, MessageRead.user_id == user_id).exists()))
    return {'id': item.id, 'status': item.status, 'created_at': utc(item.created_at),
            'last_message_at': utc(item.last_message_at), 'unread_count': unread or 0,
            'participant': {'id': other.id, 'fullname': other.fullname, 'role': other.role.code} if other else None,
            'last_message': _message_view(db, last, user_id) if last else None}


def list_conversations(db: Session, user: User, page: int, limit: int):
    query = select(Conversation).join(ConversationParticipant).where(
        ConversationParticipant.user_id == user.id,
        ConversationParticipant.is_active.is_(True),
        ConversationParticipant.archived_at.is_(None))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(query.order_by(case((Conversation.last_message_at.is_(None), 1), else_=0),
                                      Conversation.last_message_at.desc(), Conversation.created_at.desc())
                       .offset((page - 1) * limit).limit(limit))
    return {'items': [conversation_view(db, item, user.id) for item in items],
            'total': total, 'page': page, 'limit': limit}


def create_conversation(db: Session, user: User, target_id: str, initial_message: str | None):
    target = _active_user(db, target_id)
    if target.id == user.id:
        fail(400, 'SELF_CONVERSATION_NOT_ALLOWED')
    if user.role.code == 'patient' and target.role.code == 'psychologist':
        _approved_psychologist(db, target)
    elif user.role.code == 'psychologist' and target.role.code == 'patient':
        _approved_psychologist(db, user)
        pair = sorted((user.id, target.id))
        existing = db.scalar(select(Conversation).where(
            Conversation.user_low == pair[0], Conversation.user_high == pair[1]))
        if not existing:
            fail(403, 'PATIENT_MUST_START_CONVERSATION')
    else:
        fail(403, 'INVALID_CONVERSATION_PARTICIPANTS')
    pair = sorted((user.id, target.id))
    conversation = db.scalar(select(Conversation).where(
        Conversation.user_low == pair[0], Conversation.user_high == pair[1]))
    created = conversation is None
    if conversation is None:
        conversation = Conversation(user_low=pair[0], user_high=pair[1], created_by=user.id)
        db.add(conversation)
        db.flush()
        db.add_all([ConversationParticipant(conversation_id=conversation.id, user_id=pair[0]),
                    ConversationParticipant(conversation_id=conversation.id, user_id=pair[1])])
    if initial_message:
        send_message(db, user, conversation.id, initial_message, commit=False)
    db.commit()
    return {'conversation': conversation_view(db, conversation, user.id), 'created': created}


def _consume_quota(db: Session, user: User):
    # Locking the user serializes creation and increments on MySQL as well as SQLite.
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    quota = db.get(MessageQuota, user.id)
    timestamp = now()
    if not quota:
        quota = MessageQuota(user_id=user.id, window_start=timestamp, count=0)
        db.add(quota)
        db.flush()
    if utc(quota.window_start) <= timestamp - timedelta(minutes=1):
        quota.window_start, quota.count = timestamp, 0
    if quota.count >= get_settings().message_rate_limit:
        fail(429, 'MESSAGE_RATE_LIMIT_EXCEEDED')
    quota.count += 1


def send_message(db: Session, user: User, conversation_id: str, content: str, *, commit=True):
    conversation = db.scalar(select(Conversation).where(
        Conversation.id == conversation_id).with_for_update())
    if not conversation:
        fail(404, 'CONVERSATION_NOT_FOUND')
    _member(db, conversation_id, user.id, lock=True)
    if conversation.status != 'active':
        fail(409, 'CONVERSATION_CLOSED')
    if len(content) > get_settings().message_max_characters:
        fail(422, 'MESSAGE_TOO_LONG')
    _consume_quota(db, user)
    message = Message(conversation_id=conversation.id, sender_id=user.id,
                      content=content, message_type='text')
    db.add(message)
    db.flush()
    conversation.last_message_at = message.created_at or now()
    recipient_id = conversation.user_high if conversation.user_low == user.id else conversation.user_low
    notifications.notify(db, recipient_id, 'new_message', event_key=str(message.id),
                         data={'conversation_id': conversation.id, 'message_id': message.id})
    db.add(RealtimeEvent(user_id=recipient_id, event='new_message', data={
        'conversation_id': conversation.id, 'message_id': message.id}))
    if commit:
        db.commit()
        db.refresh(message)
    return message


def list_messages(db: Session, user: User, conversation_id: str,
                  before_id: int | None, page: int, limit: int):
    _member(db, conversation_id, user.id)
    query = select(Message).where(Message.conversation_id == conversation_id)
    if before_id is not None:
        query = query.where(Message.id < before_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(db.scalars(query.order_by(Message.id.desc()).limit(limit)))
    incoming = [item for item in items if item.sender_id != user.id and item.deleted_at is None]
    if incoming:
        seen = set(db.scalars(select(MessageRead.message_id).where(
            MessageRead.user_id == user.id, MessageRead.message_id.in_([m.id for m in incoming]))))
        db.add_all([MessageRead(message_id=m.id, user_id=user.id) for m in incoming if m.id not in seen])
        participant = _member(db, conversation_id, user.id, lock=True)
        participant.last_read_at = now()
        db.commit()
    items.reverse()
    return {'items': [_message_view(db, item, user.id) for item in items],
            'total': total, 'page': page, 'limit': limit,
            'next_before_id': items[0].id if items else None}


def create_message(db: Session, user: User, conversation_id: str, content: str):
    try:
        item = send_message(db, user, conversation_id, content)
    except IntegrityError:
        db.rollback()
        fail(429, 'MESSAGE_RATE_LIMIT_EXCEEDED')
    return {'message': _message_view(db, item, user.id)}


def edit_message(db: Session, user: User, conversation_id: str, message_id: int, content: str):
    _member(db, conversation_id, user.id, lock=True)
    item = db.scalar(select(Message).where(Message.id == message_id,
        Message.conversation_id == conversation_id).with_for_update())
    if not item:
        fail(404, 'MESSAGE_NOT_FOUND')
    if item.sender_id != user.id:
        fail(403, 'MESSAGE_EDIT_FORBIDDEN')
    if item.deleted_at or item.message_type != 'text':
        fail(409, 'MESSAGE_CANNOT_BE_EDITED')
    if (now() - utc(item.created_at)).total_seconds() > get_settings().message_edit_minutes * 60:
        fail(409, 'MESSAGE_EDIT_WINDOW_EXPIRED')
    if len(content) > get_settings().message_max_characters:
        fail(422, 'MESSAGE_TOO_LONG')
    db.add(MessageRevision(message_id=item.id, previous_content=item.content))
    item.content, item.edited_at = content, now()
    db.commit()
    return {'message': _message_view(db, item, user.id)}


def delete_message(db: Session, user: User, conversation_id: str, message_id: int):
    _member(db, conversation_id, user.id, lock=True)
    item = db.scalar(select(Message).where(Message.id == message_id,
        Message.conversation_id == conversation_id).with_for_update())
    if not item:
        fail(404, 'MESSAGE_NOT_FOUND')
    if item.sender_id != user.id:
        fail(403, 'MESSAGE_DELETE_FORBIDDEN')
    if item.deleted_at:
        return {'message': 'Message supprimé.'}
    if (now() - utc(item.created_at)).total_seconds() > get_settings().message_edit_minutes * 60:
        fail(409, 'MESSAGE_DELETE_WINDOW_EXPIRED')
    item.content, item.deleted_at = None, now()
    attachment = db.scalar(select(MessageAttachment).where(MessageAttachment.message_id == item.id))
    stored_path = None
    if attachment:
        attachment.deleted_at = now()
        if _ATTACHMENT_NAME.fullmatch(attachment.storage_path):
            stored_path = Path(get_settings().private_message_directory) / attachment.storage_path
    db.commit()
    if stored_path:
        try:
            stored_path.unlink(missing_ok=True)
        except OSError:
            import logging
            logging.getLogger(__name__).warning('Private message attachment cleanup failed')
    return {'message': 'Message supprimé.'}


_ATTACHMENT_NAME = re.compile(r'^[a-f0-9-]{36}\.(?:jpg|png|pdf)$')


def save_attachment(db: Session, user: User, conversation_id: str, *, content: bytes,
                    mime_type: str, extension: str, filename: str, caption: str | None):
    conversation = db.scalar(select(Conversation).where(
        Conversation.id == conversation_id).with_for_update())
    if not conversation:
        fail(404, 'CONVERSATION_NOT_FOUND')
    _member(db, conversation_id, user.id, lock=True)
    if conversation.status != 'active':
        fail(409, 'CONVERSATION_CLOSED')
    _consume_quota(db, user)
    settings = get_settings()
    stored = uid() + extension
    if not _ATTACHMENT_NAME.fullmatch(stored):
        fail(500, 'ATTACHMENT_KEY_INVALID')
    path = Path(settings.private_message_directory) / stored
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
    except OSError:
        path.unlink(missing_ok=True)
        fail(503, 'FILE_STORAGE_UNAVAILABLE')
    try:
        item = Message(conversation_id=conversation_id, sender_id=user.id,
                       content=caption, message_type='image' if mime_type.startswith('image/') else 'document')
        db.add(item)
        db.flush()
        attachment = MessageAttachment(message_id=item.id, original_filename=filename[:255],
            stored_filename=stored, storage_path=stored, mime_type=mime_type,
            file_size=len(content))
        db.add(attachment)
        conversation.last_message_at = now()
        recipient_id = conversation.user_high if conversation.user_low == user.id else conversation.user_low
        notifications.notify(db, recipient_id, 'new_message', event_key=str(item.id),
                             data={'conversation_id': conversation_id, 'message_id': item.id})
        db.add(RealtimeEvent(user_id=recipient_id, event='new_message', data={
            'conversation_id': conversation_id, 'message_id': item.id}))
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    return {'message': _message_view(db, item, user.id)}


def attachment_path(db: Session, user: User, conversation_id: str, attachment_id: str):
    _member(db, conversation_id, user.id)
    attachment = db.scalar(select(MessageAttachment).join(Message).where(
        MessageAttachment.id == attachment_id, Message.conversation_id == conversation_id,
        MessageAttachment.deleted_at.is_(None), Message.deleted_at.is_(None)))
    if not attachment or not _ATTACHMENT_NAME.fullmatch(attachment.storage_path):
        fail(404, 'ATTACHMENT_NOT_FOUND')
    path = Path(get_settings().private_message_directory) / attachment.storage_path
    if not path.is_file():
        fail(404, 'ATTACHMENT_NOT_FOUND')
    return attachment, path


def list_notifications(db: Session, user: User, page: int, limit: int, unread_only=False):
    return notifications.list_notifications(db, user, page, limit, unread_only)


def preferences_view(db: Session, user: User):
    item = db.scalar(select(NotificationPreferences).where(NotificationPreferences.user_id == user.id))
    return notifications.preferences(db, user.id)
