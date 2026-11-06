"""Préparer les quatre fiches éditoriales comme brouillons sans contenu inventé."""
from sqlalchemy import select

from app.core.database import SessionLocal
from app.modules.auth.models.entities import Role, User
from app.modules.content.models import Article

ARTICLES = (
    ('depression-afrique-briser-silence-guerir', 'La dépression en Afrique : briser le silence pour guérir.'),
    ('enfant-ne-va-pas-bien-reconnaitre-aider', "Mon enfant ne va pas bien : comment le reconnaître et l'aider ?"),
    ('burn-out-entreprise-travail-brise-humain', "Burn-out en entreprise : quand le travail brise l'humain."),
    ('psychologue-en-ligne-revolution-sante-mentale-afrique',
     'Consulter un psychologue en ligne : une révolution pour la santé mentale en Afrique.'),
)


def main():
    with SessionLocal() as db:
        admin = db.scalar(select(User).join(Role).where(
            Role.code == 'admin', User.is_active.is_(True), Role.is_active.is_(True)).order_by(User.created_at))
        if not admin:
            raise SystemExit('Créez d’abord un compte administrateur.')
        created = 0
        for slug, title in ARTICLES:
            if not db.scalar(select(Article.id).where(Article.slug == slug)):
                db.add(Article(slug=slug, title=title, excerpt='', body='', author_id=admin.id,
                               is_published=False))
                created += 1
        db.commit()
    print(f'{created} brouillon(s) créé(s); aucun article n’a été publié.')


if __name__ == '__main__':
    main()
