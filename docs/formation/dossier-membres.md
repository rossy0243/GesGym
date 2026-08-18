# Dossier de formation - Membres

> Fiches membres, preinscriptions, cartes, portail du membre.

Ce dossier rassemble la matiere brute du module. Il sert a rediger la
formation : il n'en est pas une. Les intitules proviennent du code, donc
de ce que le logiciel fait reellement, pas de ce qu'on croit qu'il fait.

## Parcours accessibles

### Application `members`

| Adresse | Vue | Nom interne |
|---|---|---|
| `` | `member_list` | `member_list` |
| `me/` | `member_portal` | `member_portal` |
| `me/goals/create/` | `member_goal_create` | `member_goal_create` |
| `me/goals/measurements/create/` | `member_goal_measurement_create` | `member_goal_measurement_create` |
| `me/change-password/` | `member_change_password` | `member_change_password` |
| `me/choose-coach/` | `member_choose_coach` | `member_choose_coach` |
| `me/choose-group-program/` | `member_choose_group_program` | `member_choose_group_program` |
| `me/coaching-feedback/` | `member_submit_coaching_feedback` | `member_submit_coaching_feedback` |
| `me/messages/<int:notification_id>/read/` | `member_notification_read` | `member_notification_read` |
| `me/qr/` | `member_portal_qr` | `member_portal_qr` |
| `me/subscription-request/` | `member_subscription_request` | `member_subscription_request` |
| `app/org-<int:organization_id>/icon-<int:size>.png` | `member_app_organization_icon` | `member_app_organization_icon` |
| `app/icon-<int:size>.png` | `member_app_icon` | `member_app_icon` |
| `app/manifest.json` | `member_app_manifest` | `member_app_manifest` |
| `app/service-worker.js` | `member_app_service_worker` | `member_app_service_worker` |
| `api/login/` | `member_api_login` | `member_api_login` |
| `api/logout/` | `member_api_logout` | `member_api_logout` |
| `api/me/` | `member_api_me` | `member_api_me` |
| `api/me/password/` | `member_api_password` | `member_api_password` |
| `api/me/notifications/<int:notification_id>/read/` | `member_api_notification_read` | `member_api_notification_read` |
| `api/me/subscription-requests/` | `member_api_subscription_request` | `member_api_subscription_request` |
| `api/me/goals/` | `member_api_goal_create` | `member_api_goal_create` |
| `api/me/goals/measurements/` | `member_api_goal_measurement_create` | `member_api_goal_measurement_create` |
| `api/me/coaches/choose/` | `member_api_choose_coach` | `member_api_choose_coach` |
| `api/me/group-programs/choose/` | `member_api_choose_group_program` | `member_api_choose_group_program` |
| `api/me/coaching-feedback/` | `member_api_coaching_feedback` | `member_api_coaching_feedback` |
| `preinscriptions/` | `pre_registration_list` | `pre_registration_list` |
| `preinscriptions/lien/regenerer/` | `regenerate_pre_registration_link` | `regenerate_pre_registration_link` |
| `preinscriptions/<int:pre_registration_id>/confirm/` | `confirm_pre_registration` | `confirm_pre_registration` |
| `preinscriptions/<int:pre_registration_id>/cancel/` | `cancel_pre_registration` | `cancel_pre_registration` |
| `preinscription/<uuid:token>/` | `public_pre_registration` | `public_pre_registration` |
| `create/` | `create_member` | `create_member` |
| `organization-logo/` | `member_organization_logo` | `organization_logo` |
| `edit/<int:member_id>/` | `edit_member` | `edit_member` |
| `<int:member_id>/delete/` | `delete_member` | `delete_member` |
| `suspend/<int:member_id>/` | `suspend_member` | `suspend_member` |
| `<int:member_id>/reset-password/` | `reset_member_password` | `reset_member_password` |
| `<int:member_id>/card.png` | `member_card_image` | `member_card_image` |
| `<int:member_id>/regenerate-qr/` | `regenerate_member_qr` | `regenerate_member_qr` |
| `<int:member_id>/` | `member_detail` | `member_detail` |
| `qr/<uuid:uuid>/` | `member_qr` | `member_qr` |
| `reactivate/<int:member_id>/` | `reactivate_member` | `reactivate_member` |

## Donnees manipulees

### `Member`

> Représente un membre d’un gym.
> Toutes les données sont isolées par gym (multi-tenant).


| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `user` | OneToOneField |
| `qr_code` | UUIDField |
| `qr_code_expires_at` | DateTimeField |
| `first_name` | CharField |
| `last_name` | CharField |
| `photo` | ImageField |
| `coach_notes` | TextField |
| `address` | TextField |
| `phone` | CharField |
| `email` | EmailField |
| `is_active` | BooleanField |
| `status` | CharField |
| `created_by` | ForeignKey |
| `registration_source` | CharField |
| `created_at` | DateTimeField |

Valeurs possibles `STATUS_CHOICES` :

```python
(('active', 'Active'), ('expired', 'Expired'), ('suspended', 'Suspended'))
```

Valeurs possibles `SOURCE_CHOICES` :

```python
((SOURCE_MANUAL, 'Saisie directe'), (SOURCE_PRE_REGISTRATION, 'Preinscription confirmee'), (SOURCE_OTHER, 'Autre / reprise de donnees'))
```

### `MemberGoal`

| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `member` | ForeignKey |
| `goal_type` | CharField |
| `target_weight` | DecimalField |
| `target_date` | DateField |
| `measurement_starter` | CharField |
| `note` | TextField |
| `status` | CharField |
| `created_by` | ForeignKey |
| `created_at` | DateTimeField |
| `updated_at` | DateTimeField |

Valeurs possibles `GOAL_TYPE_CHOICES` :

```python
((GOAL_LOSE_WEIGHT, 'Perte de poids'), (GOAL_GAIN_WEIGHT, 'Prise de poids'))
```

Valeurs possibles `STARTER_CHOICES` :

```python
((STARTER_MEMBER, 'Le membre commence les releves'), (STARTER_COACH, 'Le coach commence les releves'))
```

Valeurs possibles `STATUS_CHOICES` :

```python
((STATUS_ACTIVE, 'Actif'), (STATUS_ACHIEVED, 'Atteint'), (STATUS_CANCELLED, 'Annule'))
```

### `MemberWeightMeasurement`

| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `goal` | ForeignKey |
| `member` | ForeignKey |
| `weight` | DecimalField |
| `measured_at` | DateField |
| `note` | TextField |
| `source` | CharField |
| `recorded_by` | ForeignKey |
| `created_at` | DateTimeField |

Valeurs possibles `SOURCE_CHOICES` :

```python
((SOURCE_MEMBER, 'Membre'), (SOURCE_COACH, 'Coach'))
```

### `MemberPreRegistrationLink`

> Lien public permanent de preinscription pour une salle precise.
> Les demandes creees via ce lien expirent separement apres 7 jours.


| Champ | Type |
|---|---|
| `gym` | OneToOneField |
| `token` | UUIDField |
| `is_active` | BooleanField |
| `created_at` | DateTimeField |
| `updated_at` | DateTimeField |

### `MemberPreRegistration`

> Demande de preinscription publique. Elle ne devient un vrai membre
> qu'apres confirmation interne par un Owner ou Manager du gym.


| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `link` | ForeignKey |
| `member` | OneToOneField |
| `token` | UUIDField |
| `first_name` | CharField |
| `last_name` | CharField |
| `phone` | CharField |
| `email` | EmailField |
| `address` | TextField |
| `ip_address` | GenericIPAddressField |
| `status` | CharField |
| `created_at` | DateTimeField |
| `expires_at` | DateTimeField |
| `confirmed_at` | DateTimeField |
| `confirmed_by` | ForeignKey |
| `cancelled_at` | DateTimeField |
| `cancelled_by` | ForeignKey |

Valeurs possibles `STATUS_CHOICES` :

```python
((STATUS_PENDING, 'En attente'), (STATUS_CONFIRMED, 'Confirmee'), (STATUS_CANCELLED, 'Annulee'), (STATUS_EXPIRED, 'Expiree'))
```

## Qui a le droit de faire quoi

Garde-fous poses sur chaque vue. A traduire en langage metier dans la
formation : « la reception peut pointer mais pas consulter les salaires ».

| Action | Protections |
|---|---|
| `pre_registration_list` | `login_required` |
| `regenerate_pre_registration_link` | `login_required`<br>`require_POST` |
| `confirm_pre_registration` | `login_required`<br>`require_POST` |
| `cancel_pre_registration` | `login_required`<br>`require_POST` |
| `member_portal` | `login_required` |
| `member_goal_create` | `login_required`<br>`require_POST` |
| `member_goal_measurement_create` | `login_required`<br>`require_POST` |
| `member_submit_coaching_feedback` | `login_required`<br>`require_POST` |
| `member_change_password` | `login_required`<br>`require_POST` |
| `member_subscription_request` | `login_required`<br>`require_POST` |
| `member_choose_coach` | `login_required`<br>`require_POST` |
| `member_choose_group_program` | `login_required`<br>`require_POST` |
| `member_notification_read` | `login_required`<br>`require_POST` |
| `member_portal_qr` | `login_required` |
| `member_organization_logo` | `login_required` |
| `member_app_icon` | `login_required` |
| `member_api_login` | `csrf_exempt`<br>`require_POST` |
| `member_api_logout` | `csrf_exempt`<br>`require_POST` |
| `member_api_password` | `csrf_exempt`<br>`require_POST` |
| `member_api_notification_read` | `csrf_exempt`<br>`require_POST` |
| `member_api_subscription_request` | `csrf_exempt`<br>`require_POST` |
| `member_api_goal_create` | `csrf_exempt`<br>`require_POST` |
| `member_api_goal_measurement_create` | `csrf_exempt`<br>`require_POST` |
| `member_api_choose_coach` | `csrf_exempt`<br>`require_POST` |
| `member_api_choose_group_program` | `csrf_exempt`<br>`require_POST` |
| `member_api_coaching_feedback` | `csrf_exempt`<br>`require_POST` |
| `member_list` | `login_required` |
| `create_member` | `login_required` |
| `member_qr` | `login_required` |
| `edit_member` | `login_required` |
| `member_detail` | `login_required` |
| `member_card_image` | `login_required` |
| `regenerate_member_qr` | `login_required`<br>`require_POST` |
| `reset_member_password` | `login_required`<br>`require_POST` |
| `delete_member` | `login_required`<br>`require_POST` |
| `suspend_member` | `login_required`<br>`require_POST` |
| `reactivate_member` | `login_required`<br>`require_POST` |

## Regles metier appliquees

Refus opposes par le logiciel. Chacun merite une explication dans la
formation : pourquoi la regle existe, et que faire quand on la rencontre.

- Envoi refuse.
- L'email est obligatoire.
- L'objectif doit appartenir au meme gym que le membre.
- La mesure doit appartenir au meme gym que l'objectif.
- La mesure doit appartenir au meme gym que le membre.
- La mesure doit viser le meme membre que l'objectif.
- Le poids cible doit etre superieur a zero.
- Le poids releve doit etre superieur a zero.
- Un membre de cette salle utilise deja ce numero de telephone.
- Un membre de cette salle utilise deja cette adresse e-mail.
- Un membre existe deja avec ce telephone.
- Un membre existe deja avec cet email.
- Une preinscription active existe deja avec ce telephone.
- Une preinscription active existe deja avec cet email.

## Ce que l'utilisateur lit a l'ecran

Messages affiches apres une action. Ils donnent le vocabulaire exact a
employer dans la formation : l'apprenant doit reconnaitre ce qu'il verra.

### Confirmations

- Demande de souscription enregistree. Le paiement sera finalise quand le module de paiement sera branche.
- Membre modifié avec succès.
- Membre supprime avec succes.
- Merci, votre avis coaching a bien ete enregistre.
- Mot de passe temporaire regenere pour {valeur} {valeur}. {valeur}
- Nouveau lien de preinscription genere. L'ancien lien ne fonctionne plus.
- Objectif cree. La premiere pesee doit maintenant etre enregistree par {valeur}.
- Pesee enregistree dans votre suivi.
- Votre mot de passe a ete mis a jour.
- Vous avez rejoint le programme "{valeur}".
- {valeur} Membre : {valeur} {valeur}. Identifiant : {valeur}. Mot de passe temporaire : {valeur}. Il devra etre change a la premiere connexion. {valeur}
- {valeur} est maintenant votre coach referent.
- {valeur} {valeur} a ete reactive. {valeur}

### Avertissements

- Cette preinscription a expire. Elle reste consultable dans le filtre « Expirees », mais ne peut plus etre confirmee.
- {valeur} {valeur} a ete suspendu. {valeur}

### Refus et erreurs

- Ce membre n'a pas encore de compte utilisateur associe.
- Cette preinscription n'est plus en attente.
- L'objectif n'a pas pu etre enregistre. Verifiez les champs saisis.
- La pesee n'a pas pu etre enregistree. Verifiez les champs saisis.
- La premiere pesee doit etre enregistree par le coach.
- Un objectif actif existe deja sur ce compte.
- Votre avis n'a pas pu etre enregistre. Verifiez les notes renseignees.
- Votre formule actuelle ne permet pas de choisir un coach individuel.
- Votre formule actuelle ne permet pas de laisser un avis coaching individuel.
- Votre formule actuelle ne permet pas de laisser un avis sur un programme groupe.
- Votre formule actuelle ne permet pas de rejoindre un programme groupe.
- {valeur} : {valeur}

### Informations

- Preinscription annulee.

## Traces laissees dans le journal sensible

Actions consignees. Utile pour expliquer aux equipes ce qui est trace,
et rassurer sur ce qui ne l'est pas.

- `member.created`
- `member.deleted`
- `member.password_reset`
- `member.pre_registration_cancelled`
- `member.pre_registration_confirmed`
- `member.qr_regenerated`
- `member.reactivated`
- `member.suspended`
- `member.updated`

## Ecrans concernes

- `members\templates\members\member_list.html`
- `members\templates\members\member_portal.html`
- `members\templates\members\pre_registration_list.html`
- `members\templates\members\pre_registration_public.html`

## Comportements garantis par les tests

Chaque intitule decrit une promesse verifiee automatiquement. C'est la
meilleure source pour les cas limites a montrer en formation.

### MemberPreRegistrationTests
- member list exposes public pre registration link for current gym
- member list active filter excludes future subscriptions
- cashier cannot access member list
- reception can create and edit member
- create member sends credentials email
- reception can reset member password and view temporary credentials
- sensitive member actions require post
- only owner can delete member and action is logged
- managers and owners can regenerate member qr and action is logged
- cashier cannot reset member password
- owner and manager can suspend and reactivate member
- member list masks write and status actions by role
- member photo upload rejects non image file
- public pre registration creates pending request and sends received email
- public pre registration requires phone and email
- confirm pre registration creates member and default user
- pre registration list is scoped to current gym
- expired pending pre registrations are marked by command — _Elles sont conservees pour le suivi commercial, plus supprimees._

### MemberPortalTests
- member login redirects to mobile portal
- member portal shows identity card and subscription
- member portal hides future subscription from home overview
- member computed status is expired when only paused subscription exists
- member can read in app notification
- member can create weight goal with member starter
- member can record first weight when member starts goal
- member cannot record first weight when coach must start goal
- member portal shows waiting message when coach must start goal
- member detail json exposes subscription offers
- member detail json converts unexpected model values
- member detail uses same origin organization logo for card
- member offer only plan unlocks coach and group choices
- member portal hides unsent notifications
- member can create pending subscription request without activating plan
- member plans tab shows best selling plan first
- member portal messages tab shows unread badge and compact sections
- member can change password from portal
- member can choose a new coach from portal
- member can join group program from portal
- member can submit feedback for current coach
- member can submit feedback for current group program
- member cannot submit individual feedback without current individual rights
- member portal qr is limited to authenticated member
- member portal qr never rotates the printed code — _Le QR est imprime sur la carte : le consulter ne doit pas le changer._
- member api payload never rotates the printed code
- rotate member qrcodes command rotates expired members
- pwa manifest and service worker are available
- pwa manifest uses authenticated member organization logo
- pwa manifest keeps the gym brand without session cookie
- pwa manifest falls back when the organization is unknown
- member api login and me payload
- member api rejects non member account
- member api me scopes to current member gym
- member api actions update existing portal models

### PreRegistrationLinkHardeningTests

> Lien public : domaine partageable, revocation, protection anti-robot.

- link uses public domain not browsing address
- local link is flagged to the user
- regenerating the link breaks the previous one
- regeneration keeps existing requests
- reception cannot regenerate the link
- honeypot field rejects bot submission
- submissions are capped per ip
- another ip is not blocked by a saturated one
- visitor ip is recorded
- ip behind proxy is taken from forwarded header

### PreRegistrationConfirmationHardeningTests

> Remise des identifiants, atomicite de la confirmation, sort des expirees.

- credentials message does not auto dismiss
- resetting password issues new credentials and emails them — _Filet de securite quand les identifiants d'origine ont ete perdus._
- reset credentials are shown on the member list
- model refuses to confirm a duplicate member
- confirmation leaves nothing behind when it fails
- expired requests are marked not deleted
- confirming an expired request keeps it for follow up
- expired requests are listed under their own filter
- cleanup command marks instead of deleting

### MemberCreationHardeningTests

> Creation et modification d'un membre : doublons, erreurs, identifiants.

- duplicate phone is reported instead of crashing
- duplicate email is reported instead of crashing
- same phone is allowed in another gym
- two members without email can coexist
- email is required in the form
- invalid form reports the reason
- credentials message does not auto dismiss
- member name is escaped in the html message
- editing a member keeps its own phone
- editing cannot steal another member phone

### MemberQrCodeStabilityTests

> Le QR est imprime sur les cartes : il ne change que sur decision humaine.

- viewing details never changes the qr code
- reading the qr image never changes it
- new members get a long lived qr — _Une carte imprimee doit rester valable bien au-dela de quelques jours._
- manager can regenerate the qr
- owner can regenerate the qr
- reception cannot regenerate the qr
- regeneration flag is a boolean in the payload
- member portal url uses the public domain

### MemberPasswordResetEmailTests

> L'e-mail de reinitialisation est distinct de celui de creation.

- reset email does not welcome an existing member
- reset email has its own subject and type
- reset email carries the new credentials
- reset email does not attach the membership card — _Le QR code n'a pas change : rejoindre la carte n'aurait pas de sens._
- reset email warns about an unexpected request
- creation still sends the welcome email

### SuspendedMemberTests

> Suspension : messages fideles, portail bride, actions refusees.

- message mentions the paused subscription
- message admits when there is no subscription
- reactivation message states the recovered days
- reactivation message when the pause was shorter than a day
- portal shows the suspension banner
- portal hides the subscribe button
- banner disappears after reactivation
- subscription request is refused from the web
- subscription request is refused from the mobile app
- choosing a coach is refused from the mobile app
- an active member is not blocked

### MemberDownloadTests

> Telechargement du QR code et de la carte membre.

- downloaded qr is high resolution
- qr size can be requested
- absurd qr size is capped
- invalid qr size falls back to the default
- qr modules are sharp — _Deux nuances seulement : aucun reechantillonnage n'a floute le code._
- qr is shown inline by default
- qr download carries a readable filename
- card download carries a readable filename
- card is shown inline by default
- detail payload exposes download urls
- another gym member cannot be downloaded

### RegistrationAuthorshipTests

> Toute fiche membre porte le nom de qui l'a inscrite.

- a manually created member carries its author
- the author label prefers the full name
- the author label falls back to the username
- a member without author is not attributed to anyone
- the member sheet shows who registered it
- a confirmed pre registration names its confirmer
- the member born from a confirmation carries the confirmer
- the confirmation is traced in the sensitive log
- the list shows who confirmed
- a cancelled pre registration names its author
- the cancellation is traced in the sensitive log
- an already handled request cannot be cancelled again

## A completer par un humain

Le code ne dit pas tout. Avant de rediger, il faut trancher :

- Qui suit cette formation : reception, caisse, gerant, proprietaire ?
- Quelles taches quotidiennes reelles doit-on savoir faire a la fin ?
- Quels incidents arrivent souvent et doivent etre traites en exercice ?
- Quelles habitudes de la salle different de ce que propose le logiciel ?

