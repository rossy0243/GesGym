from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Sum, Q

from organizations.models import Gym
from .models import Product, StockMovement
from .forms import ProductForm, StockMovementForm

@login_required
def product_list(request, gym_id):
    """Liste des produits"""
    gym = get_object_or_404(Gym, id=gym_id)
    products = gym.products.all().order_by('name')
    
    # Filtres
    active_filter = request.GET.get('active')
    if active_filter == 'active':
        products = products.filter(is_active=True)
    elif active_filter == 'inactive':
        products = products.filter(is_active=False)
    
    low_stock = request.GET.get('low_stock')
    if low_stock:
        products = products.filter(quantity__lte=5, quantity__gt=0)
    
    out_of_stock = request.GET.get('out_of_stock')
    if out_of_stock:
        products = products.filter(quantity=0, is_active=True)
    
    context = {
        'gym': gym,
        'products': products,
        'active_filter': active_filter,
        'low_stock': low_stock,
        'out_of_stock': out_of_stock,
    }
    return render(request, 'products/product_list.html', context)

@login_required
def product_detail(request, gym_id, product_id):
    """Détail d'un produit"""
    product = get_object_or_404(Product, id=product_id, gym_id=gym_id)
    movements = product.movements.all()[:20]
    
    # Statistiques
    total_in = product.movements.filter(movement_type='in').aggregate(Sum('quantity'))['quantity__sum'] or 0
    total_out = product.movements.filter(movement_type='out').aggregate(Sum('quantity'))['quantity__sum'] or 0
    
    context = {
        'product': product,
        'movements': movements,
        'total_in': total_in,
        'total_out': total_out,
        'gym_id': gym_id,
    }
    return render(request, 'products/product_detail.html', context)

@login_required
def product_create(request, gym_id):
    """Créer un produit"""
    gym = get_object_or_404(Gym, id=gym_id)
    
    if request.method == 'POST':
        form = ProductForm(request.POST)
        if form.is_valid():
            product = form.save(commit=False)
            product.gym = gym
            product.save()
            
            # Si quantité initiale > 0, créer un mouvement d'entrée
            if product.quantity > 0:
                StockMovement.objects.create(
                    gym=gym,
                    product=product,
                    quantity=product.quantity,
                    movement_type='in',
                    reason="Stock initial"
                )
            
            messages.success(request, f'Produit "{product.name}" créé avec succès!')
            return redirect('products:detail', gym_id=gym.id, product_id=product.id)
    else:
        form = ProductForm()
    
    context = {
        'gym': gym,
        'form': form,
        'title': 'Ajouter un produit',
    }
    return render(request, 'products/product_form.html', context)

@login_required
def product_update(request, gym_id, product_id):
    """Modifier un produit"""
    product = get_object_or_404(Product, id=product_id, gym_id=gym_id)
    
    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, f'Produit "{product.name}" modifié avec succès!')
            return redirect('products:detail', gym_id=gym_id, product_id=product.id)
    else:
        form = ProductForm(instance=product)
    
    context = {
        'gym': product.gym,
        'form': form,
        'product': product,
        'title': 'Modifier le produit',
    }
    return render(request, 'products/product_form.html', context)

@login_required
def product_delete(request, gym_id, product_id):
    """Supprimer un produit (soft delete)"""
    product = get_object_or_404(Product, id=product_id, gym_id=gym_id)
    
    if request.method == 'POST':
        product.is_active = False
        product.save()
        messages.success(request, f'Produit "{product.name}" désactivé avec succès!')
        return redirect('products:list', gym_id=gym_id)
    
    context = {
        'product': product,
    }
    return render(request, 'products/product_confirm_delete.html', context)

@login_required
def stock_movement_create(request, gym_id, product_id):
    """Ajouter un mouvement de stock"""
    product = get_object_or_404(Product, id=product_id, gym_id=gym_id)
    
    if request.method == 'POST':
        form = StockMovementForm(request.POST)
        if form.is_valid():
            quantity = form.cleaned_data['quantity']
            movement_type = form.cleaned_data['movement_type']
            reason = form.cleaned_data['reason']
            
            try:
                product.update_stock(quantity, movement_type, reason)
                messages.success(request, f'Mouvement enregistré: {product.name} - {quantity}')
                return redirect('products:detail', gym_id=gym_id, product_id=product.id)
            except ValueError as e:
                messages.error(request, str(e))
    else:
        form = StockMovementForm()
    
    context = {
        'product': product,
        'form': form,
        'title': f'Ajouter un mouvement - {product.name}',
    }
    return render(request, 'products/stock_movement_form.html', context)

@login_required
def stock_movement_list(request, gym_id):
    """Liste des mouvements de stock"""
    gym = get_object_or_404(Gym, id=gym_id)
    movements = StockMovement.objects.filter(gym=gym).order_by('-created_at')
    
    # Filtres
    product_id = request.GET.get('product')
    movement_type = request.GET.get('movement_type')
    
    if product_id:
        movements = movements.filter(product_id=product_id)
    if movement_type:
        movements = movements.filter(movement_type=movement_type)
    
    # Pagination
    paginator = Paginator(movements, 30)
    page_number = request.GET.get('page')
    movements_page = paginator.get_page(page_number)
    
    context = {
        'gym': gym,
        'movements': movements_page,
        'products': Product.objects.filter(gym=gym, is_active=True),
        'selected_product': product_id,
        'selected_type': movement_type,
        'movement_types': StockMovement.MOVEMENT_TYPE,
    }
    return render(request, 'products/stock_movement_list.html', context)

@login_required
def stock_dashboard(request, gym_id):
    """Tableau de bord des stocks"""
    gym = get_object_or_404(Gym, id=gym_id)
    
    products = Product.objects.filter(gym=gym)
    
    # Statistiques
    total_products = products.filter(is_active=True).count()
    total_value = sum(p.price * p.quantity for p in products.filter(is_active=True))
    low_stock_products = products.filter(quantity__lte=5, quantity__gt=0, is_active=True)
    out_of_stock_products = products.filter(quantity=0, is_active=True)
    
    # Top produits par valeur de stock
    top_value_products = sorted(
        [p for p in products.filter(is_active=True) if p.quantity > 0],
        key=lambda p: p.price * p.quantity,
        reverse=True
    )[:5]
    
    # Derniers mouvements
    recent_movements = StockMovement.objects.filter(gym=gym)[:10]
    
    context = {
        'gym': gym,
        'total_products': total_products,
        'total_value': total_value,
        'low_stock_products': low_stock_products,
        'out_of_stock_products': out_of_stock_products,
        'top_value_products': top_value_products,
        'recent_movements': recent_movements,
    }
    return render(request, 'products/stock_dashboard.html', context)