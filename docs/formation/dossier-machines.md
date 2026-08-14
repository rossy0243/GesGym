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
| `machines/<int:machine_id>/maintenances/add/` | `views.maintenance_log_create` | `add_maintenance` |
| `maintenances/` | `views.maintenance_list` | `maintenance_list` |
| `maintenances/dashboard/` | `views.maintenance_dashboard` | `maintenance_dashboard` |
| `maintenances/<int:maintenance_id>/delete/` | `views.maintenance_delete` | `maintenance_delete` |

## Donnees manipulees

### `Machine`

> Machines du gym (tapis, vélo, etc.)


| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `name` | CharField |
| `status` | CharField |
| `purchase_date` | DateField |
| `created_at` | DateTimeField |

Valeurs possibles `STATUS` :

```python
(('ok', 'OK'), ('maintenance', 'Maintenance'), ('broken', 'En panne'))
```

### `MaintenanceLog`

> Historique des maintenances machines


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
| `maintenance_log_create` | `login_required`<br>`module_required('MACHINES')`<br>`role_required(MACHINE_ROLES)` |
| `maintenance_list` | `login_required`<br>`module_required('MACHINES')`<br>`role_required(MACHINE_ROLES)` |
| `maintenance_dashboard` | `login_required`<br>`module_required('MACHINES')`<br>`role_required(MACHINE_ROLES)` |
| `maintenance_delete` | `login_required`<br>`module_required('MACHINES')`<br>`role_required(MACHINE_ROLES)` |

## Regles metier appliquees

Refus opposes par le logiciel. Chacun merite une explication dans la
formation : pourquoi la regle existe, et que faire quand on la rencontre.

- Le cout ne peut pas etre negatif.

## Ce que l'utilisateur lit a l'ecran

Messages affiches apres une action. Ils donnent le vocabulaire exact a
employer dans la formation : l'apprenant doit reconnaitre ce qu'il verra.

### Confirmations

- Log de maintenance supprime avec succes.
- Machine "{valeur}" creee avec succes.
- Machine "{valeur}" modifiee avec succes.
- Machine "{valeur}" supprimee avec succes.
- Maintenance ajoutee pour "{valeur}" avec succes.

### Refus et erreurs

- Impossible de supprimer cette machine car certaines maintenances sont deja liees a des paiements POS.
- Impossible de supprimer cette maintenance car elle est deja liee a un paiement POS.

## Traces laissees dans le journal sensible

Actions consignees. Utile pour expliquer aux equipes ce qui est trace,
et rassurer sur ce qui ne l'est pas.

- `machines.machine_deleted`
- `machines.maintenance_deleted`
- `machines.maintenance_recorded`

## Ecrans concernes

- `machines\templates\machines\machine_confirm_delete.html`
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

## A completer par un humain

Le code ne dit pas tout. Avant de rediger, il faut trancher :

- Qui suit cette formation : reception, caisse, gerant, proprietaire ?
- Quelles taches quotidiennes reelles doit-on savoir faire a la fin ?
- Quels incidents arrivent souvent et doivent etre traites en exercice ?
- Quelles habitudes de la salle different de ce que propose le logiciel ?

