"""
Taux de reference d'une salle pour exprimer un stock en dollars.

Un produit peut etre price en francs. Les indicateurs de stock, eux, sont
libelles en dollars : sans taux, la valeur du stock melangerait deux unites et
n'aurait aucun sens. On prend le taux le plus proche de la realite du terrain.
"""

from decimal import Decimal


def gym_exchange_rate(gym):
    """
    Taux USD-CDF a retenir pour la salle, du plus fiable au plus ancien.

    1. La session de caisse ouverte : c'est le taux applique aux ventes du jour.
    2. Le dernier taux saisi par la salle.
    3. Rien : l'appelant decide quoi faire d'un stock non convertible.
    """
    from pos.models import CashRegister, ExchangeRate

    ouverte = (
        CashRegister.objects.filter(gym=gym, is_closed=False)
        .exclude(exchange_rate=None)
        .order_by("-opened_at")
        .values_list("exchange_rate", flat=True)
        .first()
    )
    if ouverte and ouverte > 0:
        return Decimal(ouverte)

    dernier = (
        ExchangeRate.objects.filter(gym=gym)
        .order_by("-date", "-created_at")
        .values_list("rate", flat=True)
        .first()
    )
    if dernier and dernier > 0:
        return Decimal(dernier)

    return None
