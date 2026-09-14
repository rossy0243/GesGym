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
import re

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
        # Les fiches connues d'abord - dont une fiche du terminal adoptee, qui
        # garde son propre numero. A defaut, le numero de la plage du personnel.
        fiches = list(StaffReaderRecord.objects.filter(device=device, employee=employee))
        if not fiches:
            fiches = [StaffReaderRecord(
                gym=device.gym,
                device=device,
                employee=employee,
                employee_no=numero,
                nom=(employee.name or "")[:255],
            )]
        for fiche in fiches:
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


# ---------------------------------------------------------------------------
# Employes enregistres comme membres
# ---------------------------------------------------------------------------
#
# Avant que le personnel ait sa place, certains employes ont ete inscrits comme
# membres pour pouvoir passer la porte. La bascule reprend leur visage sur leur
# fiche d'employe et desactive la fiche membre, sans rien effacer : paiements,
# abonnements et passages restent ce qu'ils ont ete.


def photo_reprise_possible(member):
    """
    Vrai si la photo du membre a ete prise par le lecteur a son enrolement.

    Seule celle-la est reprise : le capteur l'a deja acceptee. Une photo
    televersee depuis un telephone est souvent refusee par le lecteur.
    """
    nom = member.photo.name if member.photo else ""
    return bool(re.search(rf"visage_membre_{member.id}(?!\d)", nom or ""))


def photo_du_lecteur(member):
    """Les octets de la photo prise par le lecteur, ou None."""
    if not photo_reprise_possible(member):
        return None
    try:
        member.photo.open("rb")
        try:
            return member.photo.read()
        finally:
            member.photo.close()
    except (OSError, ValueError) as exc:
        logger.warning("Photo du membre %s illisible : %s", member.id, exc)
        return None


def membres_candidats(employee, recherche=""):
    """
    Fiches membres qui pourraient etre celles de cet employe.

    Sans recherche, on propose celles qui portent le meme telephone ou le meme
    nom. Seules les fiches actives de la salle sont proposees.
    """
    from django.db.models import Q

    from members.models import Member

    membres = Member.objects.filter(gym=employee.gym, is_active=True)
    recherche = (recherche or "").strip()

    if recherche:
        membres = membres.filter(
            Q(first_name__icontains=recherche)
            | Q(last_name__icontains=recherche)
            | Q(phone__icontains=recherche)
        )
    else:
        critere = Q(pk__in=[])
        chiffres = "".join(ch for ch in (employee.phone or "") if ch.isdigit())
        if len(chiffres) >= 9:
            critere |= Q(phone__endswith=chiffres[-9:])
        mots = (employee.name or "").split()
        if len(mots) >= 2:
            premier, reste = mots[0], " ".join(mots[1:])
            critere |= Q(first_name__iexact=premier, last_name__iexact=reste)
            critere |= Q(first_name__iexact=reste, last_name__iexact=premier)
        membres = membres.filter(critere)

    return [
        {"membre": membre, "visage": photo_reprise_possible(membre)}
        for membre in membres.order_by("first_name", "last_name")[:8]
    ]


def _reposer_membre(lecteurs, member, photo):
    """Remet la fiche membre la ou elle venait d'etre retiree."""
    for device in lecteurs:
        try:
            enrollment.inscrire_membre(device, member, photo)
        except enrollment.EnrollmentError as exc:
            logger.warning(
                "Fiche du membre %s non reposee sur %s : %s", member.id, device.name, exc
            )


def basculer_membre(employee, member):
    """
    Fait passer au personnel un employe qui entrait avec une fiche membre.

    1. la fiche membre quitte chaque lecteur - d'abord, car le lecteur refuse
       d'attacher un meme visage a deux fiches ;
    2. la fiche membre est desactivee, son historique intact ;
    3. l'employe est inscrit, avec la photo du lecteur quand elle existe.

    Si un lecteur ne repond pas a l'etape 1, rien n'est change et les fiches
    deja retirees sont reposees. Leve EnrollmentError dans ce cas.
    """
    from . import hikvision

    if member.gym_id != employee.gym_id:
        raise enrollment.EnrollmentError("Ce membre n'appartient pas a cette salle.")
    if not employee.is_active:
        raise enrollment.EnrollmentError(
            f"{employee.name} est desactive dans le module RH."
        )
    if not member.is_active:
        raise enrollment.EnrollmentError("Cette fiche membre est deja desactivee.")

    photo = photo_du_lecteur(member)
    lecteurs = enrollment.lecteurs_de(employee.gym)
    numero_membre = enrollment.employee_no(member)

    retires = []
    for device in lecteurs:
        client = hikvision.HikvisionClient.from_device(device, timeout=25)
        try:
            client.delete_user(numero_membre)
        except (hikvision.HikvisionUnreachable, hikvision.HikvisionAuthError) as exc:
            _reposer_membre(retires, member, photo)
            raise enrollment.EnrollmentError(
                f"{device.name} ne repond pas ({exc}). Rien n'a ete change : "
                "reessayez quand le lecteur est joignable."
            ) from exc
        except hikvision.HikvisionError as exc:
            # Un refus sans panne vient le plus souvent d'une fiche absente de
            # ce lecteur. Si elle y est encore, la pose du visage le dira.
            logger.info(
                "Retrait de la fiche membre %s sur %s refuse : %s",
                numero_membre, device.name, exc,
            )
        retires.append(device)

    member.is_active = False
    member.save(update_fields=["is_active"])

    echecs = []
    for device in lecteurs:
        try:
            enrollment.inscrire_employe(device, employee, photo)
        except enrollment.EnrollmentError as exc:
            echecs.append(f"{device.name} : {exc}")
            if "fiche est enregistree" not in str(exc):
                continue
        noter_inscription(device, employee)

    return {"photo": photo is not None, "lecteurs": len(lecteurs), "echecs": echecs}


# ---------------------------------------------------------------------------
# Fiches creees a la main sur le terminal
# ---------------------------------------------------------------------------
#
# Un employe cree directement sur le terminal entre avec son visage, mais
# l'application ne le connait pas. Le lecteur refuse de lui attacher le meme
# visage une seconde fois : on rattache donc sa fiche existante a l'employe,
# sans nouvelle capture. La fiche garde son petit numero ; le lien est porte
# par StaffReaderRecord, et vaut pour ce lecteur seulement.


def est_une_fiche_du_terminal(numero):
    """Vrai pour un numero que l'application n'a pas pose."""
    numero = str(numero or "").strip()
    return (
        numero.isdigit()
        and enrollment.member_id_depuis(numero) is None
        and enrollment.employee_id_depuis(numero) is None
    )


def employe_de_la_fiche(device, numero):
    """
    L'employe derriere un numero lu par ce lecteur, ou None.

    Un numero de la plage du personnel designe l'employe directement. Un petit
    numero designe un employe s'il a ete adopte - sur ce lecteur : deux
    lecteurs peuvent porter le meme petit numero pour deux personnes.
    """
    from rh.models import Employee

    numero = str(numero or "").strip()
    if not numero:
        return None

    employee_id = enrollment.employee_id_depuis(numero)
    if employee_id is not None:
        return Employee.objects.filter(gym=device.gym, id=employee_id).first()

    fiche = (
        StaffReaderRecord.objects.filter(
            device=device, employee_no=numero, employee__isnull=False, employee__gym=device.gym
        )
        .select_related("employee")
        .first()
    )
    return fiche.employee if fiche else None


def fiches_du_terminal(gym, recherche=""):
    """
    Fiches creees a la main sur les lecteurs actifs, et pas encore adoptees.

    Interroge chaque lecteur : a n'appeler que sur demande. Un lecteur
    injoignable est signale sans empecher de lire les autres.
    """
    from . import hikvision

    recherche = (recherche or "").strip().lower()
    resultat = {"fiches": [], "erreurs": []}

    for device in enrollment.lecteurs_de(gym):
        try:
            lues = hikvision.HikvisionClient.from_device(device, timeout=25).list_users()
        except hikvision.HikvisionError as exc:
            resultat["erreurs"].append(f"{device.name} : {exc}")
            continue

        adoptees = set(
            StaffReaderRecord.objects.filter(device=device).values_list("employee_no", flat=True)
        )
        for fiche in lues:
            numero = str(fiche.get("employeeNo") or "").strip()
            if (
                not numero
                or not est_une_fiche_du_terminal(numero)
                or numero in adoptees
            ):
                continue
            nom = str(fiche.get("name") or "").strip()
            if recherche and recherche not in nom.lower() and recherche not in numero:
                continue
            resultat["fiches"].append(
                {"device": device, "numero": numero, "nom": nom or f"Fiche {numero}"}
            )

    return resultat


def adopter_fiche(device, employee, numero):
    """Rattache une fiche du terminal a un employe. Leve EnrollmentError."""
    numero = str(numero or "").strip()

    if device.gym_id != employee.gym_id or not device.is_active:
        raise enrollment.EnrollmentError("Ce lecteur n'appartient pas a cette salle.")
    if not employee.is_active:
        raise enrollment.EnrollmentError(
            f"{employee.name} est desactive dans le module RH."
        )
    if not est_une_fiche_du_terminal(numero):
        raise enrollment.EnrollmentError(
            "Seule une fiche creee a la main sur le terminal peut etre rattachee."
        )

    deja = StaffReaderRecord.objects.filter(device=device, employee_no=numero).first()
    if deja is not None:
        if deja.employee_id == employee.id:
            return deja
        raise enrollment.EnrollmentError(
            f"Cette fiche est deja rattachee a {deja.nom or 'une autre personne'}."
        )

    return StaffReaderRecord.objects.create(
        gym=device.gym,
        device=device,
        employee=employee,
        employee_no=numero,
        nom=(employee.name or "")[:255],
    )


def fiches_adoptees(employee):
    """Fiches du terminal rattachees a cet employe."""
    return [
        fiche
        for fiche in StaffReaderRecord.objects.filter(
            employee=employee, retrait_demande_le__isnull=True
        ).select_related("device")
        if est_une_fiche_du_terminal(fiche.employee_no)
    ]

