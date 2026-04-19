from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from smartclub.access_control import MEMBER_ROLES, has_role
from .forms import MemberPreRegistrationForm
from .models import Member, MemberPreRegistration, MemberPreRegistrationLink


def _cleanup_expired_pre_registrations():
    MemberPreRegistration.delete_expired_pending()


def _member_management_allowed(request):
    return has_role(request, MEMBER_ROLES) and request.gym


def _get_pre_registration_public_url(request, link):
    return request.build_absolute_uri(
        reverse("members:public_pre_registration", args=[link.token])
    )


def public_pre_registration(request, token):
    _cleanup_expired_pre_registrations()
    link = get_object_or_404(
        MemberPreRegistrationLink.objects.select_related("gym__organization"),
        token=token,
        is_active=True,
        gym__is_active=True,
        gym__organization__is_active=True,
    )
    gym = link.gym
    saved_pre_registration = None

    if request.method == "POST":
        form = MemberPreRegistrationForm(request.POST, gym=gym)
        if form.is_valid():
            saved_pre_registration = form.save(commit=False)
            saved_pre_registration.gym = gym
            saved_pre_registration.link = link
            saved_pre_registration.save()
            form = MemberPreRegistrationForm(gym=gym)
    else:
        form = MemberPreRegistrationForm(gym=gym)

    return render(
        request,
        "members/pre_registration_public.html",
        {
            "form": form,
            "gym": gym,
            "organization": gym.organization,
            "saved_pre_registration": saved_pre_registration,
        },
    )


@login_required
def pre_registration_list(request):
    if not _member_management_allowed(request):
        raise PermissionDenied

    _cleanup_expired_pre_registrations()
    gym = request.gym
    link, _ = MemberPreRegistrationLink.objects.get_or_create(gym=gym)
    pre_registration_url = _get_pre_registration_public_url(request, link)

    status = request.GET.get("status", MemberPreRegistration.STATUS_PENDING)
    search = request.GET.get("search", "")
    allowed_statuses = [
        "",
        MemberPreRegistration.STATUS_PENDING,
        MemberPreRegistration.STATUS_CONFIRMED,
        MemberPreRegistration.STATUS_CANCELLED,
    ]
    if status not in allowed_statuses:
        status = MemberPreRegistration.STATUS_PENDING

    pre_registrations = MemberPreRegistration.objects.filter(gym=gym).select_related(
        "member",
        "confirmed_by",
    )
    if status:
        pre_registrations = pre_registrations.filter(status=status)
    if search:
        pre_registrations = pre_registrations.filter(
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(phone__icontains=search)
            | Q(email__icontains=search)
        )

    paginator = Paginator(pre_registrations, 15)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "page_obj": page_obj,
        "status": status,
        "search": search,
        "pre_registration_link": link,
        "pre_registration_url": pre_registration_url,
        "pending_count": MemberPreRegistration.objects.filter(
            gym=gym,
            status=MemberPreRegistration.STATUS_PENDING,
            expires_at__gt=timezone.now(),
        ).count(),
        "confirmed_count": MemberPreRegistration.objects.filter(
            gym=gym,
            status=MemberPreRegistration.STATUS_CONFIRMED,
        ).count(),
        "cancelled_count": MemberPreRegistration.objects.filter(
            gym=gym,
            status=MemberPreRegistration.STATUS_CANCELLED,
        ).count(),
        "nav_active": "clients",
        "nav_sub": "pre_registrations",
    }
    return render(request, "members/pre_registration_list.html", context)


@login_required
@require_POST
def confirm_pre_registration(request, pre_registration_id):
    if not _member_management_allowed(request):
        raise PermissionDenied

    pre_registration = get_object_or_404(
        MemberPreRegistration,
        id=pre_registration_id,
        gym=request.gym,
    )

    if pre_registration.is_expired:
        pre_registration.delete()
        messages.warning(request, "Cette preinscription a expire et a ete supprimee.")
        return redirect("members:pre_registration_list")

    if pre_registration.status != MemberPreRegistration.STATUS_PENDING:
        messages.error(request, "Cette preinscription n'est plus en attente.")
        return redirect("members:pre_registration_list")

    duplicate_query = Q(phone=pre_registration.phone)
    if pre_registration.email:
        duplicate_query |= Q(email=pre_registration.email)
    if Member.objects.filter(duplicate_query, gym=request.gym).exists():
        messages.error(request, "Impossible de confirmer : un membre existe deja avec ces coordonnees.")
        return redirect("members:pre_registration_list")

    try:
        member = pre_registration.confirm(request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("members:pre_registration_list")

    username = member.user.username if member.user else "genere automatiquement"
    messages.success(
        request,
        f"Preinscription confirmee. Membre cree : {member.first_name} {member.last_name}. "
        f"Identifiant : {username}. Mot de passe temporaire : 12345."
    )
    return redirect("members:pre_registration_list")


@login_required
@require_POST
def cancel_pre_registration(request, pre_registration_id):
    if not _member_management_allowed(request):
        raise PermissionDenied

    pre_registration = get_object_or_404(
        MemberPreRegistration,
        id=pre_registration_id,
        gym=request.gym,
        status=MemberPreRegistration.STATUS_PENDING,
    )
    pre_registration.status = MemberPreRegistration.STATUS_CANCELLED
    pre_registration.save(update_fields=["status"])
    messages.info(request, "Preinscription annulee.")
    return redirect("members:pre_registration_list")
