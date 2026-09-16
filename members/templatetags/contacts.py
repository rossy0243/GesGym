"""
Joindre un membre en un clic : telephone, WhatsApp, courriel.

Une alerte qui ne mene a aucun geste ne fait qu'informer. Ces liens ouvrent le
telephone ou la messagerie de la salle, le message deja ecrit : c'est la
relance que l'accueil passe de toute facon a la main.

Rien n'est envoye par le serveur. L'equipe relit et envoie : une relance
automatique partirait aussi aux membres qu'on vient d'avoir au telephone.
"""

from urllib.parse import quote

from django import template

register = template.Library()

# Les numeros sont saisis tantot avec l'indicatif, tantot en local. WhatsApp,
# lui, n'accepte que la forme internationale.
INDICATIF_PAR_DEFAUT = "243"


def numero_international(telephone):
    """Le numero en chiffres, indicatif compris, ou une chaine vide."""
    chiffres = "".join(caractere for caractere in str(telephone or "") if caractere.isdigit())
    if not chiffres:
        return ""

    if str(telephone or "").strip().startswith("+"):
        return chiffres
    if chiffres.startswith(INDICATIF_PAR_DEFAUT):
        return chiffres
    # Forme locale : 0820000001 devient 243820000001.
    return INDICATIF_PAR_DEFAUT + chiffres.lstrip("0")


def message_relance(member, gym=None):
    """Ce que l'equipe dirait au telephone, ecrit une fois pour toutes."""
    prenom = (member.first_name or "").strip() or "Bonjour"
    salle = getattr(gym, "name", "") or getattr(getattr(member, "gym", None), "name", "")
    fin = getattr(member, "expiration_date", None)

    phrase = f"Bonjour {prenom}, "
    if fin:
        phrase += f"votre abonnement se termine le {fin:%d/%m/%Y}. "
    else:
        phrase += "votre abonnement arrive a echeance. "
    phrase += "Passez a l'accueil pour le renouveler et garder votre acces"
    return f"{phrase} a {salle}." if salle else f"{phrase}."


@register.simple_tag
def lien_appel(member):
    """Lien qui compose le numero depuis un telephone."""
    numero = numero_international(getattr(member, "phone", ""))
    return f"tel:+{numero}" if numero else ""


@register.simple_tag
def lien_whatsapp(member, gym=None):
    """Conversation WhatsApp ouverte, avec le message de relance pre-ecrit."""
    numero = numero_international(getattr(member, "phone", ""))
    if not numero:
        return ""
    return f"https://wa.me/{numero}?text={quote(message_relance(member, gym))}"


@register.simple_tag
def lien_courriel(member, gym=None):
    """Courriel pre-rempli, vide si le membre n'a pas donne d'adresse."""
    adresse = (getattr(member, "email", "") or "").strip()
    if not adresse:
        return ""
    sujet = quote("Votre abonnement arrive a echeance")
    return f"mailto:{adresse}?subject={sujet}&body={quote(message_relance(member, gym))}"
