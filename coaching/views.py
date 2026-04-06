
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.contrib import messages

from .models import Coach
from .forms import CoachForm


@login_required
def coach_list(request):

    if request.role not in ["admin", "manager"]:
        raise PermissionDenied

    coaches = (
        Coach.objects
        .filter(gym=request.gym)
        .prefetch_related("members")  # 🔥 important
    )

    return render(request, "coaching/coach_list.html", {
        "coaches": coaches
    })


@login_required
def create_coach(request):

    if request.role not in ["admin", "manager"]:
        raise PermissionDenied

    if request.method == "POST":
        form = CoachForm(request.POST, gym=request.gym)

        if form.is_valid():
            coach = form.save(commit=False)
            coach.gym = request.gym
            coach.save()

            form.save_m2m()  # 🔥 important pour members

            messages.success(request, "Coach créé avec succès")
            return redirect("coaching:coach_list")

    else:
        form = CoachForm(gym=request.gym)

    return render(request, "coaching/create_coach.html", {
        "form": form
    })