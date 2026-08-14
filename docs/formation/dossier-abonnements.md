# Dossier de formation - Abonnements

> Formules, offres, souscriptions et renouvellements.

Ce dossier rassemble la matiere brute du module. Il sert a rediger la
formation : il n'en est pas une. Les intitules proviennent du code, donc
de ce que le logiciel fait reellement, pas de ce qu'on croit qu'il fait.

## Parcours accessibles

### Application `subscriptions`

| Adresse | Vue | Nom interne |
|---|---|---|
| `subscription-plans/` | `plan_list` | `subscription_plan_list` |
| `subscription-plans/create/` | `create_plan` | `create_subscription_plan` |
| `subscription-plans/edit/<int:plan_id>/` | `edit_plan` | `edit_subscription_plan` |
| `subscription-plans/delete/<int:plan_id>/` | `delete_plan` | `delete_subscription_plan` |
| `subscription-offers/create/` | `create_offer` | `create_subscription_offer` |
| `subscription-offers/edit/<int:offer_id>/` | `edit_offer` | `edit_subscription_offer` |
| `subscriptions/create/` | `create_subscription` | `create_subscription` |

## Donnees manipulees

### `SubscriptionOffer`

| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `name` | CharField |
| `code` | SlugField |
| `description` | TextField |
| `category` | CharField |
| `grants_individual_coaching` | BooleanField |
| `grants_group_coaching` | BooleanField |
| `is_active` | BooleanField |
| `created_at` | DateTimeField |

Valeurs possibles `CATEGORY_CHOICES` :

```python
((CATEGORY_ACCESS, 'Acces'), (CATEGORY_COACHING, 'Coaching'), (CATEGORY_CLASS, 'Cours'), (CATEGORY_OTHER, 'Autre'))
```

### `SubscriptionPlan`

| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `name` | CharField |
| `duration_days` | PositiveIntegerField |
| `price` | DecimalField |
| `description` | TextField |
| `offers` | ManyToManyField |
| `coaching_mode` | CharField |
| `coaching_level` | CharField |
| `is_active` | BooleanField |
| `created_at` | DateTimeField |

Valeurs possibles `COACHING_MODE_CHOICES` :

```python
((COACHING_MODE_NONE, 'Aucun coaching'), (COACHING_MODE_INDIVIDUAL, 'Coaching individuel'), (COACHING_MODE_GROUP, 'Programme groupe'), (COACHING_MODE_BOTH, 'Coaching individuel et groupe'))
```

Valeurs possibles `COACHING_LEVEL_CHOICES` :

```python
((COACHING_LEVEL_STANDARD, 'Standard'), (COACHING_LEVEL_PREMIUM, 'Premium'), (COACHING_LEVEL_INTENSIVE, 'Intensif'))
```

### `MemberSubscription`

| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `member` | ForeignKey |
| `plan` | ForeignKey |
| `start_date` | DateField |
| `end_date` | DateField |
| `is_active` | BooleanField |
| `auto_renew` | BooleanField |
| `created_at` | DateTimeField |
| `is_paused` | BooleanField |
| `paused_at` | DateTimeField |

### `SubscriptionRequest`

> Intention de souscription creee depuis l'espace membre.
> L'abonnement actif sera cree plus tard apres validation du paiement.


| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `member` | ForeignKey |
| `plan` | ForeignKey |
| `requested_by` | ForeignKey |
| `status` | CharField |
| `price_usd` | DecimalField |
| `aggregator_reference` | CharField |
| `notes` | TextField |
| `created_at` | DateTimeField |
| `updated_at` | DateTimeField |

Valeurs possibles `STATUS_CHOICES` :

```python
((STATUS_PENDING, 'En attente'), (STATUS_AWAITING_PAYMENT, 'Paiement en cours'), (STATUS_PAID, 'Payee'), (STATUS_CANCELLED, 'Annulee'), (STATUS_FAILED, 'Echec'))
```

## Qui a le droit de faire quoi

Garde-fous poses sur chaque vue. A traduire en langage metier dans la
formation : « la reception peut pointer mais pas consulter les salaires ».

| Action | Protections |
|---|---|
| `plan_list` | `login_required`<br>`module_required('SUBSCRIPTIONS')` |
| `create_plan` | `login_required`<br>`module_required('SUBSCRIPTIONS')` |
| `edit_plan` | `login_required`<br>`module_required('SUBSCRIPTIONS')` |
| `delete_plan` | `login_required`<br>`require_POST`<br>`module_required('SUBSCRIPTIONS')` |
| `create_offer` | `login_required`<br>`module_required('SUBSCRIPTIONS')` |
| `edit_offer` | `login_required`<br>`module_required('SUBSCRIPTIONS')` |
| `create_subscription` | `login_required`<br>`module_required('SUBSCRIPTIONS')` |

## Regles metier appliquees

Refus opposes par le logiciel. Chacun merite une explication dans la
formation : pourquoi la regle existe, et que faire quand on la rencontre.

- Ce membre a déjà un abonnement actif.
- Ce membre n'appartient pas au gym courant.
- Cette formule n'appartient pas au gym courant.
- La date de fin doit être après la date de début.
- La formule n'appartient pas au gym de cet abonnement.
- La formule n'appartient pas au gym de la demande.
- Le membre et la formule doivent appartenir au meme gym.
- Le membre n'appartient pas au gym de cet abonnement.
- Le membre n'appartient pas au gym de la demande.
- Le nom de l'offre est obligatoire.
- Le nom de la formule est obligatoire.
- Une formule avec ce nom existe deja dans ce gym.
- Une offre avec ce nom existe deja dans ce gym.

## Ce que l'utilisateur lit a l'ecran

Messages affiches apres une action. Ils donnent le vocabulaire exact a
employer dans la formation : l'apprenant doit reconnaitre ce qu'il verra.

### Confirmations

- Abonnement enregistre avec succes et paiement POS cree: {valeur} {valeur}.
- Formule creee avec succes.
- Formule desactivee pour conserver l'historique.
- Formule supprimee.
- Offre creee avec succes.
- Offre modifiee avec succes.

### Avertissements

- {valeur} {valeur} est toujours suspendu et n'aura pas acces a la salle. Reactivez son compte depuis sa fiche membre.

### Refus et erreurs

- Une formule avec ce nom existe deja dans ce gym.

### Informations

- {valeur} jour(s) restant(s) de l'abonnement precedent ont ete reportes. Echeance au {valeur}.

## Traces laissees dans le journal sensible

Actions consignees. Utile pour expliquer aux equipes ce qui est trace,
et rassurer sur ce qui ne l'est pas.

- `subscription.created`
- `subscription.offer_created`
- `subscription.offer_updated`
- `subscription.plan_created`
- `subscription.plan_deactivated`
- `subscription.plan_deleted`
- `subscription.plan_updated`

## Ecrans concernes

- `subscriptions\templates\subscriptions\create_subscription.html`
- `subscriptions\templates\subscriptions\partials\subscription_plan_form.html`
- `subscriptions\templates\subscriptions\subscription_plan_list.html`

## Comportements garantis par les tests

Chaque intitule decrit une promesse verifiee automatiquement. C'est la
meilleure source pour les cas limites a montrer en formation.

### SubscriptionTenantSafetyTests
- subscription form querysets are scoped to current gym
- plan form scopes available offers to current gym
- subscription form rejects cross gym post data
- model rejects cross gym member and plan
- plan name uniqueness is scoped to gym
- create member subscription sets gym and replaces active subscription
- plan exposes coaching rights payload
- plan can grant coaching access via parametrable offer
- plan form derives legacy coaching mode from selected offers
- plan list requires active module
- create plan can assign offers
- delete plan requires post
- create offer creates offer for current gym
- edit offer returns json payload for modal
- edit offer updates existing offer
- edit plan updates assigned offers and mode
- create subscription shows consistent success message
- create subscription requires open register for paid activation
- plan list marks best selling plan
- plan list excludes future subscriptions from active counts

### SubscriptionRenewalTests

> Renouvellement anticipe et encaissement d'un membre suspendu.

- early renewal carries the remaining days over
- the carried over days are announced
- a first subscription gets exactly the plan duration
- an expired subscription carries nothing over
- only one subscription stays active
- paying for a suspended member warns the desk
- suspended members are flagged in the dropdown
- an active member is not flagged

## A completer par un humain

Le code ne dit pas tout. Avant de rediger, il faut trancher :

- Qui suit cette formation : reception, caisse, gerant, proprietaire ?
- Quelles taches quotidiennes reelles doit-on savoir faire a la fin ?
- Quels incidents arrivent souvent et doivent etre traites en exercice ?
- Quelles habitudes de la salle different de ce que propose le logiciel ?

