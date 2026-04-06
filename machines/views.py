from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Sum, Count

from organizations.models import Gym
from .models import Machine, MaintenanceLog
from .forms import MachineForm, MaintenanceLogForm

@login_required
def machine_list(request, gym_id):
    """Liste des machines d'un gym"""
    gym = get_object_or_404(Gym, id=gym_id)
    machines = gym.machines.all().order_by('name')
    
    # Filtres
    status_filter = request.GET.get('status')
    if status_filter:
        machines = machines.filter(status=status_filter)
    
    # Pagination
    paginator = Paginator(machines, 10)
    page_number = request.GET.get('page')
    machines_page = paginator.get_page(page_number)
    
    context = {
        'gym': gym,
        'machines': machines_page,
        'status_filter': status_filter,
        'status_choices': Machine.STATUS,
    }
    return render(request, 'machines/machine_list.html', context)

@login_required
def machine_detail(request, gym_id, machine_id):
    """Détail d'une machine avec son historique"""
    machine = get_object_or_404(Machine, id=machine_id, gym_id=gym_id)
    maintenance_logs = machine.maintenance_logs.all().order_by('-created_at')
    
    # Statistiques
    total_maintenance_cost = maintenance_logs.aggregate(Sum('cost'))['cost__sum'] or 0
    maintenance_count = maintenance_logs.count()
    
    context = {
        'machine': machine,
        'maintenance_logs': maintenance_logs,
        'total_maintenance_cost': total_maintenance_cost,
        'maintenance_count': maintenance_count,
    }
    return render(request, 'machines/machine_detail.html', context)

@login_required
def machine_create(request, gym_id):
    """Créer une nouvelle machine"""
    gym = get_object_or_404(Gym, id=gym_id)
    
    if request.method == 'POST':
        form = MachineForm(request.POST)
        if form.is_valid():
            machine = form.save(commit=False)
            machine.gym = gym
            machine.save()
            messages.success(request, f'Machine "{machine.name}" créée avec succès!')
            return redirect('machines:detail', gym_id=gym.id, machine_id=machine.id)
    else:
        form = MachineForm()
    
    context = {
        'gym': gym,
        'form': form,
        'title': 'Ajouter une machine',
    }
    return render(request, 'machines/machine_form.html', context)

@login_required
def machine_update(request, gym_id, machine_id):
    """Modifier une machine"""
    machine = get_object_or_404(Machine, id=machine_id, gym_id=gym_id)
    
    if request.method == 'POST':
        form = MachineForm(request.POST, instance=machine)
        if form.is_valid():
            form.save()
            messages.success(request, f'Machine "{machine.name}" modifiée avec succès!')
            return redirect('machines:detail', gym_id=gym_id, machine_id=machine.id)
    else:
        form = MachineForm(instance=machine)
    
    context = {
        'gym': machine.gym,
        'form': form,
        'machine': machine,
        'title': 'Modifier la machine',
    }
    return render(request, 'machines/machine_form.html', context)

@login_required
def machine_delete(request, gym_id, machine_id):
    """Supprimer une machine"""
    machine = get_object_or_404(Machine, id=machine_id, gym_id=gym_id)
    
    if request.method == 'POST':
        machine_name = machine.name
        machine.delete()
        messages.success(request, f'Machine "{machine_name}" supprimée avec succès!')
        return redirect('machines:list', gym_id=gym_id)
    
    context = {
        'machine': machine,
    }
    return render(request, 'machines/machine_confirm_delete.html', context)

@login_required
def maintenance_log_create(request, gym_id, machine_id):
    """Ajouter un log de maintenance"""
    machine = get_object_or_404(Machine, id=machine_id, gym_id=gym_id)
    
    if request.method == 'POST':
        form = MaintenanceLogForm(request.POST)
        if form.is_valid():
            log = form.save(commit=False)
            log.machine = machine
            log.save()
            
            # Changer le statut de la machine si demandé
            if request.POST.get('change_status'):
                new_status = request.POST.get('status')
                if new_status in dict(Machine.STATUS).keys():
                    machine.status = new_status
                    machine.save()
            
            messages.success(request, f'Maintenance ajoutée pour "{machine.name}" avec succès!')
            return redirect('machines:detail', gym_id=gym_id, machine_id=machine.id)
    else:
        form = MaintenanceLogForm()
    
    context = {
        'gym': machine.gym,
        'machine': machine,
        'form': form,
        'title': f'Ajouter une maintenance - {machine.name}',
    }
    return render(request, 'machines/maintenance_form.html', context)

@login_required
def maintenance_list(request, gym_id):
    """Liste de toutes les maintenances"""
    gym = get_object_or_404(Gym, id=gym_id)
    maintenances = MaintenanceLog.objects.filter(machine__gym=gym).order_by('-created_at')
    
    # Pagination
    paginator = Paginator(maintenances, 15)
    page_number = request.GET.get('page')
    maintenances_page = paginator.get_page(page_number)
    
    # Statistiques
    stats = {
        'total': maintenances.count(),
        'total_cost': maintenances.aggregate(Sum('cost'))['cost__sum'] or 0,
        'by_machine': maintenances.values('machine__name').annotate(
            count=Count('id'),
            total=Sum('cost')
        ),
    }
    
    context = {
        'gym': gym,
        'maintenances': maintenances_page,
        'stats': stats,
    }
    return render(request, 'machines/maintenance_list.html', context)

@login_required
def maintenance_dashboard(request, gym_id):
    """Tableau de bord des maintenances"""
    gym = get_object_or_404(Gym, id=gym_id)
    
    # Statistiques globales
    all_maintenances = MaintenanceLog.objects.filter(machine__gym=gym)
    
    # Machines par statut
    machines_by_status = {
        'ok': Machine.objects.filter(gym=gym, status='ok').count(),
        'maintenance': Machine.objects.filter(gym=gym, status='maintenance').count(),
        'broken': Machine.objects.filter(gym=gym, status='broken').count(),
    }
    
    # Dernières maintenances
    recent_maintenances = all_maintenances.order_by('-created_at')[:10]
    
    # Top machines avec le plus de maintenances
    top_maintenance_machines = Machine.objects.filter(gym=gym).annotate(
        maintenance_count=Count('maintenance_logs')
    ).order_by('-maintenance_count')[:5]
    
    # Coût total des maintenances par machine
    maintenance_cost_by_machine = all_maintenances.values('machine__name').annotate(
        total_cost=Sum('cost')
    ).order_by('-total_cost')[:5]
    
    context = {
        'gym': gym,
        'total_machines': Machine.objects.filter(gym=gym).count(),
        'total_maintenances': all_maintenances.count(),
        'total_maintenance_cost': all_maintenances.aggregate(Sum('cost'))['cost__sum'] or 0,
        'machines_by_status': machines_by_status,
        'recent_maintenances': recent_maintenances,
        'top_maintenance_machines': top_maintenance_machines,
        'maintenance_cost_by_machine': maintenance_cost_by_machine,
    }
    return render(request, 'machines/maintenance_dashboard.html', context)

@login_required
def maintenance_delete(request, gym_id, maintenance_id):
    """Supprimer un log de maintenance"""
    maintenance = get_object_or_404(MaintenanceLog, id=maintenance_id, machine__gym_id=gym_id)
    machine = maintenance.machine
    
    if request.method == 'POST':
        maintenance.delete()
        messages.success(request, 'Log de maintenance supprimé avec succès!')
        return redirect('machines:detail', gym_id=gym_id, machine_id=machine.id)
    
    context = {
        'maintenance': maintenance,
    }
    return render(request, 'machines/maintenance_confirm_delete.html', context)