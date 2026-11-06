# Audit du backend existant

Date de l'audit : 2026-11-01. Référence fonctionnelle : `programme_endpoint_free_and_talk.txt` fourni avec la demande. Les nombres de cette page comptent les opérations HTTP (une route avec deux méthodes compte deux opérations). La comparaison se fonde sur `app.openapi()` et les modèles et services présents dans le dépôt.

## Architecture actuelle

Le backend est une application FastAPI en Python 3.12. Les modules métier sont organisés dans `app/modules`; les modèles partagent le `Base` SQLAlchemy de `app/core/database.py`. Alembic conserve la chaîne initiale et applique les évolutions sous forme de migrations additives jusqu'au catalogue, aux avis, à l'audit, aux fichiers privés et aux paiements.

La configuration lit `.env` avec Pydantic Settings. La configuration active de ce projet utilise MySQL/MariaDB; SQLite sert aux tests locaux. Le programme de référence mentionne PostgreSQL, mais ce choix ne remplace pas la base déjà configurée ni les migrations existantes.

## Modules présents

- `auth` : inscription et vérification par OTP, connexion avec OTP, sessions et rotation de refresh tokens, déconnexion, récupération/changement de mot de passe, rôles et contrôle des comptes actifs.
- `psychologists` : profil utilisateur, avatar, inscription professionnelle, pièces justificatives privées, soumission et décisions de vérification, historique administratif, annuaire public.
- `appointments` : disponibilités et indisponibilités, créneaux, réservation, annulation et replanification, actions psychologue, consultations liées aux rendez-vous, accès à la réunion et file de notifications par email.
- `communication` : routes HTTP, règles métier, stockage privé de pièces jointes et notifications sont maintenant raccordés; migration additive `c91a7f02d31e`.

Les routes de l'API sont agrégées dans `app/main.py`. Les règles métier sont principalement dans des services, avec les contrôles d'identité dans `app/modules/auth/api/routes.py`.

## Matrice de couverture

| Module du programme | Endpoints prévus | Présents dans OpenAPI | Manquants ou écartés | Statut |
|---|---:|---:|---|---|
| Authentification | 13 | 13 | Aucun endpoint du programme identifié comme manquant | Implémenté; tests existants |
| Utilisateurs | 5 | 5 | Aucun endpoint de profil demandé manquant | Implémenté |
| Psychologues et vérification | 15 | 19 liés au module | Tous les endpoints demandés présents. Ajouts : profil professionnel, téléchargement administrateur et réactivation | Implémenté |
| Disponibilités et rendez-vous | 14 | 34 liés à la planification | `PATCH` est un alias de replanification, avec les mêmes règles métier; les horaires publics masquent les adresses exactes | Endpoints prévus disponibles, avec routes complémentaires |
| Consultations | 3 | 10 routes, dont les 3 chemins REST prévus et les routes imbriquées | Les consultations sont attachées aux rendez-vous; audio/phone utilisent le fournisseur de salle en ligne, sans téléphonie RTC séparée | Routes REST et historiques implémentés |
| Messagerie | 4 dans le programme semaine 3 | 8 | Les routes essentielles sont présentes, avec édition/suppression et dépôt/téléchargement privé en plus | Implémenté; tests de service isolés |
| Notifications | 4 dans le programme semaine 3 | 7 | Préférences et suppression individuelle ajoutées; rappels/événements reliés au worker | Implémenté pour les parcours exposés; tests de service isolés |
| Articles | 5 | 5 | Les quatre contenus officiels restent à fournir; un script prépare leurs brouillons sans les publier | Endpoints et stockage de contenu implémentés |
| Ressources | 5 | 5 | Liens HTTP(S) et fichiers PDF/audio/vidéo privés pris en charge; fichiers accessibles publiquement après publication | Implémenté |
| Avis | 7 | 7 | Éligibilité rendez-vous terminé, anonymat public et modération | Implémenté |
| Paiements | 3 | 3 | Les demandes sont en mode test; intégration prestataires et callbacks signés absents. La liste admin est comptée sous Administration | Endpoints patients implémentés, pas de débit réel |
| Administration générale | 7 | 7 | Liste admin des paiements présente | Terminé pour les endpoints prévus |
| Recherche globale | 1 | 1 | Filtre disponibilité signifie « possède des horaires actifs »; il ne garantit pas qu'un créneau est libre à une date donnée | Implémenté |

Le total demandé est de 86 opérations HTTP comptées par section (les 13 opérations d'authentification incluent le changement de mot de passe; les endpoints communs réutilisés dans plusieurs sections ne sont comptés qu'une fois dans leur ligne). L'OpenAPI expose désormais 117 opérations, dont des alias et actions supplémentaires de gestion, de consultation, d'audit et de pièces jointes.

## Modèles et services réutilisables

Les modèles existants couvrent utilisateurs, rôles, OTP, sessions, jetons, événements de sécurité, profils et documents professionnels, journal de vérification, disponibilités, indisponibilités, rendez-vous, réservations, historique, consultations, paiements, messagerie, notifications, articles, ressources et avis. Les services d'authentification, de stockage sécurisé, de vérification, de réservation, de publication et de modération sont réutilisables.

Le stockage de documents professionnels est privé et les noms physiques sont générés côté serveur. L'annuaire applique les conditions de publication aux psychologues approuvés, actifs et ayant vérifié leur email. Les routes administratives de vérification vérifient le rôle.

## Écarts et points de vigilance

- Le prompt joint demande PostgreSQL, tandis que le projet et les précédentes décisions de l'utilisateur reposent sur MySQL/MariaDB. L'audit conserve MySQL/MariaDB et n'altère pas la base.
- Les consultations restent attachées aux rendez-vous. Les chemins REST prévus sont disponibles; `POST /api/consultations` démarre une consultation existante, créée lors de la confirmation du rendez-vous.
- `PATCH /api/appointments/{id}` est un alias strict de la replanification dédiée, sans mise à jour arbitraire des champs protégés.
- La date de naissance était absente du modèle utilisateur malgré sa mention dans le programme; elle est maintenant facultative et privée.
- Messagerie, contenu et avis ajoutent les migrations additives `c91a7f02d31e`, `da5c103e9a12` et `ef8a24d507c1`. Le rendu SQL hors-ligne et l'installation fraîche sur SQLite sont validés; ces migrations restent à appliquer sur les environnements avant le déploiement du nouveau code.
- La règle tarifaire et la devise sont configurables individuellement par psychologue. Le paiement utilise un instantané du rendez-vous; son adaptateur reste en mode test tant qu'aucun prestataire réel et callback signé ne sont configurés.
- Les ressources acceptent des URL HTTP(S) ou des fichiers privés PDF/audio/vidéo; les tailles et signatures de fichiers sont contrôlées avant stockage.
- `venv/bin/pytest -q` échoue à la collecte car l'exécutable ne résout pas `tests` comme paquet. `venv/bin/python -m pytest --collect-only -q` collecte 77 tests. Les tests de services sans client HTTP et ceux du runtime/migrations passent; l'ouverture des tests HTTP reste bloquée à l'entrée de `TestClient.__enter__`, avant la première requête. Un test minimal avec `FastAPI()` vide reproduit le même blocage; les parcours HTTP complets doivent être relancés dans un environnement où `TestClient` fonctionne.
- Les permissions initiales rendaient `.env` et `dev.sqlite3` lisibles par les autres comptes du système; elles sont maintenant limitées au propriétaire (`0600`). `.env` reste ignoré par Git selon `.gitignore`.
- La commande Git ne reconnaît pas `.git` comme dépôt dans l'environnement fourni. L'état de suivi Git ne peut donc pas être vérifié par cet audit.

## Ordre de travail recommandé

1. Confirmer la couverture de la phase 1 par les tests existants; ne pas la recréer.
2. Harmoniser et documenter les contrats des disponibilités, rendez-vous et consultations sans casser les routes déjà utilisées.
3. Fournir les textes officiels des articles et les paramètres du serveur Jitsi et des prestataires de paiement pour activer ces intégrations; les modes actuels restent explicitement inactifs/test.
4. Exécuter les parcours HTTP et les migrations sur une base MySQL/MariaDB temporaire représentative, sans toucher à la base active.
