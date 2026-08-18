from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from .models import Product, StockMovement
from .pricing import gym_exchange_rate


def products_queryset(gym):
    return Product.objects.filter(gym=gym)


def movements_queryset(gym):
    return StockMovement.objects.filter(gym=gym).select_related("product")


def stock_value(product, exchange_rate=None):
    """
    Valeur du stock d'un produit, toujours en dollars.

    Un produit price en francs n'est comptabilise que si la salle dispose d'un
    taux : sans lui, l'additionner aux produits en dollars donnerait un total
    faux plutot qu'un total manquant.
    """
    if product.currency == Product.CURRENCY_USD:
        return (product.price or Decimal("0")) * product.quantity

    if not exchange_rate:
        return Decimal("0")

    return product.price_usd(exchange_rate) * product.quantity


def build_product_kpis(gym, period_data=None):
    today = timezone.localdate()
    period_data = period_data or {
        "start_date": today.replace(day=1),
        "end_date": today,
    }

    products = products_queryset(gym)
    active_products_qs = products.filter(is_active=True)
    stock_ok_products = active_products_qs.filter(quantity__gt=5)
    low_stock_products = active_products_qs.filter(quantity__lte=5, quantity__gt=0)
    out_of_stock_products = active_products_qs.filter(quantity=0)
    movements = movements_queryset(gym)
    period_movements = movements.filter(
        created_at__date__range=(period_data["start_date"], period_data["end_date"])
    )
    taux = gym_exchange_rate(gym)
    top_value_products = sorted(
        [product for product in active_products_qs if product.quantity > 0],
        key=lambda product: stock_value(product, taux),
        reverse=True,
    )[:5]
    for product in top_value_products:
        product.stock_value = stock_value(product, taux)

    total_value = sum(
        (stock_value(product, taux) for product in active_products_qs), Decimal("0")
    )
    stock_value_chart_values = [float(product.stock_value) for product in top_value_products]

    # Un stock en francs sans taux disponible est invisible dans la valeur
    # totale : il faut le dire plutot que de laisser croire a un stock vide.
    produits_non_convertibles = (
        0
        if taux
        else active_products_qs.filter(currency=Product.CURRENCY_CDF, quantity__gt=0).count()
    )

    return {
        "total_products": active_products_qs.count(),
        "all_products_count": products.count(),
        "inactive_products": products.filter(is_active=False).count(),
        "stock_value_total": total_value,
        "stock_ok_count": stock_ok_products.count(),
        "low_stock_count": low_stock_products.count(),
        "out_of_stock_count": out_of_stock_products.count(),
        "low_stock_products": low_stock_products,
        "out_of_stock_products": out_of_stock_products,
        "stock_movements_period": period_movements.count(),
        "stock_in_period": period_movements.filter(movement_type="in").aggregate(total=Sum("quantity"))["total"] or 0,
        "stock_out_period": period_movements.filter(movement_type="out").aggregate(total=Sum("quantity"))["total"] or 0,
        "top_value_products": top_value_products,
        "recent_stock_movements": movements.order_by("-created_at")[:10],
        "stock_status_chart_labels": ["Stock OK", "Stock bas", "Rupture"],
        "stock_status_chart_values": [
            stock_ok_products.count(),
            low_stock_products.count(),
            out_of_stock_products.count(),
        ],
        "stock_value_chart_labels": [product.name for product in top_value_products],
        "stock_value_chart_values": stock_value_chart_values,
        "stock_exchange_rate": taux,
        "products_without_rate": produits_non_convertibles,
    }
