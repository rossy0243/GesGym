# Roadmap invitations - laissez-passer pour un invite

Cadrage arrete le 27 aout 2026 avec le proprietaire. Rien n'est encore code.

## L'idee en une phrase

Une formule d'abonnement donne au membre le droit d'inviter quelqu'un. Le
membre emet lui-meme un laissez-passer depuis son espace ; l'invite entre une
fois avec un QR code temporaire, sans jamais devenir membre.

## Ce qui a ete tranche

| Question | Decision |
| --- | --- |
| D'ou vient le droit | Inclus dans la formule, avec un quota mensuel |
| Portee du laissez-passer | Une seule entree, puis il s'eteint |
| Identite de l'invite | Nom et telephone, saisis a l'emission |
| Qui emet | Le membre, depuis son espace |
| Meme personne invitee plusieurs fois | Plafonnee, pour ne pas remplacer un abonnement |
| Remise a zero du quota | Mois calendaire, le 1er |
| Hote plus a jour a l'entree | Le laissez-passer est refuse |

## Ce que j'ai decide seul, a confirmer

Trois points de detail n'ont pas ete poses ; ils se corrigent en une ligne si
le choix ne convient pas.

- **Le quota vit sur la formule**, pas sur l'offre. C'est la formule qui est
  vendue et facturee : le droit d'inviter est une propriete de ce qu'on a
  achete. L'offre nommee « Invitations » reste descriptive, pour l'affichage
  et l'argumentaire commercial. Deux sources de verite auraient fini par
  diverger.
- **Un laissez-passer non utilise expire au bout de 7 jours.** Sans cela, un
  membre accumulerait des QR actifs pendant des mois et les distribuerait d'un
  coup.
- **Le plafond par personne se compte sur 12 mois glissants**, pas sur toute la
  vie. Interdire a quelqu'un de revenir deux ans plus tard serait absurde ; le
  but est d'empecher l'invitation permanente, pas de bannir.

## Modele de donnees

### `GuestPass`

Un laissez-passer, dans `members` : c'est l'invite d'un membre, pas un passage.

| Champ | Role |
| --- | --- |
| `gym` | la salle emettrice |
| `host` | le membre qui invite |
| `guest_name`, `guest_phone` | l'invite ; deux champs, pas une fiche |
| `code` | l'UUID porte par le QR |
| `created_at` | emission |
| `expires_at` | emission + 7 jours |
| `used_at` | horodatage du passage, vide tant qu'inutilise |
| `created_by` | le compte du membre, pour la trace |

Le telephone est indexe : c'est la cle du plafond par personne.

### `SubscriptionPlan.guest_passes_per_month`

Entier, zero par defaut. Une formule sans invitations n'a rien a declarer.

### `AccessLog.guest_pass`

Lien facultatif vers le laissez-passer. Le journal accepte deja une ligne sans
membre - travail fait pour les ouvertures manuelles - mais il faut distinguer
les deux a l'affichage : une ouverture manuelle et un invite ne racontent pas
la meme chose.

## Regles de validation

A l'emission, dans cet ordre :

1. le membre a un abonnement actif ;
2. sa formule accorde des invitations ;
3. son quota du mois calendaire n'est pas epuise ;
4. ce numero de telephone n'a pas atteint le plafond sur 12 mois glissants.

A l'entree :

1. le laissez-passer existe, n'a pas servi, n'a pas expire ;
2. **l'hote est toujours a jour** - reverifie a cet instant, pas a l'emission ;
3. le passage est journalise, et le laissez-passer s'eteint.

Chaque refus doit nommer sa cause : « ce laissez-passer a deja servi »,
« l'abonnement de l'hote a expire », « cette personne a deja ete invitee trois
fois ». Un refus muet enverrait l'accueil chercher une panne inexistante.

## Ce que voit le membre

Dans son espace : le nombre d'invitations restantes ce mois-ci, un formulaire a
deux champs, le QR a transmettre, et l'etat de ce qu'il a deja emis - utilise,
en attente, expire.

## Ce que voit la salle

Le passage d'un invite apparait au journal, nomme, avec son hote. Il **ne
compte pas** dans la frequentation des membres : personne ne s'est abonne. Un
compteur separe le rend visible sans fausser les statistiques.

## Risques reconnus

- **Le QR se transfere.** Il part par messagerie, donc n'importe qui peut le
  presenter. L'usage unique, le nom releve et l'expiration courte limitent la
  portee, sans l'annuler.
- **Un telephone invente contourne le plafond.** Rien ne l'empeche
  techniquement. C'est l'accueil qui voit la personne ; la regle decourage
  l'abus ordinaire, elle n'arrete pas la fraude deliberee.
- **La lecture des QR a la porte n'est pas verifiee.** Si le terminal ne les lit
  pas, l'invite est scanne a l'accueil. Cela ne bloque rien mais deplace le
  geste, et il faut le savoir avant de promettre l'entree autonome.

## Fichiers concernes

| Fichier | Role |
| --- | --- |
| `members/models.py` | `GuestPass`, et le lien vers l'hote |
| `subscriptions/models.py` | `SubscriptionPlan.guest_passes_per_month` |
| `access/models.py` | `AccessLog.guest_pass` |
| `access/views.py` | resolution du QR, journalisation, statistiques |
| `members/views.py` | espace membre : emission et suivi |
