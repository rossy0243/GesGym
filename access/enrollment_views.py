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
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.audit import log_sensitive_action
from members.models import Member
from smartclub.access_control import (
    ACCESS_DEVICE_ROLES,
    ACCESS_DEVICE_USE_ROLES,
    RH_EMPLOYEE_ROLES,
    has_role,
)
from smartclub.decorators import module_required, role_required

from . import enrollment, personnel
from .models import AccessDevice, StaffReaderRecord

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
            "sujet": "le membre",
            "url_capture": reverse("access:face_capture", args=[member.id]),
            "url_valider": reverse("access:face_confirm", args=[member.id]),
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


# ---------------------------------------------------------------------------
# Enrolement du personnel
# ---------------------------------------------------------------------------
#
# Meme parcours que pour un membre, depuis la fiche RH. Reserve au proprietaire
# et au gerant : inscrire quelqu'un qui entre a toute heure, sans abonnement,
# n'est pas un geste d'accueil.

CLE_SESSION_PERSONNEL = "enrolement_visage_personnel"


def _employe_de(request, employee_id):
    from rh.models import Employee

    return get_object_or_404(Employee, id=employee_id, gym=request.gym)


@login_required
@module_required("ACCESS")
@role_required(RH_EMPLOYEE_ROLES)
def staff_face_enrollment(request, employee_id):
    """Ecran d'enrolement du visage d'un employe."""
    employe = _employe_de(request, employee_id)

    capture = request.session.get(CLE_SESSION_PERSONNEL)
    apercu = None
    if capture and capture.get("employee_id") == employe.id:
        apercu = capture.get("image_b64")

    recherche_membre = (request.GET.get("membre") or "").strip()
    # Lire les fiches du lecteur prend du temps : seulement sur demande.
    afficher_fiches = request.GET.get("fiches") == "1"
    recherche_fiche = (request.GET.get("fiche") or "").strip()

    return render(
        request,
        "access/face_enrollment_employee.html",
        {
            "gym": request.gym,
            "employee": employe,
            "devices": enrollment.lecteurs_de(request.gym),
            "apercu_base64": apercu,
            "employee_no": enrollment.numero_personnel(employe),
            "sujet": "l'employé",
            "url_capture": reverse("access:staff_face_capture", args=[employe.id]),
            "url_valider": reverse("access:staff_face_confirm", args=[employe.id]),
            "recherche_membre": recherche_membre,
            "membres_candidats": (
                personnel.membres_candidats(employe, recherche_membre)
                if employe.is_active
                else []
            ),
            "recherche_fiche": recherche_fiche,
            "fiches_terminal": (
                personnel.fiches_du_lecteur(request.gym, recherche_fiche)
                if afficher_fiches and employe.is_active
                else None
            ),
            "fiches_adoptees": personnel.fiches_adoptees(employe),
        },
    )


@login_required
@module_required("ACCESS")
@role_required(RH_EMPLOYEE_ROLES)
@require_POST
def staff_face_capture(request, employee_id):
    """Declenche la photographie ; l'image attend en session d'etre acceptee."""
    employe = _employe_de(request, employee_id)

    if not employe.is_active:
        return JsonResponse(
            {"ok": False, "error": f"{employe.name} est desactive dans le module RH."},
            status=400,
        )

    lecteur = _lecteur_de(request, request.POST.get("device_id"))
    if lecteur is None:
        return JsonResponse(
            {"ok": False, "error": "Choisissez le lecteur devant lequel se trouve l'employe."},
            status=400,
        )

    try:
        image = enrollment.capturer_visage(lecteur)
    except enrollment.EnrollmentError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    encodee = base64.b64encode(image).decode()
    request.session[CLE_SESSION_PERSONNEL] = {
        "employee_id": employe.id,
        "device_id": lecteur.id,
        "image_b64": encodee,
    }
    request.session.modified = True

    return JsonResponse({"ok": True, "image": encodee, "device": lecteur.name})


@login_required
@module_required("ACCESS")
@role_required(RH_EMPLOYEE_ROLES)
@require_POST
def staff_face_confirm(request, employee_id):
    """Inscrit l'employe sur le lecteur avec le visage accepte."""
    employe = _employe_de(request, employee_id)
    capture = request.session.get(CLE_SESSION_PERSONNEL)

    if not capture or capture.get("employee_id") != employe.id:
        messages.error(request, "Aucune capture en attente. Relancez la capture.")
        return redirect("access:staff_face_enrollment", employee_id=employe.id)

    image = base64.b64decode(capture["image_b64"])
    lecteur = get_object_or_404(AccessDevice, id=capture["device_id"], gym=request.gym)

    try:
        resultat = enrollment.inscrire_employe(lecteur, employe, image)
    except enrollment.EnrollmentError as exc:
        messages.error(request, str(exc))
        return redirect("access:staff_face_enrollment", employee_id=employe.id)

    # Retenir le lecteur : c'est ce qui permettra d'en retirer le visage au
    # depart de l'employe.
    personnel.noter_inscription(lecteur, employe)
    request.session.pop(CLE_SESSION_PERSONNEL, None)
    log_sensitive_action(
        request,
        "access.staff_face_enrolled",
        "Employee",
        employe.name,
        metadata={
            "employee_id": employe.id,
            "lecteur": lecteur.name,
            "employee_no": resultat["employee_no"],
        },
        gym=request.gym,
    )
    messages.success(
        request,
        f"Visage enrole. {employe.name} entre par reconnaissance faciale, a "
        "toute heure, tant que sa fiche RH est active.",
    )
    return redirect("access:staff_face_enrollment", employee_id=employe.id)


@login_required
@module_required("ACCESS")
@role_required(RH_EMPLOYEE_ROLES)
@require_POST
def staff_face_remove(request, employee_id):
    """Retire l'employe des lecteurs de la salle."""
    employe = _employe_de(request, employee_id)

    # Un retrait non confirme reste en attente, avec son alerte.
    echecs = personnel.retirer_partout(employe)

    log_sensitive_action(
        request,
        "access.staff_face_removed",
        "Employee",
        employe.name,
        metadata={"employee_id": employe.id, "echecs": echecs},
        gym=request.gym,
    )

    if echecs:
        messages.error(request, "Retrait incomplet. " + " ".join(echecs))
    else:
        messages.success(
            request, f"{employe.name} ne peut plus entrer par reconnaissance faciale."
        )

    return redirect("access:staff_face_enrollment", employee_id=employe.id)


@login_required
@module_required("ACCESS")
@role_required(RH_EMPLOYEE_ROLES)
@require_POST
def staff_switch_from_member(request, employee_id):
    """Reprend le visage d'un employe qui entrait avec une fiche membre."""
    employe = _employe_de(request, employee_id)
    try:
        member_id = int(request.POST.get("member_id", ""))
    except (TypeError, ValueError):
        raise Http404
    membre = get_object_or_404(Member, id=member_id, gym=request.gym)
    nom_membre = f"{membre.first_name} {membre.last_name}".strip() or membre.phone

    try:
        resultat = personnel.basculer_membre(employe, membre)
    except enrollment.EnrollmentError as exc:
        messages.error(request, str(exc))
        return redirect("access:staff_face_enrollment", employee_id=employe.id)

    log_sensitive_action(
        request,
        "access.member_switched_to_staff",
        "Employee",
        employe.name,
        metadata={
            "employee_id": employe.id,
            "member_id": membre.id,
            "membre": nom_membre,
            "visage_repris": resultat["photo"],
            "echecs": resultat["echecs"],
        },
        gym=request.gym,
    )

    messages.success(
        request,
        f"La fiche membre de {nom_membre} est desactivee ; son historique est conserve.",
    )
    if resultat["non_retirees"]:
        # C'est ce qui produit ensuite "ce visage existe deja" sans qu'on sache
        # ou le chercher : autant le dire tout de suite, et dire quoi faire.
        messages.warning(
            request,
            "Le lecteur n'a pas confirme la suppression de l'ancienne fiche "
            + " ".join(resultat["non_retirees"])
            + ". Si la capture est refusee (« visage deja enregistre »), ouvrez "
            "« Fiches presentes sur le lecteur » et liberez la fiche qui le porte.",
        )
    if resultat["echecs"]:
        messages.warning(
            request, "Le lecteur n'a pas tout accepte. " + " ".join(resultat["echecs"])
        )
    elif not resultat["photo"]:
        messages.warning(
            request,
            "Sa fiche membre n'avait pas de photo prise par le lecteur : capturez "
            f"maintenant le visage de {employe.name} ci-dessous.",
        )
    elif resultat["lecteurs"]:
        messages.success(
            request, f"Visage repris : {employe.name} entre desormais comme personnel."
        )

    return redirect("access:staff_face_enrollment", employee_id=employe.id)


@login_required
@module_required("ACCESS")
@role_required(RH_EMPLOYEE_ROLES)
@require_POST
def staff_release_face(request, employee_id):
    """
    Supprime du lecteur une fiche qui bloque un visage.

    Le lecteur refuse d'attacher un meme visage a deux fiches. Quand la fiche
    qui le porte n'est plus utile - membre parti, essai, enrolement rate - il
    faut pouvoir la liberer sans passer par l'ecran du terminal.
    """
    employe = _employe_de(request, employee_id)
    try:
        device_id = int(request.POST.get("device_id", ""))
    except (TypeError, ValueError):
        raise Http404
    lecteur = get_object_or_404(AccessDevice, id=device_id, gym=request.gym, is_active=True)
    numero = (request.POST.get("employee_no") or "").strip()
    porteur = (request.POST.get("porteur") or "").strip()[:255]

    try:
        personnel.liberer_fiche(lecteur, numero)
    except enrollment.EnrollmentError as exc:
        messages.error(request, str(exc))
        return redirect("access:staff_face_enrollment", employee_id=employe.id)

    log_sensitive_action(
        request,
        "access.reader_record_released",
        "AccessDevice",
        lecteur.name,
        metadata={
            "employee_no": numero,
            "porteur": porteur,
            "demande_pour": employe.name,
            "employee_id": employe.id,
        },
        gym=request.gym,
    )
    messages.success(
        request,
        f"Fiche n° {numero} supprimee de {lecteur.name}"
        + (f" ({porteur})." if porteur else ".")
        + " Le visage est libere : vous pouvez le capturer.",
    )
    return redirect("access:staff_face_enrollment", employee_id=employe.id)


@login_required
@module_required("ACCESS")
@role_required(RH_EMPLOYEE_ROLES)
@require_POST
def staff_adopt_terminal_record(request, employee_id):
    """Rattache a un employe la fiche que le terminal porte deja pour lui."""
    employe = _employe_de(request, employee_id)
    try:
        device_id = int(request.POST.get("device_id", ""))
    except (TypeError, ValueError):
        raise Http404
    lecteur = get_object_or_404(AccessDevice, id=device_id, gym=request.gym, is_active=True)
    numero = (request.POST.get("employee_no") or "").strip()
    nom_terminal = (request.POST.get("nom") or "").strip()[:128]

    try:
        personnel.adopter_fiche(lecteur, employe, numero)
    except enrollment.EnrollmentError as exc:
        messages.error(request, str(exc))
        return redirect("access:staff_face_enrollment", employee_id=employe.id)

    log_sensitive_action(
        request,
        "access.staff_terminal_record_adopted",
        "Employee",
        employe.name,
        metadata={
            "employee_id": employe.id,
            "lecteur": lecteur.name,
            "employee_no": numero,
            "nom_sur_le_terminal": nom_terminal,
        },
        gym=request.gym,
    )
    messages.success(
        request,
        f"Fiche n° {numero} du terminal ({nom_terminal or 'sans nom'}) rattachee a "
        f"{employe.name} : il entre avec le meme visage, et ses passages sont "
        "journalises a son nom.",
    )
    return redirect("access:staff_face_enrollment", employee_id=employe.id)


@login_required
@module_required("ACCESS")
@role_required(RH_EMPLOYEE_ROLES)
@require_POST
def staff_removal_retry(request, record_id):
    """Relance le retrait d'un visage que le lecteur n'a pas confirme."""
    fiche = get_object_or_404(
        StaffReaderRecord.objects.select_related("device"),
        id=record_id,
        gym=request.gym,
        retrait_demande_le__isnull=False,
    )
    nom = fiche.nom or fiche.employee_no
    lecteur = fiche.device.name

    confirme = personnel.reessayer(fiche)

    log_sensitive_action(
        request,
        "access.staff_face_removal_retried",
        "Employee",
        nom,
        metadata={
            "employee_no": fiche.employee_no,
            "lecteur": lecteur,
            "confirme": confirme,
            "erreur": "" if confirme else fiche.derniere_erreur,
        },
        gym=request.gym,
    )

    if confirme:
        messages.success(request, f"Visage de {nom} retire de {lecteur}.")
    else:
        messages.error(
            request,
            f"{lecteur} n'a toujours pas confirme le retrait de {nom} : "
            f"{fiche.derniere_erreur}",
        )

    suite = request.POST.get("next") or ""
    if url_has_allowed_host_and_scheme(suite, allowed_hosts={request.get_host()}):
        return redirect(suite)
    return redirect("core:gym_dashboard", gym_id=request.gym.id)


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
