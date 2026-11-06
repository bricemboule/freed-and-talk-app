# État d'implémentation

Mis à jour le 2026-11-01 à partir des routes OpenAPI et des fichiers présents. « Terminé » signifie que l'élément existe dans le dépôt; la colonne Tests précise séparément la validation observée.

| Module | Modèles | Migrations | Schémas | Services | Endpoints | Tests | Documentation |
|---|---|---|---|---|---|---|---|
| Authentification | Terminé | Terminé (`a409de1d7d59`) | Terminé | Terminé | Terminé (13 opérations) | Tests présents; parcours HTTP complets restent à exécuter car `TestClient` bloque à l'ouverture | Partiel (README) |
| Utilisateurs | Terminé (modèle User partagé) | Terminé (`b1a77d5c30e4` pour date de naissance optionnelle) | Terminé | Terminé | Terminé (profil, avatar, mot de passe) | Présents dans tests de profils/auth | README et OpenAPI |
| Psychologues | Terminé | Terminé (`b73d2a814e60`, champ DOB `b1a77d5c30e4`) | Terminé | Terminé | Terminé (inscription, dossier, revue, annuaire) | Présents; DOB vérifiée par test unitaire | README et OpenAPI |
| Disponibilités et rendez-vous | Terminé | Terminé (`2e3b635c9ee6`) | Terminé | Terminé | Terminé, aliases `/api/appointments` et disponibilité publique ajoutés | Couverture métier existante; tests HTTP bloqués par `TestClient` | README et OpenAPI |
| Consultations | Terminé (attachées aux rendez-vous) | Terminé (`8ab7130c5f22`) | Terminé | Terminé | Terminé : chemins REST ajoutés en alias sur les rendez-vous | 2 tests de service participants; tests HTTP restent bloqués par TestClient | README et OpenAPI; audio/phone via salle en ligne |
| Messagerie | Terminé | Terminé (`c91a7f02d31e`) | Terminé | Terminé | Terminé pour conversations, texte, édition/suppression et pièces jointes | 4 tests de service dédiés réussis; parcours HTTP complet reste à exécuter | README et OpenAPI |
| Notifications générales | Terminé | Terminé (`c91a7f02d31e`) | Terminé | Terminé | Terminé pour liste, non-lues, lecture, suppression et préférences | 4 tests de service dédiés réussis; migration fraîche validée | README et OpenAPI |
| Articles | Terminé | Terminé (`da5c103e9a12`) | Terminé | Terminé | Terminé (CRUD public/admin) | 3 tests de service réussis | README, OpenAPI et script de brouillons |
| Ressources | Terminé | Terminé (`da5c103e9a12`, `95be1a3715ca`) | Terminé | Terminé | Terminé (catalogue, URL, dépôt privé et lecture après publication) | 4 tests de service et migration réussis | README, `.env.example` et OpenAPI |
| Avis | Terminé | Terminé (`ef8a24d507c1`) | Terminé | Terminé | Terminé (patient, public, modération admin) | 2 tests de service réussis | OpenAPI; règles décrites dans le modèle |
| Tarifs / paiements | Terminé | Terminé (`6d2c90ab11f7`) | Terminé | Terminé | Terminé en mode test (3 endpoints patients + liste admin) | 3 tests de service réussis | README et OpenAPI; prestataires réels non configurés |
| Administration générale | Terminé pour les données existantes | Journal d'audit (`4f2c880c3940`) | Terminé | Terminé | Dashboard, utilisateurs, psychologues, rendez-vous, consultations, paiements, rapports et audit présents | tests services et filtres | README et OpenAPI |
| Recherche globale | Réutilise les modèles existants | Aucune migration propre | Terminé | Terminé | Terminé | 2 tests de service réussis | OpenAPI |

## Phase active

La phase 0 est documentée dans [audit-existing-backend.md](audit-existing-backend.md). La phase 1 était déjà implémentée dans les modules `psychologists` et `auth`. Les alias rendez-vous/consultations, messagerie/notifications, articles/ressources, avis, recherche, administration et demandes de paiement en mode test sont raccordés. Dix-neuf tests de services ciblés et treize tests runtime (dont les migrations) passent; `compileall`, `pip check` et le rendu SQL hors-ligne des migrations passent. Les tests HTTP complets restent à relancer dans un environnement où `TestClient.__enter__` ne bloque pas. Les fournisseurs de paiement réels et le serveur Jitsi ne sont pas configurés; le contenu intégral des quatre articles n'a pas été fourni.

## Choix de base de données

Le projet conserve la configuration MySQL/MariaDB et les migrations présentes. La demande antérieure de l'utilisateur pour MySQL prévaut sur la suggestion PostgreSQL du document joint. Les migrations existantes ne sont pas supprimées et la base configurée n'est pas réinitialisée.
