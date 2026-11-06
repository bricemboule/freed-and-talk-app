# FREE & TALK — Authentification, profils et rendez-vous

API FastAPI des modules 1 à 3 : **13 endpoints d'authentification, 23 endpoints de profils et de vérification professionnelle, et 27 endpoints de planning et de consultation**, SQLAlchemy 2, MySQL/MariaDB, Alembic, JWT, OTP email et tests automatisés. Les identifiants restent des UUID comme au module 1.

## Prérequis

- Python 3.12+
- MySQL 8+ avec le moteur InnoDB ; SQLite reste disponible pour les tests locaux
- SMTP pour envoyer de vrais emails ; boîte locale disponible sans SMTP
- Redis (requis en production pour le rate limiting distribué)

## Installation locale

```bash
cd free_and_talk
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell : .venv\Scripts\Activate.ps1
pip install -e '.[test]'
cp .env.example .env
```

### Configuration MySQL

Avec un compte administrateur MySQL, créer une base et un utilisateur dédiés (remplacer le mot de passe d'exemple) :

```sql
CREATE DATABASE free_and_talk CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'free_and_talk'@'localhost' IDENTIFIED BY 'remplacer-par-un-mot-de-passe-fort';
GRANT ALL PRIVILEGES ON free_and_talk.* TO 'free_and_talk'@'localhost';
```

Dans `.env`, définir les identifiants correspondants :

```dotenv
DATABASE_URL=mysql+pymysql://free_and_talk:remplacer-par-un-mot-de-passe-fort@127.0.0.1:3306/free_and_talk?charset=utf8mb4
```

Les caractères spéciaux du nom d'utilisateur et du mot de passe doivent être encodés pour une URL (par exemple `@` devient `%40`, `#` devient `%23`). Le pilote [PyMySQL est pris en charge par SQLAlchemy](https://docs.sqlalchemy.org/en/20/dialects/mysql.html#module-sqlalchemy.dialects.mysql.pymysql) ; `charset=utf8mb4` permet les caractères Unicode complets. Les tables doivent utiliser InnoDB pour les transactions, les clés étrangères et les verrouillages de lignes.

Démarrer ensuite avec la boîte email locale :

```bash
python main.py
```

Cette commande applique les migrations, crée les rôles et démarre le serveur sur http://127.0.0.1:8000 (documentation interactive).
Si le port est déjà occupé, utiliser `python main.py --port 8001` et ouvrir http://127.0.0.1:8001.

En production, configurer `APP_ENV=production`, `EMAIL_BACKEND=smtp`, SMTP, Redis et deux secrets forts et distincts. Pour générer un secret :

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Sans `.env` ni variable `DATABASE_URL`, SQLite reste le repli de développement. Pour l'utiliser explicitement : `DATABASE_URL=sqlite:///./dev.sqlite3`. PostgreSQL reste compatible via `postgresql+psycopg://utilisateur:motdepasse@localhost/free_and_talk`.

Pour appliquer les migrations et lancer le serveur séparément :

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

Swagger : http://127.0.0.1:8000/docs

Santé : http://127.0.0.1:8000/health

Changer `DATABASE_URL` crée les tables sur la base choisie lors de la prochaine migration ; cela ne transfère pas les comptes déjà présents dans SQLite.

### Emails en local

Avec `EMAIL_BACKEND=file` (valeur par défaut), chaque email est enregistré dans `.local/mail/*.eml`. Ouvrir le fichier le plus récent pour récupérer le code OTP ; le destinataire et l'objet identifient le parcours. Ces fichiers contiennent des codes sensibles : ils sont exclus du dépôt et créés avec des permissions privées. Supprimer les emails après les essais.

Pour recevoir les emails dans une boîte réelle ou un serveur de développement (Mailpit, MailHog), choisir `EMAIL_BACKEND=smtp` et renseigner `SMTP_HOST`, `SMTP_PORT` et les paramètres associés. Pour un serveur local sans TLS, définir `SMTP_STARTTLS=false`. Un échec d'envoi retourne HTTP 503.

Pour le SSL implicite sur le port 465 :

```dotenv
EMAIL_BACKEND=smtp
SMTP_PORT=465
SMTP_SSL=true
SMTP_STARTTLS=false
```

Renseigner également `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD` et `SMTP_FROM_EMAIL`. Les mots de passe SMTP sont écrits tels quels dans `.env` ; l'encodage `%40` concerne uniquement les mots de passe inclus dans une URL comme `DATABASE_URL`. Le certificat du serveur SMTP est vérifié. Pour STARTTLS sur le port 587, utiliser `SMTP_SSL=false` et `SMTP_STARTTLS=true`. Pour un serveur local sans chiffrement, mettre les deux options à `false`.

Le projet fournit une API. Swagger permet d'exécuter les requêtes ; aucun écran de connexion grand public n'est encore fourni.

## Routes exposées

| Méthode | Route | Description |
|---|---|---|
| POST | `/api/auth/register` | Inscription patient |
| POST | `/api/auth/verify-email` | Vérification email |
| POST | `/api/auth/resend-email-code` | Renvoi email |
| POST | `/api/auth/login` | Mot de passe puis OTP |
| POST | `/api/auth/verify-login-otp` | Vérification OTP / tokens |
| POST | `/api/auth/resend-login-otp` | Renvoi OTP connexion |
| POST | `/api/auth/refresh` | Rotation des tokens |
| POST | `/api/auth/logout` | Révocation de session |
| GET | `/api/auth/me` | Identité authentifiée |
| POST | `/api/auth/forgot-password` | Demande de récupération |
| POST | `/api/auth/verify-reset-code` | Vérification du code reset |
| POST | `/api/auth/reset-password` | Réinitialisation |
| PUT | `/api/users/me/password` | Changement connecté |

## Module 2 : profils et vérification professionnelle

Après mise à jour du code, appliquer `alembic upgrade head`, puis relancer `uvicorn app.main:app --reload`. La migration ajoute les champs de profil aux utilisateurs existants et trois tables professionnelles ; elle conserve les comptes du module 1. `python main.py` applique aussi les migrations au démarrage.

Dans Swagger, terminer la connexion OTP, cliquer sur **Authorize** et coller l'`access_token`. La validation email donne accès au compte ; elle ne valide pas les qualifications professionnelles.

| Méthode | Route | Accès |
|---|---|---|
| GET, PUT | `/api/users/me` | Utilisateur connecté, son propre profil |
| POST, DELETE | `/api/users/me/avatar` | Utilisateur connecté, son propre avatar |
| POST | `/api/auth/register/psychologist` | Public, inscription avec confirmation du mot de passe |
| GET, PUT | `/api/psychologists/me` | Psychologue connecté |
| POST, GET | `/api/psychologists/me/documents` | Psychologue connecté, ses propres documents |
| DELETE | `/api/psychologists/me/documents/{document_id}` | Propriétaire, si document non verrouillé |
| POST | `/api/psychologists/me/submit-verification` | Psychologue connecté |
| GET | `/api/psychologists/me/verification-status` | Psychologue connecté |
| GET | `/api/admin/psychologists/verifications` | Administrateur |
| GET | `/api/admin/psychologists/{psychologist_id}/verification` | Administrateur |
| GET | `/api/admin/psychologists/{psychologist_id}/documents/{document_id}` | Administrateur, téléchargement privé journalisé |
| POST | `/api/admin/psychologists/{psychologist_id}/documents/{document_id}/approve` | Administrateur |
| POST | `/api/admin/psychologists/{psychologist_id}/documents/{document_id}/reject` | Administrateur, motif obligatoire |
| POST | `/api/admin/psychologists/{psychologist_id}/approve` | Administrateur |
| POST | `/api/admin/psychologists/{psychologist_id}/reject` | Administrateur, motif obligatoire |
| POST | `/api/admin/psychologists/{psychologist_id}/suspend` | Administrateur, motif obligatoire |
| POST | `/api/admin/psychologists/{psychologist_id}/reactivate` | Administrateur |
| GET | `/api/psychologists` | Public, annuaire filtré et paginé |
| GET | `/api/psychologists/{psychologist_id}` | Public, uniquement les profils publiables |

### Tester le parcours psychologue

1. Créer le compte avec `/api/auth/register/psychologist` (exemple disponible dans Swagger). Le rôle est imposé côté serveur et le statut initial est `pending_documents`.
2. Vérifier l'email, se connecter et confirmer l'OTP comme au module 1.
3. Compléter le profil et déposer les justificatifs via le champ multipart `file` et `document_type`.
4. Soumettre avec `/api/psychologists/me/submit-verification`.
5. Avec un autre compte administrateur, consulter la file, télécharger les documents et approuver ou rejeter chacun d'eux. La première décision sur un document passe le dossier en `under_review`.
6. Approuver le profil après validation de ses pièces obligatoires. Il devient visible dans l'annuaire.

Pour créer le premier administrateur depuis un terminal de confiance :

```bash
python -m app.cli.create_admin --email admin@votre-domaine.com --fullname "Administrateur"
```

Le mot de passe est demandé sans affichage ni argument de commande. Cette commande crée un nouveau compte dont l'email est considéré comme vérifié par l'opérateur ; elle ne transforme pas un compte existant. La connexion reste protégée par OTP email. Aucune route publique ne permet de créer un administrateur.

### Documents et décisions

Les pièces obligatoires sont **la pièce d'identité et le diplôme** par défaut. La spécification ne fixant pas cette liste, elle est configurable avec `REQUIRED_PROFESSIONAL_DOCUMENTS=identity_document,diploma`. Ajouter `professional_license` ou `professional_registration` selon la politique retenue. Les types `cv` et `other` sont aussi acceptés.

Les profils doivent comporter un titre, une spécialité, l'expérience, une présentation, au moins une langue et un mode de consultation, ainsi que le pays et la ville du compte. Le numéro d'inscription professionnelle est facultatif tant que la politique de vérification ne l'exige pas.

Un dossier soumis est verrouillé pour les modifications professionnelles et les ajouts/suppressions de documents pendant l'examen. Un document approuvé ne peut pas être supprimé. Après rejet du dossier, le psychologue peut supprimer/remplacer ses pièces rejetées, corriger puis soumettre de nouveau. Les motifs restent dans l'historique.

Les changements de titre, spécialité, expérience ou numéro d'inscription après approbation ramènent le dossier à `pending_documents`, repassent les pièces approuvées à `pending` et masquent immédiatement le profil. Les changements de présentation, langues ou modes de consultation sont historisés sans retirer l'approbation. L'ajout d'un document à un dossier approuvé relance aussi la soumission. Les profils suspendus ne peuvent pas modifier leur dossier professionnel.

L'annuaire exige le statut `approved`, un compte et un rôle actifs, et un email vérifié. Il ne retourne ni coordonnées privées ni justificatifs ni motifs administratifs. Les services du module 3 recontrôlent ces conditions avant réservation et confirmation, avec des lectures verrouillées.

Filtres publics : `country`, `city`, `specialty`, `language`, `consultation_mode`, `page`, `page_size` (1 à 100), `sort` (`name`, `experience`, `newest`). Filtres administratifs : `status`, `country`, `city`, `submitted_from`, `submitted_to`, `page`, `page_size`. Sans statut, la file administrative montre les dossiers soumis ou en cours d'examen.

### Stockage des fichiers

```dotenv
MEDIA_DIRECTORY=.local/media
PRIVATE_DOCUMENTS_DIRECTORY=.local/private/documents
AVATAR_MAX_BYTES=5242880
DOCUMENT_MAX_BYTES=5242880
REQUIRED_PROFESSIONAL_DOCUMENTS=identity_document,diploma
```

Les avatars JPEG/PNG/WebP sont décodés et réencodés en WebP sans métadonnées, avec une dimension maximale de 1024 pixels. Ils sont servis via `/media/avatars/{nom_aleatoire}`. Les documents acceptent les PDF valides non chiffrés et les images JPEG/PNG décodables. Le MIME déclaré et le nom fourni par le client ne servent pas à déterminer le type réel. Les noms de stockage sont aléatoires ; les images sont normalisées et les documents PDF sont servis en pièces jointes aux seuls administrateurs.

Les justificatifs ne sont jamais exposés via une route statique. Ne pas publier le répertoire privé dans un reverse proxy ; prévoir un volume persistant et des sauvegardes de la base **et** des fichiers. Cette implémentation utilise le disque local, pas un stockage objet, et n'intègre pas d'antivirus.

## Module 3 : disponibilités, rendez-vous et consultations

Appliquer `alembic upgrade head` après mise à jour du code. La migration `2e3b635c9ee6` ajoute les horaires, indisponibilités, rendez-vous, historiques, consultations, réservations et notifications. La migration additive `8ab7130c5f22` ajoute le type et les routes REST des consultations sans modifier les comptes ni les dossiers professionnels.

### Routes du module 3

| Méthode | Route | Accès |
|---|---|---|
| GET, POST | `/api/psychologists/me/availability` | Psychologue, ses horaires |
| PUT, DELETE | `/api/psychologists/me/availability/{availability_id}` | Propriétaire |
| GET, POST | `/api/psychologists/me/unavailability` | Psychologue, ses exceptions |
| PUT, DELETE | `/api/psychologists/me/unavailability/{unavailability_id}` | Propriétaire |
| GET | `/api/psychologists/{psychologist_id}/available-slots` | Public, professionnel approuvé et actif |
| GET | `/api/psychologists/{psychologist_id}/availability` | Public, horaires hebdomadaires actifs, sans adresse exacte |
| POST | `/api/appointments` | Patient connecté |
| GET | `/api/appointments` et `/api/appointments/me` | Patient, ses rendez-vous |
| GET | `/api/appointments/{appointment_id}` | Participants ou administrateur |
| PUT | `/api/appointments/{appointment_id}/reschedule` | Patient concerné |
| PATCH | `/api/appointments/{appointment_id}` | Alias de replanification; même validation et règles de conflit |
| POST | `/api/appointments/{appointment_id}/cancel` | Patient concerné |
| GET | `/api/psychologists/me/appointments` | Psychologue, ses rendez-vous |
| POST | `/api/psychologists/me/appointments/{appointment_id}/accept` | Psychologue concerné |
| POST | `/api/appointments/{appointment_id}/accept` | Alias, psychologue concerné |
| POST | `/api/psychologists/me/appointments/{appointment_id}/reject` | Psychologue concerné, motif requis |
| POST | `/api/appointments/{appointment_id}/reject` | Alias, psychologue concerné |
| POST | `/api/appointments/{appointment_id}/complete` | Alias, psychologue concerné |
| POST | `/api/psychologists/me/appointments/{appointment_id}/complete` | Psychologue concerné |
| POST | `/api/psychologists/me/appointments/{appointment_id}/cancel` | Psychologue concerné, motif requis |
| GET | `/api/appointments/{appointment_id}/consultation` | Participants ou administrateur, métadonnées |
| POST | `/api/consultations` | Participant, démarrer une consultation confirmée avec `appointment_id` et `consultation_type` |
| GET | `/api/consultations` | Patient ou psychologue, ses consultations |
| GET | `/api/consultations/{consultation_id}` | Participant du rendez-vous |
| POST | `/api/appointments/{appointment_id}/consultation/start` | Participants uniquement |
| POST | `/api/appointments/{appointment_id}/consultation/end` | Participants uniquement |
| GET | `/api/appointments/{appointment_id}/consultation/access` | Participants uniquement, fenêtre d'accès |
| GET | `/api/admin/appointments` | Administrateur |
| GET | `/api/admin/appointments/{appointment_id}` | Administrateur, métadonnées et historique |
| POST | `/api/admin/appointments/{appointment_id}/cancel` | Administrateur, motif requis |
| GET | `/api/admin/consultations` | Administrateur, métadonnées uniquement |

Les types de consultation sont `video`, `audio`, `phone` et `in_person`. Les consultations restent liées à un rendez-vous confirmé et les nouvelles routes REST sont des alias de cette ressource. Les types `audio` et `phone` utilisent la salle de visioconférence configurée; ils ne fournissent pas une intégration téléphonique RTC autonome.

La date de naissance est facultative à l'inscription d'un psychologue et dans le profil privé. Les dates futures sont refusées; la donnée n'est jamais incluse dans l'annuaire public. La migration `b1a77d5c30e4` ajoute le champ nullable sans altérer les comptes existants.

### Horaires et fuseaux

```dotenv
APPOINTMENT_TIMEZONE=Africa/Douala
CONSULTATION_DEFAULT_MINUTES=45
CONSULTATION_ALLOWED_MINUTES=30,45,60
APPOINTMENT_SLOT_STEP_MINUTES=15
APPOINTMENT_MAX_ADVANCE_DAYS=180
APPOINTMENT_CANCEL_NOTICE_MINUTES=60
CONSULTATION_EARLY_JOIN_MINUTES=15
CONSULTATION_ACCESS_GRACE_MINUTES=15
MEETING_TOKEN_MINUTES=5
```

Les horaires hebdomadaires utilisent le fuseau de la plateforme (`Africa/Douala` par défaut). Les jours vont de 0 (dimanche) à 6 (samedi). Une plage ne traverse pas minuit et les heures sont à la minute, par exemple `09:00`. Les plages actives ne peuvent pas se chevaucher, même si leurs modes diffèrent. Un psychologue doit être approuvé et actif pour publier une plage active. Les plages inactives peuvent être préparées avant approbation.

Les dates avec offset sont converties en UTC ; les dates sans offset sont interprétées dans le fuseau configuré. Les heures locales ambiguës ou inexistantes lors des changements d'heure sont refusées. Les réponses portent un offset UTC explicite. Les créneaux publics indiquent aussi le fuseau utilisé. Configurer ce fuseau avant la mise en service : changer sa valeur réinterprète les horaires hebdomadaires existants.

Exemple de disponibilité :

```json
{
  "day_of_week": 1,
  "start_time": "09:00",
  "end_time": "12:00",
  "consultation_mode": "online",
  "is_active": true
}
```

Pour le présentiel, choisir `in_person` et renseigner `location` (cabinet ou lieu professionnel). Le lieu n'apparaît pas dans les créneaux publics ; il est communiqué au patient après confirmation du rendez-vous. Le mode doit aussi être autorisé dans le profil professionnel.

### Tester une réservation

1. Avec un psychologue approuvé, créer une disponibilité via `/api/psychologists/me/availability`.
2. Consulter `/api/psychologists/{id}/available-slots?date=YYYY-MM-DD&consultation_mode=online&duration=45` pour une date future correspondant à son horaire.
3. Se connecter avec un patient, puis envoyer à `POST /api/appointments` le `psychologist_id`, le `start_datetime` copié du créneau et le `consultation_mode`. `duration` est facultatif (45 minutes par défaut), `reason` et `notes` sont facultatifs et privés.
4. Le rendez-vous devient `pending` et bloque immédiatement le créneau. Sa consultation publique ne réservait rien ; le backend refait tous les contrôles dans la transaction de création.
5. Avec le psychologue concerné, appeler `/api/psychologists/me/appointments/{id}/accept`. Le rendez-vous devient `confirmed` et sa consultation est créée.
6. Dans la fenêtre autorisée, les participants peuvent démarrer puis terminer la consultation. Le psychologue peut aussi utiliser `/complete` pour une consultation en cours, ou une consultation confirmée dont l'heure de fin planifiée est passée.

Le statut professionnel, l'email vérifié, le compte et le rôle actifs sont contrôlés avant réservation, confirmation, démarrage et délivrance de l'accès vidéo. Les créneaux passés, bloqués, hors grille, hors horizon et les chevauchements du patient ou du psychologue sont refusés.

### Reports, annulations et conflits

Un report depuis `pending` ou `confirmed` passe à `reschedule_requested` et nécessite une nouvelle confirmation. Le nouveau créneau est réservé et l'ancien libéré dans la même transaction ; l'ancien horaire reste dans l'historique. Une tentative vers un créneau occupé conserve intégralement le rendez-vous d'origine. Une consultation précédente est invalidée, puis sa salle est renouvelée à la nouvelle confirmation. Le refus d'un report ferme la demande et libère son créneau ; il ne restaure pas automatiquement l'ancien horaire.

Les patients peuvent annuler ou reporter jusqu'au délai configuré (60 minutes avant le début par défaut). Les psychologues et administrateurs peuvent annuler les demandes ou rendez-vous confirmés sans ce délai patient. Aucun participant ne peut annuler un rendez-vous en cours ou réactiver un rendez-vous terminé. Le motif est obligatoire pour une annulation, un refus ou un report. Chaque changement est historisé avec son auteur.

Modifier/supprimer une disponibilité utilisée par un rendez-vous futur actif, ou ajouter une indisponibilité qui le recouvre, retourne 409. Traiter d'abord les rendez-vous concernés ; les demandes en attente sont protégées comme les confirmations. Le statut `no_show` est réservé dans les modèles ; aucun absent n'est déclaré automatiquement sans règle d'observation métier.

La réservation verrouille le patient puis le profil professionnel et contrôle les chevauchements avec des lectures verrouillées. La table `appointment_reservations` réserve chaque minute pour les deux ressources, avec une contrainte unique `(resource_kind, resource_id, minute)`. Cette contrainte assure l'exclusion sur MySQL/MariaDB et PostgreSQL. Les rendez-vous ont une précision d'une minute et une durée autorisée entière. Les conflits concurrents retournent 409. SQLite reste réservé aux essais locaux ; les courses sont testées sur MariaDB.

Les listes patient/psychologue acceptent `status`, `date_from`, `date_to`, `page`, `page_size`. La liste administrative des rendez-vous ajoute `patient_id`, `psychologist_id`, `consultation_mode`. Celle des consultations accepte `status`, les identifiants et les dates. Les dates de filtre sont des instants ISO 8601, avec bornes inclusives. `page_size` est limité à 100. Les créations et reports utilisent aussi le rate limiting Redis du projet lorsqu'il est configuré.

### Visioconférence Jitsi protégée par JWT

Le serveur Jitsi doit être déployé et configuré séparément avec authentification JWT **obligatoire**, vérification de la salle et sans accès anonyme aux salles. Une simple URL publique `meet.jit.si` ne suffit pas à valider les jetons de cette application. Consulter la [configuration officielle Jitsi Docker/JWT](https://github.com/jitsi/handbook/blob/master/docs/devops-guide/docker.md#authentication-using-jwt-tokens), notamment `ENABLE_AUTH`, `AUTH_TYPE`, `JWT_APP_ID`, `JWT_APP_SECRET` et `JWT_ALLOW_EMPTY`.

Dans `.env` de l'API :

```dotenv
JITSI_BASE_URL=https://video.votre-domaine.com
JITSI_APP_ID=free-and-talk
JITSI_JWT_SECRET=un-secret-distinct-et-aleatoire-d-au-moins-32-caracteres
JITSI_JWT_SUBJECT=meet.jitsi
JITSI_JWT_AUDIENCE=free-and-talk
```

L'identifiant, le secret, le domaine XMPP (`sub`) et l'audience doivent correspondre au serveur Jitsi. Les jetons sont signés en HS256, liés à une seule salle aléatoire et à l'identité du participant ; leur durée est de 5 minutes par défaut, sans dépasser la fin de la fenêtre d'accès. L'accès API commence 15 minutes avant le rendez-vous et cesse 15 minutes après sa fin prévue, ou dès sa clôture/annulation.

L'endpoint `/consultation/access` retourne `meeting_url` et `access_token` séparément, avec `Cache-Control: private, no-store`. Transmettre le jeton au client Jitsi (paramètre `jwt` de son intégration), sans le journaliser. Les autres routes, y compris administratives, ne retournent ni salle, ni URL privée, ni jeton. L'API ne donne pas aux administrateurs le droit de rejoindre une consultation.

Sans configuration Jitsi complète, les rendez-vous peuvent être organisés mais `/consultation/access` retourne **503 `MEETING_PROVIDER_NOT_CONFIGURED`**, sans inventer de lien sécurisé. Les tests vérifient les droits et les claims JWT avec une configuration de test ; une session vidéo réelle nécessite le serveur configuré. La fermeture côté API bloque les nouveaux jetons ; la révocation d'un jeton déjà émis ou la déconnexion d'une session Jitsi déjà ouverte nécessitent une politique côté fournisseur.

### Notifications durables

Les changements de rendez-vous créent deux notifications en base, une pour chaque partie, dans la même transaction que l'historique. Une panne SMTP ne supprime pas le rendez-vous. Aucun motif médical, note privée ou lien vidéo n'est envoyé dans l'email ; son objet reste **FREE & TALK**.

Lancer le worker dans un second terminal (ou comme service lors du déploiement) :

```bash
python -m app.cli.dispatch_notifications --watch
```

Pour un seul lot : `python -m app.cli.dispatch_notifications --limit 100`. Le worker utilise le transport SMTP/SSL ou la boîte fichier du projet, réessaie avec un délai croissant et marque `failed` après 5 tentatives. Les lignes sont verrouillées avec `SKIP LOCKED` sur MySQL/MariaDB et PostgreSQL pour permettre plusieurs workers. Un arrêt après l'envoi SMTP mais avant le commit peut provoquer un doublon lors de la reprise : la livraison est au moins une fois. Surveiller les lignes `failed` et relancer explicitement leur traitement après correction du transport. Le worker doit fonctionner pour que les emails en attente soient effectivement envoyés.

## Test des flux

```bash
pytest -q
```

La suite couvre l'authentification, les profils, la validation des fichiers, les permissions, les décisions, les filtres publics et la conservation des comptes pendant une migration. Elle utilise SQLite par défaut. Pour rejouer les parcours sur MySQL/MariaDB, définir `TEST_DATABASE_URL` vers une base de test **dédiée et vide**, dont le nom commence par `free_and_talk_test_`. Les tables de cette base sont créées puis supprimées par les fixtures ; ne jamais y mettre de données à conserver. La base du `.env` n'est pas utilisée pour les comptes de test.

1. `register` envoie un OTP de vérification email.
2. `verify-email` confirme l'email.
3. `login` retourne `challenge_id` (aucun JWT à cette étape).
4. `verify-login-otp` retourne `access_token` et `refresh_token`.
5. `GET /api/auth/me` requiert `Authorization: Bearer <access_token>`.
6. `refresh` retourne de nouveaux tokens et révoque le précédent.
7. `logout` révoque la session.
8. `forgot-password` + `verify-reset-code` + `reset-password` permet de restaurer l'accès.

## Architecture

- `app/core` : configuration, SQLAlchemy, JWT et rate limiting.
- `app/modules/auth/models` : modèles de données.
- `app/modules/auth/schemas` : schémas de requêtes/réponses.
- `app/modules/auth/services` : logique OTP, tokens, sessions, emailing.
- `app/modules/auth/api` : routes et dépendances.
- `alembic/versions` : migration initiale et insertion des rôles.
- `tests` : tests de parcours principaux.
- `app/modules/psychologists` : modèles, contrats, stockage privé et services des profils/vérifications ; les routes délèguent les règles métier aux services.
- `app/cli/create_admin.py` : création contrôlée du premier administrateur.
- `app/modules/appointments` : horaires, réservations, consultations, intégration Jitsi et outbox.
- `app/cli/dispatch_notifications.py` : worker commun des notifications, rendez-vous et rappels.

## Ce qui est couvert / reste à finaliser

**Vérifications effectuées :** parcours des modules 1 à 3 sur SQLite et MariaDB 10.11, dont deux scénarios de réservation simultanée sur MariaDB dans une base temporaire, migrations, cohérence modèles/schéma, protection des documents et contrôles HTTP du serveur. La migration de la base applicative conserve les comptes existants. Les opérations de vérification verrouillent le profil avec `SELECT ... FOR UPDATE` sur MySQL/InnoDB et PostgreSQL ; les tests de parcours ne remplacent pas les essais de concurrence et de charge.

**À faire avant mise en production :**
- Configurer SMTP réel, Redis et HTTPS derrière un reverse proxy.
- Étendre aux OTP l'outbox avec reprise après échec et surveiller les messages en échec.
- Compléter les tests de parcours MySQL/MariaDB par des essais de concurrence OTP/refresh et décisions, d'échecs SMTP/Redis, et de montée en charge.
- Définir et vérifier la politique de mots de passe compromis et les durées de rétention.
- Ajouter des protections supplémentaires contre les abus distribués (le rate limiting fourni est un socle fixe par IP et clé, non une défense anti-abus exhaustive).
- Vérifier les politiques de sécurité de déploiement, logs, gestion de secrets, CSP/cookies si utilisés et gouvernance des comptes admin.
- En production, le serveur refusera les secrets faibles, l'absence de Redis/SMTP et l'utilisation de SQLite, mais cela **ne dispense pas** d'un audit de sécurité.

**Note :** la vérification email et le reset acceptent ici email + OTP (conforme au programme). Le `challenge_id` protège spécifiquement le processus de connexion.

## Messagerie et notifications

La migration additive `c91a7f02d31e` ajoute les conversations, messages, pièces jointes privées, notifications, préférences et journaux d'envoi. Appliquer `alembic upgrade head` après mise à jour du code; les migrations précédentes et les données existantes sont conservées.

Les patients peuvent ouvrir une conversation avec un psychologue approuvé. Un psychologue peut répondre aux patients avec lesquels une conversation existe. Les administrateurs ne disposent pas d'un accès général au contenu des échanges. Les messages et pièces jointes sont visibles par les participants seulement; les pièces jointes acceptées sont PDF, JPEG et PNG, avec une limite définie par `MESSAGE_ATTACHMENT_MAX_BYTES`. Le contenu des messages n'est pas écrit dans les journaux d'application.

Routes ajoutées :

- `GET/POST /api/conversations`
- `GET/POST /api/conversations/{conversation_id}/messages`
- `PUT/DELETE /api/conversations/{conversation_id}/messages/{message_id}`
- `POST /api/conversations/{conversation_id}/messages/attachment`
- `GET /api/conversations/{conversation_id}/attachments/{attachment_id}`
- `GET /api/notifications` et `GET /api/notifications/unread`
- `POST /api/notifications/{notification_id}/read` et `POST /api/notifications/read-all`
- `GET/PUT /api/notifications/preferences`

Les messages sont conservés dans l'historique paginé. Leur auteur peut les corriger ou supprimer pendant la fenêtre `MESSAGE_EDIT_MINUTES`. Les emails de nouveau message sont désactivés par défaut et peuvent être activés dans les préférences. Les événements de rendez-vous et les décisions de vérification créent aussi des notifications en application.

Le worker existant traite maintenant les deux files de notifications. Lancer `python -m app.cli.dispatch_notifications --watch` pour expédier les emails et créer les rappels de rendez-vous.

## Articles et ressources

Les migrations additives jusqu'à `95be1a3715ca` ajoutent un catalogue d'articles, de ressources, d'avis et de fichiers privés. Appliquer `alembic upgrade head`; les tables et données précédentes sont conservées. Les articles et ressources restent en brouillon tant qu'un administrateur ne les publie pas. Les quatre articles mentionnés dans le programme ne contiennent pas de texte intégral dans les documents fournis. Après avoir appliqué les migrations et créé un administrateur, `python -m app.cli.seed_article_titles` ajoute leurs titres comme brouillons vides; il ne publie aucun texte inventé.

Les routes publiques sont `GET /api/articles`, `GET /api/articles/{slug}`, `GET /api/resources` et `GET /api/resources/{resource_id}`. Les routes d'administration fournissent `POST`, `PUT` et `DELETE` sous `/api/admin/articles` et `/api/admin/resources`. Un administrateur peut ajouter un PDF, audio MP3/WAV/OGG/FLAC ou vidéo MP4/WebM via `POST /api/admin/resources/{id}/file`; la route publique `/api/resources/{id}/file` ne sert le fichier qu'après publication. Le stockage local privé est configuré par `PRIVATE_RESOURCE_DIRECTORY` avec la limite `RESOURCE_MAX_BYTES`.

## Avis, recherche et administration

Un patient peut déposer un avis seulement pour un rendez-vous terminé avec le psychologue concerné. Les avis commencent en attente de modération; seuls les avis approuvés sont publics, sans nom ni identifiant patient. Les routes sont `POST/GET /api/psychologists/{id}/reviews`, `PUT/DELETE /api/reviews/{id}` et les routes de modération sous `/api/admin/reviews`.

`GET /api/search` recherche dans les psychologues approuvés, articles et ressources publiés. Les filtres `country`, `city`, `specialty`, `language` et `online` s'appliquent aux psychologues. `availability=true` indique que le psychologue a au moins un horaire actif configuré; l'API ne promet pas qu'un créneau particulier reste libre.

Les administrateurs disposent aussi de `/api/admin/dashboard`, `/api/admin/users`, `/api/admin/psychologists` et `/api/admin/reports`. Ces agrégats sont calculés depuis les données présentes, sans indicateurs fictifs.

Les publications et décisions de modération sont consignées dans `admin_audit_logs`, sans recopier les textes des articles ou avis. L'historique est consultable à `GET /api/admin/audit-log`.

## Tarifs et paiements

Chaque psychologue peut renseigner `consultation_fee` (montant entier) et `consultation_currency` (code devise à trois lettres, `XAF` par défaut) avec `PUT /api/psychologists/me`. Le montant est copié dans le rendez-vous lors de la réservation et ne peut pas être remplacé par celui envoyé par le patient. La migration `6d2c90ab11f7` ajoute ce tarif et les tables de paiement.

Le patient peut créer une demande avec `POST /api/payments` en fournissant `appointment_id`, `provider` (`orange_money`, `mtn_momo`, `mobile_money` ou `card`) et `idempotency_key`. Le rendez-vous doit être confirmé. `GET /api/payments`, `GET /api/payments/{id}` et `GET /api/admin/payments` consultent les demandes selon leurs permissions. L'adaptateur actuel est en mode test et laisse les paiements à `pending`; il ne débite rien et aucune action client ne peut marquer une demande `paid`. L'intégration réelle demande les identifiants et callbacks signés du prestataire avant d'activer un débit.
