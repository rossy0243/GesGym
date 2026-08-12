"""
Consultation du journal d'activite sensible.

Le journal ne sert a rien s'il faut faire defiler des milliers de lignes pour
retrouver qui a supprime un employe le mois dernier. Ce module concentre le
filtrage et l'export, partages par la page des parametres et le telechargement,
afin que les deux montrent exactement le meme perimetre.
"""

import csv
import io
import json
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date

from organizations.models import SensitiveActivityLog

# Regroupement par module : un gerant cherche « ce qui touche a la paie »,
# pas une action technique precise dont il ignore le nom.
ACTION_GROUPS = (
    ("employee", "Employes et acces", ("employee.", "rh.employee", "settings.")),
    ("member", "Membres", ("member.",)),
    ("money", "Caisse et paiements", ("pos.", "subscription.")),
    ("stock", "Produits et machines", ("products.", "machines.")),
    ("coaching", "Coaching", ("coaching.", "coach_specialty.")),
    ("access", "Controle d'acces", ("access.",)),
    ("notification", "Messages", ("notification.",)),
    ("organization", "Organisation", ("organization.",)),
)

DEFAULT_DAYS = 30
PAGE_SIZE = 50


def _default_period(today=None):
    today = today or timezone.localdate()
    return today - timedelta(days=DEFAULT_DAYS), today


def parse_filters(params, today=None):
    """
    Lit les filtres de l'URL et renvoie des valeurs toujours exploitables.

    Une periode absente ou incoherente ne doit jamais produire une page vide
    sans explication : on retombe sur les trente derniers jours.
    """
    today = today or timezone.localdate()
    default_from, default_to = _default_period(today)

    date_from = parse_date(params.get("log_from") or "") or default_from
    date_to = parse_date(params.get("log_to") or "") or default_to
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    group = params.get("log_group") or ""
    if group not in {key for key, _, _ in ACTION_GROUPS}:
        group = ""

    return {
        "date_from": date_from,
        "date_to": date_to,
        "group": group,
        "actor": (params.get("log_actor") or "").strip(),
        "search": (params.get("log_q") or "").strip(),
    }


def filtered_logs(organization, filters, gym=None):
    """Journal de l'organisation, restreint au perimetre demande."""
    queryset = SensitiveActivityLog.objects.filter(organization=organization)
    if gym is not None:
        queryset = queryset.filter(gym=gym)

    queryset = queryset.filter(
        created_at__date__gte=filters["date_from"],
        created_at__date__lte=filters["date_to"],
    )

    if filters["group"]:
        prefixes = next(
            prefixes for key, _, prefixes in ACTION_GROUPS if key == filters["group"]
        )
        matching = SensitiveActivityLog.objects.none()
        for prefix in prefixes:
            matching = matching | queryset.filter(action__startswith=prefix)
        queryset = matching

    if filters["actor"]:
        queryset = queryset.filter(actor__username__icontains=filters["actor"])

    if filters["search"]:
        term = filters["search"]
        queryset = queryset.filter(target_label__icontains=term) | queryset.filter(
            action__icontains=term
        )

    return queryset.select_related("actor", "gym").order_by("-created_at").distinct()


def group_choices():
    return [(key, label) for key, label, _ in ACTION_GROUPS]


def export_filename(organization, filters):
    slug = (organization.slug or "organisation").replace("/", "-")
    return (
        f"journal-sensible-{slug}-"
        f"{filters['date_from']:%Y%m%d}-{filters['date_to']:%Y%m%d}.csv"
    )


def build_csv(logs):
    """
    Export CSV du journal.

    Separateur point-virgule et BOM UTF-8 : c'est ce qu'attend Excel en
    configuration francaise, sans quoi les accents et les colonnes se
    melangent a l'ouverture.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        ["Date", "Heure", "Action", "Type de cible", "Cible", "Salle", "Acteur", "Details"]
    )

    for entry in logs:
        moment = timezone.localtime(entry.created_at)
        details = entry.metadata or {}
        lisible = "; ".join(
            f"{cle}={valeur}"
            for cle, valeur in details.items()
            if cle not in {"ip", "path"}
        )
        writer.writerow(
            [
                moment.strftime("%d/%m/%Y"),
                moment.strftime("%H:%M:%S"),
                entry.action,
                entry.target_type or "",
                entry.target_label or "",
                entry.gym.name if entry.gym_id else "Organisation",
                entry.actor.username if entry.actor_id else "Systeme",
                lisible,
            ]
        )

    return "﻿".encode("utf-8") + buffer.getvalue().encode("utf-8")
