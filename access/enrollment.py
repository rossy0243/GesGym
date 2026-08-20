"""
Inscription des membres sur les lecteurs a reconnaissance faciale.

Le lecteur tient sa propre base : une fiche par membre, avec ses dates de
validite et son visage. Il decide donc seul, instantanement, et continue de
fonctionner serveur eteint. L'application reste la source de verite et lui
pousse ce qu'elle sait.

Trois contraintes viennent du materiel, verifiees sur un DS-K1T342MFWX-E1 :

* ``employeeNo`` doit etre **numerique** : un identifiant texte est refuse.
  On utilise donc l'identifiant de la fiche membre, pas son code affiche.
* la bibliotheque de visages plafonne a 1500 personnes ;
* le lecteur refuse une photo ou il ne distingue aucun visage.
"""

import io
import logging

from django.utils import timezone

from . import hikvision
from .models import AccessDevice

logger = logging.getLogger(__name__)


# Le lecteur raisonne sur son horloge locale, sans fuseau.
FORMAT_LECTEUR = "%Y-%m-%dT%H:%M:%S"

# Bornes acceptees par le materiel pour une periode de validite.
DEBUT_PAR_DEFAUT = "2000-01-01T00:00:00"
FIN_PAR_DEFAUT = "2037-12-31T23:59:59"

# Une photo trop lourde est refusee, et une photo minuscule ne se modelise
# pas. Ces bornes conviennent au capteur du terminal.
LARGEUR_MAX = 640
QUALITE_JPEG = 88


class EnrollmentError(Exception):
    """Echec d'inscription, avec un message destine a l'utilisateur."""


# Decalage des identifiants applicatifs. Le materiel impose un employeeNo
# numerique, et les fiches saisies a la main sur le terminal occupent les
# petits nombres : badges du personnel, essais, visiteurs. Sans ce decalage,
# la premiere inscription d'un membre ecraserait la fiche numero 1 ou 2 avec
# son nom, ses dates et son visage.
PLAGE_APPLICATION = 1_000_000


def employee_no(member):
    """
    Identifiant du membre sur le lecteur.

    Numerique, impose par le materiel, et decale pour ne jamais entrer en
    collision avec une fiche creee directement sur le terminal.
    """
    return str(PLAGE_APPLICATION + member.id)


def member_id_depuis(employee_no_lu):
    """
    Retrouve le membre derriere un employeeNo remonte par le lecteur.

    Renvoie None pour une fiche qui n'a pas ete posee par l'application :
    un badge de personnel ne doit pas etre pris pour un membre.
    """
    try:
        valeur = int(str(employee_no_lu).strip())
    except (TypeError, ValueError):
        return None

    if valeur <= PLAGE_APPLICATION:
        return None
    return valeur - PLAGE_APPLICATION


def _periode_validite(member):
    """
    Fenetre pendant laquelle le lecteur laissera entrer ce membre.

    Elle suit l'abonnement en cours. Sans abonnement, la fiche est creee mais
    fermee : le membre existe sur le lecteur, il n'entre pas.
    """
    subscription = member.active_subscription
    if subscription is None:
        return None, None

    debut = subscription.start_date.strftime("%Y-%m-%dT00:00:00")
    fin = subscription.end_date.strftime("%Y-%m-%dT23:59:59")
    return debut, fin


def preparer_photo(image_bytes):
    """
    Met une image au format attendu par le lecteur.

    Convertit en JPEG, retire la transparence et borne la largeur : une image
    trop lourde est rejetee par le materiel.
    """
    from PIL import Image, UnidentifiedImageError

    try:
        image = Image.open(io.BytesIO(image_bytes))
    except UnidentifiedImageError as exc:
        raise EnrollmentError("Ce fichier n'est pas une image exploitable.") from exc

    image = image.convert("RGB")
    if image.width > LARGEUR_MAX:
        ratio = LARGEUR_MAX / image.width
        image = image.resize(
            (LARGEUR_MAX, max(1, round(image.height * ratio))), Image.LANCZOS
        )

    tampon = io.BytesIO()
    image.save(tampon, format="JPEG", quality=QUALITE_JPEG, optimize=True)
    return tampon.getvalue()


def capturer_visage(device):
    """
    Photographie la personne presente devant le lecteur.

    L'image vient du capteur qui servira ensuite a la reconnaissance : c'est
    ce qui rend l'enrolement fiable, la ou une photo de telephone echoue
    souvent au cadrage ou a l'eclairage.
    """
    client = hikvision.HikvisionClient.from_device(device, timeout=25)
    try:
        return client.capture_face()
    except hikvision.HikvisionUnreachable as exc:
        raise EnrollmentError(
            f"Lecteur injoignable ({device.host}). Verifiez qu'il est allume "
            "et sur le meme reseau."
        ) from exc
    except hikvision.HikvisionAuthError as exc:
        raise EnrollmentError(
            "Le lecteur refuse les identifiants enregistres."
        ) from exc
    except hikvision.HikvisionError as exc:
        raise EnrollmentError(
            "Aucun visage capture. Demandez a la personne de se placer face au "
            f"lecteur, a hauteur d'ecran, puis recommencez. ({exc})"
        ) from exc


def inscrire_membre(device, member, image_bytes=None):
    """
    Cree ou met a jour la fiche du membre sur le lecteur, avec son visage.

    ``image_bytes`` est facultatif : sans lui, seules la fiche et ses dates
    sont mises a jour, le visage deja enregistre est conserve.
    """
    client = hikvision.HikvisionClient.from_device(device, timeout=25)
    debut, fin = _periode_validite(member)
    sans_abonnement = debut is None

    nom = f"{member.first_name} {member.last_name}".strip() or f"Membre {member.id}"
    numero = employee_no(member)

    try:
        client.upsert_user(
            numero,
            nom,
            debut or DEBUT_PAR_DEFAUT,
            # Sans abonnement, la fiche existe mais n'ouvre rien : on la ferme
            # a hier plutot que de la supprimer, pour garder le visage.
            fin or timezone.localdate().strftime("%Y-%m-%dT00:00:00"),
            door_number=device.door_number,
        )
    except hikvision.HikvisionUnreachable as exc:
        raise EnrollmentError(f"Lecteur injoignable ({device.host}).") from exc
    except hikvision.HikvisionError as exc:
        raise EnrollmentError(f"Le lecteur a refuse la fiche : {exc}") from exc

    if image_bytes:
        try:
            client.set_face(numero, preparer_photo(image_bytes))
        except hikvision.HikvisionError as exc:
            # La fiche est posee ; seul le visage manque. On le dit sans
            # laisser croire que rien n'a marche.
            raise EnrollmentError(
                "La fiche est enregistree mais le visage a ete refuse : le "
                f"lecteur n'y distingue pas de visage exploitable. ({exc})"
            ) from exc

    device.last_seen_at = timezone.now()
    device.last_error = ""
    device.save(update_fields=["last_seen_at", "last_error", "updated_at"])

    return {"employee_no": numero, "sans_abonnement": sans_abonnement}


def retirer_membre(device, member):
    """Supprime la fiche et le visage du membre sur le lecteur."""
    client = hikvision.HikvisionClient.from_device(device, timeout=25)
    try:
        client.delete_user(employee_no(member))
    except hikvision.HikvisionUnreachable as exc:
        raise EnrollmentError(f"Lecteur injoignable ({device.host}).") from exc
    except hikvision.HikvisionError as exc:
        raise EnrollmentError(f"Le lecteur a refuse le retrait : {exc}") from exc


def lecteurs_de(gym):
    """Lecteurs actifs de la salle, ceux qu'il faut tenir a jour."""
    return list(AccessDevice.objects.filter(gym=gym, is_active=True))


def propager(member, image_bytes=None):
    """
    Reporte l'etat d'un membre sur tous les lecteurs de sa salle.

    Ne leve jamais : une salle sans lecteur, ou un lecteur debranche, ne doit
    pas empecher d'encaisser un abonnement. Renvoie le detail par lecteur.
    """
    resultats = []
    for device in lecteurs_de(member.gym):
        try:
            inscrire_membre(device, member, image_bytes)
            resultats.append({"device": device.name, "ok": True, "error": ""})
        except EnrollmentError as exc:
            logger.warning(
                "Synchronisation du membre %s vers %s impossible : %s",
                member.id, device.name, exc,
            )
            resultats.append({"device": device.name, "ok": False, "error": str(exc)})
    return resultats


# ---------------------------------------------------------------------------
# Declaration de l'application au lecteur
# ---------------------------------------------------------------------------
#
# Le lecteur decide seul a la porte, mais il doit prevenir l'application de
# chaque passage, sinon rien n'apparait au journal d'acces. Pour cela il lui
# faut une adresse joignable **depuis lui** : celle du serveur sur le reseau
# local, jamais 127.0.0.1.


def adresse_serveur_vue_du_lecteur(device):
    """
    Adresse IP par laquelle le lecteur peut joindre ce serveur.

    On la deduit de la route reelle vers le lecteur plutot que de la deviner :
    une machine a souvent plusieurs interfaces (Wi-Fi, Ethernet, VPN) et seule
    celle qui porte la route vers le lecteur convient.
    """
    import socket

    sonde = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Aucun paquet n'est emis : connect() sur UDP choisit juste l'interface.
        sonde.connect((device.host, device.port or 80))
        return sonde.getsockname()[0]
    except OSError as exc:
        raise EnrollmentError(
            f"Impossible de determiner par quelle adresse le lecteur "
            f"({device.host}) verrait ce serveur : {exc}"
        ) from exc
    finally:
        sonde.close()


def url_de_notification(device, port_serveur, adresse=None):
    """URL complete du webhook de ce lecteur, vue depuis le lecteur."""
    from django.urls import reverse

    hote = adresse or adresse_serveur_vue_du_lecteur(device)
    chemin = reverse("access:device_webhook", args=[device.webhook_token])
    return f"http://{hote}:{port_serveur}{chemin}"


def declarer_application(device, port_serveur, adresse=None):
    """
    Apprend au lecteur ou pousser ses evenements.

    Sans cette declaration, un visage reconnu ouvre bien la porte mais
    n'apparait nulle part : ni journal d'acces, ni frequentation, ni
    "dernier acces" sur la fiche du membre.
    """
    url = url_de_notification(device, port_serveur, adresse)
    client = hikvision.HikvisionClient.from_device(device, timeout=25)

    try:
        client.set_event_notification(url)
    except hikvision.HikvisionUnreachable as exc:
        raise EnrollmentError(f"Lecteur injoignable ({device.host}).") from exc
    except hikvision.HikvisionError as exc:
        raise EnrollmentError(f"Le lecteur a refuse la declaration : {exc}") from exc

    device.last_seen_at = timezone.now()
    device.last_error = ""
    device.save(update_fields=["last_seen_at", "last_error", "updated_at"])

    return url


# ---------------------------------------------------------------------------
# Messages affiches sur l'ecran du lecteur
# ---------------------------------------------------------------------------
#
# Le terminal affiche une phrase courte selon l'issue de la lecture. Elle est
# reglable, contrairement a la voix : le materiel annonce des sons
# personnalisables mais n'expose aucun point d'entree pour les televerser.
#
# L'ecran du lecteur affiche du texte simple, sans couleur. Le code couleur de
# l'ecran de reglage sert a l'operateur, pas au membre.

MESSAGES_LECTEUR = (
    (
        "authenticationSuccess",
        "Acces accorde",
        "Ce que lit le membre reconnu, dont l'abonnement est valide.",
        "succes",
    ),
    (
        "authenticationFailed",
        "Acces refuse",
        "Membre reconnu, mais abonnement expire, suspendu ou hors plage horaire.",
        "refus",
    ),
    (
        "stranger",
        "Visage inconnu",
        "Personne non enrolee sur ce lecteur : visiteur, prospect, passant.",
        "inconnu",
    ),
)

LONGUEUR_MESSAGE_MAX = 16


def lire_messages(device):
    """Messages actuellement portes par le lecteur."""
    client = hikvision.HikvisionClient.from_device(device, timeout=20)
    try:
        return client.get_custom_prompt()
    except hikvision.HikvisionUnreachable as exc:
        raise EnrollmentError(f"Lecteur injoignable ({device.host}).") from exc
    except hikvision.HikvisionError as exc:
        raise EnrollmentError(f"Le lecteur n'a pas repondu : {exc}") from exc


def ecrire_messages(device, enabled, messages):
    """
    Ecrit les messages sur le lecteur.

    Un texte vide n'efface pas : le materiel exige au moins un caractere. Pour
    revenir aux messages d'origine, il faut decocher l'affichage.
    """
    for cle, libelle, _aide, _couleur in MESSAGES_LECTEUR:
        contenu = (messages.get(cle) or "").strip()
        if len(contenu) > LONGUEUR_MESSAGE_MAX:
            raise EnrollmentError(
                f"« {libelle} » depasse {LONGUEUR_MESSAGE_MAX} caracteres "
                f"({len(contenu)}). L'ecran du lecteur ne peut pas l'afficher."
            )

    client = hikvision.HikvisionClient.from_device(device, timeout=20)
    try:
        client.set_custom_prompt(enabled, messages)
    except hikvision.HikvisionUnreachable as exc:
        raise EnrollmentError(f"Lecteur injoignable ({device.host}).") from exc
    except hikvision.HikvisionError as exc:
        raise EnrollmentError(f"Le lecteur a refuse les messages : {exc}") from exc

    device.last_seen_at = timezone.now()
    device.last_error = ""
    device.save(update_fields=["last_seen_at", "last_error", "updated_at"])
