"""
Le personnel sur les lecteurs : ou se trouve chaque visage, et son retrait.

Un employe qui quitte la salle doit perdre l'acces le jour meme. Le retrait se
fait sur le lecteur, qui peut etre eteint ou injoignable a ce moment-la : le
retrait est donc d'abord *demande*, puis *tente*, et reste en attente - avec
une alerte sur le tableau de bord - tant que le lecteur ne l'a pas confirme.

Aucune fonction de ce module ne leve : desactiver un employe ne doit jamais
echouer parce qu'un lecteur est debranche.
"""

import logging

from django.utils import timezone

from . import enrollment
from .models import StaffReaderRecord

logger = logging.getLogger(__name__)


def noter_inscription(device, employee):
    """Retient qu'un employe a ete inscrit sur ce lecteur."""
    fiche, _ = StaffReaderRecord.objects.update_or_create(
        device=device,
        employee_no=enrollment.numero_personnel(employee),
        defaults={
            "gym": device.gym,
            "employee": employee,
            "nom": (employee.name or "")[:255],
            "retrait_demande_le": None,
            "derniere_erreur": "",
        },
    )
    return fiche


def demander_retrait(employee):
    """
    Marque les fiches de l'employe comme a retirer, sans appeler le lecteur.

    Appelee a chaque desactivation, d'ou qu'elle vienne : meme si personne ne
    tente le retrait tout de suite, l'alerte existe.
    """
    return StaffReaderRecord.objects.filter(
        employee=employee, retrait_demande_le__isnull=True
    ).update(retrait_demande_le=timezone.now())


def tenter(fiche):
    """Tente le retrait d'une fiche. Vrai si le lecteur l'a confirme."""
    maintenant = timezone.now()
    fiche.derniere_tentative_le = maintenant
    if fiche.retrait_demande_le is None:
        fiche.retrait_demande_le = maintenant

    try:
        enrollment.retirer_fiche(fiche.device, fiche.employee_no)
    except enrollment.EnrollmentError as exc:
        fiche.derniere_erreur = str(exc)[:1000]
        if fiche.pk:
            fiche.save(update_fields=[
                "retrait_demande_le", "derniere_tentative_le", "derniere_erreur",
            ])
        else:
            fiche.save()
        logger.warning(
            "Retrait de la fiche %s sur %s non confirme : %s",
            fiche.employee_no, fiche.device.name, exc,
        )
        return False

    if fiche.pk:
        fiche.delete()
    return True


def retirer_des_lecteurs(employee):
    """
    Retire l'employe des lecteurs ou il a ete inscrit.

    Seules les fiches connues sont concernees : un employe jamais enrole ne
    declenche aucun appel au materiel. Renvoie le nombre de retraits confirmes
    et les fiches encore en attente.
    """
    demander_retrait(employee)
    confirmees = 0
    restantes = []
    fiches = StaffReaderRecord.objects.filter(
        employee=employee, retrait_demande_le__isnull=False
    ).select_related("device")
    for fiche in fiches:
        if tenter(fiche):
            confirmees += 1
        else:
            restantes.append(fiche)
    return {"confirmees": confirmees, "restantes": restantes}


def retirer_partout(employee):
    """
    Retrait demande depuis l'ecran d'enrolement : tous les lecteurs actifs.

    La fiche est tentee meme si l'application ne l'a pas notee : l'operateur
    qui clique veut que la personne n'entre plus, ou qu'elle ait ete inscrite.
    Renvoie les echecs, lisibles.
    """
    numero = enrollment.numero_personnel(employee)
    echecs = []
    for device in enrollment.lecteurs_de(employee.gym):
        fiche = StaffReaderRecord.objects.filter(device=device, employee_no=numero).first()
        if fiche is None:
            fiche = StaffReaderRecord(
                gym=device.gym,
                device=device,
                employee=employee,
                employee_no=numero,
                nom=(employee.name or "")[:255],
            )
        if not tenter(fiche):
            echecs.append(f"{device.name} : {fiche.derniere_erreur}")
    return echecs


def reessayer(fiche):
    """Nouvelle tentative, depuis l'alerte du tableau de bord."""
    return tenter(fiche)


def en_attente(gym):
    """Retraits demandes que le lecteur n'a pas encore confirmes."""
    return (
        StaffReaderRecord.objects.filter(
            gym=gym, retrait_demande_le__isnull=False, device__is_active=True
        )
        .select_related("device", "employee")
        .order_by("retrait_demande_le")
    )
