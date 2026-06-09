# Etat du projet GesGym

Version de reference: etat du depot actualise au 09/06/2026.

## 1. Niveau actuel

Le projet a deja franchi une etape importante de structuration produit, surtout sur les modules Coaching, RH et Reporting.

Les grands acquis a retenir:

- les formules d'abonnement portent maintenant des droits coaching
- le membre dispose d'un espace mobile plus utile, avec activation de son accompagnement
- le coach dispose d'un portail mobile dedie
- le manager dispose d'une vue de pilotage coaching plus operationnelle
- le systeme trace les suivis, les feedbacks et les alertes prioritaires
- le module RH couvre maintenant une vraie base de paie mensuelle
- les taxes et cotisations RH sont parametrables par salle
- les rapports intègrent la lecture RH `brut / net`
- les controles role + multi-tenant ont ete revalidés avant beta
- le manuel utilisateur a ete remis a jour en fonction de l'etat reel du produit
- l'inventaire des images et medias a ete clarifie pour preparer Backblaze B2

## 1.1 Packs SaaS et activation

La logique d'activation des modules a evolue :

- le `pack` est choisi au niveau `Organization`
- les modules restent stockes au niveau `GymModule`
- une synchronisation automatique applique le pack choisi sur tous les gyms de l'organisation
- les verifications runtime continuent de passer par `module_required(...)`

Packs actuellement poses :

- `Pack Club` : `MEMBERS`, `SUBSCRIPTIONS`, `POS`, `ACCESS`, `NOTIFICATIONS`, `CORE`
- `Pack Premium` : `Pack Club` + `PRODUCTS`, `RH`, `MACHINES`, `COACHING`

Valeur produit :

- l'offre commerciale devient lisible
- l'admin SaaS n'a plus a cocher les modules un par un
- un changement de pack peut etre propage proprement sur tout le client

## 1.2 Comptes temporaires et messages applicatifs

Le comportement actuel sur les identifiants temporaires et les messages utilisateur est le suivant :

- les creations et reinitialisations sensibles utilisent des mots de passe temporaires forts et uniques
- le changement de mot de passe a la premiere connexion est force via `force_password_change`
- les mots de passe temporaires sont affiches au moment du succes pour plusieurs flux critiques : owner SaaS, employes internes, membres et confirmations de preinscription
- le flux owner gym de creation ou reinitialisation d'utilisateur interne reste incomplet : le mot de passe y est genere mais n'est pas encore restitue visuellement

Concernant les messages :

- le systeme n'a pas encore un comportement toast parfaitement homogene sur toute l'application
- le back-office principal s'appuie sur un conteneur toast dans le layout principal
- les ecrans d'authentification et le portail membre utilisent encore des messages inline

Implication produit :

- les messages fonctionnent, mais l'experience visuelle n'est pas encore totalement uniformisee
- pour les flux de communication de credentials, il faut se fier au message affiche sur l'ecran de succes prevu par le workflow

## 1.3 Images et stockage media

Le projet utilise aujourd'hui deux familles d'images :

- les fichiers statiques du produit : logos SmartClub, favicon, avatars par defaut, icones PWA
- les medias utilisateurs : photos membres, logos organisations, logos de site public de salle

Etat actuel :

- les statiques restent servis par WhiteNoise apres `collectstatic`
- les medias utilisateurs utilisent encore le storage local Django
- `DJANGO_SERVE_MEDIA=True` peut servir les medias via Django, mais ce n'est pas la cible ideale en production
- Backblaze B2 est identifie comme prochaine solution de stockage persistant des medias

Champs uploadables identifies :

- `Member.photo`
- `Organization.logo`
- `GymWebsite.logo`

Decision de securite :

- ne jamais utiliser ni transmettre la Master Application Key Backblaze dans le chat ou le depot
- creer plus tard une Application Key limitee au bucket de medias GesGym
- injecter les secrets uniquement via Render ou un `.env` local prive

Documentation dediee :

- [docs/MEDIA_STORAGE_GESGYM.md](D:/GesGym/docs/MEDIA_STORAGE_GESGYM.md)

## 2. Sprints deja livres

### Sprint 1 - Fondations Coaching

Livre:

- ajout des droits coaching dans les formules
- modes de coaching: `aucun`, `individuel`, `groupe`, `individuel + groupe`
- niveaux de service: `standard`, `premium`, `intensif`
- exposition de ces droits dans la logique metier et dans le portail membre

Valeur:

- le systeme sait maintenant ce que le membre a reellement achete

### Sprint 2 - Choix membre

Livre:

- le membre peut choisir son coach referent si sa formule l'autorise
- le membre peut rejoindre un programme groupe si sa formule l'autorise
- le choix est direct et visible ensuite cote coaching
- mise en place de la brique `programme groupe`

Valeur:

- le coaching inclus devient concret pour le membre

### Sprint 3 - Espace coach mobile

Livre:

- redirection dediee des comptes `coach`
- portail coach mobile-first
- vues `Accueil`, `Membres`, `Programmes`
- UX/UI rapprochee du portail membre

Valeur:

- le coach a enfin un espace adapte a son usage terrain

### Sprint 4 - Suivi coaching

Livre:

- journal de suivi coaching
- fiche membre cote coach
- type d'action, resume, prochaine action, prochaine date de relance
- historique des suivis

Valeur:

- le coaching devient tracable et mesurable

### Sprint 5 - Vue manager / owner

Livre:

- ecran `Coaches` transforme en vue de pilotage
- suivi des charges
- membres sans suivi
- relances en retard
- enrichissement de la fiche coach

Valeur:

- le manager peut piloter le service coaching plutot que seulement voir une liste

### Sprint 6 - Feedback et qualite

Livre:

- feedback membre sur coach et programme groupe
- notes structurees
- commentaire libre
- demande de recontact
- remontee manager de la satisfaction

Valeur:

- la qualite percue du coaching devient visible

### Sprint 7A - Alertes suivi

Livre:

- alertes `sans suivi`
- alertes `premier contact en retard`
- alertes `suivi ancien`
- alertes `relance en retard`

Valeur:

- reduction du risque de membres oublies

### Sprint 7B - Alertes feedback

Livre:

- detection des `feedbacks sensibles`
- prise en compte des mauvaises notes
- prise en compte des demandes de recontact

Valeur:

- les cas sensibles remontent automatiquement

### Sprint 7C - File de priorites coach / manager

Livre:

- file unifiee `A traiter maintenant` cote coach
- file unifiee `A traiter` cote manager
- priorisation des urgences

Valeur:

- l'equipe sait quoi traiter en premier

### Raffinement operationnel

Livre:

- historique d'affectation coach via une vraie date de debut
- cloture des anciennes affectations lors d'un changement de coach
- recalcul plus juste du `premier contact en retard`

Valeur:

- les alertes se basent sur la vraie vie metier et non sur des approximations

### Sprint RH 1 a 4 - Paie evolutive

Livre:

- remuneration `journaliere` ou `mensuelle fixe`
- bulletin mensuel avec statuts `brouillon`, `verifie`, `approuve`, `paye`
- ajustements de paie : `primes`, `avances`, `retenues`
- `heures supplementaires`
- `conges`
- PDF bulletin
- workflow de validation
- journal d'actions de workflow
- cotisations et taxes parametrables par salle
- integration du paiement de salaire avec le POS

Valeur:

- la RH n'est plus limitee a un simple calcul `jours presents x salaire journalier`
- la paie est exploitable en contexte beta et demonstration client

### Sprint Reporting RH

Livre:

- bloc RH mensuel dans les rapports
- dataset personnalise `Paie RH`
- lecture `masse brute / masse nette` dans les KPI principaux
- scrolls ergonomiques sur les zones longues RH et rapports

Valeur:

- la lecture manager/owner de la paie devient plus claire sans quitter les dashboards et rapports

## 3. Etat fonctionnel actuel par espace

### Espace membre

Disponible:

- connexion membre dediee
- portail mobile
- carte membre et QR code
- messages
- abonnement actif
- affichage des droits coaching
- choix du coach referent
- choix du programme groupe
- feedback sur coach et programme
- mise en avant de la formule `La plus choisie`

### Espace coach

Disponible:

- connexion coach dediee
- portail mobile-first
- portefeuille de membres
- programmes groupes
- priorites du jour
- file `A traiter maintenant`
- saisie de suivis
- historique des suivis

### Espace manager / owner

Disponible:

- pilotage des formules
- pilotage coaching depuis la page `Coaches`
- pilotage RH depuis le dashboard, le dashboard RH et les rapports
- suivi des membres sans coach
- suivi des membres sans suivi
- gestion des retards de premier contact
- gestion des relances en retard
- lecture des feedbacks sensibles
- file manager `A traiter`

### Espace RH

Disponible:

- creation et mise a jour des employes RH
- pointage des presences
- tableau de paie mensuelle
- calcul brut/net
- ajustements, conges, heures sup
- cotisations et taxes
- validation et paiement
- PDF bulletin

## 4. Regles metier deja posees

- les droits coaching viennent de la formule active du membre
- un membre peut activer lui-meme ses droits si sa formule l'autorise
- un membre garde un coach referent actif a la fois dans ce flux
- un membre garde un programme groupe actif a la fois dans ce flux
- un programme groupe a une capacite et ne peut plus etre rejoint s'il est plein
- un feedback est sensible si la note globale est inferieure ou egale a 2, ou si le membre demande un recontact
- les alertes de premier contact se basent sur la date reelle d'affectation au coach
- un owner peut basculer entre plusieurs salles de sa propre organisation
- les donnees metier visibles et modifiables sont filtrees sur la salle active
- un staff non-owner est pense pour travailler sur une seule salle active a la fois
- les cotisations employeur n'abaissent pas le net a payer du salarie
- les taxes et cotisations salarie abaissent le net a payer
- un bulletin paye reste lie a un paiement POS de type `salary`

## 5. Documentation deja alignee

Fichier a jour:

- [MANUEL_ADMIN_SAAS_GESGYM.md](D:/GesGym/MANUEL_ADMIN_SAAS_GESGYM.md)
- [MANUEL_CLIENT_GESGYM.md](D:/GesGym/MANUEL_CLIENT_GESGYM.md)
- [MANUEL_UTILISATEUR_GESGYM.md](D:/GesGym/MANUEL_UTILISATEUR_GESGYM.md)
- [README.md](D:\GesGym\README.md)
- [docs\MEDIA_STORAGE_GESGYM.md](D:\GesGym\docs\MEDIA_STORAGE_GESGYM.md)
- [docs\kpi-test-coverage.md](D:\GesGym\docs\kpi-test-coverage.md)
- [docs\reporting-test-coverage.md](D:\GesGym\docs\reporting-test-coverage.md)
- [static\README_IMAGES.md](D:\GesGym\static\README_IMAGES.md)

Les manuels ont ete mis a jour sur:

- roles et acces
- logique packs organisation / activation modules
- formules et droits coaching
- espace membre
- module coaching
- module RH
- rapports RH
- routines manager et coach
- images, medias utilisateurs et preparation Backblaze B2

## 6. Pistes logiques pour la suite

Les prochaines evolutions les plus naturelles sont:

- historique d'entree/sortie des programmes groupes
- notifications internes automatiques pour coach et manager
- dashboard manager plus analytique
- support propre d'un meme compte staff sur plusieurs salles si ce besoin devient reel
- stockage persistant des medias utilisateurs
- configuration Backblaze B2 avec `django-storages` et `boto3`
- recommandations intelligentes de coach/programme selon objectif membre
- gestion plus fine des changements de coach ou de programme
- monetisation plus poussee des offres coaching
- cotisations/taxes plus formalisees selon le contexte legal du client

## 7. Point de reprise recommande

Si on reprend le projet plus tard, le meilleur point de reprise est:

1. relire ce fichier
2. relire le chapitre coaching du manuel
3. relire le chapitre RH et rapports du manuel
4. choisir un axe unique pour le prochain sprint:
   - automatisation
   - analytics
   - monetisation
   - experience membre
   - industrialisation RH
   - stockage media Backblaze B2

Ce fichier sert de memoire projet rapide pour repartir sans perdre le niveau atteint.
