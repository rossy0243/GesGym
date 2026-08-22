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
| `devices/<int:device_id>/annoncer/` | `device_views.device_announce` | `device_announce` |
| `devices/webhook/<uuid:token>/` | `device_views.device_webhook` | `device_webhook` |
| `membres/<int:member_id>/visage/` | `enrollment_views.face_enrollment` | `face_enrollment` |
| `membres/<int:member_id>/visage/capturer/` | `enrollment_views.face_capture` | `face_capture` |
| `membres/<int:member_id>/visage/valider/` | `enrollment_views.face_confirm` | `face_confirm` |
| `membres/<int:member_id>/visage/retirer/` | `enrollment_views.face_remove` | `face_remove` |
| `devices/<int:device_id>/messages/` | `enrollment_views.device_messages` | `device_messages` |

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
| `host` | CharField |
| `port` | PositiveIntegerField |
| `use_https` | BooleanField |
| `tunnel_client_id` | CharField |
| `tunnel_client_secret` | CharField |
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
| `is_return` | BooleanField |
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
| `device_announce` | `login_required`<br>`module_required('ACCESS')`<br>`role_required(ACCESS_DEVICE_ROLES)`<br>`require_POST` |
| `face_enrollment` | `login_required`<br>`module_required('ACCESS')`<br>`role_required(ACCESS_DEVICE_ROLES)` |
| `face_capture` | `login_required`<br>`module_required('ACCESS')`<br>`role_required(ACCESS_DEVICE_ROLES)`<br>`require_POST` |
| `face_confirm` | `login_required`<br>`module_required('ACCESS')`<br>`role_required(ACCESS_DEVICE_ROLES)`<br>`require_POST` |
| `face_remove` | `login_required`<br>`module_required('ACCESS')`<br>`role_required(ACCESS_DEVICE_ROLES)`<br>`require_POST` |
| `device_messages` | `login_required`<br>`module_required('ACCESS')`<br>`role_required(ACCESS_DEVICE_ROLES)` |
| `acces_dashboard` | `login_required`<br>`role_required(ACCESS_ROLES)`<br>`module_required('ACCESS')` |
| `realtime_access` | `login_required`<br>`role_required(ACCESS_ROLES)`<br>`module_required('ACCESS')` |
| `manual_access_entry` | `login_required`<br>`role_required(ACCESS_ROLES)`<br>`require_POST`<br>`module_required('ACCESS')` |
| `member_access` | `login_required`<br>`role_required(ACCESS_ROLES)`<br>`require_POST`<br>`module_required('ACCESS')` |

## Regles metier appliquees

Refus opposes par le logiciel. Chacun merite une explication dans la
formation : pourquoi la regle existe, et que faire quand on la rencontre.

- Adresse du lecteur manquante.
- Aucun lecteur actif a synchroniser.
- Aucun lecteur actif enregistre.
- Aucun lecteur enregistre dans l'application. Ajoute-le d'abord depuis Controle d'acces > Lecteurs.
- Aucun lecteur numero {valeur}.
- Indiquez une adresse IPv4 (192.168.1.87) ou un nom d'hote (lecteur-kinshasa.exemple.com).
- Le membre n'appartient pas a ce gym.
- Lecteur injoignable. Si Proton VPN tourne, quittez-le : son filtrage bloque le reseau local.
- Lecteur {valeur} injoignable : {valeur} Verifie qu'il est alimente, cable, et qu'aucun VPN ne bloque le reseau local.
- Mot de passe du lecteur incorrect : rien d'autre ne marchera.
- Plusieurs lecteurs actifs, precisez --lecteur : {valeur}

## Ce que l'utilisateur lit a l'ecran

Messages affiches apres une action. Ils donnent le vocabulaire exact a
employer dans la formation : l'apprenant doit reconnaitre ce qu'il verra.

### Confirmations

- Messages enregistres sur {valeur}.
- Visage enrole. {valeur} {valeur} entre par reconnaissance faciale jusqu'au {valeur}.
- {valeur} {valeur} ne peut plus entrer par reconnaissance faciale.

### Avertissements

- Visage enrole pour {valeur} {valeur}. Aucun abonnement en cours : le lecteur le reconnaitra mais n'ouvrira pas tant qu'un abonnement n'est pas encaisse.

### Refus et erreurs

- Aucune capture en attente. Relancez la capture.
- Retrait incomplet.

### Informations

- {valeur} affiche de nouveau ses messages d'origine.

## Traces laissees dans le journal sensible

Actions consignees. Utile pour expliquer aux equipes ce qui est trace,
et rassurer sur ce qui ne l'est pas.

- `access.device_announced`
- `access.device_deleted`
- `access.device_messages_updated`
- `access.device_registered`
- `access.door_opened_remotely`
- `access.face_enrolled`
- `access.face_removed`

## Ecrans concernes

- `access\templates\access\acces.html`
- `access\templates\access\device_messages.html`
- `access\templates\access\face_enrollment.html`

## Comportements garantis par les tests

Chaque intitule decrit une promesse verifiee automatiquement. C'est la
meilleure source pour les cas limites a montrer en formation.

### AccessControlTests
- access log rejects cross gym member
- manual access creates scoped log for current gym
- manual access refuses a second entry the same day — _Le nom donne a l'accueil ne prouve rien : n'importe qui peut le donner._
- qr access refuses a second scan the same day
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
- a second qr scan the same day is refused
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
- a second qr scan the same day leaves the door closed — _L'application commande le relais quand le passage vient d'un QR code :_
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

### FaceEnrollmentServiceTests

> Traduction d'un membre en fiche lecteur.

- the reader id is shifted out of the manual range
- a manual record is never taken for a member
- an application record maps back to its member
- a photo is converted to jpeg and bounded
- a file that is not an image is refused clearly
- the reader receives the subscription window
- a member without subscription is kept but closed
- an unreachable reader never blocks the business
- a gym without reader propagates nothing
- a rejected face says the record still exists
- a file that is not an image is caught before the reader

### FaceEnrollmentScreenTests

> Le parcours d'enrolement, vu de l'ecran.

- the screen spells out the three steps
- the screen says plainly when no reader exists
- a member of another gym is out of reach
- a receptionist cannot enrol faces
- the capture waits for validation before touching the file
- a failed capture explains what to do
- validating stores the photo and enrols the member
- validating without a capture is refused
- the enrolment is traced in the sensitive log
- removing takes the member off every reader

### FaceEventWebhookTests

> Un visage reconnu doit apparaitre au journal d'acces.

- a recognised face is written to the access log
- the log says the passage came from a face
- a face is not refused for an expired qr code
- a manual record is not taken for a member
- an unknown member is refused
- a member of another gym is refused
- a suspended member is refused and the refusal is logged
- a qr code event still resolves the member

### ReaderDeclarationTests

> L'application doit s'annoncer au lecteur pour recevoir ses evenements.

- the declared url carries the device token
- the declared url never points at the loopback
- the reader receives address port and subscription
- a path longer than the hardware limit is refused
- an unreachable reader is reported plainly

### DeviceScreenMessagesTests

> Reglage des phrases affichees sur l'ecran du terminal.

- the screen lists the three messages
- the screen warns that the reader shows plain text
- the screen says the voice is not configurable
- an unreachable reader does not block the screen
- the messages reach the reader
- a message longer than the screen is refused before sending
- unchecking gives the reader back its own messages
- the change is traced in the sensitive log
- a reader of another gym is out of reach
- an empty message is sent as a dash
- the three prompt types are always sent

### ReturnPassageTests

> Un membre deja entre aujourd'hui repasse devant le lecteur.

- the first passage is a plain entry
- a second passage is granted not refused
- a second passage is marked as a return
- a third passage is also a return
- returns never inflate the daily attendance
- two different members count two visits
- a suspended member is still refused on a return
- a member without subscription is refused not marked a return
- the journal distinguishes a return from an entry

### ReturnOnlyByFaceTests

> Un QR code se prete, un badge se passe, un nom se donne a l'accueil.

- a face may come back the same day
- a badge may not come back the same day
- a fingerprint is treated prudently
- a combined mode does not prove the face was used
- a missing mode never grants a return
- the journal names the mode used
- the refusal says why and what works
- a real event from the hardware is recognised as a face — _Evenement releve sur un DS-K1T342MFWX-E1 en V4.48.40._
- the face rectangle alone proves a face
- the documented face event code counts
- a permissive mode alone never proves a face
- an explicit face mode still counts
- an empty or absurd event is never a face

### DeviceAnnounceButtonTests

> Declarer l'application au lecteur depuis l'ecran des lecteurs.

- the button declares the application to the reader
- the declared address is never the loopback
- an unreachable reader is reported without crashing
- the declaration is traced in the sensitive log
- a reader of another gym is out of reach
- a receptionist cannot declare the application

### TunnelledDeviceTests

> Un serveur heberge ne peut pas atteindre une adresse privee.

- a hostname is accepted as an address
- a local address still works
- an absurd address is refused with an example
- the client builds an https url from the hostname
- every request carries the tunnel token
- a device on the local network sends no token
- half a token is treated as no token
- the token reaches the actual request
- the secret never leaves the server
- a local device is reported as unprotected

## A completer par un humain

Le code ne dit pas tout. Avant de rediger, il faut trancher :

- Qui suit cette formation : reception, caisse, gerant, proprietaire ?
- Quelles taches quotidiennes reelles doit-on savoir faire a la fin ?
- Quels incidents arrivent souvent et doivent etre traites en exercice ?
- Quelles habitudes de la salle different de ce que propose le logiciel ?

