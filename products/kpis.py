from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from .models import Product, StockMovement


def products_queryset(gym):
    return Product.objects.filter(gym=gym)


def movements_queryset(gym):
    return StockMovement.objects.filter(gym=gym).select_related("product")


def stock_value(product):
    return (product.price or Decimal("0")) * product.quantity


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
    top_value_products = sorted(
        [product for product in active_products_qs if product.quantity > 0],
        key=stock_value,
        reverse=True,
    )[:5]
    for product in top_value_products:
        product.stock_value = stock_value(product)

    total_value = sum((stock_value(product) for product in active_products_qs), Decimal("0"))
    stock_value_chart_values = [float(stock_value(product)) for product in top_value_products]

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
    }
