"""
Gestion des lecteurs physiques de controle d'acces.

Couvre la decouverte reseau (l'app propose les lecteurs qu'elle detecte),
l'enregistrement, le test de liaison, l'ouverture distante de la porte et la
reception des evenements pousses par le lecteur.
"""

import json
import logging

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.audit import log_sensitive_action
from members.models import Member
from smartclub.access_control import ACCESS_DEVICE_ROLES
from smartclub.decorators import module_required, role_required

from . import door, enrollment, hikvision
from .models import AccessDevice
from .views import _record_access, _today_stats


logger = logging.getLogger("access")

UNKNOWN_CREDENTIAL_REASON = "Identifiant inconnu pour cette salle."


def _libelle_methode(device, nature, par_le_visage=False):
    """
    Ce que lira l'equipe dans le journal d'acces.

    On ne dit "visage" que si le lecteur l'affirme : un badge remonte par le
    meme champ ne doit pas passer pour une reconnaissance faciale.
    """
    if par_le_visage:
        return f"{device.name} (visage)"
    if nature == "lecteur":
        return f"{device.name} (badge)"
    return device.name
EMPTY_CREDENTIAL_REASON = "Aucun identifiant lisible dans le scan."


def _serialize_device(device):
    """Representation JSON d'un lecteur. Le mot de passe n'est jamais expose."""
    return {
        "id": device.id,
        "name": device.name,
        "brand": device.get_brand_display(),
        "host": device.host,
        "use_https": device.use_https,
        # Le secret du tunnel n'est jamais renvoye : on indique seulement
        # qu'il est renseigne, comme pour le mot de passe du lecteur.
        "tunnel_protege": bool(device.tunnel_client_id and device.tunnel_client_secret),
        "port": device.port,
        "door_number": device.door_number,
        "model": device.model_name,
        "serial": device.serial_number,
        "firmware": device.firmware,
        "mac": device.mac_address,
        "is_active": device.is_active,
        "open_on_granted": device.open_on_granted,
        "online": device.is_online,
        # Les deux sens de circulation, distincts : le lecteur nous parle
        # tout seul, mais lui parler exige d'entrer dans le reseau de la
        # salle. Un seul voyant pour les deux faisait passer un lecteur
        # parfaitement vivant pour une panne.
        "nous_parle": device.nous_parle,
        "joignable": device.est_joignable,
        "last_seen": device.last_seen_at.strftime("%d/%m/%Y %H:%M") if device.last_seen_at else "",
        "last_error": device.last_error,
        "webhook_path": f"/access/devices/webhook/{device.webhook_token}/",
    }


@login_required
@role_required(ACCESS_DEVICE_ROLES)
@module_required("ACCESS")
def device_list(request):
    """Lecteurs deja enregistres pour la salle courante."""
    devices = AccessDevice.objects.filter(gym=request.gym)
    return JsonResponse({"devices": [_serialize_device(item) for item in devices]})


@login_required
@role_required(ACCESS_DEVICE_ROLES)
@require_POST
@module_required("ACCESS")
def device_discover(request):
    """
    Cherche les lecteurs presents sur le reseau et les propose a l'utilisateur.

    Tente d'abord la decouverte SADP (multicast). Si le reseau la filtre, un
    balayage du sous-reseau du serveur prend le relais.
    """
    found = hikvision.discover_devices()
    method = "sadp"

    if not found:
        base = _server_subnet_base(request)
        if base:
            found = [
                {
                    "host": item["host"],
                    "mac": "",
                    "model": "",
                    "serial": "",
                    "firmware": "",
                    "http_port": item["http_port"],
                    "activated": True,
                    "dhcp": False,
                    "subnet_mask": "",
                    "gateway": "",
                }
                for item in hikvision.scan_subnet(base)
            ]
            method = "scan"

    known = AccessDevice.objects.filter(gym=request.gym)
    known_hosts = {item.host for item in known}
    known_macs = {item.mac_address.upper() for item in known if item.mac_address}

    for item in found:
        item["already_registered"] = (
            item["host"] in known_hosts
            or (item["mac"] and item["mac"].upper() in known_macs)
        )

    return JsonResponse({"devices": found, "method": method, "count": len(found)})


def _server_subnet_base(request):
    """Prefixe /24 du serveur, utilise pour le balayage de repli."""
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()

    parts = address.split(".")
    if len(parts) != 4:
        return None
    return ".".join(parts[:3])


@login_required
@role_required(ACCESS_DEVICE_ROLES)
@require_POST
@module_required("ACCESS")
def device_create(request):
    """Enregistre un lecteur, puis verifie immediatement la liaison."""
    payload = _request_payload(request)

    host = (payload.get("host") or "").strip()
    password = payload.get("password") or ""

    if not host:
        return JsonResponse({"error": "Adresse IP du lecteur manquante."}, status=400)
    if not password:
        return JsonResponse({"error": "Mot de passe du lecteur manquant."}, status=400)

    device = AccessDevice(
        gym=request.gym,
        name=(payload.get("name") or "").strip() or f"Lecteur {host}",
        host=host,
        port=int(payload.get("port") or 80),
        # Un lecteur joint par tunnel repond en HTTPS sur le port 443, et
        # exige un jeton pour prouver que l'appel vient de notre serveur.
        use_https=bool(payload.get("use_https")),
        tunnel_client_id=(payload.get("tunnel_client_id") or "").strip(),
        tunnel_client_secret=(payload.get("tunnel_client_secret") or "").strip(),
        username=(payload.get("username") or "admin").strip(),
        password=password,
        door_number=int(payload.get("door_number") or 1),
        mac_address=(payload.get("mac") or "").strip().upper(),
        model_name=(payload.get("model") or "").strip(),
        serial_number=(payload.get("serial") or "").strip(),
        firmware=(payload.get("firmware") or "").strip(),
    )

    try:
        device.full_clean(exclude=["webhook_token"])
    except Exception as exc:  # ValidationError : messages deja lisibles
        return JsonResponse({"error": _first_error(exc)}, status=400)

    try:
        device.save()
    except IntegrityError:
        return JsonResponse(
            {"error": "Un lecteur est deja enregistre sur cette adresse IP."},
            status=400,
        )

    log_sensitive_action(
        request,
        "access.device_registered",
        "AccessDevice",
        device.name,
        metadata={"device_id": device.id, "host": device.host, "port": device.port},
        gym=request.gym,
    )
    status = _refresh_device_state(device)
    return JsonResponse({"device": _serialize_device(device), "test": status}, status=201)


@login_required
@role_required(ACCESS_DEVICE_ROLES)
@require_POST
@module_required("ACCESS")
def device_test(request, device_id):
    """Verifie que le lecteur repond et rafraichit ses informations."""
    device = get_object_or_404(AccessDevice, id=device_id, gym=request.gym)
    status = _refresh_device_state(device)
    return JsonResponse({"device": _serialize_device(device), "test": status})


@login_required
@role_required(ACCESS_DEVICE_ROLES)
@require_POST
@module_required("ACCESS")
def device_open_door(request, device_id):
    """Ouverture distante du relais : sert a valider le cablage."""
    device = get_object_or_404(AccessDevice, id=device_id, gym=request.gym)
    client = hikvision.HikvisionClient.from_device(device)

    try:
        client.open_door(device.door_number)
    except hikvision.HikvisionError as exc:
        device.last_error = str(exc)[:255]
        device.save(update_fields=["last_error", "updated_at"])
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)

    device.last_seen_at = now()
    device.last_error = ""
    device.save(update_fields=["last_seen_at", "last_error", "updated_at"])
    # Ouvrir la porte a distance donne acces a la salle sans presenter de QR :
    # l'operation doit pouvoir etre rattachee a quelqu'un.
    log_sensitive_action(
        request,
        "access.door_opened_remotely",
        "AccessDevice",
        device.name,
        metadata={"device_id": device.id, "host": device.host, "porte": device.door_number},
        gym=request.gym,
    )
    return JsonResponse({"ok": True, "message": "Commande d'ouverture envoyee."})


@login_required
@role_required(ACCESS_DEVICE_ROLES)
@require_POST
@module_required("ACCESS")
def device_delete(request, device_id):
    device = get_object_or_404(AccessDevice, id=device_id, gym=request.gym)
    device_name = device.name
    device_host = device.host
    device.delete()
    log_sensitive_action(
        request,
        "access.device_deleted",
        "AccessDevice",
        device_name,
        metadata={"device_id": device_id, "host": device_host},
        gym=request.gym,
    )
    return JsonResponse({"ok": True})


def _refresh_device_state(device):
    """Interroge le lecteur et memorise le resultat sur la fiche."""
    client = hikvision.HikvisionClient.from_device(device)

    try:
        info = client.device_info()
    except hikvision.HikvisionAuthError as exc:
        device.last_error = str(exc)[:255]
        device.save(update_fields=["last_error", "updated_at"])
        return {"ok": False, "error": str(exc), "kind": "auth"}
    except hikvision.HikvisionUnreachable as exc:
        device.last_error = f"Lecteur injoignable : {exc}"[:255]
        device.save(update_fields=["last_error", "updated_at"])
        return {"ok": False, "error": device.last_error, "kind": "network"}
    except hikvision.HikvisionError as exc:
        device.last_error = str(exc)[:255]
        device.save(update_fields=["last_error", "updated_at"])
        return {"ok": False, "error": str(exc), "kind": "protocol"}

    device.model_name = info.get("model") or device.model_name
    device.serial_number = info.get("serial") or device.serial_number
    device.firmware = info.get("firmware") or device.firmware
    device.mac_address = info.get("mac") or device.mac_address
    device.last_seen_at = now()
    device.last_error = ""
    device.save(
        update_fields=[
            "model_name",
            "serial_number",
            "firmware",
            "mac_address",
            "last_seen_at",
            "last_error",
            "updated_at",
        ]
    )
    return {"ok": True, "info": info}


# ---------------------------------------------------------------------------
# Reception des evenements pousses par le lecteur
# ---------------------------------------------------------------------------


@csrf_exempt
def device_webhook(request, token):
    """
    Endpoint appele par le lecteur a chaque scan.

    Non authentifie au sens Django : c'est le ``webhook_token`` de l'URL qui
    identifie le lecteur, le materiel ne sachant pas gerer de session.
    """
    if request.method not in ("POST", "PUT"):
        return JsonResponse({"error": "Methode non autorisee."}, status=405)

    try:
        device = AccessDevice.objects.select_related("gym").get(
            webhook_token=token,
            is_active=True,
        )
    except (AccessDevice.DoesNotExist, ValueError):
        raise Http404

    parsed = hikvision.parse_event_payload(
        request.body,
        request.META.get("CONTENT_TYPE", ""),
    )
    credential = parsed["credential"]

    # Trace integrale : indispensable pour identifier ce que le materiel
    # transmet reellement lors des premiers essais sur site.
    logger.info(
        "Evenement lecteur '%s' | content-type=%s | identifiant=%r | mode=%r | brut=%s",
        device.name,
        request.META.get("CONTENT_TYPE", ""),
        credential,
        parsed["verify_mode"],
        parsed["raw"],
    )

    device.last_seen_at = now()
    device.last_error = ""
    device.save(update_fields=["last_seen_at", "last_error", "updated_at"])

    if not credential:
        # Evenements de service (etat porte, sabotage...) : rien a journaliser.
        return JsonResponse({"access": False, "reason": EMPTY_CREDENTIAL_REASON})

    member, nature = _resolve_member(device.gym, credential)
    if member is None:
        return JsonResponse({"access": False, "reason": UNKNOWN_CREDENTIAL_REASON})

    # Seul un visage autorise un second passage le meme jour : un badge ou un
    # QR code se pretent, et le lecteur ne saurait pas dire que la personne
    # devant lui n'est pas la bonne.
    par_le_visage = nature == "lecteur" and hikvision.est_un_visage(parsed["event"])

    access_granted, reason, log = _record_access(
        gym=device.gym,
        member=member,
        user=None,
        method=_libelle_methode(device, nature, par_le_visage),
        # Un visage n'a pas de QR code : verifier sa peremption refuserait
        # tous les passages faits en reconnaissance faciale.
        require_valid_qr=(nature == "qr"),
        device=device,
        allow_return=par_le_visage,
    )

    # Le lecteur a lu le QR, l'application a tranche : on lui rend la main sur
    # le relais uniquement si l'acces est accorde.
    door_status = door.summarize(
        door.open_doors(device.gym, device=device) if access_granted else []
    )

    return JsonResponse({
        "access": access_granted,
        "member": f"{member.first_name} {member.last_name}",
        "reason": reason,
        "log_id": log.id,
        "stats": _today_stats(device.gym),
        "door": door_status,
    })


def _resolve_member(gym, credential):
    """
    Retrouve le membre derriere l'identifiant remonte par le lecteur.

    Deux formes coexistent selon le mode de presentation :

    * un QR code, dont le contenu est l'UUID de la fiche membre ;
    * un ``employeeNo``, remonte apres une reconnaissance faciale ou un badge.
      C'est le numero que l'application a pose sur le lecteur.

    Renvoie aussi la nature reconnue : un visage n'a pas de QR code a valider,
    exiger sa fraicheur refuserait tous les passages.
    """
    import uuid as uuid_module

    brut = (credential or "").strip()
    if not brut:
        return None, ""

    try:
        qr_code = uuid_module.UUID(brut)
    except (ValueError, AttributeError):
        pass
    else:
        return Member.objects.filter(gym=gym, qr_code=qr_code).first(), "qr"

    # Fiche posee par l'application : visage reconnu, badge ou empreinte.
    member_id = enrollment.member_id_depuis(brut)
    if member_id is None:
        return None, "inconnu"

    return Member.objects.filter(gym=gym, id=member_id).first(), "lecteur"


def _request_payload(request):
    content_type = request.META.get("CONTENT_TYPE", "")
    if "application/json" in content_type:
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}
    return request.POST.dict()


def _first_error(exc):
    message_dict = getattr(exc, "message_dict", None)
    if message_dict:
        field, messages = next(iter(message_dict.items()))
        return f"{field} : {messages[0]}"
    messages = getattr(exc, "messages", None)
    if messages:
        return messages[0]
    return str(exc)


@login_required
@module_required("ACCESS")
@role_required(ACCESS_DEVICE_ROLES)
@require_POST
def device_announce(request, device_id):
    """
    Apprend au lecteur ou pousser ses evenements.

    A ne pas confondre avec la detection reseau, qui cherche les lecteurs
    presents. Ici le lecteur est deja connu : on lui donne l'adresse a
    laquelle joindre l'application.

    Sans cette declaration, un visage reconnu ouvre la porte mais n'apparait
    ni au journal d'acces, ni dans la frequentation. A relancer a chaque
    changement d'adresse du serveur.
    """
    device = get_object_or_404(AccessDevice, id=device_id, gym=request.gym)
    port = request.get_port() or "8000"

    try:
        url = enrollment.declarer_application(device, port)
    except enrollment.EnrollmentError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    log_sensitive_action(
        request,
        "access.device_announced",
        "AccessDevice",
        device.name,
        metadata={"url": url},
        gym=request.gym,
    )

    return JsonResponse({
        "ok": True,
        "url": url,
        "message": (
            f"{device.name} sait maintenant joindre l'application. "
            "Les passages remonteront au journal d'acces."
        ),
    })
