# Dossier de formation - Messages membres

> Envois groupes vers l'espace membre, annulation, suppression.

Ce dossier rassemble la matiere brute du module. Il sert a rediger la
formation : il n'en est pas une. Les intitules proviennent du code, donc
de ce que le logiciel fait reellement, pas de ce qu'on croit qu'il fait.

## Parcours accessibles

### Application `notifications`

| Adresse | Vue | Nom interne |
|---|---|---|
| `` | `notification_dashboard` | `dashboard` |
| `envois/<uuid:batch_id>/annuler/` | `cancel_message_batch` | `cancel_message_batch` |
| `envois/<uuid:batch_id>/supprimer/` | `delete_message_batch` | `delete_message_batch` |

## Donnees manipulees

### `Notification`

> Notifications envoyees aux membres.
> La V1 utilise le canal in-app; SMS, Email et WhatsApp restent disponibles
> pour les integrations futures.


| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `member` | ForeignKey |
| `title` | CharField |
| `message` | TextField |
| `channel` | CharField |
| `status` | CharField |
| `sent_at` | DateTimeField |
| `read_at` | DateTimeField |
| `created_at` | DateTimeField |
| `sent_by` | ForeignKey |
| `batch_id` | UUIDField |
| `cancelled_at` | DateTimeField |
| `cancelled_by` | ForeignKey |
| `error_message` | TextField |

Valeurs possibles `STATUS_CHOICES` :

```python
((STATUS_PENDING, 'Pending'), (STATUS_SENT, 'Sent'), (STATUS_FAILED, 'Failed'), (STATUS_CANCELLED, 'Annulee'))
```

Valeurs possibles `CHANNEL_CHOICES` :

```python
((CHANNEL_IN_APP, 'In-app'), (CHANNEL_SMS, 'SMS'), (CHANNEL_WHATSAPP, 'WhatsApp'), (CHANNEL_EMAIL, 'Email'))
```

## Qui a le droit de faire quoi

Garde-fous poses sur chaque vue. A traduire en langage metier dans la
formation : « la reception peut pointer mais pas consulter les salaires ».

| Action | Protections |
|---|---|
| `notification_dashboard` | `login_required`<br>`role_required(NOTIFICATION_ROLES)`<br>`module_required('NOTIFICATIONS')` |
| `cancel_message_batch` | `login_required`<br>`role_required(NOTIFICATION_ROLES)`<br>`require_POST`<br>`module_required('NOTIFICATIONS')` |
| `delete_message_batch` | `login_required`<br>`role_required(NOTIFICATION_ROLES)`<br>`require_POST`<br>`module_required('NOTIFICATIONS')` |

## Regles metier appliquees

Refus opposes par le logiciel. Chacun merite une explication dans la
formation : pourquoi la regle existe, et que faire quand on la rencontre.

- Le membre n'appartient pas a ce gym.

## Ce que l'utilisateur lit a l'ecran

Messages affiches apres une action. Ils donnent le vocabulaire exact a
employer dans la formation : l'apprenant doit reconnaitre ce qu'il verra.

### Confirmations

- Envoi annule : retire de la boite de reception de {valeur} membre(s).{valeur}
- Envoi supprime pour {valeur} membre(s).
- Message envoye a {valeur} membre(s) - {valeur}.

### Avertissements

- Aucun membre ne correspond a cette audience.
- Cet envoi n'existe plus ou est deja annule.
- Cet envoi n'existe plus.

## Traces laissees dans le journal sensible

Actions consignees. Utile pour expliquer aux equipes ce qui est trace,
et rassurer sur ce qui ne l'est pas.

- `notification.batch_cancelled`
- `notification.batch_deleted`
- `notification.batch_sent`

## Ecrans concernes

- `notifications\templates\notifications\in_app_dashboard.html`

## Comportements garantis par les tests

Chaque intitule decrit une promesse verifiee automatiquement. C'est la
meilleure source pour les cas limites a montrer en formation.

### InAppNotificationDashboardTests
- dashboard sends in app message
- dashboard can send to active members only
- dashboard can send to expired members
- dashboard excludes future subscriptions from active and expiring audiences
- dashboard history and counts ignore unsent notifications
- manager can open dashboard when module is active
- reception cannot open dashboard
- dashboard groups large campaigns in collapsible history
- dashboard shows read and unread members per campaign

### MemberMessageRenderingTests

> Le corps d'un message doit s'afficher entier, et sans jamais s'executer.

- tag like text is not swallowed — _striptags supprimait « <promo> » sans prevenir personne._
- html in a message is never executed
- line breaks are preserved
- plain message reaches the member intact

### MessageBatchCancellationTests

> Annulation et suppression d'un envoi groupe.

- a send gets one shared batch id
- cancelling removes the message from every inbox
- cancelling keeps the history for the gym
- cancelling records who and when
- cancelling reports how many had already read
- cancelling twice is reported not repeated
- deleting removes every trace
- a cancelled send can still be deleted
- deleting an unknown send is reported
- another gym send cannot be touched
- reception cannot cancel a send
- get requests change nothing

## A completer par un humain

Le code ne dit pas tout. Avant de rediger, il faut trancher :

- Qui suit cette formation : reception, caisse, gerant, proprietaire ?
- Quelles taches quotidiennes reelles doit-on savoir faire a la fin ?
- Quels incidents arrivent souvent et doivent etre traites en exercice ?
- Quelles habitudes de la salle different de ce que propose le logiciel ?

