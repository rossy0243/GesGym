# Images et stockage media GesGym

Derniere actualisation : 09/06/2026.

## 1. Objectif

Ce document recense les endroits ou le projet utilise des images et prepare la future configuration Backblaze B2.

La regle de base est simple :

- les fichiers statiques du produit restent dans `static/` et sont servis par WhiteNoise
- les images envoyees par les utilisateurs doivent aller vers un stockage persistant
- Backblaze B2 est prevu pour les medias utilisateurs, mais n'est pas encore bloquant pour l'utilisation actuelle

## 2. Images statiques du produit

Ces fichiers appartiennent au code ou au theme. Ils ne doivent pas etre stockes dans Backblaze B2.

Emplacements principaux :

- `static/avatar/`
- `static/icons/`
- `static/icons/line-icon/`
- `static/images/`

Usages :

- favicon
- logo SmartClub par defaut
- avatars par defaut
- icones PWA de l'espace membre
- images de fallback quand un membre ou une organisation n'a pas d'image propre

Ces fichiers continuent d'etre servis par WhiteNoise apres :

```powershell
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
```

## 3. Medias utilisateurs

Ces champs Django creent ou lisent des fichiers uploades.

| Modele | Champ | Dossier actuel | Usage |
| --- | --- | --- | --- |
| `members.Member` | `photo` | `members/` | photo du membre |
| `organizations.Organization` | `logo` | `organizations/logos/` | logo client / organisation |
| `website.GymWebsite` | `logo` | `website/logos/` | logo du site public d'une salle |

Aujourd'hui, ces champs utilisent le storage local Django configure dans `smartclub/settings.py`.

## 4. Affichages importants

### 4.1 Photos membres

Les photos membres sont affichees ou exposees dans :

- `access/templates/access/acces.html`
- `members/templates/members/member_portal.html`
- `members/templates/members/member_list.html`
- `members/views.py` via `photo_url`
- `pos/views.py` via la recherche de membres

### 4.2 Logos organisation

Les logos organisation sont affiches ou exposes dans :

- `compte/templates/compte/welcome.html`
- `members/templates/members/pre_registration_public.html`
- `members/templates/members/member_portal.html`
- `core/templates/core/settings.html`
- `members/views.py` via `organization_logo_url`

### 4.3 Cartes membres et canvas

La carte membre generee dans `members/templates/members/member_list.html` charge :

- la photo du membre
- le logo de l'organisation
- le QR code genere cote navigateur

Quand les medias seront servis par Backblaze B2, ces URLs devront etre accessibles par le navigateur. Si un domaine personnalise ou CDN est utilise, verifier aussi les regles CORS si le canvas exporte une image PNG.

## 5. QR codes

Les QR codes ne sont pas stockes comme fichiers medias.

Ils sont generes :

- dynamiquement cote serveur pour l'espace membre
- cote navigateur dans certaines vues back-office

Backblaze B2 n'est donc pas necessaire pour les QR codes.

## 6. Etat actuel du stockage

Configuration actuelle :

```text
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DJANGO_SERVE_MEDIA=False par defaut
```

En local, les fichiers sont presents dans `media/`.

En production cloud, il faut eviter de compter sur le disque local pour des fichiers importants. Les images peuvent disparaitre lors d'un redeploiement ou d'un changement d'instance selon l'hebergeur.

## 7. Preparation Backblaze B2

Backblaze B2 sera configure via son interface S3 compatible.

Dependances probables :

```text
django-storages
boto3
```

Variables d'environnement prevues :

```env
B2_BUCKET_NAME=
B2_REGION=
B2_ENDPOINT_URL=
B2_KEY_ID=
B2_APPLICATION_KEY=
B2_CUSTOM_DOMAIN=
```

Regles de securite :

- ne jamais utiliser la Master Application Key dans le projet
- creer une Application Key limitee au bucket
- donner uniquement les droits necessaires : lecture, ecriture, suppression et liste des fichiers du bucket
- ne jamais commiter les secrets
- configurer les secrets dans Render ou dans un `.env` local prive

## 8. Plan de bascule recommande

1. Creer le bucket Backblaze B2.
2. Creer une Application Key limitee au bucket.
3. Ajouter `django-storages` et `boto3` aux dependances.
4. Ajouter la configuration storage conditionnelle dans `smartclub/settings.py`.
5. Ajouter les variables B2 dans `.env.example` sans valeurs secretes.
6. Configurer les variables reelles dans Render.
7. Tester un upload de logo organisation.
8. Tester une photo membre.
9. Verifier l'espace membre et la carte membre.
10. Migrer les fichiers existants du dossier `media/` vers le bucket si necessaire.

## 9. Fichiers existants a migrer plus tard

Au moment de cette actualisation, le dossier local `media/` contient deja :

- des photos membres dans `media/members/`
- un logo organisation dans `media/organizations/logos/`

Ces fichiers devront etre copies dans Backblaze B2 lors de la bascule si on veut conserver les images deja associees aux objets en base.
