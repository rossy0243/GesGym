# Roadmap invitations - laissez-passer pour un invite

Cadrage arrete le 27 aout 2026 avec le proprietaire. Rien n'est encore code.

## L'idee en une phrase

Une formule d'abonnement donne au membre le droit d'inviter une personne par
mois d'abonnement. Le membre emet lui-meme le laissez-passer depuis son espace ;
l'invite obtient un QR code valable 30 jours pour un nombre de seances fixe par
la salle, sans jamais devenir membre.

## Ce qui a ete tranche

| Question | Decision |
| --- | --- |
| D'ou vient le droit | Inclus dans la formule, avec un quota |
| Combien de personnes | Reglable par formule ; l'exemple du proprietaire est 1 par mois |
| Combien de seances par invite | Reglable par la salle, **1 par defaut** |
| Renouvellement | A chaque mois d'abonnement ecoule : 3 mois achetes, 3 invitations |
| Validite des seances | **30 jours pleins depuis l'emission**, ou que l'on soit dans le mois |
| Identite de l'invite | Nom et telephone, saisis a l'emission |
| Qui emet | Le membre, depuis son espace |
| Meme personne invitee plusieurs fois | Plafonnee, pour ne pas remplacer un abonnement |
| Hote plus a jour a l'entree | Le laissez-passer est refuse |
| Invite qui ne vient pas | Le membre peut reattribuer le carnet tant qu'aucune seance n'a servi |

**Le laissez-passer est un carnet, pas un billet.** Il porte un invite nomme et
un nombre de seances ; il s'epuise, il ne se consomme pas d'un coup. C'est la
correction apportee au premier cadrage, qui parlait a tort d'usage unique.

## Ce que j'ai decide seul, a confirmer

Ces points n'ont pas ete poses ; chacun se corrige en une ligne.

- **Les deux quotas vivent sur la formule**, pas sur l'offre. C'est la formule
  qui est vendue et facturee : le droit d'inviter est une propriete de ce qu'on
  a achete. L'offre nommee « Invitations » reste descriptive, pour l'affichage
  et l'argumentaire. Deux sources de verite auraient fini par diverger.
- **Un mois d'abonnement est une tranche de 30 jours depuis la date de debut**,
  et non un mois calendaire. Les durees du projet s'expriment deja en
  `duration_days` : compter autrement ferait diverger le quota de l'abonnement
  qui le porte.
- **Un carnet peut deborder sur le mois suivant.** Emis le 25e jour d'une
  tranche, il vit jusqu'au 55e. Le membre recoit alors sa nouvelle invitation
  alors que l'ancienne court encore : deux carnets actifs en meme temps, pour
  quelques jours. C'est la contrepartie assumee des 30 jours pleins ; le quota
  continue de limiter les emissions, pas les chevauchements.
- **Le plafond par personne se compte sur 12 mois glissants.** Interdire a
  quelqu'un de revenir deux ans plus tard serait absurde ; le but est
  d'empecher l'invitation permanente, pas de bannir.
- **Un carnet jamais entame se reattribue.** Le membre change le nom et le
  numero ; le carnet garde son identite et sa date limite. Il n'y a donc plus
  d'annulation : rendre le quota puis en re-emettre un aurait fait le meme
  travail en deux gestes, avec un etat de plus a expliquer.
- **La reattribution ne relance pas les 30 jours.** La date limite appartient au
  carnet, pas a l'invite. Sinon un membre la repousserait indefiniment en
  changeant de nom la veille de l'echeance.
- **Un carnet entame ne se reattribue plus.** Une seance consommee a profite a
  quelqu'un ; offrir le reliquat a un second invite reviendrait a contourner la
  regle d'une personne par mois.

## Modele de donnees

### `GuestPass`

Un carnet d'invitation, dans `members` : c'est l'invite d'un membre, pas un
passage.

| Champ | Role |
| --- | --- |
| `gym` | la salle emettrice |
| `host` | le membre qui invite |
| `guest_name`, `guest_phone` | l'invite ; deux champs, pas une fiche |
| `code` | l'UUID porte par le QR |
| `sessions_allowed` | seances accordees, copiees de la formule a l'emission |
| `sessions_used` | seances deja consommees |
| `created_at` | emission |
| `expires_at` | emission + 30 jours |
| `reassigned_count` | nombre de reattributions, pour reperer un carnet qui tourne |
| `created_by` | le compte du membre, pour la trace |

Le telephone est indexe : c'est la cle du plafond par personne.

`sessions_allowed` est **copie** a l'emission plutot que lu sur la formule :
changer le reglage de la salle ne doit pas modifier des carnets deja remis.

### `SubscriptionPlan`

Deux entiers, tous deux a zero ou un par defaut :

| Champ | Defaut | Role |
| --- | --- | --- |
| `guest_invites_per_month` | `0` | personnes invitables par mois d'abonnement |
| `guest_sessions_per_invite` | `1` | seances offertes a chaque invite |

Une formule sans invitations n'a rien a declarer : `0` suffit a la taire.

### `AccessLog.guest_pass`

Lien facultatif vers le carnet. Le journal accepte deja une ligne sans membre -
travail fait pour les ouvertures manuelles - mais il faut distinguer les deux a
l'affichage : une ouverture manuelle et un invite ne racontent pas la meme
chose.

## Regles de validation

A l'emission, dans cet ordre :

1. le membre a un abonnement actif ;
2. sa formule accorde des invitations (`guest_invites_per_month > 0`) ;
3. son quota du mois d'abonnement en cours n'est pas epuise - un carnet emis
   compte, qu'il ait servi, expire ou change de nom ;
4. ce numero de telephone n'a pas atteint le plafond sur 12 mois glissants.

A la reattribution :

1. aucune seance n'a encore ete consommee ;
2. la date limite n'est pas atteinte ;
3. le nouveau numero n'a pas atteint le plafond sur 12 mois glissants - la
   verification recommence, elle ne se transmet pas de l'ancien invite au
   nouveau.

A chaque entree de l'invite :

1. le carnet existe et n'est pas expire ;
2. il reste au moins une seance (`sessions_used < sessions_allowed`) ;
3. **l'hote est toujours a jour** - reverifie a cet instant, pas a l'emission ;
4. le passage est journalise et une seance est decomptee.

Chaque refus doit nommer sa cause : « ce carnet est epuise », « l'abonnement de
l'hote a expire », « cette personne a deja ete invitee trois fois ». Un refus
muet enverrait l'accueil chercher une panne inexistante.

## Ce que voit le membre

Dans son espace : son quota du mois, un formulaire a deux champs, le QR a
transmettre, et l'etat de ses carnets. Pour chacun, **le nom et le numero de
l'invite, et s'il est deja passe** - c'est ce qui permet au membre de savoir si
son ami est bien venu, et de repondre a l'accueil sans hesiter.

Un carnet non entame peut etre reattribue a quelqu'un d'autre, sans que la
date limite ne bouge.

## Ce que voit la salle

**Une liste des invitations en cours**, consultable a l'accueil : nom de
l'invite, numero, membre hote, seances restantes et date du dernier passage.

C'est l'ecran de verification a l'entree. Quelqu'un se presente en disant
« je viens en invite » : l'accueil retrouve son nom dans la liste, voit qui
l'invite et combien de seances il lui reste, sans avoir besoin du QR - utile
quand le telephone est vide, le QR perdu, ou l'invite arrive avant son hote.

Le passage lui-meme apparait au journal, nomme, avec son hote et le rang de la
seance : « Invite - Paul Kabeya (2/3), invite par Ada Mbala ». Il **ne compte
pas** dans la frequentation des membres : personne ne s'est abonne. Un compteur
separe le rend visible sans fausser les statistiques.

## Les etats d'un carnet

Quatre etats, les memes mots des deux cotes de l'ecran :

| Etat | Ce qui s'est passe |
| --- | --- |
| **Actif** | il reste des seances et la date limite n'est pas atteinte |
| **Epuise** | toutes les seances ont ete consommees |
| **Caduc** | les 30 jours sont passes ; l'invite ne s'est jamais presente, ou pas jusqu'au bout |

Un carnet **caduc ne rend rien** : le mois a passe avec lui. Le recours du membre
n'est pas de recuperer son quota, mais de **reattribuer le carnet avant
l'echeance**. Tant qu'aucune seance n'a servi, il change de nom et de numero, et
la date limite ne bouge pas.

C'est ce qui distingue un ami qui se decommande - on reattribue - d'un ami qu'on
oublie de relancer : le carnet meurt, et l'invitation du mois avec lui.

Le membre comme l'accueil voient l'etat en toutes lettres, avec la date : « caduc
depuis le 12/09, jamais utilise ». Personne ne doit avoir a deviner pourquoi un
QR ne fonctionne plus.

## Risques reconnus

- **Le QR se transfere.** Il part par messagerie, donc n'importe qui peut le
  presenter. Le nom releve et le decompte des seances limitent la portee, sans
  l'annuler. Un carnet de plusieurs seances est plus expose qu'un billet unique :
  c'est le prix du confort demande.
- **Un telephone invente contourne le plafond.** Rien ne l'empeche
  techniquement. C'est l'accueil qui voit la personne ; la regle decourage
  l'abus ordinaire, elle n'arrete pas la fraude deliberee.
- ~~La lecture des QR n'est pas verifiee.~~ **Point clos** : le poste de
  l'accueil lit les QR codes et commande l'ouverture. L'invite se presente
  comme un membre, sans traitement particulier.

## Fichiers concernes

| Fichier | Role |
| --- | --- |
| `members/models.py` | `GuestPass`, et le lien vers l'hote |
| `subscriptions/models.py` | les deux quotas sur `SubscriptionPlan` |
| `access/models.py` | `AccessLog.guest_pass` |
| `access/views.py` | resolution du QR, decompte, journalisation, statistiques |
| `members/views.py` | espace membre : emission, suivi, reattribution |
| `access/views.py` ou `members/views.py` | liste des invitations en cours, pour l'accueil |
