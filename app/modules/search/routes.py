from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from . import services

router = APIRouter(prefix='/api/search', tags=['Recherche'])
Db = Annotated[Session, Depends(get_db)]


@router.get('')
def global_search(db: Db, q: str = Query(min_length=2, max_length=120),
                  type: Literal['psychologist', 'article', 'resource'] | None = None,
                  country: str | None = Query(default=None, max_length=100),
                  city: str | None = Query(default=None, max_length=100),
                  specialty: str | None = Query(default=None, max_length=160),
                  language: str | None = Query(default=None, max_length=80),
                  online: bool | None = None, availability: bool | None = None,
                  page: int = Query(1, ge=1, le=100), limit: int = Query(20, ge=1, le=100)):
    return services.search(db, q=q, kind=type, country=country, city=city, specialty=specialty,
                           language=language, online=online, availability=availability,
                           page=page, limit=limit)
