# Roadmap correction d'abonnement - reparer une periode mal saisie

Cadrage arrete le 3 septembre 2026, apres un retour du client. Rien n'est
encore code.

## L'incident

La receptionniste a enregistre un abonnement avec une date de debut anterieure.
La periode etait donc **deja terminee au moment de la vente** : le membre n'a
aucun acces, alors qu'il a paye et que la recette est comptabilisee.

## Ce que l'analyse a etabli

**Rien n'a averti a la saisie.** `record_subscription_payment` refuse une date
de debut a plus de trois mois dans le futur - pour attraper une annee mal tapee
- mais accepte n'importe quelle date passee sans un mot.

**Rien ne permet de reparer.** Le module n'expose que trois routes de creation :
formule, offre, abonnement. Aucune modification, aucune annulation. Un
abonnement, une fois cree, est grave.

**L'argent est reel.** Le membre a paye, la caisse a encaisse. Le probleme n'est
pas la recette : c'est la periode.

## La distinction fondatrice

Tout le mecanisme en decoule.

| Geste | Ce qui s'est passe | L'argent |
| --- | --- | --- |
| **Corriger une periode** | le membre a paye, on s'est trompe de dates | ne bouge pas |
| **Annuler une vente** | l'abonnement n'aurait jamais du exister | doit suivre |

Le cas du client est le premier. Le second arrivera - double saisie, mauvais
membre, client rembourse - et un mecanisme qui les confond fera disparaitre de
l'argent reellement encaisse, ou laissera des recettes fantomes.

**Ce document ne traite que la correction de periode.** L'annulation d'une vente
est un autre sujet, a cadrer separement.

## Un piege deja rencontre

Interdire les dates passees a ete tente plus tot dans ce projet : cela a casse
le renouvellement anticipe, ou le formulaire prerempli la date du jour. **Une
date passee est souvent legitime** - on saisit la vente d'hier, ou un abonnement
commence lundi.

Ce qui est presque toujours une erreur, c'est une periode **deja close** au
moment de la saisie. C'est ce cas precis, et lui seul, qu'il faut attraper.

## Ce qui a ete tranche

| Question | Decision |
| --- | --- |
| A la saisie | Avertir et demander confirmation si la periode est deja terminee |
| Reparation | Corriger les dates sur place ; la fin se recalcule sur la duree de la formule |
| L'argent | Jamais touche par une correction |
| Qui corrige | Le proprietaire et le gerant |
| **Contrepartie** | **Toute correction reste affichee au proprietaire jusqu'a ce qu'il en accuse reception** |

## L'accusé de reception, cle du dispositif

C'est la demande explicite du proprietaire, et ce qui rend acceptable qu'un
gerant touche a une periode vendue.

Une correction n'est pas une ligne de journal qu'on peut ne jamais lire : elle
**s'impose au proprietaire** par un bandeau, comme celui des lecteurs hors
ligne, et **ne disparait que lorsqu'il declare l'avoir vue**.

- le bandeau nomme le membre, l'ancienne periode, la nouvelle, l'auteur et le
  motif ;
- il reste tant que l'accuse de reception n'est pas donne, sans expiration ;
- une correction faite **par le proprietaire lui-meme** est acquittee d'office :
  il n'a pas a s'accuser reception a lui-meme ;
- l'accuse de reception part au journal d'activite : on sait qui a vu, et quand.

## Modele de donnees

### `SubscriptionCorrection`

| Champ | Role |
| --- | --- |
| `subscription` | l'abonnement corrige |
| `gym` | la salle, pour le cloisonnement |
| `previous_start`, `previous_end` | la periode d'avant, seule trace qui en reste |
| `new_start`, `new_end` | la periode posee |
| `reason` | motif, **obligatoire** : le proprietaire doit savoir pourquoi |
| `corrected_by`, `corrected_at` | l'auteur |
| `acknowledged_by`, `acknowledged_at` | l'accuse de reception, vides tant qu'il manque |

Une table a part plutot que des champs sur l'abonnement : une periode peut etre
corrigee deux fois, et l'historique de ces gestes est precisement ce que le
proprietaire veut pouvoir relire.

## Regles

**A la saisie d'un abonnement**

1. la date de debut reste libre, passee comprise ;
2. si `start + duree < aujourd'hui`, l'ecran avertit : « Cette periode s'est
   terminee le 12/08 : le membre n'aura aucun acces. Confirmer ? » ;
3. confirmee, la vente passe - on ne bloque pas une regularisation comptable.

**A la correction**

1. reservee au proprietaire et au gerant ;
2. seule la date de debut se saisit ; la fin se recalcule sur la duree de la
   formule, pour qu'une correction ne puisse pas allonger discretement un
   abonnement ;
3. le motif est obligatoire ;
4. la nouvelle periode ne doit chevaucher aucun autre abonnement du membre -
   la regle existe deja dans `MemberSubscription.clean()` ;
5. **le paiement n'est pas touche** ;
6. si l'auteur n'est pas le proprietaire, la correction attend son accuse de
   reception.

## Ce qu'il reste a decider

- **Le nombre de corrections par abonnement.** Faut-il en limiter le nombre ?
  Une periode corrigee trois fois signale autre chose qu'une faute de frappe.
- **La visibilite cote gerant.** Doit-il voir que sa correction attend encore
  l'accuse de reception du proprietaire ?

## Fichiers concernes

| Fichier | Role |
| --- | --- |
| `pos/services.py` | l'avertissement sur une periode deja close |
| `subscriptions/models.py` | `SubscriptionCorrection` |
| `subscriptions/views.py` | l'ecran de correction, l'accuse de reception |
| `smartclub/context_processors.py` | le bandeau, a cote de celui des lecteurs |
| `templates/base.html` | l'affichage du bandeau |
