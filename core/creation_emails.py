import logging
from email.utils import formataddr, parseaddr

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape
from django.utils.text import slugify


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


def _reply_to_for_organization(organization):
    email = (getattr(organization, "email", "") or "").strip()
    if not email:
        return []
    _name, parsed_email = parseaddr(email)
    return [email] if parsed_email else []


def _message_to_html(message):
    paragraphs = []
    current_lines = []
    for line in message.splitlines():
        if line.strip():
            current_lines.append(escape(line))
            continue
        if current_lines:
            paragraphs.append("<br>".join(current_lines))
            current_lines = []
    if current_lines:
        paragraphs.append("<br>".join(current_lines))

    body = "\n".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
    return f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f6f7f9;font-family:Arial,sans-serif;color:#111827;">
    <div style="max-width:640px;margin:0 auto;padding:24px;">
      <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;padding:24px;line-height:1.55;">
        {body}
      </div>
      <p style="font-size:12px;color:#6b7280;margin:16px 4px 0;">
        Email transactionnel envoye suite a une action effectuee dans SmartClub Pro.
      </p>
    </div>
  </body>
</html>"""


def _send_creation_email(
    subject,
    message,
    recipient,
    organization_name="",
    organization=None,
    attachments=None,
):
    recipient = (recipient or "").strip()
    if not recipient:
        return False

    email = EmailMultiAlternatives(
        subject=subject,
        body=message,
        from_email=organization_sender(organization_name),
        to=[recipient],
        reply_to=_reply_to_for_organization(organization),
        headers={
            "Auto-Submitted": "auto-generated",
            "X-Auto-Response-Suppress": "All",
            "X-SmartClub-Email-Type": "account-creation",
        },
    )
    email.attach_alternative(_message_to_html(message), "text/html")
    for filename, content, mimetype in attachments or []:
        email.attach(filename, content, mimetype)
    email.send(fail_silently=False)
    return True


def send_member_creation_email(member, temporary_password="", portal_url=""):
    gym_name = member.gym.name if member.gym_id else "votre salle"
    organization = getattr(member.gym, "organization", None) if member.gym_id else None
    organization_name = organization.name if organization else ""
    username = member.user.username if getattr(member, "user", None) else "genere automatiquement"
    temporary_password = temporary_password or "genere automatiquement"
    card_attachment = []
    try:
        from members.card_images import render_member_card_png

        filename_slug = slugify(f"{member.first_name}-{member.last_name}") or f"membre-{member.id}"
        card_attachment = [
            (
                f"carte_membre_{filename_slug}.png",
                render_member_card_png(member),
                "image/png",
            )
        ]
    except Exception as exc:
        logger.exception("Impossible de generer la carte membre pour %s: %s", member, exc)

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
            "Votre carte membre est jointe a cet email au format PNG.",
        ]
    )
    if portal_url:
        lines.extend(["", f"Espace membre : {portal_url}"])

    return _send_creation_email(
        subject=f"{organization_name or gym_name} - Vos coordonnees membre",
        message="\n".join(lines),
        recipient=member.email,
        organization_name=organization_name,
        organization=organization,
        attachments=card_attachment,
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
        organization=organization,
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
        organization=organization,
    )


def notify_creation_email_failure(target_label, exc):
    logger.exception("Impossible d'envoyer l'email de creation a %s: %s", target_label, exc)
