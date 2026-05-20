# Etat du projet GesGym

Version de reference: etat du depot au 17/05/2026.

## 1. Niveau actuel

Le projet a deja franchi une etape importante de structuration produit, surtout sur le module Coaching.

Les grands acquis a retenir:

- les formules d'abonnement portent maintenant des droits coaching
- le membre dispose d'un espace mobile plus utile, avec activation de son accompagnement
- le coach dispose d'un portail mobile dedie
- le manager dispose d'une vue de pilotage coaching plus operationnelle
- le systeme trace les suivis, les feedbacks et les alertes prioritaires
- le manuel utilisateur a ete remis a jour en fonction de l'etat reel du produit

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
- suivi des membres sans coach
- suivi des membres sans suivi
- gestion des retards de premier contact
- gestion des relances en retard
- lecture des feedbacks sensibles
- file manager `A traiter`

## 4. Regles metier deja posees

- les droits coaching viennent de la formule active du membre
- un membre peut activer lui-meme ses droits si sa formule l'autorise
- un membre garde un coach referent actif a la fois dans ce flux
- un membre garde un programme groupe actif a la fois dans ce flux
- un programme groupe a une capacite et ne peut plus etre rejoint s'il est plein
- un feedback est sensible si la note globale est inferieure ou egale a 2, ou si le membre demande un recontact
- les alertes de premier contact se basent sur la date reelle d'affectation au coach

## 5. Documentation deja alignee

Fichier a jour:

- [MANUEL_UTILISATEUR_GESGYM.md](D:\GesGym\MANUEL_UTILISATEUR_GESGYM.md)

Le manuel a ete mis a jour sur:

- roles et acces
- formules et droits coaching
- espace membre
- module coaching
- routines manager et coach

## 6. Pistes logiques pour la suite

Les prochaines evolutions les plus naturelles sont:

- historique d'entree/sortie des programmes groupes
- notifications internes automatiques pour coach et manager
- dashboard manager plus analytique
- recommandations intelligentes de coach/programme selon objectif membre
- gestion plus fine des changements de coach ou de programme
- monetisation plus poussee des offres coaching

## 7. Point de reprise recommande

Si on reprend le projet plus tard, le meilleur point de reprise est:

1. relire ce fichier
2. relire le chapitre coaching du manuel
3. choisir un axe unique pour le prochain sprint:
   - automatisation
   - analytics
   - monetisation
   - experience membre

Ce fichier sert de memoire projet rapide pour repartir sans perdre le niveau atteint.
