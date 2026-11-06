from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.auth.models.entities import now, uid

Timestamp = DateTime(timezone=True).with_variant(DATETIME(fsp=6), 'mysql')


class Article(Base):
    __tablename__ = 'articles'
    __table_args__ = (Index('ix_articles_publication', 'is_published', 'published_at'),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    excerpt: Mapped[str] = mapped_column(String(1000), default='')
    body: Mapped[str] = mapped_column(Text, default='')
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    author_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    published_at: Mapped[datetime | None] = mapped_column(Timestamp)
    deleted_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=now, onupdate=now)


class Resource(Base):
    __tablename__ = 'resources'
    __table_args__ = (
        CheckConstraint("resource_type IN ('article','video','audio','pdf','guide')", name='ck_resource_type'),
        Index('ix_resources_publication', 'is_published', 'resource_type', 'created_at'),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    resource_type: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(String(2000), default='')
    url: Mapped[str | None] = mapped_column(String(2000))
    storage_path: Mapped[str | None] = mapped_column(String(100), unique=True, index=True)
    file_name: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int | None] = mapped_column(Integer)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    author_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    deleted_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=now, onupdate=now)
