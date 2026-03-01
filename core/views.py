#core/views.py
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from core.models import Gym
from django.core.exceptions import PermissionDenied

@login_required
def superadmin_dashboard(request):
    return render(request, 'dashboard/superadmin.html')

@login_required
@login_required
def admin_dashboard(request):
    gym = request.gym
    return render(request, 'dashboard/admin.html', {'gym': gym})

@login_required
def manager_dashboard(request):
    gym = request.gym
    return render(request, 'dashboard/manager.html', {'gym': gym})

@login_required
def cashier_dashboard(request):
    gym = request.gym
    return render(request, 'dashboard/cashier.html', {'gym': gym})

@login_required
def reception_dashboard(request):
    gym = request.gym
    return render(request, 'dashboard/reception.html', {'gym': gym})

@login_required
def member_dashboard(request):
    member = request.user.member_profile
    return render(request, 'dashboard/member.html', {
        'member': member,
        'gym': member.gym
    })
