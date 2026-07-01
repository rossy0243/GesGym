from email.utils import parseaddr

from django.conf import settings
from django.core.checks import Tags, Warning, register


LOCAL_EMAIL_DOMAINS = {"localhost", "local", "test", "example.com", "gesgym.local"}


def _email_domain(value):
    _name, email = parseaddr(value or "")
    if "@" not in email:
        return ""
    return email.rsplit("@", 1)[1].lower()


@register(Tags.security, deploy=True)
def email_deliverability_check(app_configs, **kwargs):
    warnings = []
    from_domain = _email_domain(settings.DEFAULT_FROM_EMAIL)

    if not from_domain:
        warnings.append(
            Warning(
                "DJANGO_DEFAULT_FROM_EMAIL doit etre une adresse email valide.",
                hint="Utilisez une adresse du domaine configure avec SPF, DKIM et DMARC, par exemple noreply@smartclubpro.org.",
                id="core.W001",
            )
        )
    elif from_domain in LOCAL_EMAIL_DOMAINS or from_domain.endswith(".local"):
        warnings.append(
            Warning(
                "DJANGO_DEFAULT_FROM_EMAIL utilise un domaine local ou de test.",
                hint="Pour limiter le spam en production, utilisez un domaine verifie avec SPF, DKIM et DMARC.",
                id="core.W002",
            )
        )

    smtp_backend = "django.core.mail.backends.smtp.EmailBackend"
    if not settings.DEBUG and settings.EMAIL_BACKEND == smtp_backend and not settings.EMAIL_HOST_USER:
        warnings.append(
            Warning(
                "EMAIL_HOST_USER n'est pas configure pour le backend SMTP.",
                hint="Configurez un compte SMTP authentifie et aligne avec le domaine de DJANGO_DEFAULT_FROM_EMAIL.",
                id="core.W003",
            )
        )

    return warnings
