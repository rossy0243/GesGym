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

# Plage du personnel, au-dessus de celle des membres. Les membres occupent les
# numeros de PLAGE_APPLICATION (exclu) a PLAGE_PERSONNEL (inclus) : un million
# de fiches, bien au-dela des 1500 visages que tient le lecteur.
#
# Borner la plage des membres est indispensable : sans borne, un employe serait
# pris pour un membre inconnu, et la purge de la synchronisation retirerait son
# visage du lecteur comme celui d'un membre disparu.
PLAGE_PERSONNEL = 2_000_000


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

    if valeur <= PLAGE_APPLICATION or valeur > PLAGE_PERSONNEL:
        return None
    return valeur - PLAGE_APPLICATION


def numero_personnel(employee):
    """
    Identifiant d'un employe sur le lecteur.

    Dans sa propre plage : un employe n'est jamais confondu avec un membre, ni
    avec une fiche creee a la main sur le terminal.
    """
    return str(PLAGE_PERSONNEL + employee.id)


def employee_id_depuis(employee_no_lu):
    """Retrouve l'employe derriere un employeeNo, ou None hors de sa plage."""
    try:
        valeur = int(str(employee_no_lu).strip())
    except (TypeError, ValueError):
        return None

    if valeur <= PLAGE_PERSONNEL:
        return None
    return valeur - PLAGE_PERSONNEL


def _periode_validite(member):
    """
    Fenetre pendant laquelle le lecteur laissera entrer ce membre.

    Elle suit l'abonnement en cours. Sans abonnement, la fiche est creee mais
    fermee : le membre existe sur le lecteur, il n'entre pas.
    """
    # Une fiche membre desactivee - un employe passe au personnel, par exemple -
    # n'ouvre plus rien, meme avec un abonnement encore en cours.
    if not member.is_active:
        return None, None

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


# Le lecteur explique son refus dans un code technique. Le traduire evite
# d'envoyer l'utilisateur sur une fausse piste : longtemps, tout refus etait
# annonce comme "aucun visage exploitable", y compris quand le visage etait
# parfaitement lisible mais deja enrole ailleurs.
REFUS_VISAGE = (
    (
        "alreadyExistThisFace",
        "Ce visage est deja enregistre sous une autre fiche du lecteur. Le "
        "terminal refuse d'attacher un meme visage a deux identites. "
        "Verifiez que cette personne n'est pas deja enrolee, sous un autre "
        "membre ou sous une fiche creee a la main sur le terminal.",
    ),
    (
        "lowScoreOfFaceQuality",
        "Le visage est lisible mais de trop mauvaise qualite. Eclairez le "
        "visage de face, sans contre-jour, et recommencez.",
    ),
    (
        "faceQuality",
        "Le visage est lisible mais de trop mauvaise qualite. Eclairez le "
        "visage de face, sans contre-jour, et recommencez.",
    ),
    (
        "noFace",
        "Le lecteur ne distingue aucun visage sur l'image. Demandez a la "
        "personne de se placer face au lecteur, a hauteur d'ecran.",
    ),
    (
        "analysisPic",
        "Le lecteur ne distingue aucun visage sur l'image. Demandez a la "
        "personne de se placer face au lecteur, a hauteur d'ecran.",
    ),
)


def _cause_du_refus(exc):
    """Traduit le refus du lecteur, ou rend None si le code est inconnu."""
    brut = str(exc)
    for code, explication in REFUS_VISAGE:
        if code.lower() in brut.lower():
            return explication
    return None


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
        _envoyer_visage(client, numero, image_bytes)

    _marquer_joignable(device)

    return {"employee_no": numero, "sans_abonnement": sans_abonnement}


def _envoyer_visage(client, numero, image_bytes):
    """Pose le visage sur une fiche deja creee."""
    try:
        client.set_face(numero, preparer_photo(image_bytes))
    except hikvision.HikvisionError as exc:
        # La fiche est posee ; seul le visage manque. On le dit sans
        # laisser croire que rien n'a marche.
        cause = _cause_du_refus(exc) or (
            f"le lecteur l'a refuse sans motif reconnu. ({exc})"
        )
        raise EnrollmentError(
            f"La fiche est enregistree mais le visage a ete refuse : {cause}"
        ) from exc


def _marquer_joignable(device):
    device.last_seen_at = timezone.now()
    device.last_error = ""
    device.save(update_fields=["last_seen_at", "last_error", "updated_at"])


def inscrire_employe(device, employee, image_bytes=None):
    """
    Cree ou met a jour la fiche d'un employe sur le lecteur.

    Un employe n'a pas d'abonnement : il entre a toute heure, tant que sa fiche
    RH est active. Sa fiche est donc ouverte sur toute la periode que le
    materiel accepte. Un employe desactive n'est jamais inscrit.
    """
    if not employee.is_active:
        raise EnrollmentError(
            f"{employee.name} est desactive dans le module RH : il ne peut pas "
            "etre inscrit sur le lecteur."
        )

    client = hikvision.HikvisionClient.from_device(device, timeout=25)
    numero = numero_personnel(employee)
    nom = (employee.name or "").strip() or f"Employe {employee.id}"

    try:
        client.upsert_user(
            numero,
            nom,
            DEBUT_PAR_DEFAUT,
            FIN_PAR_DEFAUT,
            door_number=device.door_number,
        )
    except hikvision.HikvisionUnreachable as exc:
        raise EnrollmentError(f"Lecteur injoignable ({device.host}).") from exc
    except hikvision.HikvisionError as exc:
        raise EnrollmentError(f"Le lecteur a refuse la fiche : {exc}") from exc

    if image_bytes:
        _envoyer_visage(client, numero, image_bytes)

    _marquer_joignable(device)

    return {"employee_no": numero}


def retirer_membre(device, member):
    """Supprime la fiche et le visage du membre sur le lecteur."""
    client = hikvision.HikvisionClient.from_device(device, timeout=25)
    try:
        client.delete_user(employee_no(member))
    except hikvision.HikvisionUnreachable as exc:
        raise EnrollmentError(f"Lecteur injoignable ({device.host}).") from exc
    except hikvision.HikvisionError as exc:
        raise EnrollmentError(f"Le lecteur a refuse le retrait : {exc}") from exc


def retirer_employe(device, employee):
    """Supprime la fiche et le visage d'un employe sur le lecteur."""
    retirer_fiche(device, numero_personnel(employee))


def retirer_fiche(device, numero):
    """
    Supprime une fiche du lecteur, visage compris, et verifie que c'est fait.

    Trois pieges, tous vus sur ce materiel :

    * le visage vit dans une bibliotheque a part. Supprimer la fiche sans lui
      laisse un visage orphelin, et le lecteur refuse ensuite de l'attacher
      ailleurs - "ce visage existe deja" - sans qu'aucune fiche ne l'explique ;
    * l'ancienne commande de suppression repond "ok" sans rien effacer sur
      certains firmwares : la fiche reapparait au rafraichissement ;
    * la commande recente travaille en tache de fond : il faut attendre la fin.

    On enleve donc le visage, puis la fiche, on verifie, et on reessaie par
    l'autre commande avant d'abandonner en le disant.
    """
    numero = str(numero)
    client = hikvision.HikvisionClient.from_device(device, timeout=25)

    def _tolerer(action, quoi):
        """Un refus n'est pas un echec : la fiche ou le visage peut deja manquer."""
        try:
            action()
        except hikvision.HikvisionUnreachable:
            raise
        except hikvision.HikvisionError as exc:
            logger.info("%s de %s sur %s refuse : %s", quoi, numero, device.name, exc)

    try:
        _tolerer(lambda: client.delete_face(numero), "Retrait du visage")
        _tolerer(lambda: client.delete_user(numero), "Retrait de la fiche")

        if not client.user_exists(numero):
            return

        # La fiche est toujours la : l'autre commande, puis on verifie encore.
        _tolerer(lambda: client.delete_user_detail(numero), "Retrait (seconde methode)")
        if not client.user_exists(numero):
            return
    except hikvision.HikvisionUnreachable as exc:
        raise EnrollmentError(f"Lecteur injoignable ({device.host}).") from exc
    except hikvision.HikvisionError as exc:
        raise EnrollmentError(f"Le lecteur a refuse le retrait : {exc}") from exc

    raise EnrollmentError(
        f"La fiche {numero} est toujours presente sur {device.name} apres "
        "suppression. Le lecteur l'a peut-etre verrouillee : supprimez-la "
        "depuis son ecran (Gestion des personnes), puis revenez ici."
    )


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


# Le lecteur retient deux destinations. La premiere sert au serveur du reseau
# local ; la seconde peut viser le serveur public, que le lecteur atteint tout
# seul en sortant vers internet. Cette sortie-la n'est jamais bloquee, la ou
# entrer dans le reseau de la salle exige un tunnel.
EMPLACEMENT_LOCAL = 1
EMPLACEMENT_PUBLIC = 2


def declarer_url(device, url, emplacement=EMPLACEMENT_LOCAL):
    """Ecrit une destination d'evenements dans un emplacement du lecteur."""
    client = hikvision.HikvisionClient.from_device(device, timeout=25)

    try:
        client.set_event_notification(url, host_index=emplacement)
    except hikvision.HikvisionUnreachable as exc:
        raise EnrollmentError(f"Lecteur injoignable ({device.host}).") from exc
    except hikvision.HikvisionError as exc:
        raise EnrollmentError(f"Le lecteur a refuse la declaration : {exc}") from exc

    device.last_seen_at = timezone.now()
    device.last_error = ""
    device.save(update_fields=["last_seen_at", "last_error", "updated_at"])

    return url


def declarer_application(device, port_serveur, adresse=None):
    """
    Apprend au lecteur ou pousser ses evenements.

    Sans cette declaration, un visage reconnu ouvre bien la porte mais
    n'apparait nulle part : ni journal d'acces, ni frequentation, ni
    "dernier acces" sur la fiche du membre.
    """
    return declarer_url(
        device,
        url_de_notification(device, port_serveur, adresse),
        emplacement=EMPLACEMENT_LOCAL,
    )


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
