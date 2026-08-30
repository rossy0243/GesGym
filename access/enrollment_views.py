"""
Enrolement du visage d'un membre, capture faite par le lecteur lui-meme.

Le parcours tient en trois temps, et l'ecran les enonce a l'operateur :

1. le membre se place devant le terminal ;
2. le lecteur photographie, l'operateur voit l'image et l'accepte ou la refuse ;
3. l'application range la photo dans la fiche membre et inscrit le membre sur
   le lecteur avec les dates de son abonnement.

La capture vient du capteur qui servira ensuite a reconnaitre : c'est ce qui
rend l'enrolement fiable, la ou une photo de telephone echoue souvent au
cadrage ou a l'eclairage.
"""

import base64
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.audit import log_sensitive_action
from members.models import Member
from smartclub.access_control import ACCESS_DEVICE_ROLES, ACCESS_DEVICE_USE_ROLES, has_role
from smartclub.decorators import module_required, role_required

from . import enrollment
from .models import AccessDevice

logger = logging.getLogger("access")

# Duree pendant laquelle une capture reste en session avant validation.
CLE_SESSION = "enrolement_visage"


def _lecteur_de(request, device_id=None):
    """Lecteur cible : celui demande, ou l'unique lecteur actif de la salle."""
    lecteurs = enrollment.lecteurs_de(request.gym)
    if device_id:
        for lecteur in lecteurs:
            if lecteur.id == int(device_id):
                return lecteur
        return None
    return lecteurs[0] if len(lecteurs) == 1 else None


@login_required
@module_required("ACCESS")
@role_required(ACCESS_DEVICE_USE_ROLES)
def face_enrollment(request, member_id):
    """Ecran d'enrolement : consignes, capture, validation."""
    member = get_object_or_404(
        Member.objects.select_related("gym"), id=member_id, gym=request.gym
    )
    lecteurs = enrollment.lecteurs_de(request.gym)
    subscription = member.active_subscription

    capture = request.session.get(CLE_SESSION)
    apercu = None
    if capture and capture.get("member_id") == member.id:
        apercu = capture.get("image_b64")

    return render(
        request,
        "access/face_enrollment.html",
        {
            "gym": request.gym,
            "member": member,
            "devices": lecteurs,
            "subscription": subscription,
            "apercu_base64": apercu,
            "employee_no": enrollment.employee_no(member),
        },
    )


@login_required
@module_required("ACCESS")
@role_required(ACCESS_DEVICE_USE_ROLES)
@require_POST
def face_capture(request, member_id):
    """
    Declenche la photographie sur le lecteur.

    L'image n'est pas enregistree tout de suite : elle attend en session que
    l'operateur l'accepte. Une photo floue ou mal cadree ne doit pas atterrir
    dans la fiche du membre.
    """
    member = get_object_or_404(Member, id=member_id, gym=request.gym)
    lecteur = _lecteur_de(request, request.POST.get("device_id"))

    if lecteur is None:
        return JsonResponse(
            {"ok": False, "error": "Choisissez le lecteur devant lequel se trouve le membre."},
            status=400,
        )

    try:
        image = enrollment.capturer_visage(lecteur)
    except enrollment.EnrollmentError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    encodee = base64.b64encode(image).decode()
    request.session[CLE_SESSION] = {
        "member_id": member.id,
        "device_id": lecteur.id,
        "image_b64": encodee,
    }
    request.session.modified = True

    return JsonResponse({"ok": True, "image": encodee, "device": lecteur.name})


@login_required
@module_required("ACCESS")
@role_required(ACCESS_DEVICE_USE_ROLES)
@require_POST
def face_confirm(request, member_id):
    """Range la photo dans la fiche membre et inscrit le membre sur le lecteur."""
    member = get_object_or_404(
        Member.objects.select_related("gym"), id=member_id, gym=request.gym
    )
    capture = request.session.get(CLE_SESSION)

    if not capture or capture.get("member_id") != member.id:
        messages.error(request, "Aucune capture en attente. Relancez la capture.")
        return redirect("access:face_enrollment", member_id=member.id)

    image = base64.b64decode(capture["image_b64"])
    lecteur = get_object_or_404(AccessDevice, id=capture["device_id"], gym=request.gym)

    try:
        resultat = enrollment.inscrire_membre(lecteur, member, image)
    except enrollment.EnrollmentError as exc:
        messages.error(request, str(exc))
        return redirect("access:face_enrollment", member_id=member.id)

    # La photo du lecteur devient la photo de la fiche : les deux montrent
    # desormais la meme personne, sous le meme angle.
    member.photo.save(
        f"visage_membre_{member.id}.jpg", ContentFile(image), save=True
    )

    request.session.pop(CLE_SESSION, None)
    log_sensitive_action(
        request,
        "access.face_enrolled",
        "Member",
        f"{member.first_name} {member.last_name}",
        metadata={
            "member_id": member.id,
            "lecteur": lecteur.name,
            "employee_no": resultat["employee_no"],
            "sans_abonnement": resultat["sans_abonnement"],
        },
        gym=request.gym,
    )

    if resultat["sans_abonnement"]:
        messages.warning(
            request,
            f"Visage enrole pour {member.first_name} {member.last_name}. "
            "Aucun abonnement en cours : le lecteur le reconnaitra mais "
            "n'ouvrira pas tant qu'un abonnement n'est pas encaisse.",
        )
    else:
        fin = member.active_subscription.end_date.strftime("%d/%m/%Y")
        messages.success(
            request,
            f"Visage enrole. {member.first_name} {member.last_name} entre par "
            f"reconnaissance faciale jusqu'au {fin}.",
        )

    return redirect("access:face_enrollment", member_id=member.id)


@login_required
@module_required("ACCESS")
@role_required(ACCESS_DEVICE_USE_ROLES)
@require_POST
def face_remove(request, member_id):
    """Retire le membre des lecteurs de la salle."""
    member = get_object_or_404(Member, id=member_id, gym=request.gym)

    echecs = []
    for lecteur in enrollment.lecteurs_de(request.gym):
        try:
            enrollment.retirer_membre(lecteur, member)
        except enrollment.EnrollmentError as exc:
            echecs.append(f"{lecteur.name} : {exc}")

    log_sensitive_action(
        request,
        "access.face_removed",
        "Member",
        f"{member.first_name} {member.last_name}",
        metadata={"member_id": member.id, "echecs": echecs},
        gym=request.gym,
    )

    if echecs:
        messages.error(request, "Retrait incomplet. " + " ".join(echecs))
    else:
        messages.success(
            request,
            f"{member.first_name} {member.last_name} ne peut plus entrer par "
            "reconnaissance faciale.",
        )

    return redirect("access:face_enrollment", member_id=member.id)


@login_required
@module_required("ACCESS")
@role_required(ACCESS_DEVICE_ROLES)
def device_messages(request, device_id):
    """
    Reglage des messages affiches sur l'ecran du lecteur.

    Le code couleur de cet ecran sert a l'operateur : il distingue d'un coup
    d'oeil l'accueil, le refus et l'inconnu. L'ecran du lecteur, lui, affiche
    du texte simple, sans couleur.
    """
    device = get_object_or_404(AccessDevice, id=device_id, gym=request.gym)

    etat = None
    erreur_lecture = ""
    try:
        etat = enrollment.lire_messages(device)
    except enrollment.EnrollmentError as exc:
        erreur_lecture = str(exc)

    if request.method == "POST":
        saisis = {
            cle: request.POST.get(cle, "") for cle, _l, _a, _c in enrollment.MESSAGES_LECTEUR
        }
        actif = bool(request.POST.get("enabled"))

        try:
            enrollment.ecrire_messages(device, actif, saisis)
        except enrollment.EnrollmentError as exc:
            messages.error(request, str(exc))
        else:
            log_sensitive_action(
                request,
                "access.device_messages_updated",
                "AccessDevice",
                device.name,
                metadata={"actif": actif, "messages": saisis},
                gym=request.gym,
            )
            if actif:
                messages.success(
                    request, f"Messages enregistres sur {device.name}."
                )
            else:
                messages.info(
                    request,
                    f"{device.name} affiche de nouveau ses messages d'origine.",
                )
            return redirect("access:device_messages", device_id=device.id)

        etat = {"enabled": actif, "messages": saisis}

    lignes = []
    for cle, libelle, aide, couleur in enrollment.MESSAGES_LECTEUR:
        lignes.append({
            "cle": cle,
            "libelle": libelle,
            "aide": aide,
            "couleur": couleur,
            "valeur": (etat or {}).get("messages", {}).get(cle, "") if etat else "",
        })

    return render(
        request,
        "access/device_messages.html",
        {
            "gym": request.gym,
            "device": device,
            "lignes": lignes,
            "actif": (etat or {}).get("enabled", False),
            "erreur_lecture": erreur_lecture,
            "longueur_max": enrollment.LONGUEUR_MESSAGE_MAX,
        },
    )
