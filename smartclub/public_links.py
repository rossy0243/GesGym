"""
Construction des URL destinees a l'exterieur : liens partages avec des
prospects, adresses inserees dans les e-mails.

Ces liens ne doivent jamais dependre de l'adresse par laquelle un membre du
personnel consulte l'application. Un gerant qui travaille sur
http://127.0.0.1:8000 copierait sinon un lien inutilisable pour son prospect,
et les e-mails partiraient avec la meme adresse locale.

Ordre de resolution du domaine :
  1. DJANGO_PUBLIC_BASE_URL, s'il est defini (le plus explicite) ;
  2. DJANGO_CANONICAL_HOST, deja utilise pour la redirection canonique ;
  3. a defaut, l'adresse de la requete courante (comportement historique).
"""

from urllib.parse import urlparse

from django.conf import settings

# Hotes qui n'ont aucun sens dans un lien envoye a l'exterieur.
LOCAL_HOSTNAMES = frozenset({
    "127.0.0.1",
    "localhost",
    "0.0.0.0",
    "::1",
    "testserver",
})


def public_base_url(request=None):
    """Racine des URL publiques, sans barre oblique finale."""
    configured = (getattr(settings, "PUBLIC_BASE_URL", "") or "").strip()
    if configured:
        return configured.rstrip("/")

    canonical_host = (getattr(settings, "CANONICAL_HOST", "") or "").strip()
    if canonical_host:
        scheme = "http" if settings.DEBUG else "https"
        return f"{scheme}://{canonical_host}"

    if request is not None:
        return request.build_absolute_uri("/").rstrip("/")

    return ""


def build_public_url(request, path):
    """URL absolue publique pour un chemin deja resolu par ``reverse``."""
    base = public_base_url(request)
    if not base:
        return path
    return f"{base}{path}"


def is_local_url(url):
    """Signale un lien qui ne fonctionnera que sur la machine du serveur."""
    hostname = (urlparse(url).hostname or "").strip("[]").lower()
    return hostname in LOCAL_HOSTNAMES
