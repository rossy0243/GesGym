"""
Commande d'ouverture physique de la porte apres une validation d'acces.

Le principe : la decision d'acces appartient a l'application (abonnement,
statut du membre, validite du QR code, double passage). Le lecteur n'est plus
qu'un actionneur. Quand la verification passe, on lui envoie l'ordre d'ouvrir.

Regle importante : une panne materielle ne doit jamais invalider une decision
d'acces deja prise et journalisee. Les erreurs sont donc capturees, tracees et
remontees a l'interface, jamais propagees.
"""

import logging

from django.utils.timezone import now

from . import hikvision
from .models import AccessDevice

logger = logging.getLogger("access")

# Court volontairement : le portier attend devant la porte, mieux vaut un echec
# rapide et lisible qu'une page qui se fige.
OPEN_TIMEOUT = 5


def open_doors(gym, device=None):
    """
    Ouvre le ou les lecteurs concernes et renvoie le detail de chaque tentative.

    ``device`` cible un lecteur precis (cas d'un scan pousse par ce lecteur).
    Sans lui, tous les lecteurs actifs de la salle configures pour s'ouvrir
    automatiquement sont declenches.

    Renvoie une liste de dictionnaires : name, ok, error.
    """
    if device is not None:
        devices = [device] if device.is_active and device.open_on_granted else []
    else:
        devices = list(
            AccessDevice.objects.filter(
                gym=gym,
                is_active=True,
                open_on_granted=True,
            )
        )

    results = []

    for target in devices:
        client = hikvision.HikvisionClient.from_device(target, timeout=OPEN_TIMEOUT)

        try:
            client.open_door(target.door_number)
        except hikvision.HikvisionError as exc:
            message = str(exc)[:255]
            logger.warning(
                "Ouverture refusee par le lecteur '%s' (%s) : %s",
                target.name,
                target.host,
                message,
            )
            AccessDevice.objects.filter(pk=target.pk).update(last_error=message)
            results.append({"name": target.name, "ok": False, "error": message})
            continue

        logger.info("Porte ouverte par le lecteur '%s' (%s)", target.name, target.host)
        AccessDevice.objects.filter(pk=target.pk).update(
            last_seen_at=now(),
            last_error="",
        )
        results.append({"name": target.name, "ok": True, "error": ""})

    return results


def summarize(results):
    """Resume destine a l'interface : porte ouverte, en panne, ou aucun lecteur."""
    if not results:
        return {"attempted": False, "opened": False, "message": ""}

    opened = [item for item in results if item["ok"]]
    failed = [item for item in results if not item["ok"]]

    if opened and not failed:
        return {
            "attempted": True,
            "opened": True,
            "message": "Porte ouverte.",
        }

    if opened and failed:
        return {
            "attempted": True,
            "opened": True,
            "message": "Porte ouverte, mais {} lecteur(s) n'ont pas repondu.".format(
                len(failed)
            ),
        }

    return {
        "attempted": True,
        "opened": False,
        "message": "Acces autorise mais la porte n'a pas repondu : {}".format(
            failed[0]["error"]
        ),
    }
