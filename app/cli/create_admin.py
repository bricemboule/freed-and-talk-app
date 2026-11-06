"""Créer un premier administrateur depuis un terminal de confiance."""
import argparse
from getpass import getpass

from pydantic import ValidationError
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import password_hash
from app.modules.auth.models.entities import Role, User, now
from app.modules.auth.schemas.contracts import RegisterRequest
from app.modules.auth.services.logic import event, get_user, normalize


def main():
    parser = argparse.ArgumentParser(description='Créer un administrateur FREE & TALK')
    parser.add_argument('--email', required=True)
    parser.add_argument('--fullname', required=True)
    args = parser.parse_args()
    password = getpass('Mot de passe (au moins 8 caractères) : ')
    confirmation = getpass('Confirmer le mot de passe : ')
    if password != confirmation:
        parser.exit(1, 'Les mots de passe ne correspondent pas.\n')
    try:
        body = RegisterRequest(fullname=args.fullname, email=args.email, password=password)
    except ValidationError:
        parser.exit(1, 'Nom, email ou longueur du mot de passe invalide.\n')
    with SessionLocal() as db:
        if get_user(db, str(body.email)):
            parser.exit(1, 'Cette adresse possède déjà un compte ; aucun rôle modifié.\n')
        role = db.scalar(select(Role).where(Role.code == 'admin', Role.is_active.is_(True)))
        if not role:
            parser.exit(1, 'Rôle administrateur absent : appliquer les migrations.\n')
        user = User(fullname=body.fullname, email=normalize(str(body.email)),
                    password_hash=password_hash(password), role_id=role.id,
                    email_verified=True, email_verified_at=now())
        db.add(user)
        db.flush()
        event(db, user.id, 'ADMIN_CREATED_BY_CLI')
        db.commit()
    print('Administrateur créé. La connexion reste protégée par le code OTP email.')


if __name__ == '__main__':
    main()
