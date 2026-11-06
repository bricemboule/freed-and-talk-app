from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.orm import Session

from app.modules.appointments.models import Availability
from app.modules.content.models import Article, Resource
from app.modules.psychologists import services as psychologist_services
from app.modules.psychologists.models import PsychologistProfile
from app.modules.auth.models.entities import Role, User


def _pattern(value: str) -> str:
    escaped = value.strip().replace('!', '!!').replace('%', '!%').replace('_', '!_')
    return f'%{escaped}%'


def search(db: Session, *, q: str, kind: str | None = None, country: str | None = None,
           city: str | None = None, specialty: str | None = None, language: str | None = None,
           online: bool | None = None, availability: bool | None = None, page: int = 1, limit: int = 20):
    if len(q.strip()) < 2:
        from app.modules.auth.services.logic import fail
        fail(422, 'SEARCH_QUERY_TOO_SHORT')
    pattern = _pattern(q)
    prefix = f"{q.strip().replace('!', '!!').replace('%', '!%').replace('_', '!_')}%"
    take = page * limit
    collected: list[dict] = []
    total = 0

    if kind in (None, 'psychologist'):
        psy_query = select(PsychologistProfile, User).join(
            User, User.id == PsychologistProfile.user_id).join(Role, Role.id == User.role_id)
        psy_query = psy_query.where(*psychologist_services.publication_conditions(), or_(
            User.fullname.ilike(pattern, escape='!'),
            PsychologistProfile.professional_title.ilike(pattern, escape='!'),
            PsychologistProfile.specialty.ilike(pattern, escape='!'),
            PsychologistProfile.bio.ilike(pattern, escape='!')))
        for column, value in ((User.country, country), (User.city, city), (PsychologistProfile.specialty, specialty)):
            if value:
                psy_query = psy_query.where(column == value)
        if language:
            psy_query = psy_query.where(psychologist_services.json_has(db, PsychologistProfile.languages, language))
        if online is not None:
            has_online = psychologist_services.json_has(db, PsychologistProfile.consultation_modes, 'online')
            psy_query = psy_query.where(has_online if online else ~has_online)
        if availability is not None:
            has_schedule = exists(select(Availability.id).where(
                Availability.psychologist_id == PsychologistProfile.id, Availability.is_active.is_(True)))
            psy_query = psy_query.where(has_schedule if availability else ~has_schedule)
        total += db.scalar(select(func.count()).select_from(psy_query.subquery())) or 0
        rank = case((User.fullname.ilike(q.strip(), escape='!'), 0),
                    (User.fullname.ilike(prefix, escape='!'), 1), else_=2)
        psy_rows = db.execute(psy_query.order_by(rank, User.fullname, PsychologistProfile.id).limit(take)).all()
        for profile, user in psy_rows:
            view = psychologist_services.public_view(profile, user, detailed=True)
            collected.append({'type': 'psychologist', 'id': profile.id, 'title': user.fullname,
                              'summary': profile.specialty, 'psychologist': view})

    if kind in (None, 'article'):
        article_query = select(Article).where(Article.is_published.is_(True), Article.deleted_at.is_(None),
            or_(Article.title.ilike(pattern, escape='!'), Article.excerpt.ilike(pattern, escape='!'),
                Article.body.ilike(pattern, escape='!')))
        total += db.scalar(select(func.count()).select_from(article_query.subquery())) or 0
        rank = case((Article.title.ilike(q.strip(), escape='!'), 0),
                    (Article.title.ilike(prefix, escape='!'), 1), else_=2)
        for item in db.scalars(article_query.order_by(rank, Article.title, Article.id).limit(take)):
            collected.append({'type': 'article', 'id': item.id, 'title': item.title,
                              'summary': item.excerpt, 'url': f'/api/articles/{item.slug}'})

    if kind in (None, 'resource'):
        resource_query = select(Resource).where(Resource.is_published.is_(True), Resource.deleted_at.is_(None),
            or_(Resource.title.ilike(pattern, escape='!'), Resource.description.ilike(pattern, escape='!')))
        total += db.scalar(select(func.count()).select_from(resource_query.subquery())) or 0
        rank = case((Resource.title.ilike(q.strip(), escape='!'), 0),
                    (Resource.title.ilike(prefix, escape='!'), 1), else_=2)
        for item in db.scalars(resource_query.order_by(rank, Resource.title, Resource.id).limit(take)):
            collected.append({'type': 'resource', 'id': item.id, 'title': item.title,
                              'summary': item.description, 'resource_type': item.resource_type, 'url': item.url})

    needle = q.strip().casefold()
    collected.sort(key=lambda item: (0 if item['title'].casefold() == needle else
                                    1 if item['title'].casefold().startswith(needle) else 2,
                                    item['title'].casefold(), item['type'], item['id']))
    start = (page - 1) * limit
    return {'items': collected[start:start + limit], 'total': total, 'page': page, 'limit': limit}
