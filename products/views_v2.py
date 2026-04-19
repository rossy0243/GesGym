from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Sum
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from smartclub.access_control import PRODUCT_ROLES
from smartclub.decorators import module_required, role_required

from .forms import ProductForm, StockMovementForm
from .kpis import build_product_kpis, products_queryset, stock_value, movements_queryset
from .models import Product, StockMovement


@login_required
@module_required("PRODUCTS")
@role_required(PRODUCT_ROLES)
def product_list(request):
    gym = request.gym
    products = products_queryset(gym).order_by("name")

    active_filter = request.GET.get("active")
    if active_filter == "active":
        products = products.filter(is_active=True)
    elif active_filter == "inactive":
        products = products.filter(is_active=False)

    low_stock = request.GET.get("low_stock")
    if low_stock:
        products = products.filter(quantity__lte=5, quantity__gt=0)

    out_of_stock = request.GET.get("out_of_stock")
    if out_of_stock:
        products = products.filter(quantity=0, is_active=True)

    context = {
        "gym": gym,
        "products": products,
        "active_filter": active_filter,
        "low_stock": low_stock,
        "out_of_stock": out_of_stock,
        **build_product_kpis(gym),
    }
    return render(request, "products/product_list.html", context)


@login_required
@module_required("PRODUCTS")
@role_required(PRODUCT_ROLES)
def product_detail(request, product_id):
    product = get_object_or_404(Product, id=product_id, gym=request.gym)
    product.stock_value = stock_value(product)
    movements = product.movements.filter(gym=request.gym).order_by("-created_at")[:20]
    total_in = product.movements.filter(gym=request.gym, movement_type="in").aggregate(Sum("quantity"))["quantity__sum"] or 0
    total_out = product.movements.filter(gym=request.gym, movement_type="out").aggregate(Sum("quantity"))["quantity__sum"] or 0

    context = {
        "gym": request.gym,
        "product": product,
        "movements": movements,
        "total_in": total_in,
        "total_out": total_out,
    }
    return render(request, "products/product_detail.html", context)


@login_required
@module_required("PRODUCTS")
@role_required(PRODUCT_ROLES)
def product_create(request):
    gym = request.gym

    if request.method == "POST":
        form = ProductForm(request.POST)
        if form.is_valid():
            product = form.save(commit=False)
            product.gym = gym
            product.save()

            if product.quantity > 0:
                StockMovement.objects.create(
                    gym=gym,
                    product=product,
                    quantity=product.quantity,
                    movement_type="in",
                    reason="Stock initial",
                )

            messages.success(request, f'Produit "{product.name}" cree avec succes.')
            return redirect("products:detail", product_id=product.id)
    else:
        form = ProductForm()

    return render(
        request,
        "products/product_form.html",
        {"gym": gym, "form": form, "title": "Ajouter un produit"},
    )


@login_required
@module_required("PRODUCTS")
@role_required(PRODUCT_ROLES)
def product_update(request, product_id):
    product = get_object_or_404(Product, id=product_id, gym=request.gym)
    previous_quantity = product.quantity

    if request.method == "POST":
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            with transaction.atomic():
                product = form.save()
                delta = product.quantity - previous_quantity
                if delta:
                    StockMovement.objects.create(
                        gym=request.gym,
                        product=product,
                        quantity=abs(delta),
                        movement_type="in" if delta > 0 else "out",
                        reason="Ajustement manuel",
                    )
            messages.success(request, f'Produit "{product.name}" modifie avec succes.')
            return redirect("products:detail", product_id=product.id)
    else:
        form = ProductForm(instance=product)

    return render(
        request,
        "products/product_form.html",
        {
            "gym": request.gym,
            "form": form,
            "product": product,
            "title": "Modifier le produit",
        },
    )


@login_required
@module_required("PRODUCTS")
@role_required(PRODUCT_ROLES)
def product_delete(request, product_id):
    product = get_object_or_404(Product, id=product_id, gym=request.gym)

    if request.method == "POST":
        product.is_active = False
        product.save(update_fields=["is_active"])
        messages.success(request, f'Produit "{product.name}" desactive avec succes.')
        return redirect("products:list")

    return render(
        request,
        "products/product_confirm_delete.html",
        {"gym": request.gym, "product": product},
    )


@login_required
@module_required("PRODUCTS")
@role_required(PRODUCT_ROLES)
def stock_movement_create(request, product_id):
    product = get_object_or_404(Product, id=product_id, gym=request.gym)

    if request.method == "POST":
        form = StockMovementForm(request.POST)
        if form.is_valid():
            quantity = form.cleaned_data["quantity"]
            movement_type = form.cleaned_data["movement_type"]
            reason = form.cleaned_data["reason"]

            try:
                product.update_stock(quantity, movement_type, reason)
                messages.success(request, f"Mouvement enregistre: {product.name} - {quantity}.")
                return redirect("products:detail", product_id=product.id)
            except ValueError as exc:
                messages.error(request, str(exc))
    else:
        form = StockMovementForm()

    context = {
        "gym": request.gym,
        "product": product,
        "form": form,
        "title": f"Ajouter un mouvement - {product.name}",
    }
    return render(request, "products/stock_movement_form.html", context)


@login_required
@module_required("PRODUCTS")
@role_required(PRODUCT_ROLES)
def stock_movement_list(request):
    gym = request.gym
    movements = movements_queryset(gym).order_by("-created_at")
    product_id = request.GET.get("product")
    movement_type = request.GET.get("movement_type")

    if product_id:
        movements = movements.filter(product_id=product_id, product__gym=gym)
    if movement_type:
        movements = movements.filter(movement_type=movement_type)

    paginator = Paginator(movements, 30)
    movements_page = paginator.get_page(request.GET.get("page"))

    context = {
        "gym": gym,
        "movements": movements_page,
        "products": Product.objects.filter(gym=gym, is_active=True).order_by("name"),
        "selected_product": product_id,
        "selected_type": movement_type,
        "movement_types": StockMovement.MOVEMENT_TYPE,
        **build_product_kpis(gym),
    }
    return render(request, "products/stock_movement_list.html", context)


@login_required
@module_required("PRODUCTS")
@role_required(PRODUCT_ROLES)
def stock_dashboard(request):
    gym = request.gym
    kpis = build_product_kpis(gym)
    context = {
        "gym": gym,
        "total_products": kpis["total_products"],
        "total_value": kpis["stock_value_total"],
        "low_stock_products": kpis["low_stock_products"],
        "out_of_stock_products": kpis["out_of_stock_products"],
        "top_value_products": kpis["top_value_products"],
        "recent_movements": kpis["recent_stock_movements"],
        **kpis,
    }
    return render(request, "products/stock_dashboard.html", context)
