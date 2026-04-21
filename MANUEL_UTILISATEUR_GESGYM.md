# Manuel d'utilisation GesGym

Version du manuel: basee sur l'application actuellement presente dans ce depot.

## Sommaire

1. Presentation generale
2. Architecture fonctionnelle de l'application
3. Profils utilisateurs et droits d'acces
4. Premiere connexion et demarrage
5. Navigation generale
6. Utilisation detaillee par module
7. Regles metier importantes
8. Routines de travail recommandees
9. Depannage et questions frequentes
10. Glossaire

## 1. Presentation generale

GesGym est une application de gestion de salle de sport construite autour d'un principe simple:

- une organisation peut posseder plusieurs salles
- chaque salle fonctionne comme une unite de travail isolee
- les menus visibles dependent a la fois du role de l'utilisateur et des modules actives pour la salle

L'application permet de gerer:

- les membres
- les preinscriptions publiques
- les abonnements
- la caisse et les paiements
- le controle d'acces par QR code ou pointage manuel
- les rapports
- les coaches
- les machines et maintenances
- les ressources humaines
- les produits et le stock
- les parametres organisationnels et les utilisateurs internes

## 2. Architecture fonctionnelle de l'application

### 2.1 Organisation > salle > donnees

Le niveau le plus important dans GesGym est la salle active.

- Toutes les donnees metier sont rattachees a une salle.
- Lorsqu'un utilisateur travaille dans une salle, toutes ses operations sont filtrees sur cette salle.
- Un proprietaire d'organisation peut basculer d'une salle a une autre sans quitter son compte.

### 2.2 Modules activables

Une salle peut activer ou desactiver certains modules.

Exemples:

- MEMBERS
- SUBSCRIPTIONS
- POS
- ACCESS
- COACHING
- MACHINES
- RH
- PRODUCTS

Si un module n'est pas active pour la salle, il n'est pas utilisable, meme si le role de l'utilisateur devrait normalement y avoir acces.

### 2.3 Logique de navigation

La navigation visible n'est pas fixe.

Elle depend:

- du role courant
- de la salle active
- des modules actives

Concretement, deux utilisateurs connectes sur la meme salle peuvent voir des menus differents.

## 3. Profils utilisateurs et droits d'acces

L'application utilise principalement les roles suivants:

| Role | Usage principal | Acces principaux |
| --- | --- | --- |
| `owner` | Proprietaire de l'organisation | Tous les modules fonctionnels, changement de salle, parametres organisation |
| `manager` | Gestionnaire de salle | Dashboard, membres, abonnements, POS, acces, rapports, coaching, machines, RH, stock, parametres locaux |
| `reception` | Accueil / reception | Membres, caisse simple, controle d'acces, presences RH |
| `cashier` | Caisse | Caisse POS et quelques operations membres |
| `coach` | Compte interne de coach | Pas de module Coaching dedie dans l'etat actuel; acces limite |
| `accountant` | Compte interne comptable | Pas de menu dedie visible dans l'etat actuel; acces limite |

### 3.1 Particularites importantes

- Le role `owner` peut travailler sur plusieurs salles de la meme organisation.
- Le role `manager` est le role operationnel le plus complet apres `owner`.
- Le role `reception` est centre sur l'accueil: membres, acces, pointage RH, caisse simple.
- Le role `cashier` est centre sur la caisse.
- Dans la version actuelle, la gestion du module Coaching reste reservee a `owner` et `manager`.
- Les roles `coach` et `accountant` existent comme roles internes mais n'ouvrent pas encore, dans l'etat actuel, un espace metier complet a eux seuls.

## 4. Premiere connexion et demarrage

### 4.1 Connexion

L'ecran de connexion demande:

- nom d'utilisateur
- mot de passe

Apres connexion:

- un administrateur SaaS est redirige vers l'administration
- un owner est redirige vers le choix de la salle ou directement vers un dashboard
- un employe interne est redirige selon son role et les modules actifs

### 4.2 Cas du proprietaire avec plusieurs salles

Si vous etes owner et que votre organisation possede plusieurs salles actives:

1. vous arrivez sur la page de selection de salle
2. vous voyez chaque salle sous forme de carte
3. vous pouvez basculer vers la salle de travail voulue
4. la salle choisie devient la salle active de votre session

Si une seule salle est disponible, la selection se fait automatiquement.

### 4.3 Profil personnel

Depuis `Mon profil`, chaque utilisateur peut:

- modifier son prenom
- modifier son nom
- modifier son email
- changer son mot de passe
- voir ses roles actifs rattaches aux salles accessibles

### 4.4 Mots de passe par defaut

Dans plusieurs workflows, l'application cree des comptes avec le mot de passe temporaire:

`12345`

Cela concerne notamment:

- les utilisateurs internes crees depuis les parametres
- les comptes rattaches automatiquement a certains membres
- les reinitialisations de mot de passe

Bon reflexe:

1. communiquer l'identifiant a la personne concernee
2. lui demander de se connecter
3. lui faire changer son mot de passe depuis `Mon profil`

## 5. Navigation generale

Le menu lateral peut contenir les sections suivantes:

- Tableau de bord
- Membres
- Abonnements
- Paiements
- Controle d'acces
- Rapports
- Coaching
- Machines
- Ressources Humaines
- Stock & produits
- Parametres
- Mon profil

### 5.1 Tableau de bord

Le dashboard s'adapte:

- au role
- a la salle active
- aux modules actifs
- a la periode selectionnee

Le dashboard owner/manager peut afficher:

- nombre de membres
- membres actifs, expires, suspendus
- revenus
- visites et refus d'acces
- abonnements et renouvellements
- KPI machines
- KPI RH
- KPI stock
- KPI coaching

### 5.2 Navigation contextuelle

Certaines pages servent de point d'entree rapide:

- `Membres > Tous les membres`
- `Membres > Preinscriptions`
- `Paiements > Point de vente`
- `Paiements > Journal des transactions`
- `Controle d'acces > Enregistrer les entrees`
- `RH > Enregistrer presences`
- `RH > Paie`
- `Stock & produits > Liste des produits`

## 6. Utilisation detaillee par module

## 6.1 Module Membres

### 6.1.1 Objectif

Le module Membres sert a:

- enregistrer les membres
- rechercher rapidement un membre
- consulter ses informations
- suivre ses acces
- suivre ses paiements recents
- generer ou utiliser son QR code
- suspendre ou reactiver son acces

### 6.1.2 Liste des membres

La liste des membres propose:

- recherche par prenom, nom, telephone, email ou identifiant utilisateur
- filtre par statut:
  - actif
  - expire
  - suspendu
  - expiration proche
- filtre par formule
- filtre d'acces:
  - acces recent
  - jamais venu
- filtre par periode de creation
- tri:
  - plus recents
  - plus anciens
  - ordre alphabetique
  - date d'expiration
  - dernier acces

La liste est paginee.

### 6.1.3 Creer un membre

Les informations saisies sont:

- prenom
- nom
- telephone
- email
- adresse
- photo

Quand vous creez un membre:

1. le membre est rattache a la salle active
2. un identifiant utilisateur est genere automatiquement
3. un mot de passe temporaire `12345` est attribue
4. un QR code unique est genere pour le controle d'acces

### 6.1.4 Consulter la fiche d'un membre

La fiche detaillee permet de voir:

- l'identite du membre
- la salle et l'organisation
- l'identifiant du compte associe
- le statut calcule
- le QR code
- l'abonnement actif
- la date de debut
- la date d'expiration
- les paiements recents
- les acces recents

### 6.1.5 Modifier un membre

La modification permet d'ajuster:

- les informations personnelles
- la photo
- les coordonnees

### 6.1.6 Suspendre un membre

La suspension:

- met le statut du membre a `suspended`
- met en pause son abonnement actif
- bloque l'acces a la salle

### 6.1.7 Reactiver un membre

La reactivation:

- remet le statut du membre a `active`
- reprend l'abonnement mis en pause
- rallonge la fin d'abonnement de la duree de pause

### 6.1.8 Supprimer un membre

La suppression complete d'un membre est reservee au role `owner`.

## 6.2 Module Preinscriptions

### 6.2.1 Principe

Chaque salle dispose d'un lien public de preinscription.

Ce lien permet a un futur membre de renseigner:

- prenom
- nom
- telephone
- email
- adresse

### 6.2.2 Fonctionnement

Une preinscription:

- est rattachee a une salle precise
- reste en attente par defaut
- expire automatiquement au bout de 7 jours

### 6.2.3 Liste interne des preinscriptions

Le personnel autorise peut:

- voir les demandes en attente
- filtrer par statut
- rechercher une demande
- confirmer une demande
- annuler une demande
- copier ou reutiliser le lien public

### 6.2.4 Confirmation

Lorsque vous confirmez une preinscription:

1. l'application verifie qu'elle n'est pas expiree
2. elle verifie qu'aucun membre de la salle n'existe deja avec le meme telephone ou email
3. elle cree le membre
4. elle rattache le membre a la preinscription
5. elle genere les identifiants de connexion du membre

### 6.2.5 Annulation

Une preinscription annulee n'est pas convertie en membre.

## 6.3 Module Abonnements

### 6.3.1 Objectif

Ce module sert a:

- creer les formules d'abonnement
- modifier les formules
- desactiver les formules obsoletes
- attribuer un abonnement a un membre

### 6.3.2 Gerer les formules

Chaque formule contient:

- nom
- duree en jours
- prix en USD
- description
- statut actif/inactif

Regles importantes:

- le nom d'une formule doit etre unique dans une meme salle
- une formule avec historique n'est pas supprimee physiquement: elle est desactivee

### 6.3.3 Creer un abonnement pour un membre

Pour attribuer un abonnement:

1. choisir le membre
2. choisir la formule
3. choisir la date de debut
4. choisir l'option de renouvellement automatique si necessaire

Quand un nouvel abonnement est cree:

- l'ancien abonnement actif du membre est desactive
- la date de fin est calculee automatiquement a partir de la duree de la formule

### 6.3.4 Tableau de pilotage des formules

La page des formules donne aussi une vision rapide de:

- nombre de formules actives
- nombre d'abonnements actifs
- abonnements a renouvellement auto
- abonnements proches de l'expiration

## 6.4 Module Paiements / Point de vente (POS)

### 6.4.1 Objectif

Le module POS centralise:

- l'ouverture et la fermeture de caisse
- les ventes d'abonnements
- les ventes de produits
- les decaissements
- l'historique des sessions de caisse

### 6.4.2 Regle fondamentale: la caisse doit etre ouverte

Aucun mouvement financier ne peut etre enregistre sans:

- une caisse ouverte
- un taux USD-CDF valide defini pour cette session

Il ne peut y avoir qu'une seule caisse ouverte par salle a la fois.

### 6.4.3 Ouvrir une caisse

Pour ouvrir une caisse, il faut saisir:

- le fonds d'ouverture
- le taux USD-CDF du jour

L'application:

- ouvre la session
- enregistre le taux de change du jour
- associe tous les paiements suivants a cette session

### 6.4.4 Encaisser un abonnement

Depuis le point de vente:

1. selectionner le membre
2. selectionner la formule
3. choisir la devise (`USD` ou `CDF`)
4. choisir le mode de paiement
5. valider

Effets automatiques:

- creation d'un nouvel abonnement actif
- desactivation de l'abonnement actif precedent
- creation du paiement associe dans la caisse

### 6.4.5 Enregistrer une vente de produit

Pour une vente produit:

1. selectionner le produit
2. saisir la quantite
3. choisir la devise
4. choisir le mode de paiement

Effets automatiques:

- creation d'un paiement POS
- deduction du stock
- creation d'un mouvement de stock `out`

### 6.4.6 Enregistrer un decaissement

Le decaissement permet de sortir de l'argent de la caisse pour une depense simple.

Informations saisies:

- montant
- description

Le systeme cree un paiement de sortie en CDF.

### 6.4.7 Fermer une caisse

Lors de la fermeture:

1. l'application calcule le total theorique
2. vous saisissez le montant reel present
3. l'application calcule l'ecart
4. la session est marquee comme fermee

### 6.4.8 Historique des caisses

Le journal des transactions permet de:

- rechercher une session
- filtrer par statut
- filtrer par date
- trier par date ou par ecart
- consulter le detail complet d'une caisse

## 6.5 Module Controle d'acces

### 6.5.1 Objectif

Le module Acces sert a enregistrer les entrees des membres:

- par scan du QR code
- par pointage manuel

### 6.5.2 Regles d'autorisation

Un acces est autorise seulement si:

- le membre est actif
- le membre n'est pas suspendu
- le membre a un abonnement actif
- l'abonnement n'est pas en pause
- l'abonnement n'est pas expire
- le membre n'a pas deja ete enregistre en entree le meme jour

### 6.5.3 Scan QR

Le scan QR:

1. identifie le membre
2. verifie son droit d'entree
3. enregistre un journal d'acces
4. renvoie un resultat `autorise` ou `refuse`

### 6.5.4 Pointage manuel

Le pointage manuel permet:

- de rechercher un membre par nom ou telephone
- de selectionner le membre
- d'enregistrer l'entree sans QR

### 6.5.5 Historique

Le module montre:

- les entrees du jour
- les refus du jour
- les derniers scans
- un historique elargi des journaux d'acces

### 6.5.6 Cas de refus typiques

Les motifs de refus les plus probables sont:

- membre inactif
- membre suspendu
- aucun abonnement actif
- membre deja dans la salle pour la journee

## 6.6 Module Rapports

### 6.6.1 Objectif

Le module Rapports centralise les indicateurs financiers et operationnels.

### 6.6.2 Sections disponibles

Le module gere plusieurs vues:

- journalier
- mensuel
- personnalise

### 6.6.3 Donnees visibles

Selon la periode selectionnee, vous pouvez suivre:

- chiffre d'affaires
- nombre de transactions
- nouveaux membres
- renouvellements d'abonnements
- visites
- refus d'acces
- detail des transactions
- performance par formule

### 6.6.4 Exports

Les rapports peuvent etre exportes en:

- CSV
- XLSX

## 6.7 Module Coaching

### 6.7.1 Objectif

Le module Coaching sert a:

- creer des coaches
- gerer leurs specialites
- assigner des membres a chaque coach
- suivre la charge par coach

### 6.7.2 Fiche coach

Chaque coach possede:

- nom
- telephone
- specialite
- statut actif/inactif

### 6.7.3 Specialites

Les specialites coach se gerent dans `Parametres > Specialites coach`.

Une specialite:

- peut etre creee
- peut etre desactivee
- reste visible sur les anciennes fiches si elle a deja ete utilisee

### 6.7.4 Affecter des membres a un coach

Pour affecter un membre:

1. ouvrir la fiche du coach
2. choisir un membre actif de la meme salle
3. valider l'affectation

Un coach ne peut suivre que des membres de sa propre salle.

### 6.7.5 Desactivation

La suppression d'un coach est en pratique une desactivation logique.

## 6.8 Module Machines

### 6.8.1 Objectif

Le module Machines sert a:

- enregistrer les equipements
- suivre leur statut
- enregistrer les maintenances
- suivre les couts de maintenance

### 6.8.2 Fiche machine

Chaque machine contient:

- nom
- statut (`ok`, `maintenance`, `broken`)
- date d'achat

### 6.8.3 Creer et modifier une machine

Vous pouvez:

- ajouter une machine
- modifier son statut
- mettre a jour sa date d'achat
- la supprimer

### 6.8.4 Enregistrer une maintenance

Pour une maintenance, vous saisissez:

- description
- cout en CDF

Si un cout est renseigne:

- l'application cree automatiquement une sortie POS de type `maintenance`
- la depense est rattachee au journal des paiements

Vous pouvez aussi, pendant cette operation:

- changer le statut de la machine

### 6.8.5 Tableau de bord maintenance

Le tableau de bord affiche:

- nombre total de machines
- nombre de machines OK
- nombre de machines en maintenance
- nombre de machines en panne
- nombre de maintenances
- cout total de maintenance
- machines les plus couteuses
- maintenances recentes

## 6.9 Module Ressources Humaines

### 6.9.1 Objectif

Le module RH sert a:

- gerer les employes
- enregistrer les presences
- calculer la paie mensuelle
- enregistrer les paiements de salaire

### 6.9.2 Employes

Chaque employe contient:

- nom
- role
- telephone
- salaire journalier en CDF
- statut actif/inactif

### 6.9.3 Presences

Deux modes existent:

- saisie unitaire
- saisie en groupe

La saisie en groupe permet de marquer, pour une date donnee, chaque employe comme:

- present
- absent

### 6.9.4 Liste des presences

La liste permet de filtrer:

- par employe
- par date de debut
- par date de fin

### 6.9.5 Paie

La paie mensuelle est calculee automatiquement a partir:

- du salaire journalier
- du nombre de jours marques `present`

Le tableau de paie permet de voir:

- total des salaires
- salaires deja payes
- salaires en attente
- nombre de dossiers en attente

### 6.9.6 Paiement d'un salaire

Lors du paiement:

1. l'application calcule le salaire du mois
2. vous saisissez le mode de paiement, la reference et les notes
3. le systeme cree automatiquement une sortie POS de type `salary`
4. l'historique de paie est enregistre

Un meme salaire mensuel ne doit pas etre paye deux fois.

## 6.10 Module Produits et stock

### 6.10.1 Objectif

Ce module sert a:

- enregistrer les produits vendus par la salle
- suivre les quantites
- enregistrer les mouvements de stock
- surveiller les ruptures et faibles stocks

### 6.10.2 Creer un produit

Chaque produit contient:

- nom
- prix en USD
- quantite initiale
- statut actif/inactif

Si une quantite initiale est saisie, un mouvement de stock `in` est cree automatiquement avec le motif `Stock initial`.

### 6.10.3 Modifier un produit

Si vous modifiez la quantite:

- l'application calcule la difference
- elle cree automatiquement un mouvement de stock
- le motif utilise est `Ajustement manuel`

### 6.10.4 Mouvement de stock manuel

Vous pouvez enregistrer:

- une entree
- une sortie

Avec:

- quantite
- type de mouvement
- raison

Si la sortie demande une quantite superieure au stock disponible, l'operation est refusee.

### 6.10.5 Impact des ventes POS

Une vente produit effectuee dans le module POS:

- diminue automatiquement le stock
- cree un mouvement `out`
- cree le paiement associe dans la caisse

### 6.10.6 Dashboard stock

Le dashboard donne une vision sur:

- le nombre de produits
- la valeur totale du stock
- les produits a faible stock
- les ruptures
- les produits ayant la plus grande valeur
- les derniers mouvements

### 6.10.7 Suppression

La suppression d'un produit est une desactivation logique, afin de conserver l'historique.

## 6.11 Module Parametres

### 6.11.1 Objectif

Le module Parametres centralise:

- les informations de l'organisation
- les utilisateurs internes et leurs roles
- les specialites coach
- le journal d'activite sensible

### 6.11.2 Onglet Organisation

Accessible au role `owner`.

Vous pouvez modifier:

- nom de l'organisation
- logo
- adresse
- telephone
- email

### 6.11.3 Onglet Utilisateurs & roles

Permet de creer des employes internes avec:

- prenom
- nom
- email
- salle
- role
- statut actif/inactif

Regles:

- le role `owner` ne peut pas etre cree depuis ce formulaire
- le username est genere automatiquement
- le mot de passe temporaire est `12345`

Depuis la meme zone, vous pouvez:

- reinitialiser un mot de passe
- activer un utilisateur
- desactiver un utilisateur

### 6.11.4 Onglet Specialites coach

Permet:

- d'ajouter une specialite
- d'activer/desactiver une specialite

### 6.11.5 Onglet Journal sensible

Le journal sensible conserve les actions importantes, par exemple:

- modification de l'organisation
- creation d'un employe interne
- reinitialisation d'un mot de passe
- activation/desactivation d'un utilisateur
- creation ou changement d'une specialite

Ce journal sert a l'audit interne.

## 7. Regles metier importantes

Voici les regles les plus importantes a connaitre pour bien utiliser GesGym.

### 7.1 Regles sur les membres

- Un telephone ne peut pas etre duplique pour deux membres de la meme salle.
- Un email ne peut pas etre duplique pour deux membres de la meme salle.
- Une preinscription active ne peut pas reutiliser un telephone ou email deja pris.

### 7.2 Regles sur les abonnements

- Un membre ne peut avoir qu'un seul abonnement actif a la fois.
- Un nouvel abonnement desactive l'ancien.
- Une suspension de membre met l'abonnement en pause.

### 7.3 Regles sur l'acces

- Un membre suspendu ne peut pas entrer.
- Un membre sans abonnement actif ne peut pas entrer.
- Un double scan le meme jour est refuse.

### 7.4 Regles sur la caisse

- Une seule caisse ouverte par salle.
- Le taux USD-CDF est obligatoire pour ouvrir une caisse.
- Aucun paiement sans caisse ouverte.

### 7.5 Regles sur les produits

- Le stock ne peut pas devenir negatif.
- Toute vente produit diminue le stock.
- Toute correction de quantite cree un mouvement de stock.

### 7.6 Regles sur la paie et les maintenances

- Un paiement de salaire cree aussi un paiement de sortie POS.
- Une maintenance avec cout cree aussi un paiement de sortie POS.
- Ces flux assurent la coherence entre exploitation et finance.

### 7.7 Regles sur les suppressions

Selon le module, `supprimer` ne signifie pas toujours `effacer`.

Dans la version actuelle:

- un plan avec historique est desactive
- un produit est desactive
- un coach est desactive
- un employe RH est desactive
- un membre peut etre supprime physiquement par owner
- une machine peut etre supprimee

## 8. Routines de travail recommandees

## 8.1 Routine quotidienne d'accueil

1. verifier la salle active
2. ouvrir la caisse si necessaire
3. verifier le taux USD-CDF du jour
4. enregistrer les entrees via le module Acces
5. rechercher les membres en anomalie si un acces est refuse
6. enregistrer les ventes et decaissements dans le POS

## 8.2 Routine quotidienne manager

1. consulter le dashboard
2. verifier les expirations proches
3. traiter les preinscriptions
4. controler les encaissements et le journal de caisse
5. verifier les maintenances et les ruptures de stock

## 8.3 Routine RH

1. enregistrer les presences du jour
2. controler les absences
3. a la fin du mois, ouvrir le tableau de paie
4. payer les salaires depuis le module RH
5. verifier l'impact dans la caisse

## 8.4 Routine stock

1. verifier les faibles stocks
2. enregistrer les entrees de stock a reception
3. corriger les ecarts de quantite si necessaire
4. surveiller les mouvements recents

## 8.5 Routine owner

1. verifier les journaux sensibles
2. verifier les dashboards par salle
3. basculer de salle selon les besoins
4. maintenir les utilisateurs internes
5. tenir a jour les infos organisationnelles

## 9. Depannage et questions frequentes

### 9.1 "Je ne vois pas un menu"

Ca peut venir de trois causes:

- votre role n'a pas le droit correspondant
- le module n'est pas actif pour la salle
- vous n'etes pas positionne sur la bonne salle

### 9.2 "Je suis owner mais je ne vois pas les bonnes donnees"

Verifiez la salle active. Les donnees changent quand vous changez de salle.

### 9.3 "Impossible d'enregistrer un paiement"

Verifier:

- qu'une caisse est ouverte
- qu'elle n'est pas fermee
- qu'un taux USD-CDF valide est defini

### 9.4 "Le scan QR refuse l'entree"

Verifier:

- que le membre est actif
- qu'il n'est pas suspendu
- qu'il a un abonnement actif
- qu'il n'a pas deja ete pointe aujourd'hui

### 9.5 "Je n'arrive pas a confirmer une preinscription"

Ca se produit generalement si:

- la preinscription a expire
- un membre existe deja avec le meme telephone
- un membre existe deja avec le meme email
- la demande n'est plus en statut `pending`

### 9.6 "Je ne peux pas ouvrir une deuxieme caisse"

C'est normal. Une seule caisse ouverte est autorisee par salle.

### 9.7 "Pourquoi une maintenance ou une paie apparait dans le POS ?"

Parce que GesGym centralise les sorties d'argent de la salle dans le journal financier.

### 9.8 "J'ai supprime un produit mais il apparait encore dans l'historique"

C'est normal. Les produits sont desactives pour conserver la tracabilite.

### 9.9 "Un utilisateur interne ne peut plus se connecter"

Verifier:

- son role interne
- son statut actif
- le statut actif de la salle
- le statut actif de l'organisation

### 9.10 "Le mot de passe a ete oublie"

Un owner ou un manager selon le contexte peut reinitialiser le mot de passe sur `12345`, puis l'utilisateur devra le changer apres connexion.

## 10. Glossaire

- **Organisation**: entite cliente qui possede une ou plusieurs salles.
- **Salle / gym**: unite de travail active sur laquelle les donnees sont filtrees.
- **Module**: bloc fonctionnel activable pour une salle.
- **Membre**: client inscrit dans une salle.
- **Preinscription**: demande publique avant creation definitive d'un membre.
- **Formule**: offre d'abonnement avec duree et prix.
- **Abonnement actif**: abonnement actuellement utilise pour autoriser l'acces.
- **POS**: point de vente et journal financier.
- **Caisse**: session financiere ouverte pour enregistrer les paiements.
- **Mouvement de stock**: entree ou sortie de quantite sur un produit.
- **Journal sensible**: trace des actions importantes realisees dans les parametres.

## Conclusion

GesGym est pense comme une application d'exploitation quotidienne, pas seulement comme une base de donnees.

Pour bien l'utiliser:

1. commencez toujours par verifier la salle active
2. ouvrez la caisse avant toute operation financiere
3. gardez les membres, abonnements et stocks a jour
4. utilisez les dashboards pour piloter, pas seulement pour consulter
5. surveillez les journaux sensibles et les utilisateurs internes

Ce manuel peut servir de base de formation pour:

- owner
- manager
- reception
- cashier
- personnel RH

