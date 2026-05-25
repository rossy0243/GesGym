# GesGym

Application Django de gestion de salle de sport.

## Etat fonctionnel resume

L'application couvre aujourd'hui les blocs suivants :

- gestion multi-tenant par `organisation -> salle`
- navigation et permissions par role
- membres, preinscriptions et abonnements
- POS, caisse et controle d'acces
- messages membres in-app
- rapports standards et rapports personnalises
- coaching
- machines et maintenances
- produits et stock
- RH avec paie evolutive

## Packs SaaS

Le pilotage commercial des fonctionnalites se fait maintenant par `pack` au niveau
de l'organisation.

Packs actuellement prevus :

- `Pack Club` : `MEMBERS`, `SUBSCRIPTIONS`, `POS`, `ACCESS`, `NOTIFICATIONS`, `CORE`
- `Pack Premium` : tout le `Pack Club` + `PRODUCTS`, `RH`, `MACHINES`, `COACHING`

Important :

- le choix du pack est stocke sur `Organization.subscription_pack`
- les modules restent appliques techniquement au niveau de chaque salle via `GymModule`
- une synchronisation automatique propage le pack choisi sur tous les gyms de l'organisation
- les vues continuent de verifier les activations via `module_required(...)`

## Documentation

Les manuels sont maintenant separes :

- [MANUEL_ADMIN_SAAS_GESGYM.md](D:/GesGym/MANUEL_ADMIN_SAAS_GESGYM.md) : administration de la plateforme SaaS
- [MANUEL_CLIENT_GESGYM.md](D:/GesGym/MANUEL_CLIENT_GESGYM.md) : utilisation cote client / salle
- [MANUEL_UTILISATEUR_GESGYM.md](D:/GesGym/MANUEL_UTILISATEUR_GESGYM.md) : page d'orientation vers les deux manuels

## Roles et multi-salle

Roles principaux actuellement exploites :

- `owner`
- `manager`
- `reception`
- `cashier`
- `coach`

Points importants :

- un `owner` peut travailler sur plusieurs salles de la meme organisation
- la salle active est memorisee en session via `current_gym_id`
- les donnees et actions sont filtrees sur la salle active
- un compte staff non-owner est pense pour une seule salle active a la fois
- pour un beta sur 2 salles, le cas bien supporte est : `owner multi-salles`, `staff affecte a une seule salle`
- le `pack` est choisi au niveau organisation puis synchronise sur les salles

## Administration des packs

Depuis l'admin Django :

- une organisation porte un champ `subscription_pack`
- le flux de creation d'un owner/client demande maintenant un `Pack Club` ou `Pack Premium`
- l'enregistrement resynchronise automatiquement les modules de tous les gyms de l'organisation
- des actions admin permettent de basculer une ou plusieurs organisations vers `Pack Club` ou `Pack Premium`

Flux technique :

```text
Organization.subscription_pack
-> get_pack_module_codes(pack)
-> ensure_gym_modules_for_pack(gym, pack)
-> GymModule
-> module_required("CODE")
```

## Module RH

Le module RH couvre maintenant :

- employes RH actifs/inactifs
- presences unitaires et en groupe
- remuneration `journaliere` ou `mensuelle fixe`
- ajustements : `primes`, `avances`, `retenues`
- `heures supplementaires`
- `conges` payes / sans solde / maladie
- workflow bulletin : `brouillon -> verifie -> approuve -> paye`
- generation PDF du bulletin
- cotisations et taxes parametrables par salle
- integration du paiement salaire avec le POS

### Paie RH

Le calcul du bulletin prend en compte :

- base salariale
- conges
- heures supplementaires
- primes
- avances
- retenues
- taxes salarie
- cotisations salarie
- cotisations employeur

Le dashboard RH et les rapports montrent maintenant :

- masse nette
- masse brute
- retenues salarie
- cotisations employeur

## Rapports

Le module Rapports fournit :

- vues `journalier`, `mensuel`, `personnalise`
- exports `CSV` et `XLSX`
- bloc RH mensuel avec lecture `brut / net`
- dataset personnalise `Paie RH`

Le rapport personnalise peut maintenant inclure :

- `transactions`
- `members`
- `access`
- `subscriptions`
- `registers`
- `payroll`

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
.\run_tests.ps1
```

## Tests non interactifs

Pour eviter les problemes de base de test PostgreSQL locale deja creee, le depot
fournit un settings de test dedie base sur SQLite.

```powershell
.\run_tests.ps1
```

Exemples :

```powershell
.\run_tests.ps1 members
.\run_tests.ps1 organizations.tests website.tests
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

Bootstrap admin optionnel :

- `DJANGO_BOOTSTRAP_SUPERUSER_USERNAME=admin-bootstrap`
- `DJANGO_BOOTSTRAP_SUPERUSER_PASSWORD=<mot-de-passe-initial-fort>`
- `DJANGO_BOOTSTRAP_SUPERUSER_EMAIL=admin@example.com`

Important :

- le depot ne contient plus de mot de passe admin code en dur
- ces variables servent uniquement a creer le compte initial s'il n'existe pas
- elles ne reinitialisent pas le mot de passe d'un compte deja cree

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

## Verification recommandee avant beta

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test core.tests --settings=smartclub.settings_test
.\.venv\Scripts\python.exe manage.py test rh.tests --settings=smartclub.settings_test
.\.venv\Scripts\python.exe manage.py test compte.tests --settings=smartclub.settings_test
.\.venv\Scripts\python.exe manage.py test organizations.tests --settings=smartclub.settings_test
```

Ces suites couvrent notamment :

- la separation des acces par role
- le multi-tenant et le changement de salle owner
- la synchronisation des packs organisation -> gyms
- l'isolation des donnees RH
- les KPI et les rapports RH
