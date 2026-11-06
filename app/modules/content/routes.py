from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.database import get_db
from app.modules.auth.api.routes import require_role
from app.modules.auth.models.entities import User
from . import services
from .schemas import ArticleWrite, ResourceWrite

router = APIRouter()
articles = APIRouter(prefix='/api/articles', tags=['Articles'])
resources = APIRouter(prefix='/api/resources', tags=['Ressources'])
admin_articles = APIRouter(prefix='/api/admin/articles', tags=['Administration des contenus'])
admin_resources = APIRouter(prefix='/api/admin/resources', tags=['Administration des contenus'])
Db = Annotated[Session, Depends(get_db)]
Admin = Annotated[User, Depends(require_role('admin'))]


@articles.get('')
def get_articles(db: Db, page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100)):
    return services.list_articles(db, page, limit)


@articles.get('/{slug}')
def get_article(slug: str, db: Db):
    return services.get_article(db, slug)


@admin_articles.post('', status_code=201)
def create_article(body: ArticleWrite, admin: Admin, db: Db):
    return services.save_article(db, admin, body)


@admin_articles.put('/{article_id}')
def update_article(article_id: str, body: ArticleWrite, admin: Admin, db: Db):
    return services.save_article(db, admin, body, article_id)


@admin_articles.delete('/{article_id}')
def remove_article(article_id: str, admin: Admin, db: Db):
    return services.delete_article(db, admin, article_id)


@resources.get('')
def get_resources(db: Db, page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100),
                  resource_type: Literal['article', 'video', 'audio', 'pdf', 'guide'] | None = None):
    return services.list_resources(db, page, limit, resource_type)


@resources.get('/{resource_id}')
def get_resource(resource_id: str, db: Db):
    return services.get_resource(db, resource_id)


@resources.get('/{resource_id}/file')
def download_resource_file(resource_id: str, db: Db):
    item, path = services.public_resource_file(db, resource_id)
    return FileResponse(path, media_type=item.mime_type, filename=item.file_name,
                        headers={'X-Content-Type-Options': 'nosniff'})


@admin_resources.post('', status_code=201)
def create_resource(body: ResourceWrite, admin: Admin, db: Db):
    return services.save_resource(db, admin, body)


@admin_resources.post('/{resource_id}/file')
async def upload_resource_file(resource_id: str, admin: Admin, db: Db, file: UploadFile = File(...)):
    maximum = get_settings().resource_max_bytes
    try:
        content = await file.read(maximum + 1)
    finally:
        await file.close()
    if not content:
        from app.modules.auth.services.logic import fail
        fail(400, 'EMPTY_FILE')
    if len(content) > maximum:
        from app.modules.auth.services.logic import fail
        fail(413, 'FILE_TOO_LARGE')
    extension, mime_type = _detect_resource_file(content)
    name = (file.filename or 'ressource').replace('\\', '/').rsplit('/', 1)[-1]
    name = ''.join(ch for ch in name if ch.isprintable()).strip()[:255] or 'ressource'
    return await run_in_threadpool(services.save_resource_file, db, admin, resource_id,
                                   content=content, mime_type=mime_type,
                                   extension=extension, filename=name)


def _detect_resource_file(data: bytes):
    from app.modules.auth.services.logic import fail
    if data.startswith(b'%PDF-'):
        from io import BytesIO
        from pypdf import PdfReader
        try:
            reader = PdfReader(BytesIO(data), strict=True)
            if reader.is_encrypted or not reader.pages:
                fail(400, 'DOCUMENT_INVALID')
        except Exception as exc:
            from fastapi import HTTPException
            if isinstance(exc, HTTPException):
                raise
            fail(400, 'DOCUMENT_INVALID')
        return '.pdf', 'application/pdf'
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WAVE':
        return '.wav', 'audio/wav'
    if data.startswith(b'ID3') or (len(data) >= 2 and data[0] == 0xff and data[1] & 0xe0 == 0xe0):
        return '.mp3', 'audio/mpeg'
    if data.startswith(b'OggS'):
        return '.ogg', 'audio/ogg'
    if data.startswith(b'fLaC'):
        return '.flac', 'audio/flac'
    if len(data) >= 12 and data[4:8] == b'ftyp':
        return '.mp4', 'video/mp4'
    if data.startswith(b'\x1a\x45\xdf\xa3'):
        return '.webm', 'video/webm'
    fail(415, 'FILE_TYPE_NOT_ALLOWED')


@admin_resources.put('/{resource_id}')
def update_resource(resource_id: str, body: ResourceWrite, admin: Admin, db: Db):
    return services.save_resource(db, admin, body, resource_id)


@admin_resources.delete('/{resource_id}')
def remove_resource(resource_id: str, admin: Admin, db: Db):
    return services.delete_resource(db, admin, resource_id)


router.include_router(articles)
router.include_router(resources)
router.include_router(admin_articles)
router.include_router(admin_resources)
