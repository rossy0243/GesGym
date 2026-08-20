from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_sensitive_action
from core.creation_emails import (
    notify_creation_email_failure,
    send_member_creation_email,
    send_pre_registration_received_email,
)
from smartclub.access_control import (
    PRE_REGISTRATION_LINK_ROLES,
    PRE_REGISTRATION_ROLES,
    has_role,
)
from smartclub.public_links import build_public_url, is_local_url
from .forms import MemberPreRegistrationForm
from .models import MemberPreRegistration, MemberPreRegistrationLink


def _cleanup_expired_pre_registrations():
    MemberPreRegistration.mark_expired_pending()


def _member_management_allowed(request):
    """
    Qui traite les demandes de preinscription.

    Ensemble distinct des fiches membres : le commercial convertit les
    prospects sans avoir acces a la liste des membres ni a leurs coordonnees.
    """
    return has_role(request, PRE_REGISTRATION_ROLES) and request.gym


def _link_management_allowed(request):
    """Revoquer un lien est plus sensible que consulter les demandes."""
    return has_role(request, PRE_REGISTRATION_LINK_ROLES) and request.gym


def _get_pre_registration_public_url(request, link):
    return build_public_url(
        request,
        reverse("members:public_pre_registration", args=[link.token]),
    )


def _client_ip(request):
    """IP du visiteur, en tenant compte du proxy de Render."""
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")
    if forwarded and forwarded[0].strip():
        return forwarded[0].strip()
    return request.META.get("REMOTE_ADDR") or ""


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
    ip_address = _client_ip(request)
    form_kwargs = {"gym": gym, "link": link, "ip_address": ip_address}

    if request.method == "POST":
        form = MemberPreRegistrationForm(request.POST, **form_kwargs)
        if form.is_valid():
            saved_pre_registration = form.save(commit=False)
            saved_pre_registration.gym = gym
            saved_pre_registration.link = link
            saved_pre_registration.ip_address = ip_address or None
            saved_pre_registration.save()
            try:
                send_pre_registration_received_email(saved_pre_registration)
            except Exception as exc:
                notify_creation_email_failure(str(saved_pre_registration), exc)
            form = MemberPreRegistrationForm(**form_kwargs)
    else:
        form = MemberPreRegistrationForm(**form_kwargs)

    return render(
        request,
        "members/pre_registration_public.html",
        {
            "form": form,
            "gym": gym,
            "organization": gym.organization,
            "saved_pre_registration": saved_pre_registration,
            "seo_title": f"Preinscription membre | {gym.name}",
            "seo_description": (
                f"Formulaire de preinscription membre pour {gym.name}. "
                "Page reservee aux prospects du club."
            ),
            "seo_robots": "noindex, nofollow, noarchive",
            "seo_canonical_url": request.build_absolute_uri(),
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
        MemberPreRegistration.STATUS_EXPIRED,
    ]
    if status not in allowed_statuses:
        status = MemberPreRegistration.STATUS_PENDING

    pre_registrations = MemberPreRegistration.objects.filter(gym=gym).select_related(
        "member",
        "confirmed_by",
        "cancelled_by",
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
        # Alerte l'utilisateur avant qu'il n'envoie un lien local a un prospect.
        "pre_registration_url_is_local": is_local_url(pre_registration_url),
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
        "expired_count": MemberPreRegistration.objects.filter(
            gym=gym,
            status=MemberPreRegistration.STATUS_EXPIRED,
        ).count(),
        "nav_active": "clients",
        "nav_sub": "pre_registrations",
    }
    return render(request, "members/pre_registration_list.html", context)


@login_required
@require_POST
def regenerate_pre_registration_link(request):
    """
    Renouvelle le jeton du lien public : l'ancien cesse aussitot de fonctionner.

    Reserve aux proprietaires et gerants, car l'operation coupe l'acces a
    toute personne detenant l'ancienne adresse.
    """
    if not _link_management_allowed(request):
        raise PermissionDenied

    link, _ = MemberPreRegistrationLink.objects.get_or_create(gym=request.gym)
    link.regenerate_token()

    messages.success(
        request,
        "Nouveau lien de preinscription genere. L'ancien lien ne fonctionne plus.",
    )
    return redirect("members:pre_registration_list")


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
        if pre_registration.status == MemberPreRegistration.STATUS_PENDING:
            pre_registration.status = MemberPreRegistration.STATUS_EXPIRED
            pre_registration.save(update_fields=["status"])
        messages.warning(
            request,
            "Cette preinscription a expire. Elle reste consultable dans le filtre "
            "« Expirees », mais ne peut plus etre confirmee.",
        )
        return redirect("members:pre_registration_list")

    if pre_registration.status != MemberPreRegistration.STATUS_PENDING:
        messages.error(request, "Cette preinscription n'est plus en attente.")
        return redirect("members:pre_registration_list")

    try:
        member = pre_registration.confirm(request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("members:pre_registration_list")

    log_sensitive_action(
        request,
        "member.pre_registration_confirmed",
        "MemberPreRegistration",
        pre_registration.full_name,
        metadata={
            "preinscription_id": pre_registration.id,
            "member_id": member.id,
            "telephone": pre_registration.phone,
        },
        gym=request.gym,
    )
    _announce_member_credentials(request, member, action="Preinscription confirmee.")
    return redirect("members:pre_registration_list")


def _announce_member_credentials(request, member, action):
    """
    Envoie les identifiants par e-mail et les affiche de facon persistante.

    Le mot de passe temporaire n'est stocke nulle part en clair : s'il n'est ni
    lu ni recu, il est perdu. Le message ne doit donc pas s'effacer tout seul.
    """
    username = member.user.username if member.user else "genere automatiquement"
    temporary_password = getattr(member, "_temporary_password", "")

    try:
        email_sent = send_member_creation_email(
            member,
            temporary_password=temporary_password,
            portal_url=build_public_url(request, reverse("members:member_portal")),
        )
    except Exception as exc:
        notify_creation_email_failure(str(member), exc)
        email_sent = False

    delivery = (
        "Identifiants egalement envoyes par e-mail."
        if email_sent
        else "L'envoi de l'e-mail a echoue : notez ces identifiants avant de fermer ce message."
    )

    messages.success(
        request,
        f"{action} Membre : {member.first_name} {member.last_name}. "
        f"Identifiant : {username}. Mot de passe temporaire : {temporary_password}. "
        f"Il devra etre change a la premiere connexion. {delivery}",
        extra_tags="persistent",
    )
    return email_sent


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
    pre_registration.cancel(request.user)
    log_sensitive_action(
        request,
        "member.pre_registration_cancelled",
        "MemberPreRegistration",
        pre_registration.full_name,
        metadata={
            "preinscription_id": pre_registration.id,
            "telephone": pre_registration.phone,
        },
        gym=request.gym,
    )
    messages.info(request, "Preinscription annulee.")
    return redirect("members:pre_registration_list")
