# Dossiers de formation

Ce répertoire contient un **dossier par module** : la matière brute extraite du
code, destinée à écrire les supports de formation des équipes.

Ce ne sont pas des formations. Ce sont les documents de travail à partir
desquels on en rédige une.

## Régénérer les dossiers

```bash
python manage.py dossier_module --tous --dossier docs/formation
```

Un seul module, affiché à l'écran :

```bash
python manage.py dossier_module caisse
```

La liste des modules disponibles :

```bash
python manage.py dossier_module --liste
```

## Ce que contient chaque dossier

| Section | Contenu | Intérêt pour la formation |
|---|---|---|
| Parcours accessibles | Toutes les adresses du module et leur vue | Recenser les écrans à montrer |
| Données manipulées | Champs des modèles, valeurs possibles | Expliquer le vocabulaire métier |
| Qui a le droit de faire quoi | Garde-fous posés sur chaque action | Adapter la formation au rôle formé |
| Règles métier appliquées | Tous les refus opposés par le logiciel | Expliquer le *pourquoi* de chaque blocage |
| Ce que l'utilisateur lit | Messages exacts affichés à l'écran | Employer les mêmes mots que le logiciel |
| Traces au journal sensible | Actions consignées | Dire ce qui est tracé, et ce qui ne l'est pas |
| Écrans concernés | Gabarits du module | Préparer les captures d'écran |
| Comportements garantis | Intitulés des tests automatisés | **Les cas limites à faire pratiquer** |
| À compléter par un humain | Questions ouvertes | Ce que le code ne peut pas dire |

## Comment s'en servir avec Claude

Ouvre une conversation en lui donnant le dossier du module :

> Voici le dossier de formation du module Caisse (`docs/formation/dossier-caisse.md`).
> Rédige le support de formation destiné aux **caissiers**, avec les gestes
> quotidiens, les erreurs fréquentes et des exercices pratiques.

Le dossier fournit les faits ; l'audience, le ton et les exercices restent à
préciser. La section « À compléter par un humain » liste les décisions à
prendre avant de rédiger.

## Pourquoi ne pas générer la formation directement

Une documentation produite mécaniquement à partir du code donne un catalogue de
fonctions. Une formation répond à d'autres questions : que fait-on le matin en
ouvrant la salle, que se passe-t-il quand un membre conteste un montant, quel
geste corrige quelle erreur. Le code ne contient pas ces réponses — il contient
les faits sur lesquels elles s'appuient.

La section **Comportements garantis par les tests** est la plus précieuse : chaque
intitulé décrit une promesse vérifiée automatiquement. Ce sont exactement les cas
limites qu'une équipe doit savoir reconnaître.

## Fraîcheur

Les dossiers reflètent le code au moment de leur génération. Régénère-les après
toute évolution d'un module, sinon la formation décrira un logiciel qui n'existe
plus.
