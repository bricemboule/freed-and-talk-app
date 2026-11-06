"""Services des profils généraux, partagés par les patients et psychologues."""
from sqlalchemy import select
from sqlalchemy.orm import Session, lazyload

from app.modules.auth.models.entities import User
from app.modules.auth.services.logic import event
from . import storage
from .schemas import UserUpdate


def avatar_url(user: User):
    return f'/media/avatars/{user.avatar_path}' if user.avatar_path else None


def user_view(user: User):
    return {'id': user.id, 'fullname': user.fullname, 'email': user.email,
            'phone': user.phone, 'country': user.country, 'city': user.city,
            'date_of_birth': user.date_of_birth,
            'role': user.role.code, 'avatar_url': avatar_url(user),
            'email_verified': user.email_verified, 'is_active': user.is_active}


def locked_user(db: Session, user: User):
    return db.scalar(select(User).options(lazyload(User.role)).where(User.id == user.id).with_for_update())


def update_user(db: Session, user: User, body: UserUpdate):
    user = locked_user(db, user)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(user, key, value)
    event(db, user.id, 'USER_PROFILE_UPDATED')
    db.commit()
    return {'message': 'Profil mis à jour avec succès.', 'user': user_view(user)}


def replace_avatar(db: Session, user: User, upload):
    content, _, extension, _ = upload
    user = locked_user(db, user)
    old = user.avatar_path
    key = storage.save_file(content, extension, avatar=True)
    try:
        user.avatar_path = key
        event(db, user.id, 'AVATAR_UPDATED')
        db.commit()
    except Exception:
        db.rollback()
        storage.remove_file(key, avatar=True)
        raise
    storage.remove_file(old, avatar=True)
    return {'message': 'Photo de profil mise à jour.', 'avatar_url': avatar_url(user)}


def delete_avatar(db: Session, user: User):
    user = locked_user(db, user)
    old = user.avatar_path
    user.avatar_path = None
    event(db, user.id, 'AVATAR_DELETED')
    db.commit()
    storage.remove_file(old, avatar=True)
    return {'message': 'Photo de profil supprimée.'}
