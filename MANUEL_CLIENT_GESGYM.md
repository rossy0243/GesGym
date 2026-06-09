# Manuel Client GesGym

Version du manuel : basee sur l'application actuellement presente dans ce depot.

Derniere actualisation : 09/06/2026.

## 1. Presentation generale

GesGym est une application de gestion de salle de sport pensee pour le pilotage quotidien d'une salle ou d'un reseau de salles.

Elle permet de gerer :

- les membres
- les preinscriptions publiques
- les abonnements
- la caisse et les paiements
- le controle d'acces
- les rapports
- les messages membres in-app
- le coaching
- les machines et maintenances
- les ressources humaines
- les produits et le stock

Selon votre offre et votre configuration, certains modules peuvent etre visibles ou non dans votre salle.

## 2. Organisation de l'application

### 2.1 Organisation et salle active

- une organisation peut posseder plusieurs salles
- chaque salle fonctionne comme une unite de travail isolee
- toutes les operations sont filtrees sur la salle active
- un owner peut basculer d'une salle a une autre

### 2.2 Modules disponibles

Les modules visibles dependent :

- de votre role
- de la salle active
- des modules inclus dans l'offre de votre organisation

Exemples de modules :

- membres
- abonnements
- caisse
- acces
- rapports
- coaching
- RH
- machines
- produits
- messages membres

## 3. Profils utilisateurs

Roles principaux :

| Role | Usage principal |
| --- | --- |
| `owner` | proprietaire de l'organisation |
| `manager` | gestion quotidienne et pilotage |
| `reception` | accueil, acces, caisse simple |
| `cashier` | caisse |
| `coach` | portail coach et suivi des membres |
| `member` | espace membre mobile |

Points utiles :

- `owner` peut travailler sur plusieurs salles de son organisation
- `manager` est le role operationnel le plus complet apres `owner`
- `coach` dispose d'un portail dedie et n'utilise pas tout le back-office

## 4. Connexion et demarrage

Apres connexion :

- un administrateur SaaS est redirige vers l'administration
- un owner est redirige vers le choix de la salle ou vers son tableau de bord
- un employe interne est redirige selon son role
- un membre est redirige vers son espace mobile

Bon reflexe :

- verifier la salle active des le debut de session

Gestion des mots de passe temporaires :

- certains comptes peuvent etre crees avec un mot de passe temporaire
- ce mot de passe doit etre communique immediatement a la personne concernee
- a la premiere connexion, l'utilisateur devra definir son propre mot de passe
- tant que ce changement n'est pas fait, l'acces complet a l'application reste limite

Capture de reference :

![Ecran de connexion client](D:/GesGym/docs/screenshots/client-login-final.png)

## 5. Navigation generale

Le menu peut contenir :

- Tableau de bord
- Membres
- Abonnements
- Caisse & paiements
- Controle d'acces
- Rapports
- Coaching
- Machines
- Ressources humaines
- Stock & produits
- Parametres
- Mon profil

La navigation visible s'adapte toujours a votre role et aux modules disponibles dans votre salle.

Exemple d'ecran apres connexion :

![Tableau de bord manager](D:/GesGym/docs/screenshots/manager-dashboard-final.png)

## 6. Utilisation par module

### 6.1 Membres

Le module Membres permet de :

- creer un membre
- consulter sa fiche
- suivre ses acces et paiements recents
- suspendre ou reactiver son acces
- generer et utiliser son QR code

Lors de la creation d'un membre :

- un identifiant utilisateur est genere automatiquement
- un mot de passe temporaire peut etre affiche dans le message de succes
- ce mot de passe doit etre transmis au membre pour sa premiere connexion

### 6.2 Espace membre mobile

Le membre connecte dispose d'un espace mobile dedie avec :

- carte membre
- QR code
- messages recus
- abonnement actif
- historique recent
- consultation des formules

Selon les droits inclus dans sa formule, il peut aussi :

- choisir son coach referent
- rejoindre un programme groupe
- laisser un feedback coaching

### 6.3 Preinscriptions

Chaque salle peut utiliser un lien public de preinscription.

Ce lien permet :

- de collecter les demandes avant inscription
- de confirmer ensuite un prospect en vrai membre

Lors de la confirmation d'une preinscription :

- le membre est cree dans la salle
- un identifiant peut etre genere automatiquement
- un mot de passe temporaire peut etre affiche juste apres confirmation
- il faut le communiquer au membre sans attendre

### 6.4 Abonnements

Le module Abonnements sert a :

- creer des formules
- gerer les prix et durees
- attribuer un abonnement a un membre
- suivre les renouvellements et expirations

Les formules peuvent aussi porter des droits coaching selon l'offre vendue au membre.

### 6.5 Caisse / POS

Le module POS centralise :

- ouverture et fermeture de caisse
- encaissement d'abonnements
- ventes produits
- decaissements
- historique des sessions

Regle cle :

- aucun paiement ne peut etre enregistre sans caisse ouverte

### 6.6 Controle d'acces

Le module Acces permet :

- le scan QR
- le pointage manuel
- l'enregistrement des entrees autorisees ou refusees

Un acces est refuse si le membre :

- est suspendu
- n'a pas d'abonnement actif
- a deja ete enregistre pour la journee

### 6.7 Rapports

Le module Rapports centralise les indicateurs financiers et operationnels utiles au pilotage.

Il permet de lire :

- activite membres
- abonnements
- transactions
- acces
- paie RH si disponible

Des exports `CSV` et `XLSX` sont disponibles selon les ecrans.

### 6.8 Messages membres

Le module `Messages membres` permet d'envoyer des messages visibles dans l'espace mobile des membres.

Les audiences possibles incluent par exemple :

- un membre precis
- tous les membres
- membres actifs
- membres expires
- membres proches de l'expiration

### 6.9 Coaching

Si le module Coaching est actif dans votre offre, il permet :

- la gestion des coaches
- l'affectation de membres
- les programmes groupes
- les suivis
- les feedbacks
- les alertes de priorite

### 6.10 Machines

Le module Machines permet :

- la gestion du parc machine
- le suivi des maintenances
- la lecture des couts associes

### 6.11 RH

Le module RH permet :

- la gestion des employes
- le pointage
- la paie
- les conges, primes, retenues et heures supplementaires

### 6.12 Produits

Le module Produits permet :

- la creation des produits
- le suivi du stock
- les mouvements d'entree et sortie
- l'alimentation des ventes POS

### 6.13 Parametres

Le module Parametres permet aux owners et managers autorises de gerer :

- les informations de l'organisation
- le logo de l'organisation
- les utilisateurs internes
- les roles
- certaines briques de configuration locale

Pour les utilisateurs internes :

- la creation ou la reinitialisation d'un compte peut produire un mot de passe temporaire
- ce mot de passe doit etre communique au collaborateur concerne
- le collaborateur devra le remplacer a sa prochaine connexion

### 6.14 Images et logos

L'application utilise deux familles d'images :

- les images propres au client : logo de l'organisation, photos des membres, logo du site public de salle
- les images du produit : favicon, logo SmartClub, avatars par defaut, icones PWA

Les images propres au client apparaissent notamment :

- dans l'espace membre mobile
- dans les listes et fiches membres
- sur les cartes membres generees depuis le back-office
- sur les preinscriptions publiques
- dans les parametres de l'organisation

Etat actuel :

- les images uploadables fonctionnent deja en local et en demonstration
- le stockage distant Backblaze B2 est prevu pour rendre ces fichiers persistants en production cloud
- ce point ne bloque pas l'utilisation courante de l'application

## 7. Regles metier importantes

- un membre ne peut avoir qu'un seul abonnement actif a la fois
- un nouvel abonnement remplace l'ancien abonnement actif
- un membre suspendu ne peut pas acceder a la salle
- une seule caisse ouverte est autorisee par salle
- les ventes produits diminuent le stock
- un paiement de salaire ou une maintenance payante cree aussi un mouvement POS associe

## 8. Routines recommandees

### 8.1 Accueil

1. verifier la salle active
2. ouvrir la caisse si necessaire
3. enregistrer les entrees
4. traiter les membres en anomalie

### 8.2 Manager

1. consulter le dashboard
2. verifier les expirations proches
3. suivre la caisse
4. traiter les alertes coaching si le module est actif
5. verifier RH, stock, coaching et machines selon les modules disponibles

### 8.3 Coach

1. ouvrir le portail coach
2. consulter `A traiter maintenant`
3. enregistrer les suivis
4. traiter les relances et feedbacks

## 9. Depannage et questions frequentes

### 9.1 "Je ne vois pas un menu"

Verifier :

- votre role
- la salle active
- les modules inclus dans votre offre

### 9.2 "Un membre ne peut pas entrer"

Verifier :

- son statut
- son abonnement actif
- l'absence de double scan

### 9.3 "Je ne peux pas enregistrer un paiement"

Verifier :

- qu'une caisse est ouverte
- qu'un taux USD-CDF a ete saisi

### 9.4 "Je vois un message, mais pas en toast"

Selon l'ecran utilise, les messages peuvent apparaitre :

- sous forme de toast visuel
- ou sous forme de message affiche directement dans la page

Regle pratique :

- si une action importante vient d'etre faite, lire attentivement le message affiche avant de quitter l'ecran
- c'est particulierement important apres une creation de compte ou une reinitialisation de mot de passe

### 9.5 "Une photo ou un logo n'apparait pas"

Verifier :

- que l'image a bien ete envoyee depuis le formulaire
- que le fichier est bien associe au membre ou a l'organisation
- que l'environnement de production sert correctement les medias

Note :

- les images statiques SmartClub ne dependent pas des medias utilisateurs
- la future configuration Backblaze B2 concernera surtout les photos membres et logos clients
