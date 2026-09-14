"""
Le depart d'un employe se repercute sur les lecteurs.

Les signaux ne font que *marquer* le retrait : aucun appel reseau ici, pour
qu'une desactivation - depuis l'ecran RH, l'administration ou un script - ne
soit jamais ralentie ni bloquee par un lecteur. Le retrait est ensuite tente
par l'ecran RH, le bouton de l'alerte ou la synchronisation.
"""

from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver


@receiver(post_save, sender="rh.Employee")
def employe_desactive(sender, instance, created, **kwargs):
    if created or instance.is_active:
        return
    from . import personnel

    personnel.demander_retrait(instance)


@receiver(pre_delete, sender="rh.Employee")
def employe_supprime(sender, instance, **kwargs):
    from . import personnel

    personnel.demander_retrait(instance)
