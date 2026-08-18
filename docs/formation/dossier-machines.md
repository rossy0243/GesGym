# Dossier de formation - Machines

> Parc de machines, maintenances et couts associes.

Ce dossier rassemble la matiere brute du module. Il sert a rediger la
formation : il n'en est pas une. Les intitules proviennent du code, donc
de ce que le logiciel fait reellement, pas de ce qu'on croit qu'il fait.

## Parcours accessibles

### Application `machines`

| Adresse | Vue | Nom interne |
|---|---|---|
| `machines/` | `views.machine_list` | `list` |
| `machines/create/` | `views.machine_create` | `create` |
| `machines/<int:machine_id>/` | `views.machine_detail` | `detail` |
| `machines/<int:machine_id>/update/` | `views.machine_update` | `update` |
| `machines/<int:machine_id>/delete/` | `views.machine_delete` | `delete` |
| `machines/<int:machine_id>/declasser/` | `views.machine_declass` | `declass` |
| `machines/<int:machine_id>/remettre-en-service/` | `views.machine_return_to_service` | `return_to_service` |
| `machines/<int:machine_id>/maintenances/add/` | `views.maintenance_log_create` | `add_maintenance` |
| `maintenances/` | `views.maintenance_list` | `maintenance_list` |
| `maintenances/dashboard/` | `views.maintenance_dashboard` | `maintenance_dashboard` |
| `maintenances/<int:maintenance_id>/delete/` | `views.maintenance_delete` | `maintenance_delete` |

## Donnees manipulees

### `Machine`

> Equipement du gym.
> 
> Deux natures cohabitent, parce qu'elles ne se gerent pas pareil :
> 
> - une **machine** (tapis, velo, presse) s'entretient. Elle a un rythme de
>   maintenance, un historique d'interventions, et un cout d'entretien ;
> - un **accessoire** (halteres, tapis de sol, elastiques) ne s'entretient
>   pas. Quand il est use, on ne le repare pas : on le sort du parc.
> 
> Les confondre revenait a proposer un entretien periodique pour une corde a
> sauter, et a n'offrir aucun moyen propre de sortir du parc un accessoire
> hors d'usage autrement qu'en le supprimant, ce qui effacait son historique.


| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `name` | CharField |
| `equipment_type` | CharField |
| `status` | CharField |
| `purchase_date` | DateField |
| `maintenance_interval_days` | PositiveIntegerField |
| `declassed_on` | DateField |
| `declassed_reason` | CharField |
| `created_at` | DateTimeField |

Valeurs possibles `STATUS` :

```python
((STATUS_OK, 'OK'), (STATUS_MAINTENANCE, 'Maintenance'), (STATUS_BROKEN, 'En panne'), (STATUS_DECLASSED, 'Declasse'))
```

### `MaintenanceLog`

> Historique des maintenances machines.
> 
> Reserve aux machines encore au parc : un accessoire ne se repare pas, et
> un equipement declasse n'a plus a coûter d'entretien.


| Champ | Type |
|---|---|
| `machine` | ForeignKey |
| `description` | TextField |
| `cost` | DecimalField |
| `pos_payment` | OneToOneField |
| `created_at` | DateTimeField |

## Qui a le droit de faire quoi

Garde-fous poses sur chaque vue. A traduire en langage metier dans la
formation : « la reception peut pointer mais pas consulter les salaires ».

| Action | Protections |
|---|---|
| `machine_list` | `login_required`<br>`module_required('MACHINES')`<br>`role_required(MACHINE_ROLES)` |
| `machine_detail` | `login_required`<br>`module_required('MACHINES')`<br>`role_required(MACHINE_ROLES)` |
| `machine_create` | `login_required`<br>`module_required('MACHINES')`<br>`role_required(MACHINE_ROLES)` |
| `machine_update` | `login_required`<br>`module_required('MACHINES')`<br>`role_required(MACHINE_ROLES)` |
| `machine_delete` | `login_required`<br>`module_required('MACHINES')`<br>`role_required(MACHINE_ROLES)` |
| `machine_declass` | `login_required`<br>`module_required('MACHINES')`<br>`role_required(MACHINE_ROLES)` |
| `machine_return_to_service` | `login_required`<br>`module_required('MACHINES')`<br>`role_required(MACHINE_ROLES)`<br>`require_POST` |
| `maintenance_log_create` | `login_required`<br>`module_required('MACHINES')`<br>`role_required(MACHINE_ROLES)` |
| `maintenance_list` | `login_required`<br>`module_required('MACHINES')`<br>`role_required(MACHINE_ROLES)` |
| `maintenance_dashboard` | `login_required`<br>`module_required('MACHINES')`<br>`role_required(MACHINE_ROLES)` |
| `maintenance_delete` | `login_required`<br>`module_required('MACHINES')`<br>`role_required(MACHINE_ROLES)` |

## Regles metier appliquees

Refus opposes par le logiciel. Chacun merite une explication dans la
formation : pourquoi la regle existe, et que faire quand on la rencontre.

- Cet equipement est declasse : remettez-le en service avant d'y engager une depense.
- Le cout ne peut pas etre negatif.
- Un accessoire ne s'entretient pas : il se declasse quand il est hors d'usage.
- Un declassement ne se date pas dans le futur.
- Un equipement en service ne peut pas porter de declassement.

## Ce que l'utilisateur lit a l'ecran

Messages affiches apres une action. Ils donnent le vocabulaire exact a
employer dans la formation : l'apprenant doit reconnaitre ce qu'il verra.

### Confirmations

- "{valeur}" a ete sorti du parc.
- "{valeur}" est de nouveau en service.
- Log de maintenance supprime avec succes.
- Machine "{valeur}" creee avec succes.
- Machine "{valeur}" modifiee avec succes.
- Machine "{valeur}" supprimee avec succes.
- Maintenance ajoutee pour "{valeur}" avec succes.

### Refus et erreurs

- Impossible de supprimer cette machine car certaines maintenances sont deja liees a des paiements POS.
- Impossible de supprimer cette maintenance car elle est deja liee a un paiement POS.

### Informations

- "{valeur}" est deja declasse.
- "{valeur}" est deja en service.

## Traces laissees dans le journal sensible

Actions consignees. Utile pour expliquer aux equipes ce qui est trace,
et rassurer sur ce qui ne l'est pas.

- `machines.equipment_declassed`
- `machines.equipment_returned_to_service`
- `machines.machine_deleted`
- `machines.maintenance_deleted`
- `machines.maintenance_recorded`

## Ecrans concernes

- `machines\templates\machines\machine_confirm_delete.html`
- `machines\templates\machines\machine_declass.html`
- `machines\templates\machines\machine_detail.html`
- `machines\templates\machines\machine_form.html`
- `machines\templates\machines\machine_list.html`
- `machines\templates\machines\maintenance_confirme_delete.html`
- `machines\templates\machines\maintenance_dashboard.html`
- `machines\templates\machines\maintenance_dashboard_v2.html`
- `machines\templates\machines\maintenance_form.html`
- `machines\templates\machines\maintenance_list.html`

## Comportements garantis par les tests

Chaque intitule decrit une promesse verifiee automatiquement. C'est la
meilleure source pour les cas limites a montrer en formation.

### MachinesTenantTests
- machine list is scoped to current gym
- other gym machine detail is not accessible
- other gym machine update is not accessible
- maintenance history is scoped to current gym
- dashboard kpis are scoped to current gym
- general dashboard includes scoped machine kpis
- create maintenance uses current gym machine
- cannot delete maintenance linked to pos payment
- cannot delete machine when paid maintenance exists
- can delete maintenance without pos payment

### MaintenanceAlertTests

> Une maintenance periodique doit se signaler avant la panne.

- a machine without interval has no deadline
- the deadline starts from the purchase date
- the last maintenance resets the cycle
- an interval below one day is refused
- a deadline two weeks away is announced
- a deadline beyond the lead time stays quiet
- a passed deadline is reported as overdue
- the most urgent machine comes first
- another gym machines are never counted
- the lead time is configurable per gym
- the settings page saves the new lead time
- an absurd lead time is refused
- the banner follows the manager on every page
- a cashier never sees the maintenance banner

### EquipmentNatureTests

> Une machine s'entretient ; un accessoire se declasse.

- an accessory cannot carry a maintenance interval
- an accessory cannot be put under maintenance
- an accessory refuses a maintenance log
- the form refuses an interval on an accessory
- the maintenance page turns an accessory away
- an accessory is never in the maintenance alerts
- an accessory is declassed directly
- a machine can also be declassed at end of life
- a declassement is never dated in the future
- the declassement is traced in the sensitive log
- a declassed machine no longer raises a maintenance alert
- a declassed machine refuses a new maintenance
- a declassement can be undone
- a machine in service cannot carry a declassement
- a maintenance form cannot declass the machine
- the park counts both natures apart
- a declassed item leaves the availability rate
- the list hides declassed items unless asked
- the list filters on the nature
- the declassed status is not offered in the edit form

## A completer par un humain

Le code ne dit pas tout. Avant de rediger, il faut trancher :

- Qui suit cette formation : reception, caisse, gerant, proprietaire ?
- Quelles taches quotidiennes reelles doit-on savoir faire a la fin ?
- Quels incidents arrivent souvent et doivent etre traites en exercice ?
- Quelles habitudes de la salle different de ce que propose le logiciel ?

