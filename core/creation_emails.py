import logging
from email.utils import formataddr, parseaddr

from django.conf import settings
from django.core.mail import send_mail


logger = logging.getLogger(__name__)


def _clean_header_value(value):
    return " ".join(str(value or "").split())


def organization_sender(organization_name):
    display_name = _clean_header_value(organization_name)
    if not display_name:
        return settings.DEFAULT_FROM_EMAIL

    _, email_address = parseaddr(settings.DEFAULT_FROM_EMAIL)
    email_address = email_address or settings.DEFAULT_FROM_EMAIL
    return formataddr((display_name, email_address))


def _send_creation_email(subject, message, recipient, organization_name=""):
    recipient = (recipient or "").strip()
    if not recipient:
        return False

    send_mail(
        subject=subject,
        message=message,
        from_email=organization_sender(organization_name),
        recipient_list=[recipient],
        fail_silently=False,
    )
    return True


def send_member_creation_email(member, temporary_password="", portal_url=""):
    gym_name = member.gym.name if member.gym_id else "votre salle"
    organization = getattr(member.gym, "organization", None) if member.gym_id else None
    organization_name = organization.name if organization else ""
    username = member.user.username if getattr(member, "user", None) else "genere automatiquement"
    temporary_password = temporary_password or "genere automatiquement"

    lines = [
        f"Bonjour {member.first_name},",
        "",
        f"Votre fiche membre a ete creee chez {gym_name}.",
    ]
    if organization_name:
        lines.append(f"Organisation : {organization_name}")
    lines.extend(
        [
            "",
            "Vos coordonnees enregistrees :",
            f"- Nom : {member.first_name} {member.last_name}",
            f"- Telephone : {member.phone}",
            f"- Email : {member.email or 'Non renseigne'}",
            f"- Adresse : {member.address or 'Non renseignee'}",
            "",
            "Vos identifiants de connexion :",
            f"- Identifiant : {username}",
            f"- Mot de passe temporaire : {temporary_password}",
            "",
            "Vous devrez changer ce mot de passe lors de votre premiere connexion.",
        ]
    )
    if portal_url:
        lines.extend(["", f"Espace membre : {portal_url}"])

    return _send_creation_email(
        subject=f"{organization_name or gym_name} - Vos coordonnees membre",
        message="\n".join(lines),
        recipient=member.email,
        organization_name=organization_name,
    )


def send_pre_registration_received_email(pre_registration):
    gym_name = pre_registration.gym.name if pre_registration.gym_id else "votre salle"
    organization = getattr(pre_registration.gym, "organization", None) if pre_registration.gym_id else None
    organization_name = organization.name if organization else ""

    lines = [
        f"Bonjour {pre_registration.first_name},",
        "",
        f"Votre preinscription chez {organization_name or gym_name} a bien ete recue.",
        f"Salle de sport : {organization_name + ' - ' if organization_name else ''}{gym_name}.",
    ]
    lines.extend(
        [
            "",
            "Votre demande est en attente de confirmation.",
            "Passez a la salle afin que l'equipe confirme votre inscription et finalise votre fiche membre.",
            "",
            "Coordonnees recues :",
            f"- Nom : {pre_registration.first_name} {pre_registration.last_name}",
            f"- Telephone : {pre_registration.phone}",
            f"- Email : {pre_registration.email}",
            f"- Adresse : {pre_registration.address or 'Non renseignee'}",
            "",
            f"Validite de la demande : jusqu'au {pre_registration.expires_at:%d/%m/%Y %H:%M}.",
        ]
    )

    return _send_creation_email(
        subject=f"{organization_name or gym_name} - Preinscription recue",
        message="\n".join(lines),
        recipient=pre_registration.email,
        organization_name=organization_name,
    )


def send_employee_creation_email(employee):
    gym_name = employee.gym.name if employee.gym_id else "votre salle"
    organization = getattr(employee.gym, "organization", None) if employee.gym_id else None
    organization_name = organization.name if organization else ""

    lines = [
        f"Bonjour {employee.name},",
        "",
        f"Votre fiche employe a ete creee chez {gym_name}.",
    ]
    if organization_name:
        lines.append(f"Organisation : {organization_name}")
    lines.extend(
        [
            "",
            "Vos coordonnees enregistrees :",
            f"- Nom : {employee.name}",
            f"- Role : {employee.get_role_display()}",
            f"- Telephone : {employee.phone or 'Non renseigne'}",
            f"- Email : {employee.email or 'Non renseigne'}",
            f"- Mode de remuneration : {employee.get_compensation_label()}",
        ]
    )
    if employee.compensation_type == employee.COMPENSATION_MONTHLY:
        lines.append(f"- Salaire mensuel : {employee.monthly_salary} CDF")
    else:
        lines.append(f"- Salaire journalier : {employee.daily_salary} CDF")

    lines.append(f"- Statut : {'Actif' if employee.is_active else 'Inactif'}")

    return _send_creation_email(
        subject=f"{organization_name or gym_name} - Vos coordonnees employe",
        message="\n".join(lines),
        recipient=employee.email,
        organization_name=organization_name,
    )


def notify_creation_email_failure(target_label, exc):
    logger.exception("Impossible d'envoyer l'email de creation a %s: %s", target_label, exc)
