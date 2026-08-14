# Dossier de formation - Coaching

> Coachs, affectations, programmes de groupe, portail coach.

Ce dossier rassemble la matiere brute du module. Il sert a rediger la
formation : il n'en est pas une. Les intitules proviennent du code, donc
de ce que le logiciel fait reellement, pas de ce qu'on croit qu'il fait.

## Parcours accessibles

### Application `coaching`

| Adresse | Vue | Nom interne |
|---|---|---|
| `portal/` | `views.coach_portal` | `coach_portal` |
| `portal/members/<int:member_id>/` | `views.coach_member_detail` | `coach_member_detail` |
| `portal/members/<int:member_id>/weight/` | `views.coach_member_weight_measurement_create` | `coach_member_weight_measurement_create` |
| `coaches/` | `views.coach_list` | `list` |
| `coaches/create/` | `views.coach_create` | `create` |
| `coaches/<int:coach_id>/` | `views.coach_detail` | `detail` |
| `coaches/<int:coach_id>/update/` | `views.coach_update` | `update` |
| `coaches/<int:coach_id>/delete/` | `views.coach_delete` | `delete` |
| `coaches/<int:coach_id>/assign/` | `views.assign_member` | `assign_member` |
| `coaches/<int:coach_id>/remove/<int:member_id>/` | `views.remove_member` | `remove_member` |
| `programs/` | `views.group_program_list` | `group_program_list` |
| `programs/create/` | `views.group_program_create` | `group_program_create` |
| `programs/<int:program_id>/` | `views.group_program_detail` | `group_program_detail` |
| `programs/<int:program_id>/update/` | `views.group_program_update` | `group_program_update` |
| `programs/<int:program_id>/delete/` | `views.group_program_delete` | `group_program_delete` |

## Donnees manipulees

### `CoachSpecialty`

> Specialite configurable par gym pour standardiser les fiches coach.


| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `name` | CharField |
| `is_active` | BooleanField |
| `created_at` | DateTimeField |

### `Coach`

> Coach du gym (version simple V1)


| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `user` | OneToOneField |
| `name` | CharField |
| `phone` | CharField |
| `specialty` | CharField |
| `members` | ManyToManyField |
| `is_active` | BooleanField |
| `created_at` | DateTimeField |

### `GroupCoachingProgram`

| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `coach` | ForeignKey |
| `name` | CharField |
| `objective` | CharField |
| `description` | TextField |
| `capacity` | PositiveIntegerField |
| `participants` | ManyToManyField |
| `is_active` | BooleanField |
| `created_at` | DateTimeField |

### `CoachAssignment`

| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `coach` | ForeignKey |
| `member` | ForeignKey |
| `started_at` | DateTimeField |
| `ended_at` | DateTimeField |

### `CoachingFollowUp`

| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `coach` | ForeignKey |
| `member` | ForeignKey |
| `interaction_type` | CharField |
| `summary` | TextField |
| `next_action` | CharField |
| `next_follow_up_at` | DateField |
| `created_at` | DateTimeField |

Valeurs possibles `INTERACTION_CHOICES` :

```python
((INTERACTION_CALL, 'Appel'), (INTERACTION_MESSAGE, 'Message'), (INTERACTION_ASSESSMENT, 'Bilan'), (INTERACTION_SESSION, 'Seance'), (INTERACTION_FOLLOW_UP, 'Relance'))
```

### `CoachingFeedback`

| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `member` | ForeignKey |
| `coach` | ForeignKey |
| `group_program` | ForeignKey |
| `overall_rating` | PositiveSmallIntegerField |
| `listening_rating` | PositiveSmallIntegerField |
| `clarity_rating` | PositiveSmallIntegerField |
| `motivation_rating` | PositiveSmallIntegerField |
| `availability_rating` | PositiveSmallIntegerField |
| `comment` | TextField |
| `wants_contact` | BooleanField |
| `created_at` | DateTimeField |

## Qui a le droit de faire quoi

Garde-fous poses sur chaque vue. A traduire en langage metier dans la
formation : « la reception peut pointer mais pas consulter les salaires ».

| Action | Protections |
|---|---|
| `coach_list` | `login_required`<br>`module_required('COACHING')`<br>`role_required(COACHING_ROLES)` |
| `coach_detail` | `login_required`<br>`module_required('COACHING')`<br>`role_required(COACHING_ROLES)` |
| `coach_create` | `login_required`<br>`module_required('COACHING')`<br>`role_required(COACHING_ROLES)` |
| `coach_update` | `login_required`<br>`module_required('COACHING')`<br>`role_required(COACHING_ROLES)` |
| `coach_delete` | `login_required`<br>`module_required('COACHING')`<br>`role_required(COACHING_ROLES)` |
| `assign_member` | `login_required`<br>`require_POST`<br>`module_required('COACHING')`<br>`role_required(COACHING_ROLES)` |
| `remove_member` | `login_required`<br>`require_POST`<br>`module_required('COACHING')`<br>`role_required(COACHING_ROLES)` |
| `group_program_list` | `login_required`<br>`module_required('COACHING')`<br>`role_required(COACHING_ROLES)` |
| `group_program_detail` | `login_required`<br>`module_required('COACHING')`<br>`role_required(COACHING_ROLES)` |
| `group_program_create` | `login_required`<br>`module_required('COACHING')`<br>`role_required(COACHING_ROLES)` |
| `group_program_update` | `login_required`<br>`module_required('COACHING')`<br>`role_required(COACHING_ROLES)` |
| `group_program_delete` | `login_required`<br>`module_required('COACHING')`<br>`role_required(COACHING_ROLES)` |
| `coach_portal` | `login_required`<br>`module_required('COACHING')`<br>`role_required(COACH_PORTAL_ROLES)` |
| `coach_member_detail` | `login_required`<br>`module_required('COACHING')`<br>`role_required(COACH_PORTAL_ROLES)` |
| `coach_member_weight_measurement_create` | `login_required`<br>`require_POST`<br>`module_required('COACHING')`<br>`role_required(COACH_PORTAL_ROLES)` |

## Regles metier appliquees

Refus opposes par le logiciel. Chacun merite une explication dans la
formation : pourquoi la regle existe, et que faire quand on la rencontre.

- Ce programme groupe est deja complet.
- La capacite doit etre superieure a zero.
- La capacite du programme groupe serait depassee.
- Le coach de l'affectation doit appartenir au meme gym.
- Le coach de l'avis doit appartenir au meme gym.
- Le coach doit suivre ce membre avant d'enregistrer un suivi.
- Le coach du programme doit appartenir au meme gym.
- Le coach du suivi doit appartenir au meme gym.
- Le membre de l'affectation doit appartenir au meme gym.
- Le membre de l'avis doit appartenir au meme gym.
- Le membre doit appartenir au meme gym que le coach.
- Le membre doit appartenir au meme gym que le programme.
- Le membre doit avoir un abonnement actif avec acces au coaching groupe.
- Le membre doit avoir un abonnement actif avec coaching individuel.
- Le membre doit etre rattache a ce coach pour laisser un avis.
- Le membre doit participer au programme pour laisser un avis.
- Le membre du suivi doit appartenir au meme gym.
- Le programme groupe de l'avis doit appartenir au meme gym.
- Le programme groupe doit etre relie au meme coach.
- Les notes doivent etre comprises entre 1 et 5.
- Un coach ne peut suivre que les membres de son gym.
- Un programme groupe ne peut contenir que les membres de son gym.

## Ce que l'utilisateur lit a l'ecran

Messages affiches apres une action. Ils donnent le vocabulaire exact a
employer dans la formation : l'apprenant doit reconnaitre ce qu'il verra.

### Confirmations

- Coach "{valeur}" cree avec succes.
- Coach "{valeur}" desactive avec succes.
- Coach "{valeur}" modifie avec succes.
- Membre "{valeur} {valeur}" assigne a {valeur}.
- Membre "{valeur}" retire de {valeur}.
- Pesee enregistree dans le suivi du membre.
- Programme "{valeur}" cree avec succes.
- Programme "{valeur}" desactive avec succes.
- Programme "{valeur}" modifie avec succes.
- Suivi enregistre avec succes.

### Refus et erreurs

- La pesee n'a pas pu etre enregistree. Verifie les champs saisis.
- La premiere pesee doit etre enregistree par le membre.
- Le suivi n'a pas pu etre enregistre. Verifie les champs saisis.
- Membre invalide pour ce coach.

## Traces laissees dans le journal sensible

Actions consignees. Utile pour expliquer aux equipes ce qui est trace,
et rassurer sur ce qui ne l'est pas.

- `coaching.coach_deactivated`
- `coaching.member_assigned`
- `coaching.member_unassigned`
- `coaching.program_deactivated`

## Ecrans concernes

- `coaching\templates\coaching\coach_confirm_delete.html`
- `coaching\templates\coaching\coach_detail.html`
- `coaching\templates\coaching\coach_form.html`
- `coaching\templates\coaching\coach_list.html`
- `coaching\templates\coaching\coach_member_detail.html`
- `coaching\templates\coaching\coach_portal.html`
- `coaching\templates\coaching\coach_profile_missing.html`
- `coaching\templates\coaching\group_program_confirm_delete.html`
- `coaching\templates\coaching\group_program_detail.html`
- `coaching\templates\coaching\group_program_form.html`
- `coaching\templates\coaching\group_program_list.html`

## Comportements garantis par les tests

Chaque intitule decrit une promesse verifiee automatiquement. C'est la
meilleure source pour les cas limites a montrer en formation.

### CoachingTenantTests
- coach list is scoped to current gym
- coach list search filters results
- other gym coach detail is not accessible
- assign member uses current gym only
- assign member rejects other gym member
- assign member rejects member without individual coaching rights
- assign member accepts member with individual coaching offer only
- model rejects cross gym member assignment
- remove member uses current gym only
- member assignment actions require post
- form pages render without gym id urls
- general dashboard includes scoped coaching kpis
- coach mobile portal is available for coach role
- coach portal hides member without current coaching access
- coach portal hides alerts for members without current coaching access
- same user cannot be active coach in two gyms
- group program pages are scoped to current gym
- group program rejects member without group coaching rights
- group program accepts member with group coaching offer only
- coach can open member follow up detail
- coach can record first weight when coach starts goal
- coach cannot record first weight when member must start goal
- coach member detail shows weight goal section
- coach cannot open member outside portfolio
- coach can add follow up for assigned member
- coach portal shows follow up shortcuts
- coach portal surfaces first contact alerts
- coach portal surfaces sensitive feedback alerts
- coach portal builds unified priority queue
- manager dashboard shows follow up alerts
- manager dashboard shows first contact and stale follow up alerts
- manager dashboard shows recent feedbacks
- manager dashboard shows sensitive feedback alerts
- manager dashboard builds priority queue
- reassigning member closes old assignment and opens new one

### CoachProfileBindingTests

> Le rattachement d'un compte a une fiche coach est un acte de gestion.

- a namesake never inherits another coach profile — _« Jean » ne doit pas hériter de la fiche de « Jean-Pierre »._
- a namesake sees no member
- no coach profile is created on the fly
- the page explains what to ask for
- a linked coach reaches the portal
- a manager can link an account from the coach form
- only coach role accounts are offered
- an account already linked is not offered elsewhere
- its own account stays offered when editing

## A completer par un humain

Le code ne dit pas tout. Avant de rediger, il faut trancher :

- Qui suit cette formation : reception, caisse, gerant, proprietaire ?
- Quelles taches quotidiennes reelles doit-on savoir faire a la fin ?
- Quels incidents arrivent souvent et doivent etre traites en exercice ?
- Quelles habitudes de la salle different de ce que propose le logiciel ?

