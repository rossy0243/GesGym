# Manuel Administrateur SaaS GesGym

Version du manuel : basee sur l'application actuellement presente dans ce depot.

## 1. Objectif

Ce document est reserve a l'equipe qui administre la plateforme GesGym.

Il sert de reference pour :

- creer et configurer un client
- choisir le bon pack
- verifier l'activation des modules
- basculer une organisation d'un pack a l'autre
- comprendre la relation entre organisation, salles et modules

Capture de reference :

![Liste des organisations SaaS](D:/GesGym/docs/screenshots/saas-organizations-final.png)

## 2. Perimetre SaaS

Le back-office SaaS gere principalement :

- les `Organization`
- les `Gym`
- les `Owner`
- les utilisateurs internes si intervention exceptionnelle
- les packs commerciaux
- la synchronisation technique des modules

Ce manuel ne couvre pas l'exploitation quotidienne d'une salle. Pour cela, utiliser [MANUEL_CLIENT_GESGYM.md](D:/GesGym/MANUEL_CLIENT_GESGYM.md).

## 3. Architecture de tenancy

### 3.1 Organisation et salles

- une `Organization` represente un client SaaS
- une organisation peut posseder plusieurs `Gym`
- les donnees metier restent filtrees par gym
- un `owner` peut circuler entre les gyms de sa propre organisation

### 3.2 Activation technique des modules

Le choix commercial est porte par `Organization.subscription_pack`.

Les modules actifs sont ensuite materialises au niveau de chaque salle via `GymModule`.

Flux technique :

```text
Organization.subscription_pack
-> get_pack_module_codes(pack)
-> ensure_gym_modules_for_pack(gym, pack)
-> GymModule(gym, module, is_active)
-> module_required("CODE")
```

En pratique :

- le pilotage commercial est au niveau organisation
- l'activation runtime reste lue au niveau gym

## 4. Packs et activation des modules

### 4.1 Pack Club

Le `Pack Club` active :

- `MEMBERS`
- `SUBSCRIPTIONS`
- `POS`
- `ACCESS`
- `NOTIFICATIONS`
- `CORE`

Lecture produit :

- membres
- abonnements
- caisse
- controle d'acces
- messages membres in-app
- rapports

### 4.2 Pack Premium

Le `Pack Premium` active :

- tout le `Pack Club`
- `PRODUCTS`
- `RH`
- `MACHINES`
- `COACHING`

Lecture produit :

- stock et produits
- ressources humaines
- machines et maintenances
- coaching

### 4.3 Principes a retenir

- un pack unique s'applique a toute l'organisation
- tous les gyms de l'organisation sont resynchronises sur ce pack
- le systeme reste compatible avec une lecture des modules par gym
- les vues continuent de s'appuyer sur `module_required(...)`

## 5. Operations admin principales

### 5.1 Creer un client depuis l'admin

Le flux de creation `Owner + organisation + gyms` demande maintenant :

- prenom et nom de l'owner
- email de l'owner
- organisation existante ou nouvelle organisation
- liste des gyms a creer
- `Pack Club` ou `Pack Premium`

Resultat attendu :

- creation de l'organisation si necessaire
- creation de l'owner
- creation des gyms
- affectation du role owner sur les gyms
- synchronisation automatique des modules selon le pack

Repere visuel utile :

- la liste des organisations affiche directement la colonne `subscription pack`
- c'est le point d'entree le plus simple pour verifier rapidement le niveau d'offre actif sur un client

### 5.2 Organisation existante

Si une organisation existe deja :

- le workflow peut la reutiliser
- les gyms actifs existants peuvent etre conserves
- le pack selectionne devient le nouveau pack de reference de l'organisation
- les gyms concernes sont resynchronises

### 5.3 Verification post-creation

Verifier systematiquement :

- que l'organisation est active
- que l'owner est actif
- que `force_password_change` est bien positionne
- que les gyms attendus existent
- que les modules actifs correspondent au pack choisi

### 5.4 Recuperer les mots de passe temporaires

Les comptes crees par la plateforme utilisent maintenant un mot de passe temporaire fort et unique.

Principe :

- le mot de passe temporaire doit etre communique juste apres creation ou reinitialisation
- l'utilisateur devra le remplacer a la premiere connexion
- le systeme positionne `force_password_change=True` sur ces comptes

Ou recuperer le mot de passe selon le flux :

- creation d'un `Owner` client par l'admin SaaS : le mot de passe apparait dans la page de recapitulatif [D:/GesGym/compte/templates/admin/create_owner_success.html](D:/GesGym/compte/templates/admin/create_owner_success.html)
- creation d'un employe interne depuis les parametres : le mot de passe apparait dans le message de succes genere par [D:/GesGym/core/views.py](D:/GesGym/core/views.py)
- reinitialisation d'un employe interne : le mot de passe apparait aussi dans le message de succes genere par [D:/GesGym/core/views.py](D:/GesGym/core/views.py)
- creation d'un membre : le mot de passe apparait dans le message de succes genere par [D:/GesGym/members/views.py](D:/GesGym/members/views.py)
- confirmation d'une preinscription : le mot de passe apparait dans le message de succes genere par [D:/GesGym/members/pre_registration_views.py](D:/GesGym/members/pre_registration_views.py)

Limite connue :

- pour la creation ou la reinitialisation d'un utilisateur interne depuis l'espace owner gym, le mot de passe temporaire est bien genere mais n'est pas encore restitue a l'ecran dans [D:/GesGym/compte/views.py](D:/GesGym/compte/views.py)
- dans ce flux precis, il ne faut donc pas promettre une communication immediate du mot de passe tant que ce point n'a pas ete complete

## 6. Changement de pack

### 6.1 Depuis l'admin Organization

Deux possibilites existent :

- modifier directement le champ `subscription_pack` d'une organisation puis enregistrer
- utiliser les actions de masse sur la liste des organisations

Actions disponibles dans la liste des organisations :

- `Basculer les organisations selectionnees vers le Pack Club`
- `Basculer les organisations selectionnees vers le Pack Premium`

### 6.2 Effets d'une bascule

Quand un pack change :

- `Organization.subscription_pack` est mis a jour
- chaque gym de l'organisation est resynchronise
- les modules non compris dans le pack cible sont desactives
- les modules compris dans le pack cible sont actives

### 6.3 Cas typiques

Passage `Club -> Premium` :

- active produits, RH, machines et coaching

Passage `Premium -> Club` :

- desactive produits, RH, machines et coaching
- conserve le socle membres, abonnements, POS, acces, notifications, rapports

## 7. Controles et verifications

### 7.1 Verifications fonctionnelles

Apres creation ou bascule de pack :

- ouvrir une salle du client
- verifier la navigation visible
- verifier qu'un module non inclus ne s'affiche plus
- verifier qu'un module inclus est bien accessible

### 7.2 Verifications techniques

Commandes utiles :

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test organizations.tests --settings=smartclub.settings_test
.\.venv\Scripts\python.exe manage.py test compte.tests --settings=smartclub.settings_test
```

### 7.3 Points de coherence a verifier

- `Pack Club` doit inclure `NOTIFICATIONS` pour les messages membre in-app
- `Pack Club` doit inclure `CORE` pour les rapports
- `Pack Premium` doit inclure `COACHING` si l'espace coaching doit etre vendu

## 8. Bonnes pratiques d'administration

- choisir le pack avant de communiquer l'acces au client
- eviter les modifications manuelles gym par gym sauf cas de maintenance exceptionnelle
- documenter toute bascule de pack commerciale importante
- verifier les modules sur au moins une salle apres changement

## 9. Depannage rapide

### 9.1 "Le client ne voit pas un module vendu"

Verifier :

- le `subscription_pack` de l'organisation
- les `GymModule` de la salle active
- la presence d'un role autorise pour l'utilisateur

### 9.2 "Le client voit encore un module retire"

Verifier :

- que la bascule de pack a bien ete enregistree
- que la salle concernee appartient bien a cette organisation
- qu'une resynchronisation a bien eu lieu

### 9.3 "Les menus ne correspondent pas au pack"

Rappel :

- les menus dependent a la fois du pack, des `GymModule`, du role et de la salle active
- un module techniquement actif ne sera pas visible si le role courant n'a pas les droits

### 9.4 "Le message de succes n'apparait pas comme un toast"

Le comportement actuel des messages n'est pas uniforme sur toute l'application.

Etat reel :

- le back-office principal rend les messages dans un conteneur Bootstrap toast via [D:/GesGym/templates/base.html](D:/GesGym/templates/base.html)
- certaines pages affichent effectivement les messages en toast, par exemple la liste des membres
- les pages d'authentification utilisent des messages inline dans [D:/GesGym/compte/templates/compte/auth_base.html](D:/GesGym/compte/templates/compte/auth_base.html)
- le portail membre utilise aussi des messages inline dans [D:/GesGym/members/templates/members/member_portal.html](D:/GesGym/members/templates/members/member_portal.html)

Conclusion admin :

- il faut verifier la presence du message, pas seulement son format visuel
- en cas de doute sur un flux sensible, controler le contenu du message affiche avant de quitter l'ecran
