# Où placer les images (static)

Les templates et scripts utilisent les chemins suivants. Placez vos fichiers dans les dossiers indiqués.

## Structure

| Fichier à placer | Dossier | Utilisé dans |
|------------------|--------|--------------|
| **1.png** (photo profil / avatar par défaut) | `personnel/static/avatar/` | Header, Profil, Paiements, Accès |
| **2.png** (avatar secondaire) | `personnel/static/avatar/` | Accès (liste membres) |
| **logo_smartclub.png** | `personnel/static/avatar/` | Accès (logo) |
| **favicon.ico** | `personnel/static/images/` | Base (favicon de l’onglet) |

## Chemins utilisés dans le projet

- **base.html** : `{% static 'images/favicon.ico' %}`
- **include/header.html** : `{% static 'avatar/1.png' %}` (photo utilisateur)
- **profil.html** : `{% static 'avatar/1.png' %}`
- **paiements.html** : `{% static 'avatar/1.png' %}` (photo client)
- **acces.html** + **script_acces.js** : `avatar/1.png`, `avatar/2.png`, `avatar/logo_smartclub.png`

Tant que les fichiers ne sont pas présents, les balises `<img>` utilisent un `onerror` qui affiche un placeholder (cercle coloré avec initiales ou icône).
