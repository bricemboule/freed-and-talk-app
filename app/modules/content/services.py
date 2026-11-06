from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from pathlib import Path
import os
import re
from uuid import uuid4

from app.core.config import get_settings
from app.modules.auth.models.entities import User, now
from app.modules.auth.services.logic import fail, utc
from .models import Article, Resource
from .schemas import ArticleWrite, ResourceWrite


def article_view(item: Article):
    return {'id': item.id, 'slug': item.slug, 'title': item.title, 'excerpt': item.excerpt,
            'body': item.body, 'published_at': utc(item.published_at), 'created_at': utc(item.created_at),
            'updated_at': utc(item.updated_at)}


def resource_view(item: Resource):
    return {'id': item.id, 'resource_type': item.resource_type, 'title': item.title,
            'description': item.description, 'url': item.url,
            'file': ({'filename': item.file_name, 'mime_type': item.mime_type,
                      'file_size': item.file_size, 'download_url': f'/api/resources/{item.id}/file'}
                     if item.storage_path else None), 'created_at': utc(item.created_at),
            'updated_at': utc(item.updated_at)}


def list_articles(db: Session, page: int, limit: int):
    base = select(Article).where(Article.is_published.is_(True), Article.deleted_at.is_(None))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = db.scalars(base.order_by(Article.published_at.desc(), Article.id)
                       .offset((page - 1) * limit).limit(limit))
    return {'items': [article_view(item) for item in items], 'total': total, 'page': page, 'limit': limit}


def get_article(db: Session, slug: str):
    item = db.scalar(select(Article).where(Article.slug == slug,
        Article.is_published.is_(True), Article.deleted_at.is_(None)))
    if not item:
        fail(404, 'ARTICLE_NOT_FOUND')
    return article_view(item)


def save_article(db: Session, admin: User, body: ArticleWrite, article_id: str | None = None):
    from app.modules.administration.services import record_admin_action
    item = db.get(Article, article_id) if article_id else None
    if article_id and not item:
        fail(404, 'ARTICLE_NOT_FOUND')
    if item and item.deleted_at:
        fail(404, 'ARTICLE_NOT_FOUND')
    if item is None:
        item = Article(author_id=admin.id)
        db.add(item)
    previous_published = item.is_published
    for key, value in body.model_dump().items():
        if key == 'is_published' and value and (not body.body.strip() or not body.excerpt.strip()):
            fail(422, 'ARTICLE_CONTENT_REQUIRED')
        setattr(item, key, value)
    if item.is_published and (not previous_published or item.published_at is None):
        item.published_at = now()
    elif not item.is_published:
        item.published_at = None
    try:
        db.flush()
        record_admin_action(db, admin, 'ARTICLE_UPDATED' if article_id else 'ARTICLE_CREATED',
                            'article', item.id, {'is_published': item.is_published})
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409, 'ARTICLE_SLUG_ALREADY_EXISTS')
    return article_view(item)


def delete_article(db: Session, admin: User, article_id: str):
    from app.modules.administration.services import record_admin_action
    item = db.get(Article, article_id)
    if not item or item.deleted_at:
        fail(404, 'ARTICLE_NOT_FOUND')
    item.deleted_at, item.is_published = now(), False
    record_admin_action(db, admin, 'ARTICLE_DELETED', 'article', item.id)
    db.commit()
    return {'message': 'Article supprimé.'}


def list_resources(db: Session, page: int, limit: int, resource_type: str | None = None):
    base = select(Resource).where(Resource.is_published.is_(True), Resource.deleted_at.is_(None))
    if resource_type:
        base = base.where(Resource.resource_type == resource_type)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = db.scalars(base.order_by(Resource.created_at.desc(), Resource.id)
                       .offset((page - 1) * limit).limit(limit))
    return {'items': [resource_view(item) for item in items], 'total': total, 'page': page, 'limit': limit}


def get_resource(db: Session, resource_id: str):
    item = db.scalar(select(Resource).where(Resource.id == resource_id,
        Resource.is_published.is_(True), Resource.deleted_at.is_(None)))
    if not item:
        fail(404, 'RESOURCE_NOT_FOUND')
    return resource_view(item)


def save_resource(db: Session, admin: User, body: ResourceWrite, resource_id: str | None = None):
    from app.modules.administration.services import record_admin_action
    item = db.get(Resource, resource_id) if resource_id else None
    if resource_id and (not item or item.deleted_at):
        fail(404, 'RESOURCE_NOT_FOUND')
    if item is None:
        item = Resource(author_id=admin.id)
        db.add(item)
    for key, value in body.model_dump(mode='json').items():
        setattr(item, key, value)
    if item.is_published and not item.url and not item.storage_path:
        fail(422, 'RESOURCE_TARGET_REQUIRED')
    db.flush()
    record_admin_action(db, admin, 'RESOURCE_UPDATED' if resource_id else 'RESOURCE_CREATED',
                        'resource', item.id, {'resource_type': item.resource_type,
                                              'is_published': item.is_published})
    db.commit()
    return resource_view(item)


def delete_resource(db: Session, admin: User, resource_id: str):
    from app.modules.administration.services import record_admin_action
    item = db.get(Resource, resource_id)
    if not item or item.deleted_at:
        fail(404, 'RESOURCE_NOT_FOUND')
    stored_path = (Path(get_settings().private_resource_directory) / item.storage_path
                   if item.storage_path and _RESOURCE_KEY.fullmatch(item.storage_path) else None)
    item.deleted_at, item.is_published = now(), False
    record_admin_action(db, admin, 'RESOURCE_DELETED', 'resource', item.id)
    db.commit()
    if stored_path:
        try:
            stored_path.unlink(missing_ok=True)
        except OSError:
            import logging
            logging.getLogger(__name__).warning('Private resource cleanup failed')
    return {'message': 'Ressource supprimée.'}


_RESOURCE_KEY = re.compile(r'^[a-f0-9-]{36}\.(?:pdf|mp3|wav|ogg|flac|mp4|webm)$')


def save_resource_file(db: Session, admin: User, resource_id: str, *, content: bytes,
                       mime_type: str, extension: str, filename: str):
    from app.modules.administration.services import record_admin_action
    item = db.scalar(select(Resource).where(Resource.id == resource_id).with_for_update())
    if not item or item.deleted_at:
        fail(404, 'RESOURCE_NOT_FOUND')
    allowed = {'pdf': {'.pdf'}, 'guide': {'.pdf'}, 'audio': {'.mp3', '.wav', '.ogg', '.flac'},
               'video': {'.mp4', '.webm'}}
    if extension not in allowed.get(item.resource_type, set()):
        fail(415, 'RESOURCE_FILE_TYPE_MISMATCH')
    stored = f'{uuid4()}{extension}'
    if not _RESOURCE_KEY.fullmatch(stored):
        fail(500, 'RESOURCE_KEY_INVALID')
    path = Path(get_settings().private_resource_directory) / stored
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
    except OSError:
        path.unlink(missing_ok=True)
        fail(503, 'FILE_STORAGE_UNAVAILABLE')
    old_path = Path(get_settings().private_resource_directory) / item.storage_path if (
        item.storage_path and _RESOURCE_KEY.fullmatch(item.storage_path)) else None
    try:
        item.storage_path, item.file_name, item.mime_type, item.file_size = stored, filename[:255], mime_type, len(content)
        db.flush()
        record_admin_action(db, admin, 'RESOURCE_FILE_UPLOADED', 'resource', item.id,
                            {'mime_type': mime_type, 'file_size': len(content)})
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    if old_path:
        try:
            old_path.unlink(missing_ok=True)
        except OSError:
            import logging
            logging.getLogger(__name__).warning('Previous private resource cleanup failed')
    return resource_view(item)


def public_resource_file(db: Session, resource_id: str):
    item = db.scalar(select(Resource).where(Resource.id == resource_id,
        Resource.is_published.is_(True), Resource.deleted_at.is_(None)))
    if not item or not item.storage_path or not _RESOURCE_KEY.fullmatch(item.storage_path):
        fail(404, 'RESOURCE_FILE_NOT_FOUND')
    path = Path(get_settings().private_resource_directory) / item.storage_path
    if not path.is_file():
        fail(404, 'RESOURCE_FILE_NOT_FOUND')
    return item, path
