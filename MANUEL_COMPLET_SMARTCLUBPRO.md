# Manuel complet explicatif SmartClub Pro

Version du manuel : 14/06/2026.

Ce manuel presente SmartClub Pro dans son ensemble: vision produit, organisation SaaS, roles, modules, parcours d'utilisation, regles metier, exploitation quotidienne et pistes d'evolution.

Il s'adresse a trois publics:

- l'equipe SmartClub Pro qui administre la plateforme;
- les proprietaires et managers de salles de sport;
- les collaborateurs terrain: reception, caisse, coachs et equipe operationnelle.

## 1. Presentation generale

SmartClub Pro est une plateforme SaaS de gestion de salles de sport.

Elle permet a une salle ou a un reseau de salles de centraliser les operations quotidiennes:

- gestion des membres;
- preinscriptions;
- abonnements;
- caisse et paiements;
- controle d'acces;
- rapports;
- messages membres;
- espace membre mobile;
- coaching;
- produits et stock;
- ressources humaines;
- machines et maintenances;
- administration multi-salle.

La plateforme est pensee pour fonctionner avec plusieurs organisations clientes. Chaque organisation peut posseder une ou plusieurs salles.

## 2. Objectif de la plateforme

SmartClub Pro poursuit quatre objectifs principaux.

### 2.1 Centraliser les operations

Au lieu d'avoir des fichiers Excel, des carnets papier, une caisse separee et des listes manuelles, SmartClub Pro regroupe les donnees dans une seule plateforme.

### 2.2 Securiser les acces

Les membres peuvent etre controles par QR code ou recherche manuelle. L'acces depend du statut du membre et de son abonnement actif.

### 2.3 Donner de la visibilite au manager

Les tableaux de bord, rapports et historiques permettent de suivre:

- les revenus;
- les abonnements;
- les membres actifs;
- les entrees;
- la caisse;
- les stocks;
- les presences RH;
- le coaching;
- les maintenances.

### 2.4 Accompagner la croissance multi-salle

Un owner peut gerer plusieurs salles d'une meme organisation. Chaque salle conserve ses propres donnees, sa caisse, ses membres, ses employes, ses produits et ses rapports.

## 3. Structure SaaS

### 3.1 Organisation

Une organisation represente un client SmartClub Pro.

Exemples:

```text
Elite Fitness Group
Urban Gym Network
Smart Shape Club
```

Une organisation peut avoir une seule salle ou plusieurs salles.

### 3.2 Gym

Un gym represente une salle physique.

Exemples:

```text
Elite Fitness Gombe
Elite Fitness Limete
Urban Gym Bandal
```

Les donnees metier sont rattachees au gym:

- membres;
- abonnements;
- paiements;
- acces;
- caisse;
- produits;
- machines;
- employes RH;
- coaches;
- programmes coaching.

### 3.3 Salle active

Pour un owner multi-salle, la salle active est le contexte courant de travail.

Toutes les actions se font dans cette salle active, sauf certaines actions owner qui concernent toute l'organisation.

Exemple:

```text
Organisation: Elite Fitness Group
Salle active: Elite Fitness Gombe
```

Dans ce contexte, le dashboard, les membres, les paiements et les rapports affichent les donnees de Gombe.

## 4. Packs fonctionnels

SmartClub Pro fonctionne par packs.

Le pack est choisi au niveau de l'organisation, puis les modules sont synchronises sur les salles.

### 4.1 Pack Club

Le Pack Club couvre le socle d'exploitation d'une salle.

Modules inclus:

- membres;
- abonnements;
- caisse et POS;
- controle d'acces;
- messages membres;
- rapports essentiels;
- espace membre mobile.

Ce pack convient a une salle qui veut d'abord mieux gerer les membres, les paiements et les entrees.

### 4.2 Pack Premium

Le Pack Premium inclut tout le Pack Club et ajoute les modules avances.

Modules supplementaires:

- produits et stock;
- ressources humaines;
- machines et maintenances;
- coaching.

Ce pack convient a une salle ou un reseau plus structure, avec des operations plus riches et un besoin de pilotage plus complet.

## 5. Roles utilisateurs

SmartClub Pro repose sur une logique de roles. Chaque role a un perimetre clair.

### 5.1 Admin SaaS

L'admin SaaS appartient a l'equipe SmartClub Pro.

Il peut:

- creer des organisations clientes;
- creer les owners;
- choisir le pack commercial;
- superviser les modules;
- intervenir en cas de support technique.

Il n'est pas un utilisateur terrain de la salle.

### 5.2 Owner

L'owner est le proprietaire de l'organisation cliente.

Il peut:

- acceder aux salles de son organisation;
- basculer entre ses salles;
- gerer les employes internes;
- voir les rapports;
- gerer les parametres de l'organisation;
- creer managers, coaches, receptionnistes et caissiers;
- gerer les modules disponibles selon son pack.

Regle importante:

- un owner ne peut pas creer un autre owner depuis les parametres internes.

### 5.3 Manager

Le manager pilote une salle precise.

Il peut:

- gerer les membres;
- gerer les abonnements;
- suivre les rapports;
- gerer les operations courantes;
- gerer les employes internes de sa salle;
- consulter la caisse selon ses droits;
- suivre stock, RH, machines et coaching si les modules sont actifs.

Regles importantes:

- un manager ne gere que sa salle active;
- il ne peut pas creer un autre manager;
- il ne peut pas creer un employe dans une autre salle;
- il ne peut pas modifier un owner.

### 5.4 Reception

La reception gere l'accueil.

Elle peut typiquement:

- consulter ou creer des membres selon configuration;
- verifier les acces;
- enregistrer des presences;
- utiliser certaines fonctions de caisse si autorisees.

### 5.5 Cashier

Le caissier travaille principalement dans le module caisse.

Il peut:

- ouvrir sa caisse;
- enregistrer des encaissements;
- vendre des produits;
- faire des decaissements autorises;
- cloturer sa caisse.

Regle importante:

- le suivi de caisse est rattache a l'utilisateur qui l'a ouverte.

### 5.6 Coach

Le coach dispose d'un portail dedie.

Il peut:

- voir ses membres suivis;
- consulter les priorites du jour;
- enregistrer les suivis;
- traiter les relances;
- consulter ses programmes groupes;
- renseigner certains objectifs ou mesures si le parcours le permet.

Regle importante:

- un meme compte coach ne doit pas etre actif dans deux gyms.
- si un coach travaille dans une autre salle, il faut lui creer des identifiants separes pour cette salle.

### 5.7 Membre

Le membre utilise l'espace mobile.

Il peut:

- voir sa carte membre;
- presenter son QR code;
- consulter son abonnement;
- lire ses messages;
- consulter son historique;
- acceder aux informations coaching selon sa formule.

## 6. Connexion et mots de passe

### 6.1 Connexion

Chaque utilisateur se connecte avec un identifiant et un mot de passe.

Apres connexion:

- l'admin SaaS va vers l'administration;
- l'owner va vers son choix de salle ou son dashboard;
- le manager va vers son espace de pilotage;
- le caissier va vers la caisse;
- le coach va vers le portail coach;
- le membre va vers son espace mobile.

### 6.2 Mot de passe temporaire

Lorsqu'un compte est cree ou reinitialise, SmartClub Pro peut generer un mot de passe temporaire.

Ce mot de passe doit etre communique immediatement a l'utilisateur.

A la premiere connexion, l'utilisateur devra definir son propre mot de passe.

### 6.3 Recuperation par email

La recuperation de mot de passe par email existe cote application.

Elle depend de la configuration SMTP de production.

Exemple pour LWS:

```env
DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
DJANGO_EMAIL_HOST=mail.smartclubpro.org
DJANGO_EMAIL_PORT=465
DJANGO_EMAIL_HOST_USER=noreply@smartclubpro.org
DJANGO_EMAIL_HOST_PASSWORD=secret
DJANGO_EMAIL_USE_TLS=False
DJANGO_EMAIL_USE_SSL=True
DJANGO_DEFAULT_FROM_EMAIL=noreply@smartclubpro.org
DJANGO_SERVER_EMAIL=noreply@smartclubpro.org
```

## 7. Module Membres

Le module Membres centralise la base adherents.

Il permet:

- creation de membre;
- modification des informations;
- consultation de la fiche;
- photo;
- statut actif, expire ou suspendu;
- QR code;
- historique des acces;
- historique des paiements;
- rattachement a un utilisateur membre.

### 7.1 Creation d'un membre

Lors de la creation:

- les informations personnelles sont saisies;
- un identifiant peut etre genere;
- un mot de passe temporaire peut etre affiche;
- le membre pourra ensuite acceder a son espace mobile.

### 7.2 Suspension et reactivation

Un membre suspendu ne doit pas pouvoir entrer.

La suspension est utile en cas de:

- impaye;
- comportement a traiter;
- demande administrative;
- erreur a corriger.

### 7.3 Details membre

La fiche membre regroupe:

- informations personnelles;
- abonnement;
- acces;
- paiements;
- coaching;
- objectifs;
- notes utiles.

## 8. Espace membre mobile

L'espace membre mobile est concu comme une PWA.

Il donne au membre un acces simple depuis son telephone.

Fonctions principales:

- carte membre;
- QR code;
- abonnement actif;
- messages;
- historique;
- formules disponibles;
- informations coaching selon droits.

Le QR code peut etre presente a la reception ou scanne par un equipement compatible.

Un scanner QR de type clavier USB ou Bluetooth est generalement compatible s'il envoie le code comme une saisie texte suivie d'une validation.

## 9. Preinscriptions

Les preinscriptions permettent a une salle de collecter des demandes avant creation definitive du membre.

Parcours:

1. Le prospect remplit le formulaire public.
2. La salle consulte la demande.
3. La demande est confirmee.
4. Le membre est cree.
5. Les identifiants sont communiques si un acces membre est cree.

Ce flux est utile pour les campagnes marketing, les essais gratuits ou les inscriptions a distance.

## 10. Abonnements

Le module Abonnements gere les formules vendues aux membres.

Une formule contient notamment:

- nom;
- duree;
- prix;
- droits coaching eventuels;
- statut actif.

Regles importantes:

- un membre ne doit avoir qu'un abonnement actif principal a la fois;
- un abonnement expire ne donne pas acces;
- un abonnement suspendu ou pause ne donne pas les memes droits qu'un abonnement actif.

Les paiements par tranche ne sont pas encore geres dans la logique actuelle.

## 11. POS, caisse et paiements

Le POS est le module de caisse.

Il permet:

- ouverture de caisse;
- encaissement d'abonnement;
- vente de produit;
- decaissement;
- suivi des entrees et sorties;
- fermeture de caisse;
- historique.

### 11.1 Ouverture de caisse

Un utilisateur autorise ouvre une caisse avec:

- montant d'ouverture;
- taux de change si necessaire;
- salle active.

La caisse est rattachee a l'utilisateur qui l'a ouverte.

### 11.2 Paiements

Un paiement peut concerner:

- abonnement;
- produit;
- salaire RH;
- maintenance;
- depense;
- autre operation.

Regle importante:

- un paiement ne doit pas etre enregistre sans caisse ouverte.

### 11.3 Suivi par utilisateur

Pour preserver la tracabilite, le manager ne doit pas utiliser une caisse ouverte par un autre utilisateur comme si c'etait la sienne.

Chaque session de caisse doit permettre de savoir:

- qui l'a ouverte;
- quand elle a ete ouverte;
- quelles transactions ont ete faites;
- qui a cree les paiements;
- quand elle a ete fermee.

## 12. Controle d'acces

Le controle d'acces permet de verifier si un membre peut entrer.

Deux modes existent:

- scan QR;
- verification manuelle.

Un acces peut etre refuse si:

- le membre est suspendu;
- il n'a pas d'abonnement actif;
- son abonnement est expire;
- le QR code est invalide;
- il a deja ete enregistre selon la regle appliquee.

Le message d'acces doit etre lisible:

- succes pour acces autorise;
- warning ou danger pour acces refuse.

## 13. Rapports

Le module Rapports aide au pilotage.

Il permet de lire:

- revenus journaliers;
- revenus mensuels;
- transactions;
- acces;
- abonnements;
- membres;
- caisse;
- paie RH;
- exports personnalises.

Formats utiles:

- affichage dans l'interface;
- CSV;
- XLSX.

Les rapports doivent toujours respecter la salle active et le role de l'utilisateur.

## 14. Messages membres

SmartClub Pro permet d'envoyer des messages visibles dans l'espace membre.

Audiences possibles:

- un membre precis;
- tous les membres;
- membres actifs;
- membres expires;
- membres suspendus;
- membres proches de l'expiration;
- membres sans abonnement.

Ce module peut servir pour:

- rappels d'abonnement;
- annonces;
- promotions;
- informations de fermeture;
- communications internes de la salle.

## 15. Coaching

Le module Coaching couvre la relation entre les coaches et les membres.

Il permet:

- creation des coaches;
- specialites;
- affectation des membres;
- suivi individuel;
- programmes groupes;
- feedbacks;
- priorites;
- relances.

### 15.1 Portail coach

Le coach dispose d'un portail dedie.

Il voit:

- son portefeuille de membres actifs;
- les priorites du jour;
- les relances;
- les feedbacks sensibles;
- ses programmes groupes;
- les fiches de suivi membre.

Les alertes doivent seulement concerner les membres encore actifs dans son portefeuille coaching.

### 15.2 Programmes groupes

Les programmes groupes sont rattaches a:

- une salle;
- un coach;
- une capacite;
- des participants.

Un membre ne doit rejoindre un programme groupe que si sa formule donne ce droit.

### 15.3 Feedback coaching

Les feedbacks permettent de detecter:

- satisfaction basse;
- besoin de recontact;
- problemes de suivi;
- experience positive.

Les feedbacks sensibles doivent etre visibles par le coach et/ou le manager selon le contexte.

## 16. Produits et stock

Le module Produits permet de gerer le stock vendu ou utilise par la salle.

Fonctions principales:

- creation de produit;
- prix;
- quantite;
- statut actif;
- mouvements d'entree et sortie;
- vente via POS;
- dashboard stock.

Le dashboard stock affiche:

- produits actifs;
- valeur du stock;
- stock bas;
- ruptures;
- top valeur;
- derniers mouvements.

Regles importantes:

- une vente produit diminue le stock;
- une entree de stock augmente le stock;
- une sortie manuelle doit etre justifiee;
- les ruptures doivent etre surveillees.

## 17. Ressources humaines

Le module RH gere les employes de la salle.

Il couvre:

- employes RH;
- presences;
- pointage;
- salaires;
- primes;
- avances;
- retenues;
- heures supplementaires;
- conges;
- cotisations;
- taxes;
- bulletins;
- paiement salaire via POS.

### 17.1 Presences

Les presences peuvent etre enregistrees pour suivre:

- jours presents;
- absences;
- retards;
- conges.

### 17.2 Paie

La paie peut prendre en compte:

- salaire de base;
- primes;
- avances;
- retenues;
- heures supplementaires;
- conges;
- taxes;
- cotisations employe;
- cotisations employeur.

Workflow type:

```text
brouillon -> verifie -> approuve -> paye
```

## 18. Machines et maintenances

Le module Machines sert a suivre le parc d'equipements.

Il permet:

- creation de machine;
- statut;
- historique de maintenance;
- cout de maintenance;
- paiement lie au POS;
- alertes de disponibilite.

Statuts possibles selon la logique de la salle:

- disponible;
- en maintenance;
- hors service;
- a surveiller.

## 19. Parametres

Le module Parametres centralise la configuration accessible au client.

Pour l'owner:

- informations organisation;
- logo;
- utilisateurs internes;
- roles;
- specialites coach;
- activite sensible.

Pour le manager:

- gestion des employes internes de sa salle;
- creation de coach, reception ou caissier selon droits;
- pas de creation d'un autre manager;
- pas de modification de l'owner.

Regle importante:

- apres une action dans les parametres, l'utilisateur doit rester dans la section en cours.

## 20. Administration SaaS

L'administration SaaS est reservee a l'equipe SmartClub Pro.

Elle permet:

- creation d'organisation;
- creation d'owner;
- choix du pack;
- creation de gyms;
- verification des modules;
- supervision des clients.

Apres creation d'un client:

1. Verifier l'organisation.
2. Verifier les gyms.
3. Verifier le pack.
4. Verifier les modules.
5. Communiquer les identifiants owner.
6. Demander a l'owner de changer son mot de passe temporaire.

## 21. Notifications et communication

La plateforme permet les messages in-app aux membres.

Elle peut evoluer vers:

- email;
- SMS;
- WhatsApp;
- campagnes automatisees;
- rappels d'expiration.

Toute communication doit respecter la qualite des donnees:

- telephone valide;
- email valide;
- statut membre;
- consentement si necessaire.

## 22. Medias et images

Images gerees:

- logo organisation;
- photo membre;
- logo site public;
- icones PWA;
- favicon;
- images statiques SmartClub.

En production durable, les medias utilisateurs devraient etre stockes sur un stockage objet externe.

Backblaze B2 est une option prevue.

## 23. Securite et tracabilite

Principes importants:

- chaque utilisateur a son propre compte;
- ne pas partager les identifiants;
- les mots de passe temporaires doivent etre changes;
- les actions sensibles doivent etre tracees;
- les donnees sont filtrees par salle;
- les roles limitent les menus et les actions;
- les actions de modification doivent etre faites en POST.

Exemples d'actions sensibles:

- creation utilisateur;
- reinitialisation mot de passe;
- suspension membre;
- modification caisse;
- paiement;
- changement d'organisation;
- desactivation employe.

## 24. Exploitation quotidienne

### 24.1 Routine owner

1. Choisir la salle active.
2. Consulter le dashboard.
3. Verifier les revenus.
4. Verifier les alertes.
5. Controler les rapports.
6. Superviser les managers.

### 24.2 Routine manager

1. Verifier la salle active.
2. Consulter les KPI.
3. Controler les expirations.
4. Suivre caisse et paiements.
5. Traiter les anomalies membres.
6. Surveiller stock, RH, coaching et machines.

### 24.3 Routine reception

1. Verifier les membres entrants.
2. Scanner les QR codes.
3. Enregistrer les presences.
4. Orienter les membres en anomalie.
5. Remonter les cas au manager.

### 24.4 Routine caissier

1. Ouvrir sa caisse.
2. Enregistrer les paiements.
3. Vendre les produits.
4. Controler les montants.
5. Cloturer sa caisse.

### 24.5 Routine coach

1. Ouvrir le portail coach.
2. Lire les priorites.
3. Consulter les membres suivis.
4. Enregistrer les suivis.
5. Traiter les relances.
6. Signaler les feedbacks sensibles.

## 25. Regles metier importantes

- une organisation peut avoir plusieurs salles;
- un owner peut gerer les salles de son organisation;
- un manager reste limite a sa salle;
- un coach doit avoir un identifiant separe par gym si besoin;
- un membre suspendu ne doit pas entrer;
- un membre sans abonnement actif ne doit pas entrer;
- une caisse doit etre ouverte avant paiement;
- les paiements doivent etre traces;
- les ventes produits diminuent le stock;
- les salaires payes doivent passer par le POS si le module RH le demande;
- les rapports doivent respecter le contexte de salle.

## 26. Points actuels a connaitre

### 26.1 Devises

La plateforme est encore orientee RDC avec une logique `CDF` / `USD`.

Une roadmap multi-devise existe:

[docs/ROADMAP_MULTI_DEVISE.md](D:/GesGym/docs/ROADMAP_MULTI_DEVISE.md)

Avant une expansion multi-pays, la couche financiere devra etre generalisee.

### 26.2 Affiliation

Une roadmap affiliation existe:

[docs/ROADMAP_AFFILIATION.md](D:/GesGym/docs/ROADMAP_AFFILIATION.md)

Le modele recommande pour une premiere version est:

```text
code affilie + commission unique + validation manuelle
```

### 26.3 Stockage media

Les medias utilisateurs doivent evoluer vers un stockage objet pour une production durable.

Document associe:

[docs/MEDIA_STORAGE_GESGYM.md](D:/GesGym/docs/MEDIA_STORAGE_GESGYM.md)

## 27. Bonnes pratiques

### 27.1 Pour l'equipe SmartClub Pro

- creer les clients avec le bon pack;
- verifier les modules apres creation;
- documenter les changements importants;
- ne pas manipuler les donnees client sans raison;
- privilegier les actions tracees.

### 27.2 Pour l'owner

- creer un compte separe par employe;
- ne pas partager son compte owner;
- verifier la salle active;
- controler les rapports;
- reinitialiser les mots de passe si necessaire.

### 27.3 Pour le manager

- travailler uniquement sur sa salle;
- surveiller les anomalies;
- verifier la caisse;
- suivre les expirations;
- traiter les alertes.

### 27.4 Pour les equipes terrain

- utiliser son propre compte;
- ne pas noter les mots de passe dans un lieu public;
- signaler les erreurs;
- fermer ou cloturer les sessions sensibles;
- verifier les messages de confirmation.

## 28. Depannage rapide

### 28.1 Un menu n'apparait pas

Verifier:

- role de l'utilisateur;
- salle active;
- pack de l'organisation;
- module actif sur le gym;
- droits du role.

### 28.2 Un paiement ne passe pas

Verifier:

- caisse ouverte;
- utilisateur autorise;
- montant;
- devise;
- taux de change si applicable;
- membre ou produit selectionne.

### 28.3 Un membre ne peut pas entrer

Verifier:

- statut du membre;
- abonnement actif;
- QR code;
- suspension;
- historique d'acces.

### 28.4 Un coach ne voit pas ses membres

Verifier:

- role coach actif;
- fiche coach rattachee;
- membres affectes;
- abonnement coaching individuel actif;
- salle active.

### 28.5 Un employe ne peut pas se connecter

Verifier:

- compte actif;
- role actif;
- gym actif;
- organisation active;
- mot de passe;
- obligation de changement de mot de passe.

## 29. Lexique

### Organisation

Client SaaS qui possede une ou plusieurs salles.

### Gym

Salle physique geree dans SmartClub Pro.

### Owner

Proprietaire de l'organisation.

### Manager

Responsable operationnel d'une salle.

### POS

Point de vente et caisse.

### PWA

Application web installable sur mobile.

### Module

Brique fonctionnelle activable selon le pack.

### Pack

Offre commerciale regroupant plusieurs modules.

### Salle active

Salle actuellement selectionnee dans la session de l'utilisateur.

## 30. Conclusion

SmartClub Pro est une plateforme SaaS complete pour l'exploitation d'une salle de sport moderne.

Sa force principale est la combinaison de plusieurs dimensions:

- gestion client;
- controle d'acces;
- caisse;
- reporting;
- espace membre;
- coaching;
- stock;
- RH;
- maintenance;
- multi-salle.

La plateforme est deja structuree pour accompagner des salles et reseaux de salles. Les prochaines grandes evolutions strategiques seront la multi-devise, l'affiliation marketing et le renforcement du stockage media en production.
