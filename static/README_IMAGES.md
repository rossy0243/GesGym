# Images statiques GesGym

Derniere actualisation : 09/06/2026.

Ce dossier contient les images statiques du produit. Elles font partie du code applicatif et sont servies par WhiteNoise en production apres `collectstatic`.

Ces fichiers ne sont pas les medias utilisateurs. Les photos membres et logos clients sont documentes dans [../docs/MEDIA_STORAGE_GESGYM.md](../docs/MEDIA_STORAGE_GESGYM.md).

## Structure actuelle

| Dossier | Usage |
| --- | --- |
| `static/avatar/` | avatars par defaut, logo SmartClub de fallback |
| `static/icons/` | icones PWA et icones applicatives |
| `static/icons/line-icon/` | icones graphiques du theme |
| `static/images/` | favicon et logo SmartClub complet |

## Fichiers importants

| Fichier | Usage principal |
| --- | --- |
| `static/avatar/1.png` | avatar par defaut membre/utilisateur |
| `static/avatar/logo_smartclub.png` | logo fallback dans l'espace membre et les cartes |
| `static/images/favicon-smartclub.png` | favicon des pages d'authentification |
| `static/images/smartclub-logo-full.png` | image SEO/Open Graph et logo produit |
| `static/icons/1.png` | icone PWA principale de l'espace membre |

## Regle de maintenance

- ne pas placer les photos membres dans `static/`
- ne pas placer les logos clients dans `static/`
- ne pas supprimer les avatars de fallback sans verifier les templates et scripts
- lancer `collectstatic` apres changement d'image statique en production

## Difference avec les medias utilisateurs

Les medias utilisateurs sont aujourd'hui dans `media/` en local et seront plus tard stockes dans Backblaze B2.

Champs concernes :

- `Member.photo`
- `Organization.logo`
- `GymWebsite.logo`
