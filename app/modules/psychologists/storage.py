"""Stockage local : avatars publics normalisés et justificatifs privés."""
from io import BytesIO
import os
from pathlib import Path
import re
import warnings

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

from app.core.config import get_settings
from app.modules.auth.models.entities import uid
from app.modules.auth.services.logic import fail

IMAGE_TYPES = {'JPEG': ('image/jpeg', '.jpg'), 'PNG': ('image/png', '.png'),
               'WEBP': ('image/webp', '.webp')}
SAFE_KEY = re.compile(r'^[a-f0-9-]{36}\.(?:jpg|png|webp|pdf)$')


def file_path(key: str, *, avatar: bool = False) -> Path:
    if not SAFE_KEY.fullmatch(key):
        fail(404, 'FILE_NOT_FOUND')
    settings = get_settings()
    root = Path(settings.media_directory) / 'avatars' if avatar else Path(settings.private_documents_directory)
    return root / key


def image_content(data: bytes, *, avatar: bool):
    """Décoder l'image entière, puis retirer métadonnées et contenu ajouté."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                allowed = {'JPEG', 'PNG', 'WEBP'} if avatar else {'JPEG', 'PNG'}
                if source.format not in allowed:
                    fail(415, 'FILE_TYPE_NOT_ALLOWED')
                if source.width * source.height > 20_000_000:
                    fail(400, 'IMAGE_DIMENSIONS_TOO_LARGE')
                source.load()
                output = BytesIO()
                # Les avatars sont tous réencodés en WebP, sans métadonnées EXIF.
                target = 'WEBP' if avatar else source.format
                image = source.convert('RGB' if target == 'JPEG' else 'RGBA')
                if avatar:
                    image.thumbnail((1024, 1024))
                image.save(output, format=target)
                mime, extension = IMAGE_TYPES[target]
                return output.getvalue(), mime, extension
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning):
        fail(415, 'FILE_TYPE_NOT_ALLOWED')


def validate_content(data: bytes, *, avatar: bool):
    if not avatar and data.startswith(b'%PDF-'):
        try:
            reader = PdfReader(BytesIO(data), strict=True)
            if reader.is_encrypted or not len(reader.pages):
                fail(400, 'DOCUMENT_INVALID')
        except Exception as exc:
            from fastapi import HTTPException
            if isinstance(exc, HTTPException):
                raise
            fail(400, 'DOCUMENT_INVALID')
        return data, 'application/pdf', '.pdf'
    return image_content(data, avatar=avatar)


async def prepare_upload(file: UploadFile, *, avatar: bool = False):
    settings = get_settings()
    maximum = settings.avatar_max_bytes if avatar else settings.document_max_bytes
    try:
        data = await file.read(maximum + 1)
    finally:
        await file.close()
    if len(data) > maximum:
        fail(413, 'FILE_TOO_LARGE')
    if not data:
        fail(400, 'EMPTY_FILE')
    # Le nom et le Content-Type reçus ne déterminent jamais le format autorisé.
    from starlette.concurrency import run_in_threadpool
    content, mime, extension = await run_in_threadpool(validate_content, data, avatar=avatar)
    if len(content) > maximum:
        fail(413, 'FILE_TOO_LARGE')
    name = (file.filename or 'document').replace('\\', '/').rsplit('/', 1)[-1]
    name = ''.join(char for char in name if char.isprintable()).strip()[:240] or 'document'
    return content, mime, extension, name


def save_file(content: bytes, extension: str, *, avatar: bool = False) -> str:
    key = uid() + extension
    path = file_path(key, avatar=avatar)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
    except OSError:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        fail(503, 'FILE_STORAGE_UNAVAILABLE')
    return key


def remove_file(key: str | None, *, avatar: bool = False):
    if key:
        # Après commit, un échec de nettoyage ne doit pas annuler la réponse.
        try:
            file_path(key, avatar=avatar).unlink(missing_ok=True)
        except OSError:
            import logging
            logging.getLogger(__name__).warning('Stored file cleanup failed')
