# FREE & TALK — API d'authentification, profils et services

API FastAPI construite avec SQLAlchemy 2, MySQL/MariaDB, Alembic, JWT et OTP email. Elle comprend l'authentification, les profils et vérifications professionnelles, les disponibilités et rendez-vous, la messagerie, les notifications, les articles, les ressources, les avis, la recherche et l'administration. Les identifiants sont des UUID.

## Prérequis

- Python 3.12+
- MySQL 8+ avec le moteur InnoDB ; SQLite reste disponible pour les tests locaux
- Aucun SMTP nécessaire en développement avec `EMAIL_BACKEND=file` ; SMTP configurable pour l'envoi réel
- Redis facultatif en développement et requis en production pour le rate limiting distribué

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

| Méthode | Route                         | Description                |
| ------- | ----------------------------- | -------------------------- |
| POST    | `/api/auth/register`          | Inscription patient        |
| POST    | `/api/auth/verify-email`      | Vérification email         |
| POST    | `/api/auth/resend-email-code` | Renvoi email               |
| POST    | `/api/auth/login`             | Mot de passe puis OTP      |
| POST    | `/api/auth/verify-login-otp`  | Vérification OTP / tokens  |
| POST    | `/api/auth/resend-login-otp`  | Renvoi OTP connexion       |
| POST    | `/api/auth/refresh`           | Rotation des tokens        |
| POST    | `/api/auth/logout`            | Révocation de session      |
| GET     | `/api/auth/me`                | Identité authentifiée      |
| POST    | `/api/auth/forgot-password`   | Demande de récupération    |
| POST    | `/api/auth/verify-reset-code` | Vérification du code reset |
| POST    | `/api/auth/reset-password`    | Réinitialisation           |
| PUT     | `/api/users/me/password`      | Changement connecté        |

## Module 2 : profils et vérification professionnelle

Dans Swagger, terminer la connexion OTP, cliquer sur **Authorize** et coller l'`access_token`. La validation email donne accès au compte ; elle ne valide pas les qualifications professionnelles.

| Méthode      | Route                                                                        | Accès                                                 |
| ------------ | ---------------------------------------------------------------------------- | ----------------------------------------------------- |
| GET, PUT     | `/api/users/me`                                                              | Utilisateur connecté, son propre profil               |
| POST, DELETE | `/api/users/me/avatar`                                                       | Utilisateur connecté, son propre avatar               |
| POST         | `/api/auth/register/psychologist`                                            | Public, inscription avec confirmation du mot de passe |
| GET, PUT     | `/api/psychologists/me`                                                      | Psychologue connecté                                  |
| POST, GET    | `/api/psychologists/me/documents`                                            | Psychologue connecté, ses propres documents           |
| DELETE       | `/api/psychologists/me/documents/{document_id}`                              | Propriétaire, si document non verrouillé              |
| POST         | `/api/psychologists/me/submit-verification`                                  | Psychologue connecté                                  |
| GET          | `/api/psychologists/me/verification-status`                                  | Psychologue connecté                                  |
| GET          | `/api/admin/psychologists/verifications`                                     | Administrateur                                        |
| GET          | `/api/admin/psychologists/{psychologist_id}/verification`                    | Administrateur                                        |
| GET          | `/api/admin/psychologists/{psychologist_id}/documents/{document_id}`         | Administrateur, téléchargement privé journalisé       |
| POST         | `/api/admin/psychologists/{psychologist_id}/documents/{document_id}/approve` | Administrateur                                        |
| POST         | `/api/admin/psychologists/{psychologist_id}/documents/{document_id}/reject`  | Administrateur, motif obligatoire                     |
| POST         | `/api/admin/psychologists/{psychologist_id}/approve`                         | Administrateur                                        |
| POST         | `/api/admin/psychologists/{psychologist_id}/reject`                          | Administrateur, motif obligatoire                     |
| POST         | `/api/admin/psychologists/{psychologist_id}/suspend`                         | Administrateur, motif obligatoire                     |
| POST         | `/api/admin/psychologists/{psychologist_id}/reactivate`                      | Administrateur                                        |
| GET          | `/api/psychologists`                                                         | Public, annuaire filtré et paginé                     |
| GET          | `/api/psychologists/{psychologist_id}`                                       | Public, uniquement les profils publiables             |

### Tester le parcours psychologue

1. Créer le compte avec `/api/auth/register/psychologist` (exemple disponible dans Swagger). Le rôle est imposé côté serveur et le statut initial est `pending_documents`.
2. Vérifier l'email, se connecter et confirmer l'OTP comme au module 1.
3. Compléter le profil et déposer les justificatifs via le champ multipart `file` et `document_type`.
4. Soumettre avec `/api/psychologists/me/submit-verification`.
5. Avec un autre compte administrateur, consulter la file, télécharger les documents et approuver ou rejeter chacun d'eux. La première décision sur un document passe le dossier en `under_review`.
6. Approuver le profil après validation de ses pièces obligatoires. Il devient visible dans l'annuaire.

Pour créer le premier administrateur depuis un terminal:

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
`

## Module 3 : disponibilités, rendez-vous et consultations

La gestion des disponibilités, la réservation, la confirmation, le report et l'annulation des rendez-vous sont dans le périmètre. Le mode présentiel fonctionne sans fournisseur vidéo. Les parcours de consultation en ligne et l'accès Jitsi sont différés : ne pas les considérer comme activés tant qu'un serveur Jitsi compatible n'est pas configuré. Les routes correspondantes restent présentes dans l'API.

### Routes du module 3

| Méthode     | Route                                                          | Accès                                                             |
| ----------- | -------------------------------------------------------------- | ----------------------------------------------------------------- |
| GET, POST   | `/api/psychologists/me/availability`                           | Psychologue, ses horaires                                         |
| PUT, DELETE | `/api/psychologists/me/availability/{availability_id}`         | Propriétaire                                                      |
| GET, POST   | `/api/psychologists/me/unavailability`                         | Psychologue, ses exceptions                                       |
| PUT, DELETE | `/api/psychologists/me/unavailability/{unavailability_id}`     | Propriétaire                                                      |
| GET         | `/api/psychologists/{psychologist_id}/available-slots`         | Public, professionnel approuvé et actif                           |
| GET         | `/api/psychologists/{psychologist_id}/availability`            | Public, horaires hebdomadaires actifs, sans adresse exacte        |
| POST        | `/api/appointments`                                            | Patient connecté                                                  |
| GET         | `/api/appointments` et `/api/appointments/me`                  | Patient, ses rendez-vous                                          |
| GET         | `/api/appointments/{appointment_id}`                           | Participants ou administrateur                                    |
| PUT         | `/api/appointments/{appointment_id}/reschedule`                | Patient concerné                                                  |
| PATCH       | `/api/appointments/{appointment_id}`                           | Alias de replanification; même validation et règles de conflit    |
| POST        | `/api/appointments/{appointment_id}/cancel`                    | Patient concerné                                                  |
| GET         | `/api/psychologists/me/appointments`                           | Psychologue, ses rendez-vous                                      |
| POST        | `/api/psychologists/me/appointments/{appointment_id}/accept`   | Psychologue concerné                                              |
| POST        | `/api/appointments/{appointment_id}/accept`                    | Alias, psychologue concerné                                       |
| POST        | `/api/psychologists/me/appointments/{appointment_id}/reject`   | Psychologue concerné, motif requis                                |
| POST        | `/api/appointments/{appointment_id}/reject`                    | Alias, psychologue concerné                                       |
| POST        | `/api/appointments/{appointment_id}/complete`                  | Alias, psychologue concerné                                       |
| POST        | `/api/psychologists/me/appointments/{appointment_id}/complete` | Psychologue concerné                                              |
| POST        | `/api/psychologists/me/appointments/{appointment_id}/cancel`   | Psychologue concerné, motif requis                                |
| GET         | `/api/appointments/{appointment_id}/consultation`              | Participants ou administrateur, métadonnées                       |
| POST        | `/api/consultations`                                           | Participant, route présente ; usage consultation en ligne différé |
| GET         | `/api/consultations`                                           | Patient ou psychologue ; route présente, module différé           |
| GET         | `/api/consultations/{consultation_id}`                         | Participant ; route présente, module différé                      |
| POST        | `/api/appointments/{appointment_id}/consultation/start`        | Participants ; consultation en ligne différée                     |
| POST        | `/api/appointments/{appointment_id}/consultation/end`          | Participants ; consultation en ligne différée                     |
| GET         | `/api/appointments/{appointment_id}/consultation/access`       | Participants ; accès Jitsi différé                                |
| GET         | `/api/admin/appointments`                                      | Administrateur                                                    |
| GET         | `/api/admin/appointments/{appointment_id}`                     | Administrateur, métadonnées et historique                         |
| POST        | `/api/admin/appointments/{appointment_id}/cancel`              | Administrateur, motif requis                                      |
| GET         | `/api/admin/consultations`                                     | Administrateur, métadonnées uniquement                            |

Les modes enregistrés sont `video`, `audio`, `phone` et `in_person`. Les parcours `video`, `audio` et `phone` sont différés avec l'intégration Jitsi. Le mode `in_person` s'utilise dans le parcours de rendez-vous sans plateforme de visioconférence.

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

### Reports, annulations et conflits

Un report depuis `pending` ou `confirmed` passe à `reschedule_requested` et nécessite une nouvelle confirmation. Le nouveau créneau est réservé et l'ancien libéré dans la même transaction ; l'ancien horaire reste dans l'historique. Une tentative vers un créneau occupé conserve intégralement le rendez-vous d'origine. Une consultation précédente est invalidée, puis sa salle est renouvelée à la nouvelle confirmation. Le refus d'un report ferme la demande et libère son créneau ; il ne restaure pas automatiquement l'ancien horaire.

Les patients peuvent annuler ou reporter jusqu'au délai configuré (60 minutes avant le début par défaut). Les psychologues et administrateurs peuvent annuler les demandes ou rendez-vous confirmés sans ce délai patient. Aucun participant ne peut annuler un rendez-vous en cours ou réactiver un rendez-vous terminé. Le motif est obligatoire pour une annulation, un refus ou un report. Chaque changement est historisé avec son auteur.

Modifier/supprimer une disponibilité utilisée par un rendez-vous futur actif, ou ajouter une indisponibilité qui le recouvre, retourne 409. Traiter d'abord les rendez-vous concernés ; les demandes en attente sont protégées comme les confirmations. Le statut `no_show` est réservé dans les modèles ; aucun absent n'est déclaré automatiquement sans règle d'observation métier.

La réservation verrouille le patient puis le profil professionnel et contrôle les chevauchements avec des lectures verrouillées. La table `appointment_reservations` réserve chaque minute pour les deux ressources, avec une contrainte unique `(resource_kind, resource_id, minute)`. Cette contrainte assure l'exclusion sur MySQL/MariaDB et PostgreSQL. Les rendez-vous ont une précision d'une minute et une durée autorisée entière. Les conflits concurrents retournent 409. SQLite reste réservé aux essais locaux ; les courses sont testées sur MariaDB.

Les listes patient/psychologue acceptent `status`, `date_from`, `date_to`, `page`, `page_size`. La liste administrative des rendez-vous ajoute `patient_id`, `psychologist_id`, `consultation_mode`. Celle des consultations accepte `status`, les identifiants et les dates. Les dates de filtre sont des instants ISO 8601, avec bornes inclusives. `page_size` est limité à 100. Les créations et reports utilisent aussi le rate limiting Redis du projet lorsqu'il est configuré.

### Visioconférence

Cette intégration est hors du périmètre opérationnel actuel

## Messagerie et notifications

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

Les routes publiques sont `GET /api/articles`, `GET /api/articles/{slug}`, `GET /api/resources` et `GET /api/resources/{resource_id}`. Les routes d'administration fournissent `POST`, `PUT` et `DELETE` sous `/api/admin/articles` et `/api/admin/resources`. Un administrateur peut ajouter un PDF, audio MP3/WAV/OGG/FLAC ou vidéo MP4/WebM via `POST /api/admin/resources/{id}/file`; la route publique `/api/resources/{id}/file` ne sert le fichier qu'après publication. Le stockage local privé est configuré par `PRIVATE_RESOURCE_DIRECTORY` avec la limite `RESOURCE_MAX_BYTES`.

## Avis, recherche et administration

Un patient peut déposer un avis seulement pour un rendez-vous terminé avec le psychologue concerné. Les avis commencent en attente de modération; seuls les avis approuvés sont publics, sans nom ni identifiant patient. Les routes sont `POST/GET /api/psychologists/{id}/reviews`, `PUT/DELETE /api/reviews/{id}` et les routes de modération sous `/api/admin/reviews`.

`GET /api/search` recherche dans les psychologues approuvés, articles et ressources publiés. Les filtres `country`, `city`, `specialty`, `language` et `online` s'appliquent aux psychologues. `availability=true` indique que le psychologue a au moins un horaire actif configuré; l'API ne promet pas qu'un créneau particulier reste libre.

Les administrateurs disposent aussi de `/api/admin/dashboard`, `/api/admin/users`, `/api/admin/psychologists` et `/api/admin/reports`. Ces agrégats sont calculés depuis les données présentes, sans indicateurs fictifs.

Les publications et décisions de modération sont consignées dans `admin_audit_logs`, sans recopier les textes des articles ou avis. L'historique est consultable à `GET /api/admin/audit-log`.

## Tarifs et paiements

**Module différé :** les routes ci-dessous sont présentes, mais les paiements ne font pas partie du périmètre opérationnel actuel. Aucun encaissement réel n'est effectué. Le tarif stocké dans le profil ou le rendez-vous ne signifie pas qu'un paiement est disponible.

Chaque psychologue peut renseigner `consultation_fee` (montant entier) et `consultation_currency` (code devise à trois lettres, `XAF` par défaut) avec `PUT /api/psychologists/me`. Le montant est copié dans le rendez-vous lors de la réservation et ne peut pas être remplacé par celui envoyé par le patient. La migration `6d2c90ab11f7` ajoute ce tarif et les tables de paiement.

Le patient peut créer une demande avec `POST /api/payments` en fournissant `appointment_id`, `provider` (`orange_money`, `mtn_momo`, `mobile_money` ou `card`) et `idempotency_key`. Le rendez-vous doit être confirmé. `GET /api/payments`, `GET /api/payments/{id}` et `GET /api/admin/payments` consultent les demandes selon leurs permissions. L'adaptateur actuel est en mode test et laisse les paiements à `pending`; il ne débite rien et aucune action client ne peut marquer une demande `paid`. L'intégration réelle demande les identifiants et callbacks signés du prestataire avant d'activer un débit.
