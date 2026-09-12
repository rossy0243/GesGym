"""
Mise en forme des montants.

« 1599739 CDF » ne se lit pas : l'oeil doit compter les chiffres pour savoir
s'il s'agit d'un million ou de cent mille. En francs congolais, ou les sommes
courantes depassent le million, c'est la difference entre un chiffre qu'on
verifie et un chiffre qu'on croit.

``django.contrib.humanize`` n'est pas installe, et l'activer changerait la
mise en forme de tous les nombres du projet - identifiants et annees compris.
Ce filtre ne touche que ce a quoi on l'applique.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template

register = template.Library()

# Espace insecable : un montant ne doit jamais se couper en fin de ligne.
SEPARATEUR = " "


@register.filter
def montant(valeur, decimales=0):
    """
    Groupe les milliers : ``1599739`` devient ``1 599 739``.

    Une valeur illisible est rendue telle quelle plutot que masquee : mieux
    vaut un affichage brut qu'un montant disparu.
    """
    try:
        nombre = Decimal(str(valeur if valeur not in (None, "") else 0))
    except (InvalidOperation, TypeError, ValueError):
        return valeur

    decimales = max(int(decimales or 0), 0)
    pas = Decimal(1).scaleb(-decimales)
    nombre = nombre.quantize(pas, rounding=ROUND_HALF_UP)

    signe = "-" if nombre < 0 else ""
    entier, _, fraction = str(abs(nombre)).partition(".")

    groupes = []
    while len(entier) > 3:
        groupes.insert(0, entier[-3:])
        entier = entier[:-3]
    groupes.insert(0, entier)

    rendu = SEPARATEUR.join(groupes)
    if decimales:
        rendu = f"{rendu},{fraction.ljust(decimales, '0')}"
    return f"{signe}{rendu}"


@register.filter
def montant_signe(valeur, decimales=0):
    """
    Comme ``montant``, mais un encaissement porte son ``+``.

    Dans une liste qui melange entrees et sorties, le signe est ce qui
    distingue les deux d'un coup d'oeil.
    """
    rendu = montant(valeur, decimales)
    if isinstance(rendu, str) and rendu and not rendu.startswith("-"):
        try:
            if Decimal(str(valeur or 0)) > 0:
                return f"+{rendu}"
        except (InvalidOperation, TypeError, ValueError):
            return rendu
    return rendu
