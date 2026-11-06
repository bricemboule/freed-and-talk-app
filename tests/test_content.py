import pytest
from pathlib import Path
from types import SimpleNamespace
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.modules.administration.models import AdminAuditLog
from sqlalchemy import select, func
from app.modules.auth.models.entities import Role, User
from app.modules.content import services
from app.modules.content.schemas import ArticleWrite, ResourceWrite


@pytest.fixture
def content_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        role = Role(id=3, code='admin', name='Administrateur')
        admin = User(fullname='Admin', email='admin@content.test', password_hash='x', role=role,
                     email_verified=True, is_active=True)
        db.add_all([role, admin]); db.commit()
        yield db, admin
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_article_publication_is_explicit_and_soft_delete(content_db):
    db, admin = content_db
    draft = services.save_article(db, admin, ArticleWrite(
        slug='article-officiel', title='Article officiel'))
    assert services.list_articles(db, 1, 20)['total'] == 0
    with pytest.raises(HTTPException) as error:
        services.get_article(db, draft['slug'])
    assert error.value.status_code == 404
    published = services.save_article(db, admin, ArticleWrite(
        slug='article-officiel', title='Article officiel', excerpt='Résumé fourni',
        body='Texte officiel fourni', is_published=True), draft['id'])
    assert services.get_article(db, published['slug'])['body'] == 'Texte officiel fourni'
    services.delete_article(db, admin, draft['id'])
    assert services.list_articles(db, 1, 20)['total'] == 0
    assert db.scalar(select(func.count()).select_from(AdminAuditLog)) == 3


def test_resources_are_public_only_after_publication_and_filter_by_type(content_db):
    db, admin = content_db
    item = services.save_resource(db, admin, ResourceWrite(
        resource_type='guide', title='Guide test', url='https://example.org/guide'))
    assert services.list_resources(db, 1, 20)['total'] == 0
    published = services.save_resource(db, admin, ResourceWrite(
        resource_type='guide', title='Guide test', description='Guide',
        url='https://example.org/guide', is_published=True), item['id'])
    assert services.get_resource(db, published['id'])['url'] == 'https://example.org/guide'
    assert services.list_resources(db, 1, 20, resource_type='video')['total'] == 0
    assert services.list_resources(db, 1, 20, resource_type='guide')['total'] == 1


def test_resource_urls_reject_embedded_credentials():
    with pytest.raises(ValidationError):
        ResourceWrite(resource_type='pdf', title='Document', url='https://user:secret@example.org/file.pdf')


def test_private_resource_file_is_served_only_after_publication(content_db, tmp_path, monkeypatch):
    db, admin = content_db
    monkeypatch.setattr(services, 'get_settings', lambda: SimpleNamespace(
        private_resource_directory=str(tmp_path / 'private')))
    draft = services.save_resource(db, admin, ResourceWrite(
        resource_type='pdf', title='Guide', url=None))
    stored = services.save_resource_file(db, admin, draft['id'], content=b'%PDF-test',
        mime_type='application/pdf', extension='.pdf', filename='guide.pdf')
    with pytest.raises(HTTPException):
        services.public_resource_file(db, draft['id'])
    published = services.save_resource(db, admin, ResourceWrite(
        resource_type='pdf', title='Guide', url=None, is_published=True), draft['id'])
    item, path = services.public_resource_file(db, published['id'])
    assert path.is_file() and (path.stat().st_mode & 0o777) == 0o600
    assert item.file_name == 'guide.pdf'
    services.delete_resource(db, admin, published['id'])
    assert not path.exists()
