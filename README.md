# GesGym

Application Django de gestion de salle de sport.

## Lancement local

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

## Lancement sur le reseau local

Pour tester depuis un telephone sur le meme Wi-Fi sans changer la configuration de production :

```powershell
.\runserver_lan.ps1
```

Le script :

- detecte l'IP locale privee du PC
- ajoute temporairement `127.0.0.1`, `localhost` et cette IP a `DJANGO_ALLOWED_HOSTS`
- demarre Django sur `0.0.0.0:8000`

Ensuite, ouvre depuis le telephone l'URL affichee par le script, par exemple :

```text
http://192.168.1.69:8000
```

Si le telephone ne se connecte toujours pas, verifier le pare-feu Windows et l'absence d'isolation client sur le Wi-Fi.

## Pre-deploiement

Verifier le projet :

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py check --deploy
.\.venv\Scripts\python.exe manage.py test
```

## Variables d'environnement de production

Prendre comme base le fichier `.env.example`.

Variables minimales :

- `DJANGO_ENV=production`
- `DJANGO_DEBUG=False`
- `DJANGO_SECRET_KEY=<secret long et aleatoire>`
- `DJANGO_ALLOWED_HOSTS=ton-domaine.com,www.ton-domaine.com`
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://ton-domaine.com,https://www.ton-domaine.com`
- `DATABASE_URL=postgresql://user:password@host:5432/dbname?sslmode=require`

## Demarrage production

Le depot fournit maintenant :

- `requirements.txt`
- `Procfile`
- `runtime.txt`

Commande web :

```text
gunicorn smartclub.wsgi --log-file - --access-logfile -
```

## Statiques et medias

- Les fichiers statiques sont servis en production par WhiteNoise.
- Lancer `collectstatic` pendant le build :

```powershell
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
```

- Les medias utilisateurs peuvent etre servis directement par Django seulement si `DJANGO_SERVE_MEDIA=True`.
- Pour un deploiement plus solide, preferer un vrai service de medias (Nginx, bucket objet, CDN, etc.).
