#core/views.py
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from .forms import MemberCreationForm
from core.models import Gym
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

@login_required
def superadmin_dashboard(request):
    return render(request, 'core/superadmin.html')


@login_required
def admin_dashboard(request):
    gym = request.gym
    return render(request, 'core/admin.html', {'gym': gym})

@login_required
def manager_dashboard(request):
    gym = request.gym
    return render(request, 'core/manager.html', {'gym': gym})

@login_required
def cashier_dashboard(request):
    gym = request.gym
    return render(request, 'core/cashier.html', {'gym': gym})

@login_required
def reception_dashboard(request):
    gym = request.gym
    return render(request, 'core/reception.html', {'gym': gym})

@login_required
def member_dashboard(request):
    member = request.user.member_profile
    return render(request, 'core/member.html', {
        'member': member,
        'gym': member.gym
    })


@login_required
def create_member(request):

    if request.user.role not in ["admin", "reception"]:
        raise PermissionDenied("Accès refusé.")

    if request.method == "POST":
        form = MemberCreationForm(request.POST, request.FILES)
        if form.is_valid():
            member = form.save(commit=False)
            member.gym = request.user.gym
            member.save()  # ⚡ déclenche ton signal
            return redirect("reception_dashboard")
    else:
        form = MemberCreationForm()

    return render(request, "core/create_member.html", {"form": form})