# Roadmap pointage biometrique du personnel

Etude de faisabilite menee le 27 aout 2026, a la demande du client, puis
mise en attente. Aucune ligne de code ecrite. Ce document existe pour que la
reflexion ne soit pas a refaire le jour ou le sujet revient.

## Question posee

Peut-on exploiter le lecteur d'empreinte du terminal Hikvision pour enregistrer
la presence du personnel dans le module RH ?

## Reponse courte

Oui, probablement. Mais le vrai obstacle n'est pas le materiel : il est dans le
module RH, et dans le fait que la presence pilote directement la paie.

## Ce qui reste a verifier sur le materiel

Le terminal etait injoignable pendant l'etude. **Une seule inconnue subsiste**,
levable par un appel ISAPI depuis le reseau de la salle :

```
/ISAPI/AccessControl/capabilities?format=json
```

et y chercher les mentions `FingerPrint` / `isSupportFingerPrint`.

Indices en main :

- le modele `DS-K1T342MFWX-E1` porte un `F` dans sa designation, qui chez
  Hikvision designe le module d'empreinte. Indice serieux, pas une preuve ;
- `user_count()` ne lit aujourd'hui que `userNumber`, `bindFaceUserNumber` et
  `bindCardUserNumber`. Hikvision expose aussi `bindFingerUserNumber` quand des
  empreintes existent : nous ne l'avons jamais demande, donc l'absence
  d'empreintes dans nos releves ne prouve rien.

**Le code ne sait rien faire des empreintes** : ni enroler, ni supprimer, ni
capturer. C'est a peu pres le volume de travail qu'a demande le visage.

## Obstacle 1 - le module RH ne connait pas les heures

```python
class Attendance:
    gym, employee, date, status   # present | absent
    unique_together = ("employee", "date")
```

Aucune heure : ni arrivee, ni depart, ni duree. C'est un registre **journalier**,
pas un pointage.

Un terminal biometrique produit l'inverse : des evenements horodates. Le
brancher tel quel ne donnerait qu'une information, « present ce jour ». Ni
retard, ni heures travaillees, ni sortie.

De vrais horaires ne sont donc pas un branchement, mais un nouveau modele, une
migration, et une reprise du calcul de paie.

## Obstacle 2 - la presence, c'est de l'argent

```python
def present_days_for_month(self, year, month):
    return self.attendances.filter(..., status="present").count()
```

Ces jours alimentent `PayrollSlip.present_days`, qui alimente le salaire. Pour
un employe paye a la journee, **une empreinte vaut un jour paye**.

Les deux risques ne se valent pas :

- **faux positif** (un collegue qui pointe pour un absent) : un jour paye non
  travaille. L'empreinte est justement le moyen qui y resiste le mieux, c'est
  son interet principal ici ;
- **faux negatif** (doigt sale, lecteur en panne, coupure de courant) : un jour
  de salaire *retire* a quelqu'un qui a travaille, et personne ne s'en apercoit
  avant la paie.

Regle a poser d'emblee : **le terminal propose, il ne decide jamais.** Il cree
des presences, jamais des absences, et un humain valide le mois avant paiement.

## Obstacle 3 - la numerotation entrerait en collision

Les membres occupent la bande `1 000 000 + identifiant`
(`enrollment.PLAGE_APPLICATION`). La resolution actuelle :

```python
if valeur <= PLAGE_APPLICATION:
    return None
return valeur - PLAGE_APPLICATION
```

**Tout numero au-dessus d'un million est lu comme un membre.** Un employe place
a `2 000 001` serait interprete comme « membre 1 000 001 » : introuvable, donc
refuse et non journalise. Pas de fausse attribution, mais rien ne fonctionnerait.

Il faut une bande propre aux employes, un champ sur `Employee` pour la porter,
et un aiguillage explicite a l'arrivee de l'evenement.

A noter aussi : un employe enrole comme **membre** voit aujourd'hui ses passages
comptes comme des visites de membre, ce qui gonfle la frequentation.

## Ce qui est deja acquis

La plomberie existe et ne sera pas a refaire :

- enroler demande le sens ERP vers lecteur, ouvert par le tunnel Cloudflare ;
- recevoir le passage demande le sens inverse, en service depuis le 25 aout.

## L'alternative a examiner en premier

**Le visage fonctionne deja de bout en bout.** Si l'objectif est « pointer le
personnel au terminal », le visage y arrive sans une ligne de protocole nouvelle :
capture, enrolement et remontee d'evenement sont ecrits et testes.

Il ne resterait que la bande de numerotation, l'aiguillage vers les presences et
les regles de validation - c'est-a-dire les obstacles 2 et 3, qui existent quelle
que soit la biometrie retenue.

L'empreinte n'apporte quelque chose que si le materiel la possede **et** que le
personnel la prefere, ou que les visages posent probleme : eclairage, masques,
couvre-chefs.

## Charge de travail comparee

| Voie | Travail |
| --- | --- |
| Par le visage | bande employes, aiguillage, regles de validation, ecran d'enrolement, tests |
| Par l'empreinte | tout ce qui precede, **plus** sondage materiel, capture, enrolement et suppression d'empreinte dans le client ISAPI |
| Avec de vrais horaires | l'un des deux, **plus** nouveau modele de pointage, migration, reprise du calcul de paie |

## Les deux questions a trancher avant de commencer

1. **Le client veut-il seulement « present aujourd'hui », ou de vrais horaires ?**
   C'est le facteur qui double ou triple le travail.
2. **L'empreinte est-elle une exigence, ou un moyen ?** Si c'est un moyen, le
   visage y arrive bien plus vite.

## Premiere action le jour ou le sujet revient

Depuis une machine du reseau de la salle, interroger les capacites du terminal
et chercher les mentions d'empreinte. Une heure au plus, et cela leve la seule
inconnue materielle.

## Fichiers concernes

| Fichier | Role |
| --- | --- |
| `rh/models.py` | `Attendance`, `Employee.present_days_for_month`, `PayrollSlip` |
| `rh/views_v2.py` | saisie groupee des presences (`BulkAttendanceForm`) |
| `access/enrollment.py` | `PLAGE_APPLICATION`, `employee_no`, `member_id_depuis` |
| `access/hikvision.py` | client ISAPI, `user_count`, gestion des visages |
| `access/device_views.py` | `device_webhook`, resolution de l'identifiant recu |
