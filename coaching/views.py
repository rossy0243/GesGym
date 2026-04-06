from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator

from organizations.models import Gym
from .models import Coach
from members.models import Member
from .forms import CoachForm, CoachMemberForm

@login_required
def coach_list(request, gym_id):
    """Liste des coaches"""
    gym = get_object_or_404(Gym, id=gym_id)
    coaches = Coach.objects.filter(gym=gym).order_by('name')
    
    # Filtre
    active_filter = request.GET.get('active')
    if active_filter == 'active':
        coaches = coaches.filter(is_active=True)
    elif active_filter == 'inactive':
        coaches = coaches.filter(is_active=False)
    
    context = {
        'gym': gym,
        'coaches': coaches,
        'active_filter': active_filter,
    }
    return render(request, 'coaching/coach_list.html', context)

@login_required
def coach_detail(request, gym_id, coach_id):
    """Détail d'un coach avec ses membres"""
    coach = get_object_or_404(Coach, id=coach_id, gym_id=gym_id)
    members = coach.members.all()
    
    # Membres actifs non assignés (exclure ceux déjà assignés)
    available_members = Member.objects.filter(
        gym_id=gym_id,
        status='active'  # ← Filtrer uniquement les membres actifs
    ).exclude(id__in=members.values_list('id', flat=True))
    
    context = {
        'coach': coach,
        'members': members,
        'available_members': available_members,
        'gym_id': gym_id,
    }
    return render(request, 'coaching/coach_detail.html', context)


@login_required
def coach_create(request, gym_id):
    """Créer un coach"""
    gym = get_object_or_404(Gym, id=gym_id)
    
    if request.method == 'POST':
        form = CoachForm(request.POST)
        if form.is_valid():
            coach = form.save(commit=False)
            coach.gym = gym
            coach.save()
            messages.success(request, f'Coach "{coach.name}" créé avec succès!')
            return redirect('coaching:detail', gym_id=gym.id, coach_id=coach.id)
    else:
        form = CoachForm()
    
    context = {
        'gym': gym,
        'form': form,
        'title': 'Ajouter un coach',
    }
    return render(request, 'coaching/coach_form.html', context)

@login_required
def coach_update(request, gym_id, coach_id):
    """Modifier un coach"""
    coach = get_object_or_404(Coach, id=coach_id, gym_id=gym_id)
    
    if request.method == 'POST':
        form = CoachForm(request.POST, instance=coach)
        if form.is_valid():
            form.save()
            messages.success(request, f'Coach "{coach.name}" modifié avec succès!')
            return redirect('coaching:detail', gym_id=gym_id, coach_id=coach.id)
    else:
        form = CoachForm(instance=coach)
    
    context = {
        'gym': coach.gym,
        'form': form,
        'coach': coach,
        'title': 'Modifier le coach',
    }
    return render(request, 'coaching/coach_form.html', context)

@login_required
def coach_delete(request, gym_id, coach_id):
    """Désactiver un coach"""
    coach = get_object_or_404(Coach, id=coach_id, gym_id=gym_id)
    
    if request.method == 'POST':
        coach.is_active = False
        coach.save()
        messages.success(request, f'Coach "{coach.name}" désactivé avec succès!')
        return redirect('coaching:list', gym_id=gym_id)
    
    context = {'coach': coach}
    return render(request, 'coaching/coach_confirm_delete.html', context)

@login_required
def assign_member(request, gym_id, coach_id):
    """Assigner un membre à un coach"""
    coach = get_object_or_404(Coach, id=coach_id, gym_id=gym_id)
    
    if request.method == 'POST':
        member_id = request.POST.get('member')
        if member_id:
            try:
                member = Member.objects.get(
                    id=member_id, 
                    gym_id=gym_id,
                    status='active'  # ← Vérifier que le membre est actif
                )
                coach.members.add(member)
                messages.success(request, f'Membre "{member.first_name} {member.last_name}" assigné à {coach.name}')
            except Member.DoesNotExist:
                messages.error(request, 'Membre non trouvé ou inactif')
    
    return redirect('coaching:detail', gym_id=gym_id, coach_id=coach.id)


@login_required
def remove_member(request, gym_id, coach_id, member_id):
    """Retirer un membre d'un coach"""
    coach = get_object_or_404(Coach, id=coach_id, gym_id=gym_id)
    member = get_object_or_404(Member, id=member_id, gym_id=gym_id)
    
    if request.method == 'POST':
        coach.members.remove(member)
        messages.success(request, f'Membre "{member.first_name}" retiré de {coach.name}')
    
    return redirect('coaching:detail', gym_id=gym_id, coach_id=coach.id)