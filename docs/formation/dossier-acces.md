# Dossier de formation - Controle d'acces

> Scan QR, pointage manuel, lecteurs physiques, journal d'entrees.

Ce dossier rassemble la matiere brute du module. Il sert a rediger la
formation : il n'en est pas une. Les intitules proviennent du code, donc
de ce que le logiciel fait reellement, pas de ce qu'on croit qu'il fait.

## Parcours accessibles

### Application `access`

| Adresse | Vue | Nom interne |
|---|---|---|
| `access/<uuid:qr_code>/` | `views.member_access` | `member_access` |
| `access-dashboard/` | `views.acces_dashboard` | `acces_dashboard` |
| `access/realtime/` | `views.realtime_access` | `` |
| `access/manual/entry/<int:member_id>/` | `views.manual_access_entry` | `manual_access_entry` |
| `devices/` | `device_views.device_list` | `device_list` |
| `devices/discover/` | `device_views.device_discover` | `device_discover` |
| `devices/create/` | `device_views.device_create` | `device_create` |
| `devices/<int:device_id>/test/` | `device_views.device_test` | `device_test` |
| `devices/<int:device_id>/open/` | `device_views.device_open_door` | `device_open_door` |
| `devices/<int:device_id>/delete/` | `device_views.device_delete` | `device_delete` |
| `devices/webhook/<uuid:token>/` | `device_views.device_webhook` | `device_webhook` |

## Donnees manipulees

### `AccessDevice`

> Lecteur physique de controle d'acces (borne QR / badge) rattache a un gym.
> 
> Le lecteur pousse ses evenements de scan vers l'endpoint webhook identifie
> par ``webhook_token``; l'application repond en autorisant ou refusant.


| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `name` | CharField |
| `brand` | CharField |
| `host` | GenericIPAddressField |
| `port` | PositiveIntegerField |
| `use_https` | BooleanField |
| `username` | CharField |
| `password` | CharField |
| `door_number` | PositiveSmallIntegerField |
| `open_on_granted` | BooleanField |
| `model_name` | CharField |
| `serial_number` | CharField |
| `firmware` | CharField |
| `mac_address` | CharField |
| `webhook_token` | UUIDField |
| `is_active` | BooleanField |
| `last_seen_at` | DateTimeField |
| `last_error` | CharField |
| `created_at` | DateTimeField |
| `updated_at` | DateTimeField |

Valeurs possibles `BRAND_CHOICES` :

```python
[(BRAND_HIKVISION, 'Hikvision (ISAPI)')]
```

### `AccessLog`

> Historique des accès des membres (scan QR, entrée gym).


| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `member` | ForeignKey |
| `check_in_time` | DateTimeField |
| `access_granted` | BooleanField |
| `device_used` | CharField |
| `device` | ForeignKey |
| `denial_reason` | CharField |
| `scanned_by` | ForeignKey |

## Qui a le droit de faire quoi

Garde-fous poses sur chaque vue. A traduire en langage metier dans la
formation : « la reception peut pointer mais pas consulter les salaires ».

| Action | Protections |
|---|---|
| `device_list` | `login_required`<br>`role_required(ACCESS_DEVICE_ROLES)`<br>`module_required('ACCESS')` |
| `device_discover` | `login_required`<br>`role_required(ACCESS_DEVICE_ROLES)`<br>`require_POST`<br>`module_required('ACCESS')` |
| `device_create` | `login_required`<br>`role_required(ACCESS_DEVICE_ROLES)`<br>`require_POST`<br>`module_required('ACCESS')` |
| `device_test` | `login_required`<br>`role_required(ACCESS_DEVICE_ROLES)`<br>`require_POST`<br>`module_required('ACCESS')` |
| `device_open_door` | `login_required`<br>`role_required(ACCESS_DEVICE_ROLES)`<br>`require_POST`<br>`module_required('ACCESS')` |
| `device_delete` | `login_required`<br>`role_required(ACCESS_DEVICE_ROLES)`<br>`require_POST`<br>`module_required('ACCESS')` |
| `device_webhook` | `csrf_exempt` |
| `acces_dashboard` | `login_required`<br>`role_required(ACCESS_ROLES)`<br>`module_required('ACCESS')` |
| `realtime_access` | `login_required`<br>`role_required(ACCESS_ROLES)`<br>`module_required('ACCESS')` |
| `manual_access_entry` | `login_required`<br>`role_required(ACCESS_ROLES)`<br>`require_POST`<br>`module_required('ACCESS')` |
| `member_access` | `login_required`<br>`role_required(ACCESS_ROLES)`<br>`require_POST`<br>`module_required('ACCESS')` |

## Regles metier appliquees

Refus opposes par le logiciel. Chacun merite une explication dans la
formation : pourquoi la regle existe, et que faire quand on la rencontre.

- Aucun lecteur enregistre dans l'application. Ajoute-le d'abord depuis Controle d'acces > Lecteurs.
- Le membre n'appartient pas a ce gym.
- Lecteur {valeur} injoignable : {valeur} Verifie qu'il est alimente, cable, et qu'aucun VPN ne bloque le reseau local.

## Ce que l'utilisateur lit a l'ecran

Messages affiches apres une action. Ils donnent le vocabulaire exact a
employer dans la formation : l'apprenant doit reconnaitre ce qu'il verra.

## Traces laissees dans le journal sensible

Actions consignees. Utile pour expliquer aux equipes ce qui est trace,
et rassurer sur ce qui ne l'est pas.

- `access.device_deleted`
- `access.device_registered`
- `access.door_opened_remotely`

## Ecrans concernes

- `access\templates\access\acces.html`

## Comportements garantis par les tests

Chaque intitule decrit une promesse verifiee automatiquement. C'est la
meilleure source pour les cas limites a montrer en formation.

### AccessControlTests
- access log rejects cross gym member
- manual access creates scoped log for current gym
- manual access denies second entry same day
- qr access denies second scan same day
- qr access denies expired qr code
- manual access still allows member when qr is expired
- qr access allows multiple different members in sequence
- scanner template keeps camera active after successful scan
- previous day entry does not block today
- denied attempt does not block later valid entry
- qr access cannot read member from other gym
- member without valid subscription is denied
- member with future subscription is denied until start date
- realtime access is scoped to current gym
- access dashboard renders readers section
- access dashboard requires active module

### HikvisionEventParsingTests

> Extraction de l'identifiant scanne dans les notifications du lecteur.

- extracts qr content from json event
- extracts card number when no qr
- extracts json block from multipart body
- returns empty credential on unreadable body

### AccessDeviceWebhookTests

> Passages pousses par un lecteur physique vers l'application.

- valid scan grants access and logs device
- scan marks device as seen
- unknown credential is refused without log
- member from another gym is not resolved
- expired qr code is refused
- second scan same day is refused
- unknown token returns 404
- inactive device is rejected
- get is not allowed
- granted scan opens the door
- denied scan never opens the door
- device failure does not cancel a granted access — _Une panne du relais ne doit pas invalider une decision deja prise._
- device with auto open disabled stays closed

### DashboardDoorOpeningTests

> Scan QR et pointage manuel : la porte suit la decision metier.

- valid qr opens the door
- expired qr leaves the door closed
- second scan same day leaves the door closed
- gym without device still grants access
- manual entry opens the door
- manual entry without subscription leaves the door closed
- manual entry second time same day leaves the door closed
- manual entry survives a door failure

### AccessRefusalReasonTests

> Chaque refus doit dire quoi faire, pas seulement qu'il refuse.

- a member who never subscribed is named as such
- a paused subscription says so
- an expired subscription gives its end date
- a future subscription gives its start date
- a paused subscription wins over an old expired one — _Le cas actionnable prime : c'est la pause qu'il faut lever._
- the reason is stored in the access log
- a suspended member keeps its own reason
- a valid member is still granted

## A completer par un humain

Le code ne dit pas tout. Avant de rediger, il faut trancher :

- Qui suit cette formation : reception, caisse, gerant, proprietaire ?
- Quelles taches quotidiennes reelles doit-on savoir faire a la fin ?
- Quels incidents arrivent souvent et doivent etre traites en exercice ?
- Quelles habitudes de la salle different de ce que propose le logiciel ?

