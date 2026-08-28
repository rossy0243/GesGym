"""
Ce qui merite d'apparaitre dans le journal d'acces du serveur.

Render interroge ``/health/`` toutes les quatre secondes : vingt mille lignes
par jour qui ne disent rien, et qui noient celles qui disent quelque chose. La
sonde continue de fonctionner ; elle cesse seulement de s'ecrire.

La decision vit ici plutot que dans la configuration du serveur : gunicorn ne
s'importe pas sous Windows, et une regle qu'on ne peut pas tester finit par
deriver.
"""

CHEMINS_MUETS = frozenset({"/health/", "/health/details/"})


def doit_journaliser(chemin):
    """Faut-il ecrire une ligne pour cette requete ?"""
    return (chemin or "") not in CHEMINS_MUETS
