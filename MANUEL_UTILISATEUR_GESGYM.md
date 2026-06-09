# Manuels GesGym

Ce fichier sert maintenant de point d'entree vers les deux documentations
principales de GesGym.

Derniere actualisation : 09/06/2026.

## Choisir le bon manuel

- [MANUEL_ADMIN_SAAS_GESGYM.md](D:/GesGym/MANUEL_ADMIN_SAAS_GESGYM.md)
  Manuel reserve a notre equipe SaaS.
  Il couvre l'administration de la plateforme, les organisations, les packs,
  la creation des owners, la synchronisation des modules et les operations de supervision.

- [MANUEL_CLIENT_GESGYM.md](D:/GesGym/MANUEL_CLIENT_GESGYM.md)
  Manuel destine aux clients et aux equipes terrain.
  Il couvre l'utilisation quotidienne de l'application par les owners, managers,
  receptions, cashiers, coaches et membres.

- [docs/MEDIA_STORAGE_GESGYM.md](D:/GesGym/docs/MEDIA_STORAGE_GESGYM.md)
  Note technique sur les images du projet.
  Elle distingue les fichiers statiques SmartClub, les medias utilisateurs et
  la preparation de la future configuration Backblaze B2.

## Regle de lecture

- si le sujet concerne la plateforme, les packs, l'onboarding d'un client ou l'admin Django : lire le manuel SaaS
- si le sujet concerne l'exploitation d'une salle, les modules metier ou les routines quotidiennes : lire le manuel client

## Notes

- le pack est choisi au niveau `Organization`
- les modules restent appliques techniquement au niveau des `GymModule`
- les deux manuels sont alignes sur l'etat actuel du depot
- les medias utilisateurs sont encore locaux aujourd'hui ; Backblaze B2 est prevu mais ne bloque pas l'utilisation actuelle
