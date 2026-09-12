from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.shortcuts import get_object_or_404, redirect, render
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.db.models import Q, Count, Sum, Exists, OuterRef
from django.db.models.functions import ExtractHour, ExtractMonth, TruncDate
from django.utils.timezone import localtime, now
from datetime import timedelta
import calendar
import json
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
from access.models import AccessLog
from smartclub.decorators import role_required
from core import marketing_qr
from core import purge
from core.audit import log_sensitive_action
from members.models import MemberPreRegistrationLink
from smartclub.public_links import build_public_url, public_base_url
from compte.models import UserGymRole
from compte.models import User
from compte.utils import generate_temporary_password, generate_username, has_other_active_access
from coaching.models import CoachSpecialty
from organizations.models import SensitiveActivityLog
from . import activity_log
from .audit import log_sensitive_action
from machines.alerts import maintenance_alert_summary

from .forms import (
    CoachSpecialtyForm,
    GymContactForm,
    GymMaintenanceSettingsForm,
    InternalEmployeeForm,
    InternalEmployeeProfileForm,
    OrganizationSettingsForm,
)
from members.models import Member
from organizations.models import Gym, GymModule, LandingFaq
from pos.models import CashRegister, Payment

# Un abonnement compte ce que ses paiements ont rapporte. Les retours de
# decaissement et les apports remplissent le tiroir sans rien rapporter : ils
# n'ont rien a faire dans le revenu d'une formule.
RECETTE = Q(
    payments__status="success",
    payments__type="in",
) & ~Q(payments__category__in=Payment.CATEGORIES_HORS_RECETTE)
from pos.validation import CONTRESIGNATURE
from subscriptions.models import MemberSubscription
from .accounting_reports import (
    accounting_filename,
    build_accounting_report,
    build_csv_export,
    build_custom_csv_export,
    build_custom_report,
    build_custom_xlsx_export,
    build_xlsx_export,
    get_report_period,
    get_report_section,
)
from smartclub.access_control import (
    MEMBER_ROLES,
    POS_HISTORY_ROLES,
    SUBSCRIPTION_ROLES,
    EMPLOYEE_ROLES_BY_MANAGER,
    EMPLOYEE_ROLES_BY_OWNER,
    DASHBOARD_SALES_ROLES,
    SETTINGS_GYM_CONTACT_ROLES,
    SETTINGS_LANDING_ROLES,
    DASHBOARD_ROLES,
    REPORT_ROLES,
    SETTINGS_ORGANIZATION_ROLES,
    PRE_REGISTRATION_LINK_ROLES,
    SETTINGS_ROLES,
    current_role,
    has_role,
    role_home_route,
)


PERIOD_LABELS = {
    "day": "Jour",
    "week": "Semaine",
    "month": "Mois",
    "year": "Année",
}

MONTH_LABELS = ["", "Jan", "Fev", "Mar", "Avr", "Mai", "Juin", "Juil", "Aout", "Sep", "Oct", "Nov", "Dec"]


def _to_json(value):
    return json.dumps(value, ensure_ascii=False)


def _chart_number(value):
    if value is None:
        return 0
    return float(value)


def _build_revenue_rows(payments_qs, period_data):
    period_key = period_data["key"]
    rows = []

    if period_key == "day":
        totals_by_slot = {}
        for hour, amount in payments_qs.values_list("created_at__hour", "amount_cdf"):
            slot_start = (hour // 4) * 4
            totals_by_slot[slot_start] = totals_by_slot.get(slot_start, 0) + _chart_number(amount)

        for slot_start in range(0, 24, 4):
            slot_end = slot_start + 3
            rows.append({
                "label": f"{slot_start:02d}h-{slot_end:02d}h",
                "total": totals_by_slot.get(slot_start, 0),
            })

    elif period_key == "week":
        totals_by_day = {
            item["day"]: _chart_number(item["total"])
            for item in payments_qs.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(total=Sum("amount_cdf"))
        }
        weekdays = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        for index in range(7):
            current_day = period_data["start_date"] + timedelta(days=index)
            rows.append({"label": weekdays[index], "total": totals_by_day.get(current_day, 0)})

    elif period_key == "month":
        totals_by_day = {
            item["day"]: _chart_number(item["total"])
            for item in payments_qs.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(total=Sum("amount_cdf"))
        }
        week_start = period_data["start_date"]
        week_index = 1
        while week_start <= period_data["end_date"]:
            week_end = min(week_start + timedelta(days=6), period_data["end_date"])
            total = 0
            current_day = week_start
            while current_day <= week_end:
                total += totals_by_day.get(current_day, 0)
                current_day += timedelta(days=1)
            rows.append({"label": f"Semaine {week_index}", "total": total})
            week_start = week_end + timedelta(days=1)
            week_index += 1

    else:
        totals_by_month = {
            item["month"]: _chart_number(item["total"])
            for item in payments_qs.annotate(month=ExtractMonth("created_at"))
            .values("month")
            .annotate(total=Sum("amount_cdf"))
        }
        for month_number in range(1, 13):
            rows.append({
                "label": MONTH_LABELS[month_number],
                "total": totals_by_month.get(month_number, 0),
            })

    return rows


def _build_dashboard_chart_data(
    *,
    revenue_rows,
    attendance_rows,
    status_chart_labels,
    status_chart_values,
    plan_labels,
    plan_values,
    expiry_1_day,
    expiry_3_days,
    expiry_7_days,
    expiry_soon,
    visits_period,
    denied_period,
):
    return {
        "revenue": {
            "labels": [row["label"] for row in revenue_rows],
            "values": [_chart_number(row["total"]) for row in revenue_rows],
        },
        "attendance": {
            "labels": [row["label"] for row in attendance_rows],
            "values": [int(row["count"]) for row in attendance_rows],
        },
        "member_status": {
            "labels": status_chart_labels,
            "values": [int(value) for value in status_chart_values],
        },
        "plans": {
            "labels": plan_labels,
            "values": [int(value) for value in plan_values],
        },
        "expirations": {
            "labels": ["J-1", "J-3", "J-7", "J-15"],
            "values": [expiry_1_day, expiry_3_days, expiry_7_days, expiry_soon],
        },
        "access": {
            "labels": ["Autorises", "Refuses"],
            "values": [visits_period, denied_period],
        },
    }


def _build_report_chart_data(accounting_report):
    category_rows = accounting_report.get("category_summary", [])
    method_rows = accounting_report.get("method_summary", [])

    return {
        "categories": {
            "labels": [row["label"] for row in category_rows],
            "entries": [_chart_number(row.get("entries_cdf")) for row in category_rows],
            "exits": [_chart_number(row.get("exits_cdf")) for row in category_rows],
        },
        "methods": {
            "labels": [row["label"] for row in method_rows],
            "entries": [_chart_number(row.get("entries_cdf")) for row in method_rows],
            "exits": [_chart_number(row.get("exits_cdf")) for row in method_rows],
        },
        "totals": {
            "entries": _chart_number(accounting_report.get("total_entries_cdf")),
            "exits": _chart_number(accounting_report.get("total_exits_cdf")),
            "net": _chart_number(accounting_report.get("net_total_cdf")),
            "transactions": int(accounting_report.get("transaction_count") or 0),
        },
    }


def _personnes_distinctes(passages):
    """
    Combien de personnes differentes derriere ces passages.

    Un passage d'invite n'a pas de membre, une ouverture manuelle n'a ni l'un
    ni l'autre. Compter ``member_id`` sans les ecarter rangeait toutes ces
    lignes sous un meme visiteur nul : dix ouvertures manuelles comptaient
    pour une personne.
    """
    membres = (
        passages.filter(member__isnull=False)
        .values("member_id")
        .distinct()
        .count()
    )
    invites = (
        passages.filter(guest_pass__isnull=False)
        .values("guest_pass_id")
        .distinct()
        .count()
    )
    return membres + invites


# Assez de motifs pour expliquer l'essentiel d'une journee, assez peu pour
# tenir sur une ligne sous le total.
MOTIFS_AFFICHES = 4


def _tableau_de_caisse(gym, today):
    """
    L'etat de la caisse aujourd'hui, salle d'abord puis caissier par caissier.

    Le systeme autorise une session ouverte **par utilisateur** : trois
    caissiers font trois caisses simultanees. "Le caissier connecte" n'existe
    donc pas au singulier, et un total de salle sans le detail ne dirait pas
    qui tient quoi.

    Une session ouverte hier et jamais clôturee compte parmi celles du jour :
    c'est precisement l'anomalie qu'il faut voir en haut de l'ecran, pas une
    ligne a exclure parce que sa date d'ouverture est passee.
    """
    sessions = list(
        CashRegister.objects.filter(gym=gym)
        .filter(Q(is_closed=False) | Q(closed_at__date=today))
        .select_related("opened_by", "closed_by")
        .order_by("-opened_at")
    )

    zero = Decimal("0.00")
    if not sessions:
        return {
            "sessions": [],
            "ouvertes": 0,
            "a_contre_signer": 0,
            "retours": zero,
            "apports": zero,
            "motifs": [],
            "autres_sorties": 0,
            "encaissements": zero,
            "decaissements": zero,
            "solde_theorique": zero,
            "ecart": zero,
            "a_un_ecart": False,
            "oubliee_depuis_hier": 0,
            "par_methode": [],
        }

    # Une seule requete pour toutes les ventilations : appeler expected_total()
    # session par session en aurait declenche deux par caisse.
    ventilation = {}
    lignes = (
        Payment.objects.filter(cash_register__in=sessions, gym=gym, status="success")
        .values("cash_register_id", "type", "method", "category")
        .annotate(total=Sum("amount_cdf"))
    )
    for ligne in lignes:
        ventilation.setdefault(ligne["cash_register_id"], {})[
            (ligne["type"], ligne["method"], ligne["category"])
        ] = ligne["total"] or zero

    def _somme(session_id, sens, methode=None, categories=None, hors=None):
        """
        Les mouvements d'une session, filtres par sens, methode et nature.

        ``hors`` sert au chiffre encaisse : les retours de decaissement et les
        apports remplissent bien le tiroir, mais la salle ne les a pas gagnes.
        """
        mouvements = ventilation.get(session_id, {})
        return sum(
            (
                total
                for (type_, method, categorie), total in mouvements.items()
                if type_ == sens
                and (methode is None or method == methode)
                and (categories is None or categorie in categories)
                and (hors is None or categorie not in hors)
            ),
            zero,
        )

    # "Decaissements : total et motifs" - un total sans motif ne dit pas ou
    # l'argent est parti, et c'est precisement la question qu'on se pose en
    # lisant le chiffre. On montre les plus grosses sorties, celles qui
    # expliquent l'essentiel du total.
    sorties = Payment.objects.filter(
        cash_register__in=sessions, gym=gym
    ).sorties().prefetch_related("refunds")
    motifs = [
        {
            "motif": (sortie.description or "").strip() or "Sans motif",
            # Le net : une sortie de 50 000 dont 20 000 sont revenus n'a coute
            # que 30 000, et c'est ce chiffre qu'on veut lire.
            "montant": sortie.montant_net,
            "rendu": sortie.montant_rendu,
        }
        for sortie in sorties.order_by("-amount_cdf")[:MOTIFS_AFFICHES]
    ]
    autres_sorties = max(sorties.count() - MOTIFS_AFFICHES, 0)

    libelles = dict(Payment.PAYMENT_METHODS)
    totaux_methode = {code: zero for code in libelles}
    encaissements = decaissements = solde_theorique = ecart = zero
    total_retours = total_apports = zero
    oubliee_depuis_hier = 0
    a_contre_signer = 0
    rangs = []

    hors_recette = Payment.CATEGORIES_HORS_RECETTE

    for session in sessions:
        # Encaisse : ce que la salle a gagne. Les retours et les apports sont
        # comptes a part - les melanger ici ferait passer de l'argent rendu
        # pour une recette.
        entrees = _somme(session.id, "in", hors=hors_recette)
        retours = _somme(session.id, "in", categories={"expense_refund"})
        apports = _somme(session.id, "in", categories={"cash_injection"})
        # Depense reellement : une sortie de 50 000 dont 20 000 sont revenus a
        # coute 30 000.
        sorties = _somme(session.id, "out") - retours
        especes_entrees = _somme(session.id, "in", CashRegister.CASH_METHOD)
        especes_sorties = _somme(session.id, "out", CashRegister.CASH_METHOD)
        # Seules les especes transitent par le tiroir : c'est deja la regle de
        # expected_total(), et la refaire ici garde le meme sens.
        attendu = session.opening_amount + especes_entrees - especes_sorties

        for code in libelles:
            totaux_methode[code] += _somme(
                session.id, "in", code, hors=hors_recette
            )

        encaissements += entrees
        decaissements += sorties
        total_retours += retours
        total_apports += apports
        solde_theorique += attendu
        if session.is_closed and session.difference is not None:
            ecart += session.difference
        if not session.is_closed and session.opened_at.date() < today:
            oubliee_depuis_hier += 1
        if session.validation_regime == CONTRESIGNATURE and not session.is_validated:
            a_contre_signer += 1

        rangs.append({
            "id": session.id,
            "code": session.session_code or f"Caisse {session.id}",
            "responsable": _nom_utilisateur(session.opened_by),
            "ouverte_a": session.opened_at,
            "fonds_ouverture": session.opening_amount,
            "encaissements": entrees,
            "decaissements": sorties,
            "solde_theorique": attendu,
            "solde_compte": session.closing_amount,
            # Un booleen plutot qu'un test "is not None" dans le gabarit : un
            # montant compte a zero est une information, pas une absence.
            "est_compte": session.closing_amount is not None,
            "ecart": session.difference,
            "ecart_connu": session.difference is not None,
            "est_fermee": session.is_closed,
            "fermee_a": session.closed_at,
            "fermee_par": _nom_utilisateur(session.closed_by),
            # Une caisse fermee par quelqu'un d'autre que son titulaire n'est
            # pas anormale - un gerant debloque un poste abandonne - mais elle
            # doit se voir.
            "cloture_forcee": session.was_force_closed,
            "est_validee": session.is_validated,
            "validee_par": _nom_utilisateur(session.validated_by) if session.is_validated else "",
            "oubliee": not session.is_closed and session.opened_at.date() < today,
            "tresorerie_negative": attendu < 0,
        })

    return {
        "sessions": rangs,
        "ouvertes": sum(1 for rang in rangs if not rang["est_fermee"]),
        "encaissements": encaissements,
        "decaissements": decaissements,
        "retours": total_retours,
        "apports": total_apports,
        "solde_theorique": solde_theorique,
        "ecart": ecart,
        "a_un_ecart": ecart != zero,
        "oubliee_depuis_hier": oubliee_depuis_hier,
        "a_contre_signer": a_contre_signer,
        "motifs": motifs,
        "autres_sorties": autres_sorties,
        "par_methode": [
            {"code": code, "label": libelle, "total": totaux_methode[code]}
            for code, libelle in libelles.items()
            if totaux_methode[code]
        ],
    }


def _nom_utilisateur(utilisateur):
    if not utilisateur:
        return "Compte supprime"
    return utilisateur.get_full_name() or utilisateur.username



def _refus_repetes(gym, today, seuil=3):
    """
    Les personnes a qui la porte s'est fermee plusieurs fois aujourd'hui.

    Un refus isole n'est pas une anomalie : un abonnement echu se presente, la
    porte reste fermee, le dispositif fonctionne. Trois refus sur la meme
    personne dans la journee racontent autre chose - un abonnement expire que
    personne ne lui a signale, ou quelqu'un qui insiste.

    Compter les refus du jour et crier au-dela d'un seuil aurait sonne tous
    les soirs dans une salle frequentee, et jamais dans une salle calme. Ce
    qui se repete est anormal partout.
    """
    lignes = (
        AccessLog.objects.filter(
            gym=gym,
            check_in_time__date=today,
            access_granted=False,
            member__isnull=False,
        )
        .values("member_id", "member__first_name", "member__last_name")
        .annotate(tentatives=Count("id"))
        .filter(tentatives__gte=seuil)
        .order_by("-tentatives")
    )
    return [
        {
            "member_id": ligne["member_id"],
            "nom": (
                f'{ligne["member__first_name"]} {ligne["member__last_name"]}'.strip()
                or "Membre sans nom"
            ),
            "tentatives": ligne["tentatives"],
        }
        for ligne in lignes
    ]


def _alertes_urgentes(caisse, refus_repetes, expirations_48h, machines_hs,
                      stock_epuise, stock_bas):
    """
    Ce qui demande un geste aujourd'hui, et rien d'autre.

    Une alerte qui sonne tous les jours ne se lit plus. Les echeances a sept
    jours restent donc dans le bloc Membres : seules les 48 heures arrivent
    ici, parce que c'est la que le coup de telephone change encore quelque
    chose.

    Le ton dit l'urgence, pas la couleur : "urgent" appelle un geste
    aujourd'hui, "attention" demande a etre surveille. La feuille de style
    decide de la teinte, et elle seule.
    """
    alertes = []

    if caisse["oubliee_depuis_hier"]:
        alertes.append({
            "ton": "urgent",
            "titre": f'{caisse["oubliee_depuis_hier"]} caisse non clôturee',
            "detail": "Ouverte la veille : son solde theorique court toujours.",
            "url": reverse("pos:register_history"),
        })

    if caisse["a_un_ecart"]:
        alertes.append({
            "ton": "urgent",
            "titre": "Ecart de caisse",
            "detail": "Le montant compte ne correspond pas au solde theorique.",
            "url": reverse("pos:register_history"),
        })

    if caisse["a_contre_signer"]:
        # Une clôture que personne d'autre n'a regardee n'est pas encore un
        # controle : elle attend une seconde signature. Celles d'un gerant
        # remontent au proprietaire par son bandeau, pas ici : les compter
        # deux fois lui ferait chercher un geste deja demande ailleurs.
        alertes.append({
            "ton": "attention",
            "titre": f'{caisse["a_contre_signer"]} clôture a contre-signer',
            "detail": "Le tiroir a ete compte, mais personne d'autre ne l'a verifie.",
            "url": reverse("pos:register_history"),
        })

    for personne in refus_repetes:
        alertes.append({
            "ton": "attention",
            "titre": f'{personne["nom"]} refuse {personne["tentatives"]} fois',
            "detail": "Abonnement echu, ou quelqu'un qui insiste.",
            "url": reverse("access:acces_dashboard"),
        })

    if expirations_48h:
        alertes.append({
            "ton": "attention",
            "titre": f"{expirations_48h} abonnement(s) a echeance sous 48 h",
            "detail": "Passe ce delai, le membre trouvera porte close.",
            "url": f'{reverse("members:member_list")}?status=expiring&expiring_days=2',
        })

    if machines_hs:
        alertes.append({
            "ton": "attention",
            "titre": f"{machines_hs} machine(s) en panne",
            "detail": "Le parc rend moins que ce que les membres attendent.",
            "url": reverse("machines:list"),
        })

    if stock_epuise:
        alertes.append({
            "ton": "urgent",
            "titre": f"{stock_epuise} produit(s) en rupture",
            "detail": "Plus rien a vendre au comptoir.",
            "url": reverse("products:list"),
        })
    elif stock_bas:
        alertes.append({
            "ton": "attention",
            "titre": f"{stock_bas} produit(s) sous le seuil",
            "detail": "A reapprovisionner avant la rupture.",
            "url": reverse("products:list"),
        })

    return alertes


def _get_period_window(period_key, reference_date):
    period_key = period_key if period_key in PERIOD_LABELS else "month"

    if period_key == "day":
        start_date = end_date = reference_date
    elif period_key == "week":
        start_date = reference_date - timedelta(days=reference_date.weekday())
        end_date = start_date + timedelta(days=6)
    elif period_key == "year":
        start_date = reference_date.replace(month=1, day=1)
        end_date = reference_date.replace(month=12, day=31)
    else:
        start_date = reference_date.replace(day=1)
        if start_date.month == 12:
            next_month = start_date.replace(year=start_date.year + 1, month=1, day=1)
        else:
            next_month = start_date.replace(month=start_date.month + 1, day=1)
        end_date = next_month - timedelta(days=1)

    period_days = (end_date - start_date).days + 1
    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end - timedelta(days=period_days - 1)

    return {
        "key": period_key,
        "label": PERIOD_LABELS[period_key],
        "start_date": start_date,
        "end_date": end_date,
        "previous_start": previous_start,
        "previous_end": previous_end,
        "days": period_days,
    }


def _format_period_range(start_date, end_date):
    if start_date == end_date:
        return start_date.strftime("%d/%m/%Y")
    return f"{start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}"


def _build_trend(current_value, previous_value):
    delta = current_value - previous_value
    if previous_value:
        percent = round((delta / previous_value) * 100, 1)
    elif current_value:
        percent = 100.0
    else:
        percent = 0.0

    if delta > 0:
        direction = "up"
        badge_class = "success"
        prefix = "+"
    elif delta < 0:
        direction = "down"
        badge_class = "danger"
        prefix = ""
    else:
        direction = "flat"
        badge_class = "secondary"
        prefix = ""

    # Sans base, "+100 %" ne distingue pas un doublement d'un depart de zero :
    # le pourcentage vaut exactement 100 dans les deux cas, parce que 100 est
    # la valeur de repli quand la periode precedente est vide.
    if not previous_value and current_value:
        display = "nouveau"
        basis = "Rien sur la periode precedente"
    else:
        display = f"{prefix}{percent:.1f}%"
        basis = f"Periode precedente : {previous_value}"

    return {
        "delta": delta,
        "percent": percent,
        "current": current_value,
        "previous": previous_value,
        "basis": basis,
        "direction": direction,
        "badge_class": badge_class,
        "display": display,
    }


def _format_hour_range(hour):
    end_hour = (hour + 1) % 24
    return f"{hour:02d}h-{end_hour:02d}h"


def _build_peak_hour(access_logs):
    peak = (
        access_logs.filter(access_granted=True)
        .annotate(hour=ExtractHour("check_in_time"))
        .values("hour")
        .annotate(count=Count("id"))
        .order_by("-count", "hour")
        .first()
    )

    if not peak or peak["hour"] is None:
        return {
            "label": "Aucune donnee",
            "count": 0,
            "has_data": False,
        }

    hour = int(peak["hour"])
    return {
        "label": _format_hour_range(hour),
        "count": peak["count"],
        "has_data": True,
    }


def _build_attendance_rows(gym, period_data):
    access_logs = AccessLog.objects.filter(
        gym=gym,
        access_granted=True,
        check_in_time__date__range=(period_data["start_date"], period_data["end_date"]),
    )
    period_key = period_data["key"]
    rows = []

    if period_key == "day":
        counts_by_slot = {}
        for hour in access_logs.values_list("check_in_time__hour", flat=True):
            slot_start = (hour // 4) * 4
            counts_by_slot[slot_start] = counts_by_slot.get(slot_start, 0) + 1

        for slot_start in range(0, 24, 4):
            slot_end = slot_start + 3
            label = f"{slot_start:02d}h-{slot_end:02d}h"
            rows.append({"label": label, "count": counts_by_slot.get(slot_start, 0)})

    elif period_key == "week":
        counts_by_day = {
            item["day"]: item["count"]
            for item in access_logs.annotate(day=TruncDate("check_in_time"))
            .values("day")
            .annotate(count=Count("id"))
        }
        weekdays = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        for index in range(7):
            current_day = period_data["start_date"] + timedelta(days=index)
            rows.append({"label": weekdays[index], "count": counts_by_day.get(current_day, 0)})

    elif period_key == "month":
        counts_by_day = {
            item["day"]: item["count"]
            for item in access_logs.annotate(day=TruncDate("check_in_time"))
            .values("day")
            .annotate(count=Count("id"))
        }
        week_start = period_data["start_date"]
        week_index = 1
        while week_start <= period_data["end_date"]:
            week_end = min(week_start + timedelta(days=6), period_data["end_date"])
            total = 0
            current_day = week_start
            while current_day <= week_end:
                total += counts_by_day.get(current_day, 0)
                current_day += timedelta(days=1)
            rows.append({"label": f"Semaine {week_index}", "count": total})
            week_start = week_end + timedelta(days=1)
            week_index += 1

    else:
        counts_by_month = {
            item["month"]: item["count"]
            for item in access_logs.annotate(month=ExtractMonth("check_in_time"))
            .values("month")
            .annotate(count=Count("id"))
        }
        for month_number in range(1, 13):
            rows.append({
                "label": calendar.month_abbr[month_number],
                "count": counts_by_month.get(month_number, 0),
            })

    max_count = max((row["count"] for row in rows), default=0)
    for row in rows:
        row["percent"] = round((row["count"] / max_count) * 100, 1) if max_count else 0

    return rows


def _build_member_growth_rows(members_qs, period_data):
    created_members = members_qs.filter(
        created_at__date__range=(period_data["start_date"], period_data["end_date"])
    )
    period_key = period_data["key"]
    rows = []

    if period_key == "day":
        counts_by_slot = {}
        for hour in created_members.values_list("created_at__hour", flat=True):
            slot_start = (hour // 4) * 4
            counts_by_slot[slot_start] = counts_by_slot.get(slot_start, 0) + 1

        for slot_start in range(0, 24, 4):
            slot_end = slot_start + 3
            rows.append({
                "label": f"{slot_start:02d}h-{slot_end:02d}h",
                "count": counts_by_slot.get(slot_start, 0),
            })

    elif period_key == "week":
        counts_by_day = {
            item["day"]: item["count"]
            for item in created_members.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(count=Count("id"))
        }
        weekdays = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        for index in range(7):
            current_day = period_data["start_date"] + timedelta(days=index)
            rows.append({"label": weekdays[index], "count": counts_by_day.get(current_day, 0)})

    elif period_key == "month":
        counts_by_day = {
            item["day"]: item["count"]
            for item in created_members.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(count=Count("id"))
        }
        week_start = period_data["start_date"]
        week_index = 1
        while week_start <= period_data["end_date"]:
            week_end = min(week_start + timedelta(days=6), period_data["end_date"])
            total = 0
            current_day = week_start
            while current_day <= week_end:
                total += counts_by_day.get(current_day, 0)
                current_day += timedelta(days=1)
            rows.append({"label": f"Semaine {week_index}", "count": total})
            week_start = week_end + timedelta(days=1)
            week_index += 1

    else:
        counts_by_month = {
            item["month"]: item["count"]
            for item in created_members.annotate(month=ExtractMonth("created_at"))
            .values("month")
            .annotate(count=Count("id"))
        }
        for month_number in range(1, 13):
            rows.append({
                "label": MONTH_LABELS[month_number],
                "count": counts_by_month.get(month_number, 0),
            })

    return rows


def _should_use_member_portal(user):
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_saas_admin or user.owned_organization_id:
        return False
    try:
        user.member_profile
    except AttributeError:
        return False
    return not UserGymRole.objects.filter(user=user, is_active=True).exists()


@login_required
def dashboard_redirect(request):
    """Redirige vers le bon dashboard apres connexion."""
    if not request.user.is_authenticated:
        return redirect('login')

    if _should_use_member_portal(request.user):
        return redirect("members:member_portal")

    if getattr(request, 'is_owner', False):
        owned_gyms = list(getattr(request, 'owned_gyms', []))
        current_gym_id = request.session.get('current_gym_id')

        if len(owned_gyms) == 1:
            gym = owned_gyms[0]
            request.session['current_gym_id'] = gym.id
            return redirect('core:gym_dashboard', gym_id=gym.id)

        if len(owned_gyms) > 1:
            current_gym = next(
                (gym for gym in owned_gyms if str(gym.id) == str(current_gym_id)),
                None,
            )
            if current_gym:
                return redirect('core:gym_dashboard', gym_id=current_gym.id)
            return redirect('core:select_gym')

        return redirect('core:select_gym')

    if getattr(request, 'gym', None):
        if not has_role(request, DASHBOARD_ROLES):
            return redirect(role_home_route(request))
        return redirect('core:gym_dashboard', gym_id=request.gym.id)

    return redirect('core:select_gym')

@login_required
def select_gym(request):
    """Page de selection d'une salle accessible."""
    if getattr(request, 'is_owner', False):
        gyms = Gym.objects.filter(
            organization=request.organization,
            is_active=True,
        )
    else:
        gyms = Gym.objects.filter(
            user_roles__user=request.user,
            user_roles__is_active=True,
            is_active=True,
            organization__is_active=True,
        )

    gyms = (
        gyms.annotate(
            members_count=Count("members", distinct=True),
            machines_count=Count("machines", distinct=True),
            coaches_count=Count("coaches", distinct=True),
        )
        .select_related("organization")
        .distinct()
        .order_by("name")
    )

    if request.method == 'POST':
        gym_id = request.POST.get('gym_id')
        gym = gyms.filter(id=gym_id).first()
        if request.user.is_superuser and not gym:
            gym = Gym.objects.filter(
                id=gym_id,
                is_active=True,
                organization__is_active=True,
            ).first()
        if gym:
            request.session['current_gym_id'] = gym.id
            request.session.modified = True
            request.gym = gym
            request.organization = gym.organization
            if not has_role(request, DASHBOARD_ROLES):
                return redirect(role_home_route(request))
            return redirect('core:gym_dashboard', gym_id=gym.id)
        messages.error(request, "Acces refuse a cette salle.")
        return redirect('core:select_gym')

    context = {
        'gyms': gyms,
    }
    return render(request, 'core/select_gym.html', context)

@login_required
@require_POST
def switch_gym(request, gym_id):
    """
    Permet a un Owner de changer de salle active.
    Le changement est volontairement limite au POST + CSRF.
    """
    if not getattr(request, 'is_owner', False) or not getattr(request, 'organization', None):
        messages.error(request, "Vous n'avez pas le droit de changer de gym.")
        return redirect('core:dashboard_redirect')

    gym = Gym.objects.filter(
        id=gym_id,
        organization=request.organization,
        is_active=True,
    ).first()
    if not gym:
        messages.error(request, "Acces refuse a ce gym.")
        return redirect('core:select_gym')

    request.session['current_gym_id'] = gym.id
    request.session.modified = True

    messages.success(
        request, 
        f"Vous travaillez maintenant sur : <strong>{gym.name}</strong>",
        extra_tags='safe'
    )

    return redirect('core:gym_dashboard', gym_id=gym.id)


def _settings_allowed(request):
    """
    Qui peut ouvrir la page des parametres.

    Chaque onglet pose ensuite sa propre garde : entrer ici ne donne acces a
    rien en particulier.
    """
    return bool(
        request.user.is_authenticated
        and (
            has_role(request, SETTINGS_ROLES)
            or has_role(request, SETTINGS_GYM_CONTACT_ROLES)
            or has_role(request, SETTINGS_LANDING_ROLES)
        )
        and getattr(request, "organization", None)
    )


def _scoped_identity_change_blocked(user, role):
    return has_other_active_access(user, exclude_role_ids=[role.id])


def _employee_role_values_for_request(request):
    """
    Comptes que l'utilisateur courant peut creer, modifier et voir.

    Cette liste ne sert pas qu'a la liste deroulante : elle filtre aussi la
    liste du personnel et garde les actions de modification. Un role absent
    d'ici est invisible et intouchable, pas seulement impossible a creer.
    """
    if current_role(request) == "owner":
        return list(EMPLOYEE_ROLES_BY_OWNER)
    return list(EMPLOYEE_ROLES_BY_MANAGER)


def _refuse_settings_action(request, action, reason, target="", **metadata):
    """
    Refuse une action de parametrage en la consignant.

    Une tentative d'elever ses propres droits ou de toucher a un compte
    au-dessus de son niveau doit laisser une trace : c'est precisement le
    genre d'evenement qu'on cherche apres coup.
    """
    log_sensitive_action(
        request,
        "settings.action_refused",
        "UserGymRole",
        target or action,
        metadata={"action": action, "reason": reason, **metadata},
    )
    return HttpResponseForbidden(reason)


def _settings_redirect(tab):
    return redirect(f"{reverse('core:settings')}?tab={tab}")


def _handle_landing_faq(request, organization, action):
    """
    Questions frequentes du site public : ajout, correction, retrait.

    Renvoie une redirection quand l'action aboutit, None pour laisser la page
    se reafficher avec le message d'erreur.
    """
    if action == "faq_create":
        question = (request.POST.get("question") or "").strip()
        answer = (request.POST.get("answer") or "").strip()
        if not question or not answer:
            messages.error(request, "Une question frequente demande un intitule et une reponse.")
            return None

        derniere = (
            LandingFaq.objects.filter(organization=organization)
            .order_by("-position")
            .values_list("position", flat=True)
            .first()
        )
        faq = LandingFaq.objects.create(
            organization=organization,
            question=question,
            answer=answer,
            position=(derniere or 0) + 1,
        )
        log_sensitive_action(
            request, "organization.faq_created", "LandingFaq", faq.question,
            metadata={"faq_id": faq.id},
        )
        messages.success(request, "Question ajoutee a la page d'accueil.")
        return _settings_redirect("organization")

    faq = LandingFaq.objects.filter(
        id=request.POST.get("faq_id"), organization=organization
    ).first()
    if faq is None:
        messages.error(request, "Question introuvable.")
        return _settings_redirect("organization")

    if action == "faq_delete":
        intitule = faq.question
        faq.delete()
        log_sensitive_action(
            request, "organization.faq_deleted", "LandingFaq", intitule,
        )
        messages.success(request, "Question retiree.")
        return _settings_redirect("organization")

    if action == "faq_toggle":
        faq.is_active = not faq.is_active
        faq.save(update_fields=["is_active"])
        log_sensitive_action(
            request, "organization.faq_toggled", "LandingFaq", faq.question,
            metadata={"affichee": faq.is_active},
        )
        messages.success(
            request,
            "Question affichee sur le site." if faq.is_active else "Question masquee.",
        )
        return _settings_redirect("organization")

    # faq_update
    question = (request.POST.get("question") or "").strip()
    answer = (request.POST.get("answer") or "").strip()
    if not question or not answer:
        messages.error(request, "Une question frequente demande un intitule et une reponse.")
        return None

    faq.question = question
    faq.answer = answer
    try:
        faq.position = max(0, int(request.POST.get("position") or faq.position))
    except (TypeError, ValueError):
        pass
    faq.save(update_fields=["question", "answer", "position"])
    log_sensitive_action(
        request, "organization.faq_updated", "LandingFaq", faq.question,
        metadata={"faq_id": faq.id},
    )
    messages.success(request, "Question mise a jour.")
    return _settings_redirect("organization")


@login_required
def settings_dashboard(request):
    if not _settings_allowed(request):
        return HttpResponseForbidden("Acces non autorise")

    organization = request.organization
    gym = request.gym
    if not gym:
        return redirect("core:select_gym")

    can_manage_organization = has_role(request, SETTINGS_ORGANIZATION_ROLES)
    can_manage_landing = has_role(request, SETTINGS_LANDING_ROLES)
    can_manage_gym_contact = has_role(request, SETTINGS_GYM_CONTACT_ROLES)
    active_tab = request.GET.get("tab", "organization" if can_manage_organization else "employees")
    if active_tab == "organization" and not can_manage_organization:
        active_tab = "employees"
    employee_credentials = None
    if request.method == "GET":
        employee_credentials = request.session.pop("settings_employee_credentials", None)

    accessible_gyms = (
        organization.gyms.filter(is_active=True).order_by("name")
        if can_manage_organization
        else Gym.objects.filter(id=gym.id, is_active=True)
    )
    allowed_employee_roles = _employee_role_values_for_request(request)
    locked_employee_gym = None if can_manage_organization else gym
    organization_form = OrganizationSettingsForm(
        instance=organization,
        peut_changer_identite=can_manage_organization,
    )
    maintenance_form = GymMaintenanceSettingsForm(instance=gym)
    gym_contact_form = GymContactForm(instance=gym)
    employee_form = InternalEmployeeForm(
        organization=organization,
        gyms=accessible_gyms,
        allowed_roles=allowed_employee_roles,
        locked_gym=locked_employee_gym,
    )
    employee_edit_role = None
    employee_edit_form = None
    specialty_form = CoachSpecialtyForm()

    if request.method == "GET" and active_tab == "employees" and request.GET.get("edit_role"):
        employee_edit_role = get_object_or_404(
            UserGymRole.objects.select_related("user", "gym"),
            id=request.GET.get("edit_role"),
            gym__in=accessible_gyms,
        )
        if employee_edit_role.role == "owner" or employee_edit_role.role not in allowed_employee_roles:
            return _refuse_settings_action(
                request,
                "employee_edit_open",
                "Ce compte a un niveau d'acces superieur au votre : sa fiche ne vous est pas ouverte.",
                target=employee_edit_role.user.username,
                target_role=employee_edit_role.role,
            )
        if _scoped_identity_change_blocked(employee_edit_role.user, employee_edit_role):
            messages.error(
                request,
                "Ce compte est partage avec un autre profil actif. La modification globale est bloquee.",
            )
            return _settings_redirect("employees")
        employee_edit_form = InternalEmployeeProfileForm(
            role_instance=employee_edit_role,
            organization=organization,
            gyms=accessible_gyms,
            allowed_roles=allowed_employee_roles,
            locked_gym=locked_employee_gym,
        )

    if request.method == "POST":
        action = request.POST.get("action", "")

        # Le personnel et les specialites restent au proprietaire et au gerant.
        # La page des parametres est ouverte plus largement depuis l'arrivee du
        # commercial : sans ce garde-fou, il pourrait creer des comptes.
        if action.startswith(("employee_", "specialty_")) and not has_role(
            request, SETTINGS_ROLES
        ):
            return _refuse_settings_action(
                request, action,
                "Vous ne pouvez pas gerer le personnel.",
                target=organization.name,
            )

        if action == "organization":
            # L'identite de l'organisation (nom, logo) reste au proprietaire.
            # La vitrine publique est ouverte au commercial : le formulaire
            # ecarte lui-meme les champs qu'il n'a pas le droit de toucher.
            if not (can_manage_organization or can_manage_landing):
                return _refuse_settings_action(
                    request, "organization", "Vous ne pouvez pas modifier l'organisation.",
                    target=organization.name,
                )
            active_tab = "organization"
            organization_form = OrganizationSettingsForm(
                request.POST,
                request.FILES,
                instance=organization,
                peut_changer_identite=can_manage_organization,
            )
            if organization_form.is_valid():
                modifies = list(organization_form.changed_data)
                organization_form.save()
                log_sensitive_action(
                    request,
                    "organization.updated",
                    "Organization",
                    organization.name,
                    metadata={"champs_modifies": modifies},
                )
                messages.success(request, "Informations de l'organisation mises a jour.")
                return _settings_redirect("organization")

        elif action in {"faq_create", "faq_update", "faq_delete", "faq_toggle"}:
            if not can_manage_landing:
                return _refuse_settings_action(
                    request, action, "Vous ne pouvez pas modifier la page d'accueil.",
                    target=organization.name,
                )
            reponse = _handle_landing_faq(request, organization, action)
            if reponse is not None:
                return reponse
            active_tab = "organization"

        elif action == "gym_contact":
            if not can_manage_gym_contact:
                return _refuse_settings_action(
                    request, "gym_contact",
                    "Vous ne pouvez pas modifier les coordonnees de la salle.",
                    target=gym.name if gym else "",
                )
            active_tab = "salle"
            gym_contact_form = GymContactForm(request.POST, instance=gym)
            if gym_contact_form.is_valid():
                modifies = list(gym_contact_form.changed_data)
                gym_contact_form.save()
                log_sensitive_action(
                    request,
                    "gym.contact_updated",
                    "Gym",
                    gym.name,
                    metadata={"champs_modifies": modifies},
                )
                messages.success(
                    request, "Coordonnees de la salle mises a jour."
                )
                return _settings_redirect("salle")

        elif action == "maintenance":
            # Le rythme d'entretien du parc ne regarde pas le commercial.
            if not has_role(request, SETTINGS_ROLES):
                return _refuse_settings_action(
                    request, "maintenance",
                    "Vous ne pouvez pas modifier l'alerte de maintenance.",
                    target=gym.name if gym else "",
                )
            active_tab = "salle"
            maintenance_form = GymMaintenanceSettingsForm(request.POST, instance=gym)
            if maintenance_form.is_valid():
                avant = Gym.objects.values_list(
                    "maintenance_alert_lead_days", flat=True
                ).get(pk=gym.pk)
                maintenance_form.save()
                log_sensitive_action(
                    request,
                    "gym.maintenance_alert_updated",
                    "Gym",
                    gym.name,
                    metadata={
                        "avant": avant,
                        "apres": maintenance_form.cleaned_data["maintenance_alert_lead_days"],
                    },
                )
                messages.success(request, "Delai de prevenance des maintenances mis a jour.")
                return _settings_redirect("salle")

        elif action == "employee_create":
            active_tab = "employees"
            employee_form = InternalEmployeeForm(
                request.POST,
                organization=organization,
                gyms=accessible_gyms,
                allowed_roles=allowed_employee_roles,
                locked_gym=locked_employee_gym,
            )
            if employee_form.is_valid():
                selected_gym = employee_form.cleaned_data["gym"]
                username = generate_username(
                    employee_form.cleaned_data["first_name"],
                    employee_form.cleaned_data["last_name"],
                )
                temporary_password = generate_temporary_password()
                employee = User.objects.create(
                    username=username,
                    first_name=employee_form.cleaned_data["first_name"],
                    last_name=employee_form.cleaned_data["last_name"],
                    email=employee_form.cleaned_data["email"],
                    password=make_password(temporary_password),
                    force_password_change=True,
                    is_active=employee_form.cleaned_data["is_active"],
                    is_staff=False,
                )
                role = UserGymRole.objects.create(
                    user=employee,
                    gym=selected_gym,
                    role=employee_form.cleaned_data["role"],
                    is_active=employee_form.cleaned_data["is_active"],
                )
                log_sensitive_action(
                    request,
                    "employee.created",
                    "UserGymRole",
                    f"{employee.username} - {role.get_role_display()} ({selected_gym.name})",
                    metadata={"role": role.role, "employee_id": employee.id},
                    gym=selected_gym,
                )
                messages.success(
                    request,
                    f"Employe cree : {username}. Mot de passe temporaire : {temporary_password}. "
                    "Changement obligatoire a la premiere connexion.",
                )
                request.session["settings_employee_credentials"] = {
                    "title": "Identifiants du nouvel employe",
                    "username": username,
                    "password": temporary_password,
                }
                return _settings_redirect("employees")

        elif action == "employee_update":
            active_tab = "employees"
            role = get_object_or_404(
                UserGymRole.objects.select_related("user", "gym"),
                id=request.POST.get("role_id"),
                gym__in=accessible_gyms,
            )
            if role.role == "owner":
                return _refuse_settings_action(
                    request, action, "Le compte proprietaire ne se modifie pas depuis les parametres.",
                    target=role.user.username,
                )
            if role.role not in allowed_employee_roles:
                return _refuse_settings_action(
                    request, action,
                    "Ce compte a un niveau d'acces superieur au votre : vous ne pouvez pas le modifier.",
                    target=role.user.username, target_role=role.role,
                )
            if _scoped_identity_change_blocked(role.user, role):
                messages.error(
                    request,
                    "Ce compte est partage avec un autre profil actif. La modification globale est bloquee.",
                )
                return _settings_redirect("employees")

            employee_edit_role = role
            employee_edit_form = InternalEmployeeProfileForm(
                request.POST,
                role_instance=role,
                organization=organization,
                gyms=accessible_gyms,
                allowed_roles=allowed_employee_roles,
                locked_gym=locked_employee_gym,
            )
            if employee_edit_form.is_valid():
                selected_gym = employee_edit_form.cleaned_data["gym"]
                role_label_before = f"{role.user.username} - {role.get_role_display()} ({role.gym.name})"
                role.gym = selected_gym
                role.role = employee_edit_form.cleaned_data["role"]
                role.is_active = employee_edit_form.cleaned_data["is_active"]
                role.save(update_fields=["gym", "role", "is_active"])

                role.user.first_name = employee_edit_form.cleaned_data["first_name"]
                role.user.last_name = employee_edit_form.cleaned_data["last_name"]
                role.user.email = employee_edit_form.cleaned_data["email"]
                if role.is_active:
                    role.user.is_active = True
                elif not has_other_active_access(role.user, exclude_role_ids=[role.id]):
                    role.user.is_active = False
                role.user.save(update_fields=["first_name", "last_name", "email", "is_active"])

                log_sensitive_action(
                    request,
                    "employee.updated",
                    "UserGymRole",
                    role_label_before,
                    metadata={"role": role.role, "employee_id": role.user_id},
                    gym=role.gym,
                )
                messages.success(request, f"Profil employe mis a jour : {role.user.username}.")
                return _settings_redirect("employees")

        elif action in ["employee_activate", "employee_deactivate", "employee_reset_password"]:
            active_tab = "employees"
            role = get_object_or_404(
                UserGymRole.objects.select_related("user", "gym"),
                id=request.POST.get("role_id"),
                gym__in=accessible_gyms,
            )
            if role.role == "owner":
                return _refuse_settings_action(
                    request, action, "Le compte proprietaire ne se modifie pas depuis les parametres.",
                    target=role.user.username,
                )
            if role.role not in allowed_employee_roles:
                return _refuse_settings_action(
                    request, action,
                    "Ce compte a un niveau d'acces superieur au votre : vous ne pouvez pas le modifier.",
                    target=role.user.username, target_role=role.role,
                )

            if action == "employee_reset_password":
                if _scoped_identity_change_blocked(role.user, role):
                    messages.error(
                        request,
                        "Ce compte est partage avec un autre acces actif. Utilisez une reinitialisation globale supervisee.",
                    )
                    return _settings_redirect("employees")
                temporary_password = generate_temporary_password()
                role.user.password = make_password(temporary_password)
                role.user.force_password_change = True
                role.user.save(update_fields=["password", "force_password_change"])
                log_sensitive_action(
                    request,
                    "employee.password_reset",
                    "User",
                    role.user.username,
                    metadata={"employee_id": role.user_id},
                    gym=role.gym,
                )
                messages.success(
                    request,
                    f"Mot de passe reinitialise pour {role.user.username} : {temporary_password}. "
                    "Changement obligatoire a la premiere connexion.",
                )
                request.session["settings_employee_credentials"] = {
                    "title": "Nouveau mot de passe temporaire",
                    "username": role.user.username,
                    "password": temporary_password,
                }
                return _settings_redirect("employees")

            if role.user_id == request.user.id:
                messages.error(request, "Vous ne pouvez pas vous desactiver vous-meme.")
                return _settings_redirect("employees")

            should_activate = action == "employee_activate"
            role.is_active = should_activate
            role.save(update_fields=["is_active"])
            if should_activate:
                if not role.user.is_active:
                    role.user.is_active = True
                    role.user.save(update_fields=["is_active"])
            elif not has_other_active_access(role.user, exclude_role_ids=[role.id]):
                role.user.is_active = False
                role.user.save(update_fields=["is_active"])
            log_sensitive_action(
                request,
                "employee.activated" if should_activate else "employee.deactivated",
                "UserGymRole",
                role.user.username,
                metadata={"employee_id": role.user_id, "role": role.role},
                gym=role.gym,
            )
            status_label = "active" if should_activate else "desactive"
            messages.success(request, f"Employe {role.user.username} {status_label}.")
            return _settings_redirect("employees")

        elif action == "employee_delete":
            active_tab = "employees"
            role = get_object_or_404(
                UserGymRole.objects.select_related("user", "gym"),
                id=request.POST.get("role_id"),
                gym__in=accessible_gyms,
            )
            if role.role == "owner":
                return _refuse_settings_action(
                    request, action, "Le compte proprietaire ne se supprime pas depuis les parametres.",
                    target=role.user.username,
                )
            if role.role not in allowed_employee_roles:
                return _refuse_settings_action(
                    request, action,
                    "Ce compte a un niveau d'acces superieur au votre : vous ne pouvez pas le modifier.",
                    target=role.user.username, target_role=role.role,
                )
            if role.user_id == request.user.id:
                messages.error(request, "Vous ne pouvez pas supprimer votre propre profil d'acces.")
                return _settings_redirect("employees")

            user = role.user
            gym_for_log = role.gym
            target_label = f"{user.username} - {role.get_role_display()} ({role.gym.name})"
            should_deactivate_user = not has_other_active_access(user, exclude_role_ids=[role.id])
            role.delete()
            if should_deactivate_user:
                user.is_active = False
                user.save(update_fields=["is_active"])

            log_sensitive_action(
                request,
                "employee.deleted",
                "UserGymRole",
                target_label,
                metadata={"employee_id": user.id},
                gym=gym_for_log,
            )
            messages.success(request, f"Profil employe supprime : {user.username}.")
            return _settings_redirect("employees")

        elif action == "specialty_create":
            active_tab = "specialties"
            specialty_form = CoachSpecialtyForm(request.POST)
            if specialty_form.is_valid():
                name = specialty_form.cleaned_data["name"].strip()
                specialty, created = CoachSpecialty.objects.get_or_create(
                    gym=gym,
                    name=name,
                    defaults={"is_active": True},
                )
                if not created and not specialty.is_active:
                    specialty.is_active = True
                    specialty.save(update_fields=["is_active"])
                log_sensitive_action(
                    request,
                    "coach_specialty.created" if created else "coach_specialty.reactivated",
                    "CoachSpecialty",
                    specialty.name,
                    gym=gym,
                )
                messages.success(request, f"Specialite coach enregistree : {specialty.name}")
                return _settings_redirect("specialties")

        elif action in ["specialty_activate", "specialty_deactivate"]:
            active_tab = "specialties"
            specialty = get_object_or_404(CoachSpecialty, id=request.POST.get("specialty_id"), gym=gym)
            specialty.is_active = action == "specialty_activate"
            specialty.save(update_fields=["is_active"])
            log_sensitive_action(
                request,
                "coach_specialty.activated" if specialty.is_active else "coach_specialty.deactivated",
                "CoachSpecialty",
                specialty.name,
                gym=gym,
            )
            messages.success(request, f"Specialite {specialty.name} mise a jour.")
            return _settings_redirect("specialties")

    employee_roles = (
        UserGymRole.objects.filter(gym__in=accessible_gyms)
        .exclude(role="owner")
        .filter(role__in=allowed_employee_roles)
        .select_related("user", "gym")
        .order_by("gym__name", "user__first_name", "user__last_name")
    )
    specialties = CoachSpecialty.objects.filter(gym=gym).order_by("name")
    log_filters = activity_log.parse_filters(request.GET)
    activity_logs_qs = activity_log.filtered_logs(
        organization,
        log_filters,
        gym=None if can_manage_organization else gym,
    )
    activity_paginator = Paginator(activity_logs_qs, activity_log.PAGE_SIZE)
    activity_page = activity_paginator.get_page(request.GET.get("log_page"))

    context = {
        "organization": organization,
        "gym": gym,
        "organization_form": organization_form,
        "maintenance_form": maintenance_form,
        "gym_contact_form": gym_contact_form,
        "can_manage_landing": can_manage_landing,
        "can_manage_gym_contact": can_manage_gym_contact,
        "can_manage_settings": has_role(request, SETTINGS_ROLES),
        # Les quatre champs image se rendent en boucle : les nommer un par un
        # dans le gabarit multipliait le meme bloc de balisage.
        "organization_images": [
            organization_form[nom]
            for nom in (
                "landing_hero_image",
                "landing_image_1",
                "landing_image_2",
                "landing_image_3",
            )
        ],
        "landing_faqs": LandingFaq.objects.filter(organization=organization),
        "maintenance_alerts": maintenance_alert_summary(gym),
        "employee_form": employee_form,
        "employee_edit_form": employee_edit_form,
        "employee_edit_role": employee_edit_role,
        "employee_credentials": employee_credentials,
        "specialty_form": specialty_form,
        "employee_roles": employee_roles,
        "specialties": specialties,
        "activity_logs": activity_page,
        "activity_page": activity_page,
        "activity_total": activity_paginator.count,
        "log_filters": log_filters,
        "log_group_choices": activity_log.group_choices(),
        "log_query_string": request.GET.urlencode(),
        "active_tab": active_tab,
        "can_manage_organization": can_manage_organization,
        "allowed_employee_roles": allowed_employee_roles,
        "nav_active": "parametres",
    }
    return render(request, "core/settings.html", context)



@login_required
def activity_log_export(request):
    """
    Telecharge le journal filtre au format CSV.

    Reprend exactement les filtres de la page : ce qu'on exporte est ce qu'on
    voit, sans quoi un controle sur piece serait impossible a rejouer.
    """
    if not has_role(request, SETTINGS_ROLES):
        return HttpResponseForbidden("Acces non autorise")

    organization = getattr(request, "organization", None)
    gym = getattr(request, "gym", None)
    if not organization:
        return HttpResponseForbidden("Aucune organisation active")

    can_manage_organization = has_role(request, SETTINGS_ORGANIZATION_ROLES)
    can_manage_landing = has_role(request, SETTINGS_LANDING_ROLES)
    can_manage_gym_contact = has_role(request, SETTINGS_GYM_CONTACT_ROLES)
    filters = activity_log.parse_filters(request.GET)
    logs = activity_log.filtered_logs(
        organization,
        filters,
        gym=None if can_manage_organization else gym,
    )

    log_sensitive_action(
        request,
        "settings.activity_log_exported",
        "SensitiveActivityLog",
        f"{filters['date_from']:%d/%m/%Y} - {filters['date_to']:%d/%m/%Y}",
        metadata={"lignes": logs.count(), "groupe": filters["group"] or "tous"},
    )

    response = HttpResponse(
        activity_log.build_csv(logs), content_type="text/csv; charset=utf-8"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="{activity_log.export_filename(organization, filters)}"'
    )
    return response

@login_required
def gym_dashboard(request, gym_id):
    """Dashboard pour une salle spécifique - Vérifie les accès par rôle"""
    
    # Récupérer le gym avec son organisation
    gym = get_object_or_404(Gym.objects.select_related('organization'), id=gym_id)
    
    # ======================
    # VÉRIFICATION DES ACCÈS
    # ======================
    
    user_role = None
    is_owner = hasattr(request, 'is_owner') and request.is_owner
    
    # Owner : vérifier que le gym appartient à son organisation
    if is_owner and request.user.owned_organization:
        if gym.organization_id != request.user.owned_organization_id:
            return HttpResponseForbidden("Accès non autorisé")
        user_role = 'owner'
    
    # Non-Owner : utiliser request.role du middleware
    elif hasattr(request, 'role') and request.role:
        if not getattr(request, "gym", None) or request.gym.id != gym.id:
            return HttpResponseForbidden("Acces non autorise")
        # Vérifier que l'utilisateur a bien un rôle dans ce gym
        user_role_obj = UserGymRole.objects.filter(
            user=request.user, 
            gym=gym, 
            is_active=True
        ).first()
        if not user_role_obj:
            return HttpResponseForbidden("Accès non autorisé")
        user_role = request.role
    
    else:
        # Fallback : vérifier dans la base de données
        user_role_obj = UserGymRole.objects.filter(
            user=request.user, 
            gym=gym, 
            is_active=True
        ).first()
        if not user_role_obj:
            return HttpResponseForbidden("Accès non autorisé")
        user_role = user_role_obj.role

    if user_role not in DASHBOARD_ROLES:
        return HttpResponseForbidden("Acces non autorise")
    
    today = now().date()
    view = request.GET.get("view", "dashboard")
    period_data = _get_period_window(request.GET.get("period", "month"), today)
    
    # Récupérer les modules actifs
    active_modules = GymModule.objects.filter(
        gym=gym,
        is_active=True
    ).values_list('module__code', flat=True)

    current_month = today.month
    current_year = today.year

    members_qs = Member.objects.filter(gym=gym)
    active_subscriptions_qs = MemberSubscription.objects.filter(
        member__gym=gym,
        is_active=True,
        start_date__lte=today,
        end_date__gte=today,
        is_paused=False,
    )

    total_members = members_qs.count()
    active_members = members_qs.filter(
        status="active",
        subscriptions__in=active_subscriptions_qs,
    ).distinct().count()
    suspended_members = members_qs.filter(status="suspended").count()
    # Un membre « expire » est un membre qui a eu un abonnement et n'en a plus
    # de valable. Le deduire par soustraction comptait aussi ceux qui n'ont
    # jamais souscrit, ce qui gonflait le chiffre sans qu'on sache pourquoi.
    members_with_history = members_qs.filter(subscriptions__isnull=False).distinct()
    expired_members = (
        members_with_history.exclude(status="suspended")
        .exclude(subscriptions__in=active_subscriptions_qs)
        .distinct()
        .count()
    )
    never_subscribed_members = members_qs.filter(subscriptions__isnull=True).count()
    active_member_rate = round((active_members / total_members) * 100, 1) if total_members else 0

    new_members_month = members_qs.filter(
        created_at__year=current_year,
        created_at__month=current_month,
    ).count()
    new_members_period = members_qs.filter(
        created_at__date__range=(period_data["start_date"], period_data["end_date"])
    ).count()
    new_members_previous = members_qs.filter(
        created_at__date__range=(period_data["previous_start"], period_data["previous_end"])
    ).count()

    subscriptions_in_period = MemberSubscription.objects.filter(
        member__gym=gym,
        start_date__range=(period_data["start_date"], period_data["end_date"]),
    )
    subscriptions_previous_period = MemberSubscription.objects.filter(
        member__gym=gym,
        start_date__range=(period_data["previous_start"], period_data["previous_end"]),
    )
    previous_subscription_exists = MemberSubscription.objects.filter(
        member=OuterRef("member"),
        start_date__lt=OuterRef("start_date"),
    )
    renewals_period = subscriptions_in_period.annotate(
        has_previous=Exists(previous_subscription_exists)
    ).filter(has_previous=True).count()
    renewals_previous = subscriptions_previous_period.annotate(
        has_previous=Exists(previous_subscription_exists)
    ).filter(has_previous=True).count()

    expirations_period = MemberSubscription.objects.filter(
        member__gym=gym,
        end_date__range=(period_data["start_date"], period_data["end_date"]),
    ).count()
    expirations_previous = MemberSubscription.objects.filter(
        member__gym=gym,
        end_date__range=(period_data["previous_start"], period_data["previous_end"]),
    ).count()
    expiry_soon = None  # calcule juste apres, avec les autres paliers
    def _expiring_within(days):
        """
        Abonnements qui s'eteignent dans les ``days`` jours a venir.

        Ces compteurs utilisaient une date exacte : « expire dans 7 jours »
        ne comptait que le septieme jour, et un membre a echeance dans cinq
        jours n'apparaissait dans aucun palier. Ils cumulent desormais, comme
        la liste vers laquelle ils renvoient.
        """
        return MemberSubscription.objects.filter(
            member__gym=gym,
            is_active=True,
            is_paused=False,
            start_date__lte=today,
            end_date__gte=today,
            end_date__lte=today + timedelta(days=days),
        ).count()

    # 48 h : le dernier moment ou un appel change encore quelque chose.
    expiry_2_days = _expiring_within(2)
    expiry_7_days = _expiring_within(7)
    expiry_3_days = _expiring_within(3)
    expiry_1_day = _expiring_within(1)
    expiry_soon = _expiring_within(15)

    access_period_qs = AccessLog.objects.filter(
        gym=gym,
        check_in_time__date__range=(period_data["start_date"], period_data["end_date"]),
    )
    access_previous_qs = AccessLog.objects.filter(
        gym=gym,
        check_in_time__date__range=(period_data["previous_start"], period_data["previous_end"]),
    )
    # Un retour n'est pas une nouvelle visite : sans cette exclusion, un
    # membre ressorti puis revenu compterait double.
    visits_period = access_period_qs.filter(access_granted=True, is_return=False).count()
    visits_previous = access_previous_qs.filter(access_granted=True, is_return=False).count()
    # Une ouverture manuelle n'a ni membre ni invitation. Compter member_id
    # sans l'exclure regroupait toutes ces lignes sous un seul "visiteur"
    # fantome : on ne compte donc que les passages ou l'on sait qui entre.
    passages_period_qs = access_period_qs.filter(access_granted=True, is_return=False)
    unique_visitors_period = _personnes_distinctes(passages_period_qs)
    denied_period = access_period_qs.filter(access_granted=False).count()
    passages_today_qs = AccessLog.objects.filter(
        gym=gym,
        check_in_time__date=today,
        access_granted=True,
        is_return=False,
    )
    today_checkins = passages_today_qs.count()
    today_unique_visitors = _personnes_distinctes(passages_today_qs)
    denied_today = AccessLog.objects.filter(
        gym=gym,
        check_in_time__date=today,
        access_granted=False,
    ).count()
    # Assiduite : meme population au numerateur et au denominateur. L'ancien
    # "engagement" divisait les visiteurs de la periode - membres expires et
    # invites compris - par les membres actifs du jour. Deux populations
    # differentes, deux dates differentes : il pouvait depasser 100 %, et
    # c'est ce qu'il faisait.
    active_members_seen = members_qs.filter(
        status="active",
        subscriptions__in=active_subscriptions_qs,
        access_logs__check_in_time__date__range=(
            period_data["start_date"], period_data["end_date"]
        ),
        access_logs__access_granted=True,
        access_logs__is_return=False,
    ).distinct().count()
    attendance_rate = (
        round((active_members_seen / active_members) * 100, 1) if active_members else 0
    )

    # La moyenne porte sur les jours ecoules, pas sur la periode entiere : au
    # 11 septembre, diviser par 30 compte 19 jours qui n'ont pas eu lieu.
    elapsed_end = min(period_data["end_date"], today)
    elapsed_days = max((elapsed_end - period_data["start_date"]).days + 1, 1)
    average_daily_visits = round(visits_period / elapsed_days, 1)
    peak_hour = _build_peak_hour(access_period_qs)
    attendance_rows = _build_attendance_rows(gym, period_data)
    week_labels = [row["label"] for row in attendance_rows]
    week_values = [row["count"] for row in attendance_rows]
    member_growth_rows = _build_member_growth_rows(members_qs, period_data)
    member_growth_labels = [row["label"] for row in member_growth_rows]
    member_growth_values = [row["count"] for row in member_growth_rows]

    daily_revenue = 0
    monthly_revenue = 0
    period_revenue = 0
    previous_period_revenue = 0
    revenue_rows = _build_revenue_rows(Payment.objects.none(), period_data)
    sales_labels = []
    sales_values = []
    if user_role in DASHBOARD_SALES_ROLES:
        successful_incoming_payments = Payment.objects.filter(gym=gym).recettes()
        daily_revenue = successful_incoming_payments.filter(
            created_at__date=today
        ).aggregate(total=Sum("amount_cdf"))["total"] or 0
        monthly_revenue = successful_incoming_payments.filter(
            created_at__year=current_year,
            created_at__month=current_month,
        ).aggregate(total=Sum("amount_cdf"))["total"] or 0
        period_revenue = successful_incoming_payments.filter(
            created_at__date__range=(period_data["start_date"], period_data["end_date"])
        ).aggregate(total=Sum("amount_cdf"))["total"] or 0
        previous_period_revenue = successful_incoming_payments.filter(
            created_at__date__range=(period_data["previous_start"], period_data["previous_end"])
        ).aggregate(total=Sum("amount_cdf"))["total"] or 0
        revenue_rows = _build_revenue_rows(
            successful_incoming_payments.filter(
                created_at__date__range=(period_data["start_date"], period_data["end_date"])
            ),
            period_data,
        )

        monthly_sales = successful_incoming_payments.filter(
            created_at__year=current_year
        ).annotate(
            month=ExtractMonth("created_at")
        ).values("month").annotate(
            total=Sum("amount_cdf")
        ).order_by("month")

        for item in monthly_sales:
            sales_labels.append(calendar.month_abbr[item["month"]])
            sales_values.append(float(item["total"]))

    new_members_trend = _build_trend(new_members_period, new_members_previous)
    renewals_trend = _build_trend(renewals_period, renewals_previous)
    visits_trend = _build_trend(visits_period, visits_previous)
    revenue_trend = _build_trend(period_revenue, previous_period_revenue)
    # Les trois valeurs « periode precedente » etaient calculees sans jamais
    # servir, alors que le template attendait deja ces badges : ils
    # s'affichaient vides. On reconstitue la comparaison.
    new_members_trend = _build_trend(new_members_period, new_members_previous)
    renewals_trend = _build_trend(renewals_period, renewals_previous)
    expirations_trend = _build_trend(expirations_period, expirations_previous)
    expirations_trend = _build_trend(expirations_period, expirations_previous)

    plans_stats = MemberSubscription.objects.filter(
        member__gym=gym,
        is_active=True,
        start_date__lte=today,
        end_date__gte=today,
        is_paused=False,
    ).values("plan__name").annotate(total=Count("id")).order_by("-total")
    total_subscriptions = MemberSubscription.objects.filter(
        member__gym=gym,
        is_active=True,
        start_date__lte=today,
        end_date__gte=today,
        is_paused=False,
    ).count()
    plan_labels = [plan["plan__name"] or "Sans nom" for plan in plans_stats]
    plan_values = [plan["total"] for plan in plans_stats]
    status_chart_labels = ["Actifs", "Expires", "Suspendus"]
    status_chart_values = [active_members, expired_members, suspended_members]
    dashboard_chart_data = _build_dashboard_chart_data(
        revenue_rows=revenue_rows,
        attendance_rows=attendance_rows,
        status_chart_labels=status_chart_labels,
        status_chart_values=status_chart_values,
        plan_labels=plan_labels,
        plan_values=plan_values,
        expiry_1_day=expiry_1_day,
        expiry_3_days=expiry_3_days,
        expiry_7_days=expiry_7_days,
        expiry_soon=expiry_soon,
        visits_period=visits_period,
        denied_period=denied_period,
    )

    recent_payments = []
    if user_role in DASHBOARD_SALES_ROLES:
        recent_payments = Payment.objects.filter(gym=gym).select_related("member").order_by("-created_at")[:5]

    pending_count = 0
    pending_total = 0
    if user_role in DASHBOARD_SALES_ROLES:
        pending_payments = Payment.objects.filter(
            gym=gym,
            status="pending",
        )
        pending_count = pending_payments.count()
        pending_total = pending_payments.aggregate(total=Sum("amount_cdf"))["total"] or 0

    recent_access = []
    if user_role in ["owner", "manager", "reception"]:
        recent_access = (
            AccessLog.objects.filter(gym=gym)
            .select_related("member", "guest_pass")
            .order_by("-check_in_time")[:5]
        )

    my_members = []
    coach_name = None
    if user_role == "coach":
        from coaching.models import Coach

        coach_lookup = Q()
        for value in [request.user.get_full_name(), request.user.first_name, getattr(request.user, "phone", "")]:
            if value:
                coach_lookup |= Q(name__icontains=value) | Q(phone=value)
        coach = Coach.objects.filter(gym=gym, is_active=True).filter(coach_lookup).first() if coach_lookup else None

        if coach:
            my_members = coach.members.filter(is_active=True)
            coach_name = coach.name
        else:
            coach_name = request.user.first_name

    checkins_today = today_checkins if user_role == "reception" else 0
    sales_today = daily_revenue if user_role == "cashier" else 0

    machine_kpis = {
        "total_machines": 0,
        "machines_ok": 0,
        "machines_maintenance": 0,
        "machines_broken": 0,
        "machines_ok_percent": 0,
        "machines_maintenance_percent": 0,
        "machines_broken_percent": 0,
        "availability_rate": 0,
        "attention_count": 0,
        "total_maintenances": 0,
        "total_maintenance_cost": 0,
        "period_maintenances": 0,
        "period_maintenance_cost": 0,
        "monthly_maintenance_cost": 0,
        "average_maintenance_cost": 0,
        "top_costly_machine": "-",
    }
    if "MACHINES" in active_modules:
        from machines.kpis import build_machine_kpis

        machine_kpis = build_machine_kpis(gym, period_data)

    rh_kpis = {
        "total_employees": 0,
        "active_employees": 0,
        "inactive_employees": 0,
        "attendance_today_present": 0,
        "attendance_today_absent": 0,
        "attendance_today_rate": 0,
        "attendance_period_present": 0,
        "attendance_period_absent": 0,
        "attendance_period_rate": 0,
        "monthly_payroll": 0,
        "monthly_payroll_paid": 0,
        "monthly_payroll_pending": 0,
        "monthly_payroll_pending_count": 0,
        "salary_paid_period": 0,
        "salary_payments_period": 0,
        "employee_role_breakdown": [],
    }
    if "RH" in active_modules:
        from rh.kpis import build_rh_kpis

        rh_kpis = build_rh_kpis(gym, period_data)

    product_kpis = {
        "total_products": 0,
        "all_products_count": 0,
        "inactive_products": 0,
        "stock_value_total": 0,
        "stock_ok_count": 0,
        "low_stock_count": 0,
        "out_of_stock_count": 0,
        "stock_movements_period": 0,
        "stock_in_period": 0,
        "stock_out_period": 0,
        "top_value_products": [],
        "recent_stock_movements": [],
        "stock_status_chart_labels": [],
        "stock_status_chart_values": [],
        "stock_value_chart_labels": [],
        "stock_value_chart_values": [],
    }
    if "PRODUCTS" in active_modules:
        from products.kpis import build_product_kpis

        product_kpis = build_product_kpis(gym, period_data)

    coaching_kpis = {
        "total_coaches": 0,
        "active_coaches": 0,
        "inactive_coaches": 0,
        "assigned_members_count": 0,
        "unassigned_members_count": 0,
        "average_members_per_coach": 0,
        "new_coaches_period": 0,
        "top_coaches": [],
        "coaching_status_chart_labels": [],
        "coaching_status_chart_values": [],
        "coaching_workload_chart_labels": [],
        "coaching_workload_chart_values": [],
    }
    if "COACHING" in active_modules:
        from coaching.kpis import build_coaching_kpis

        coaching_kpis = build_coaching_kpis(gym, period_data)

    tableau_de_caisse = _tableau_de_caisse(gym, today)
    refus_repetes = _refus_repetes(gym, today)
    # Les alertes arrivent en dernier : elles lisent la caisse, les acces, le
    # parc et le stock, et ne peuvent donc se calculer qu'apres eux.
    alertes_urgentes = _alertes_urgentes(
        tableau_de_caisse,
        refus_repetes,
        expiry_2_days,
        machine_kpis["machines_broken"],
        product_kpis["out_of_stock_count"],
        product_kpis["low_stock_count"],
    )

    total_maintenance_cost = machine_kpis["total_maintenance_cost"]
    total_revenue = monthly_revenue

    context = {
        "active_modules": active_modules,
        "gym": gym,
        "organization": gym.organization,
        "context_view": view,
        "user_role": user_role,
        "is_owner": is_owner,
        "my_members": my_members,
        "coach_name": coach_name,
        "checkins_today": checkins_today,
        "sales_today": sales_today,
        "total_maintenance_cost": total_maintenance_cost,
        "total_revenue": total_revenue,
        "selected_period": period_data["key"],
        "period_label": period_data["label"],
        "period_label_lower": period_data["label"].lower(),
        "period_range_label": _format_period_range(period_data["start_date"], period_data["end_date"]),
        "period_days": period_data["days"],
        "dashboard_chart_data": dashboard_chart_data,
        "total_members": total_members,
        "active_members": active_members,
        "active_member_rate": active_member_rate,
        "expired_members": expired_members,
        "never_subscribed_members": never_subscribed_members,
        "suspended_members": suspended_members,
        "new_members_month": new_members_month,
        "new_members_period": new_members_period,
        "renewals_period": renewals_period,
        "expirations_period": expirations_period,
        "unique_visitors_period": unique_visitors_period,
        "active_members_seen": active_members_seen,
        "attendance_rate": attendance_rate,
        "average_daily_visits": average_daily_visits,
        "elapsed_days": elapsed_days,
        "peak_hour": peak_hour,
        "new_members_trend": new_members_trend,
        "renewals_trend": renewals_trend,
        "visits_trend": visits_trend,
        "revenue_trend": revenue_trend,
        "expirations_trend": expirations_trend,
        "daily_revenue": daily_revenue,
        "monthly_revenue": monthly_revenue,
        "period_revenue": period_revenue,
        "today_checkins": today_checkins,
        "today_unique_visitors": today_unique_visitors,
        "caisse": tableau_de_caisse,
        "refus_repetes": refus_repetes,
        "expiry_2_days": expiry_2_days,
        "alertes_urgentes": alertes_urgentes,
        "visits_period": visits_period,
        "denied_period": denied_period,
        "denied_today": denied_today,
        "expiry_soon": expiry_soon,
        "expiry_7_days": expiry_7_days,
        "expiry_3_days": expiry_3_days,
        "expiry_1_day": expiry_1_day,
        "plans_stats": plans_stats,
        "total_subscriptions": total_subscriptions,
        "plan_labels": plan_labels,
        "plan_values": plan_values,
        "attendance_rows": attendance_rows,
        "week_labels": week_labels,
        "week_values": week_values,
        "member_growth_rows": member_growth_rows,
        "status_chart_labels": _to_json(status_chart_labels),
        "status_chart_values": _to_json(status_chart_values),
        "member_growth_labels": _to_json(member_growth_labels),
        "member_growth_values": _to_json(member_growth_values),
        "plan_chart_labels": _to_json(plan_labels),
        "plan_chart_values": _to_json(plan_values),
        "attendance_chart_labels": _to_json(week_labels),
        "attendance_chart_values": _to_json(week_values),
        "sales_chart_labels": _to_json(sales_labels),
        "sales_chart_values": _to_json(sales_values),
        "stock_status_chart_labels_json": _to_json(product_kpis["stock_status_chart_labels"]),
        "stock_status_chart_values_json": _to_json(product_kpis["stock_status_chart_values"]),
        "stock_value_chart_labels_json": _to_json(product_kpis["stock_value_chart_labels"]),
        "stock_value_chart_values_json": _to_json(product_kpis["stock_value_chart_values"]),
        "coaching_status_chart_labels_json": _to_json(coaching_kpis["coaching_status_chart_labels"]),
        "coaching_status_chart_values_json": _to_json(coaching_kpis["coaching_status_chart_values"]),
        "coaching_workload_chart_labels_json": _to_json(coaching_kpis["coaching_workload_chart_labels"]),
        "coaching_workload_chart_values_json": _to_json(coaching_kpis["coaching_workload_chart_values"]),
        "recent_payments": recent_payments,
        "pending_count": pending_count,
        "pending_total": pending_total,
        "recent_access": recent_access,
        "sales_labels": sales_labels,
        "sales_values": sales_values,
    }
    context.update(machine_kpis)
    context.update(rh_kpis)
    context.update(product_kpis)
    context.update(coaching_kpis)

    # La vue d'ensemble affichait « 0:1 » en permanence : la cle n'etait
    # calculee nulle part, seul le repli du template s'affichait. Le vrai
    # chiffre existait deja sous un autre nom.
    context["coach_member_ratio"] = coaching_kpis.get("average_members_per_coach", 0)

    return render(request, "core/dashboard_members.html", context)

@login_required
def _legacy_reports_dashboard(request):
    gym = getattr(request, "gym", None)
    if not gym:
        return redirect("core:select_gym")

    user_role = current_role(request)
    if not has_role(request, REPORT_ROLES):
        return HttpResponseForbidden("Acces non autorise")

    today = now().date()
    section = request.GET.get("section", "journalier")
    period_data = get_report_period(request.GET)
    accounting_report = build_accounting_report(gym, period_data)
    # =========================
    # CA du jour
    # =========================
    payments_today = Payment.objects.filter(
        gym=gym, created_at__date=today
    ).recettes()

    daily_revenue = payments_today.aggregate(
        total=Sum("amount_cdf")
    )["total"] or 0

    daily_transactions = payments_today.count()

    # =========================
    # Nouveaux membres
    # =========================
    daily_new_clients = Member.objects.filter(
        gym=gym,
        created_at__date=today
    ).count()
    
    # =========================
    # Fréquentation
    # =========================
    daily_visits = AccessLog.objects.filter(
        member__gym=gym,
        check_in_time__date=today,
        access_granted=True,
        is_return=False,
    ).count()

    denied_access = AccessLog.objects.filter(
        member__gym=gym,
        check_in_time__date=today,
        access_granted=False
    ).count()

    # Un invite n'est pas un abonne : il se compte, mais jamais avec eux.
    guest_visits = AccessLog.objects.filter(
        gym=gym,
        check_in_time__date=today,
        access_granted=True,
        guest_pass__isnull=False,
    ).count()

    # =========================
    # Transactions détaillées
    # =========================
    transactions = payments_today.select_related(
        "member"
    ).order_by("-created_at")[:50]

    # =========================
    # KPI MENSUELS
    # =========================

    today = now().date()
    current_year = today.year
    current_month = today.month

    payments_month = Payment.objects.filter(
        gym=gym,
        created_at__year=current_year,
        created_at__month=current_month,
    ).recettes()

    monthly_revenue = payments_month.aggregate(
        total=Sum("amount_cdf")
    )["total"] or 0

    monthly_transactions = payments_month.count()


    # nouveaux membres ce mois
    monthly_new_members = Member.objects.filter(
        gym=gym,
        created_at__year=current_year,
        created_at__month=current_month
    ).count()


    # renouvellements abonnement
    monthly_renewals = MemberSubscription.objects.filter(
        member__gym=gym,
        start_date__year=current_year,
        start_date__month=current_month
    ).count()


    # visites
    monthly_visits = AccessLog.objects.filter(
        member__gym=gym,
        check_in_time__year=current_year,
        check_in_time__month=current_month,
        access_granted=True,
        is_return=False,
    ).count()
    
    plans_stats = MemberSubscription.objects.filter(
        member__gym=gym,
        start_date__year=current_year,
        start_date__month=current_month
        ).values(
            "plan__name"
        ).annotate(
            subscriptions=Count("id", distinct=True),
            revenue=Sum("payments__amount_cdf", filter=RECETTE)
        ).order_by("-revenue")
    
    monthly_sales = Payment.objects.filter(
        gym=gym,
        created_at__year=current_year,
        ).recettes().annotate(
            month=ExtractMonth("created_at")
        ).values("month").annotate(
            total=Sum("amount_cdf")
        ).order_by("month")
    
    sales_labels = []
    sales_values = []

    for m in monthly_sales:
        sales_labels.append(m["month"])
        sales_values.append(float(m["total"]))
    context = {
        "section": section,
        "selected_period": period_data["key"],
        "date_from": period_data["date_from"],
        "date_to": period_data["date_to"],
        "report_period_label": period_data["label"],
        "accounting_report": accounting_report,
        "can_export_accounting": user_role in REPORT_ROLES,
            # journalier
        "daily_revenue": daily_revenue,
        "daily_transactions": daily_transactions,
        "daily_new_clients": daily_new_clients,
        "daily_visits": daily_visits,
        "denied_access": denied_access,
        "guest_visits": guest_visits,
        "transactions": transactions,

        # mensuel
        "monthly_revenue": monthly_revenue,
        "monthly_new_members": monthly_new_members,
        "monthly_renewals": monthly_renewals,
        "monthly_visits": monthly_visits,
        "plans_stats": plans_stats,
        "sales_labels": sales_labels,
        "sales_values": sales_values,
        "monthly_transactions": monthly_transactions
        }

    return render(request, "core/rapports.html", context)


@login_required
def reports_dashboard(request):
    gym = getattr(request, "gym", None)
    if not gym:
        return redirect("core:select_gym")

    user_role = current_role(request)
    if not has_role(request, REPORT_ROLES):
        return HttpResponseForbidden("Acces non autorise")

    section = get_report_section(request.GET)
    default_period_by_section = {
        "journalier": "today",
        "mensuel": "month",
        "personnalise": "custom",
    }
    period_data = get_report_period(
        request.GET,
        default_period=default_period_by_section.get(section, "month"),
    )
    accounting_report = build_accounting_report(gym, period_data)
    report_chart_data = _build_report_chart_data(accounting_report)

    payments_period = Payment.objects.filter(
        gym=gym,
        created_at__date__range=(period_data["start_date"], period_data["end_date"]),
        status="success",
    )
    incoming_period = payments_period.recettes()

    daily_revenue = incoming_period.aggregate(total=Sum("amount_cdf"))["total"] or 0
    daily_transactions = payments_period.count()
    daily_new_clients = Member.objects.filter(
        gym=gym,
        created_at__date__range=(period_data["start_date"], period_data["end_date"]),
    ).count()
    # member__isnull=False ecarte les invites et les ouvertures manuelles :
    # sans lui, une entree sans abonne gonflait la frequentation.
    daily_visits = AccessLog.objects.filter(
        gym=gym,
        check_in_time__date__range=(period_data["start_date"], period_data["end_date"]),
        access_granted=True,
        is_return=False,
        member__isnull=False,
    ).count()
    denied_access = AccessLog.objects.filter(
        gym=gym,
        check_in_time__date__range=(period_data["start_date"], period_data["end_date"]),
        access_granted=False,
        member__isnull=False,
    ).count()
    guest_visits = AccessLog.objects.filter(
        gym=gym,
        check_in_time__date__range=(period_data["start_date"], period_data["end_date"]),
        access_granted=True,
        guest_pass__isnull=False,
    ).count()
    transactions = payments_period.select_related("member", "cash_register").order_by("-created_at")[:50]

    monthly_revenue = daily_revenue
    monthly_transactions = daily_transactions
    monthly_new_members = daily_new_clients
    monthly_renewals = MemberSubscription.objects.filter(
        member__gym=gym,
        start_date__range=(period_data["start_date"], period_data["end_date"]),
    ).count()
    monthly_visits = daily_visits

    plans_stats = MemberSubscription.objects.filter(
        member__gym=gym,
        start_date__range=(period_data["start_date"], period_data["end_date"]),
    ).values("plan__name").annotate(
        subscriptions=Count("id", distinct=True),
        revenue=Sum("payments__amount_cdf", filter=RECETTE),
    ).order_by("-revenue")

    monthly_sales = incoming_period.annotate(
        month=ExtractMonth("created_at")
    ).values("month").annotate(
        total=Sum("amount_cdf")
    ).order_by("month")

    sales_labels = []
    sales_values = []
    for item in monthly_sales:
        sales_labels.append(calendar.month_abbr[item["month"]])
        sales_values.append(float(item["total"]))

    custom_report = build_custom_report(gym, request.GET, period_data, limit=50)
    from rh.kpis import payroll_rows_for_period

    payroll_report = payroll_rows_for_period(gym, period_data["start_date"], period_data["end_date"])
    payroll_report_label = period_data["label"]

    context = {
        "section": section,
        "selected_period": period_data["key"],
        "date_from": period_data["date_from"],
        "date_to": period_data["date_to"],
        "report_period_label": period_data["label"],
        "accounting_report": accounting_report,
        "report_chart_data": report_chart_data,
        "can_export_accounting": user_role in REPORT_ROLES,
        "custom_report": custom_report,
        "daily_revenue": daily_revenue,
        "daily_transactions": daily_transactions,
        "daily_new_clients": daily_new_clients,
        "daily_visits": daily_visits,
        "denied_access": denied_access,
        "guest_visits": guest_visits,
        "transactions": transactions,
        "monthly_revenue": monthly_revenue,
        "monthly_new_members": monthly_new_members,
        "monthly_renewals": monthly_renewals,
        "monthly_visits": monthly_visits,
        "plans_stats": plans_stats,
        "sales_labels": sales_labels,
        "sales_values": sales_values,
        "monthly_transactions": monthly_transactions,
        "payroll_report": payroll_report,
        "payroll_report_label": payroll_report_label,
    }

    return render(request, "core/rapports.html", context)


@login_required
def accounting_report_export(request):
    gym = getattr(request, "gym", None)
    if not gym:
        return redirect("core:select_gym")

    if not has_role(request, REPORT_ROLES):
        return HttpResponseForbidden("Acces non autorise")

    export_format = request.GET.get("format", "xlsx").lower()
    if export_format == "excel":
        export_format = "xlsx"
    if export_format not in ["csv", "xlsx"]:
        return HttpResponseBadRequest("Format d'export non supporte.")

    section = get_report_section(request.GET)
    default_period_by_section = {
        "journalier": "today",
        "mensuel": "month",
        "personnalise": "custom",
    }
    period_data = get_report_period(
        request.GET,
        default_period=default_period_by_section.get(section, "month"),
    )

    if section == "personnalise":
        custom_report = build_custom_report(gym, request.GET, period_data)
        if export_format == "csv":
            content = build_custom_csv_export(custom_report)
            content_type = "text/csv; charset=utf-8"
        else:
            content = build_custom_xlsx_export(custom_report)
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = (
            f'attachment; filename="{accounting_filename(gym, period_data, export_format)}"'
        )
        return response

    report = build_accounting_report(gym, period_data)

    if export_format == "csv":
        content = build_csv_export(report)
        content_type = "text/csv; charset=utf-8"
    else:
        content = build_xlsx_export(report)
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = (
        f'attachment; filename="{accounting_filename(gym, period_data, export_format)}"'
    )
    return response


@staff_member_required
def health_details(request):
    from django.db import connections
    from django.db.utils import DatabaseError

    database_ok = True
    database_error = ""
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError as exc:
        database_ok = False
        database_error = str(exc)

    payload = {
        "status": "ok" if database_ok else "degraded",
        "database": {
            "ok": database_ok,
            "error": database_error,
        },
    }
    return JsonResponse(payload, status=200 if database_ok else 503)


# ---------------------------------------------------------------------------
# Remise a zero d'une salle
# ---------------------------------------------------------------------------
#
# Trois vues pour un seul geste, volontairement : on regarde ce qu'on va
# perdre, on emporte une copie, puis on detruit. Chaque etape est verrouillee
# separement, et la derniere exige de reecrire le nom de la salle et son propre
# mot de passe. Aucune de ces barrieres n'empeche une decision reflechie ; elles
# empechent un clic distrait.


def _salle_effacable(request):
    """La salle courante, si l'utilisateur a le droit d'y toucher."""
    if not has_role(request, SETTINGS_ORGANIZATION_ROLES):
        return None, HttpResponseForbidden("Acces reserve au proprietaire")

    gym = getattr(request, "gym", None)
    if not gym:
        return None, HttpResponseBadRequest("Aucune salle active")

    return gym, None


@login_required
def gym_purge_preview(request):
    """Ce que l'effacement detruirait, chiffre, avant toute action."""
    gym, refus = _salle_effacable(request)
    if refus:
        return refus

    return JsonResponse({"salle": gym.name, **purge.inventaire(gym)})


@login_required
@require_POST
def gym_purge_export(request):
    """Copie des donnees sur le point de disparaitre, remise avant l'effacement."""
    gym, refus = _salle_effacable(request)
    if refus:
        return refus

    contenu = purge.exporter(gym)

    log_sensitive_action(
        request,
        "gym.purge_exported",
        "Gym",
        gym.name,
        metadata={"gym_id": gym.id, "octets": len(contenu)},
        gym=gym,
    )

    horodatage = now().strftime("%Y%m%d-%H%M")
    reponse = HttpResponse(contenu, content_type="application/json; charset=utf-8")
    reponse["Content-Disposition"] = (
        f'attachment; filename="sauvegarde-{gym.slug}-{horodatage}.json"'
    )
    return reponse


@login_required
@require_POST
def gym_purge(request):
    """
    Efface les donnees d'exploitation de la salle.

    Irreversible. Le nom de la salle recopie a l'identique et le mot de passe
    de l'utilisateur sont exiges : le premier prouve qu'on sait quelle salle on
    vide, le second qu'on est bien celui qu'on pretend etre.
    """
    gym, refus = _salle_effacable(request)
    if refus:
        return refus

    try:
        charge = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Requete illisible")

    nom_saisi = (charge.get("nom_salle") or "").strip()
    if nom_saisi != gym.name:
        return JsonResponse(
            {"error": "Le nom saisi ne correspond pas a celui de la salle."},
            status=400,
        )

    mot_de_passe = charge.get("password") or ""
    if not request.user.check_password(mot_de_passe):
        return JsonResponse({"error": "Mot de passe incorrect."}, status=400)

    # Releve avant destruction : apres, plus rien ne permettrait de dire ce
    # qui a disparu.
    avant = purge.inventaire(gym)
    supprime = purge.purger(gym)

    # La trace survit a l'effacement : elle vit sur l'organisation, pas sur la
    # salle, et nomme qui a decide.
    log_sensitive_action(
        request,
        "gym.purged",
        "Gym",
        gym.name,
        metadata={"gym_id": gym.id, "total": avant["total"], "detail": supprime},
        gym=gym,
    )

    return JsonResponse({"ok": True, "supprime": supprime, "total": avant["total"]})


# ---------------------------------------------------------------------------
# QR codes a afficher en salle
# ---------------------------------------------------------------------------
#
# Deux supports : l'adresse du site, et le lien de preinscription. Ils finissent
# sur un mur, parfois en tres grand : le PDF est vectoriel et s'agrandit sans
# perte, le PNG sert au partage rapide.


SUPPORTS_QR = {
    "site": {
        "libelle": "Notre site",
        "fichier": "qr-site",
    },
    "preinscription": {
        "libelle": "Preinscription",
        "fichier": "qr-preinscription",
    },
}


def _contenu_du_qr(request, support):
    """L'adresse que portera le QR code, ou None si elle n'existe pas."""
    if support == "site":
        return public_base_url(request) or request.build_absolute_uri("/")

    lien = MemberPreRegistrationLink.objects.filter(
        gym=request.gym, is_active=True
    ).first()
    if not lien:
        return None
    return build_public_url(
        request, reverse("members:public_pre_registration", args=[lien.token])
    )


@login_required
@role_required(PRE_REGISTRATION_LINK_ROLES)
def marketing_qr_download(request, support):
    """
    Telecharge un QR code d'affichage, en PDF vectoriel ou en PNG.

    Le PDF est le format a donner a un imprimeur : une bache de deux metres y
    reste aussi nette qu'un A4. Le PNG depanne pour un envoi par messagerie.
    """
    if support not in SUPPORTS_QR:
        raise Http404("Support inconnu.")

    contenu = _contenu_du_qr(request, support)
    if not contenu:
        return HttpResponseBadRequest(
            "Aucun lien de preinscription actif pour cette salle."
        )

    fichier = SUPPORTS_QR[support]["fichier"]

    if request.GET.get("format") == "png":
        return _fichier_a_telecharger(
            marketing_qr.en_png(contenu, request.GET.get("taille")),
            f"{fichier}.png",
            "image/png",
        )

    return _fichier_a_telecharger(
        marketing_qr.en_pdf(contenu), f"{fichier}.pdf", "application/pdf"
    )


def _fichier_a_telecharger(contenu, nom, type_mime):
    reponse = HttpResponse(contenu, content_type=type_mime)
    reponse["Content-Disposition"] = f'attachment; filename="{nom}"'
    return reponse


# ---------------------------------------------------------------------------
# Recherche globale
# ---------------------------------------------------------------------------

# Assez de lignes par section pour reconnaitre ce qu'on cherchait, assez peu
# pour que les trois sections tiennent sur un ecran.
RESULTATS_PAR_SECTION = 8

# Quand on deplie une seule section, on peut en montrer davantage.
RESULTATS_DEPLIES = 50


def _montant_recherche(texte):
    """
    Le montant tape, s'il y en a un.

    "30000" et "30 000" designent la meme somme ; "Ada" n'en designe aucune.
    Sans cette lecture, chercher un montant ne ramenait rien.
    """
    nettoye = texte.replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        return Decimal(nettoye)
    except (InvalidOperation, ValueError):
        return None


@login_required
def global_search(request):
    """
    Retrouver un membre, un abonnement ou un paiement depuis n'importe ou.

    Chaque section n'apparait qu'a qui a le droit de la lire : une
    receptionniste voit les membres, pas les paiements. Les droits ne se
    relachent pas parce qu'on est passe par la recherche.

    ``section`` deplie une rubrique sans quitter la page : renvoyer vers une
    liste generale ferait perdre la recherche en chemin.
    """
    requete = (request.GET.get("q") or request.GET.get("search") or "").strip()
    depliee = (request.GET.get("section") or "").strip()
    gym = getattr(request, "gym", None)

    fabriques = []
    if has_role(request, MEMBER_ROLES):
        fabriques.append(("membres", _recherche_membres))
    if has_role(request, SUBSCRIPTION_ROLES):
        fabriques.append(("abonnements", _recherche_abonnements))
    if has_role(request, POS_HISTORY_ROLES):
        fabriques.append(("paiements", _recherche_paiements))

    sections = []
    if gym and requete:
        for cle, fabrique in fabriques:
            if depliee and cle != depliee:
                continue
            limite = RESULTATS_DEPLIES if cle == depliee else RESULTATS_PAR_SECTION
            section = fabrique(gym, requete, limite)
            section["cle"] = cle
            section["tout_voir"] = (
                f'{reverse("core:global_search")}?q={quote(requete)}&section={cle}'
            )
            sections.append(section)

    return render(
        request,
        "core/recherche.html",
        {
            "requete": requete,
            "sections": sections,
            "section_depliee": depliee,
            "total": sum(section["total"] for section in sections),
        },
    )


def _url_fiche_membre(membre):
    """
    La fiche du membre, ouverte.

    Renvoyer vers la liste complete obligeait a recommencer la recherche sur
    place. Le parametre ouvre la fiche, et le filtre laisse derriere elle une
    liste reduite a cette personne.
    """
    reference = membre.phone or f"{membre.first_name} {membre.last_name}".strip()
    return (
        f'{reverse("members:member_list")}'
        f"?search={quote(reference)}&membre={membre.id}"
    )


def _recherche_membres(gym, requete, limite):
    trouves = Member.objects.filter(gym=gym).filter(
        Q(first_name__icontains=requete)
        | Q(last_name__icontains=requete)
        | Q(phone__icontains=requete)
        | Q(email__icontains=requete)
        | Q(user__username__icontains=requete)
    ).order_by("first_name", "last_name")

    return {
        "titre": "Membres",
        "icone": "group",
        "total": trouves.count(),
        "lignes": [
            {
                "titre": f"{membre.first_name} {membre.last_name}".strip() or membre.phone,
                "detail": membre.phone or membre.email or "",
                "url": _url_fiche_membre(membre),
            }
            for membre in trouves[:limite]
        ],
    }


def _recherche_abonnements(gym, requete, limite):
    trouves = MemberSubscription.objects.filter(gym=gym).filter(
        Q(member__first_name__icontains=requete)
        | Q(member__last_name__icontains=requete)
        | Q(member__phone__icontains=requete)
        | Q(plan__name__icontains=requete)
    ).select_related("member", "plan").order_by("-start_date")

    return {
        "titre": "Abonnements",
        "icone": "card_membership",
        "total": trouves.count(),
        "lignes": [
            {
                "titre": (
                    f"{abonnement.member.first_name} {abonnement.member.last_name}".strip()
                    + (f" - {abonnement.plan.name}" if abonnement.plan else "")
                ),
                "detail": (
                    f"du {abonnement.start_date:%d/%m/%Y} au "
                    f"{abonnement.end_date:%d/%m/%Y}"
                ),
                # La fiche s'ouvre sur son onglet Abonnement, ou l'historique
                # complet du membre est deja affiche.
                "url": _url_fiche_membre(abonnement.member),
            }
            for abonnement in trouves[:limite]
        ],
    }


def _recherche_paiements(gym, requete, limite):
    criteres = (
        Q(member__first_name__icontains=requete)
        | Q(member__last_name__icontains=requete)
        | Q(description__icontains=requete)
        | Q(cash_register__session_code__icontains=requete)
    )
    # Un montant tape se cherche comme un montant, pas comme du texte.
    montant_cherche = _montant_recherche(requete)
    if montant_cherche is not None:
        criteres |= Q(amount_cdf=montant_cherche) | Q(amount=montant_cherche)

    trouves = (
        Payment.objects.filter(gym=gym)
        .filter(criteres)
        .select_related("member", "cash_register")
        .order_by("-created_at")
    )

    lignes = []
    for paiement in trouves[:limite]:
        if paiement.type == "out":
            qui = "Decaissement"
        elif paiement.member:
            qui = f"{paiement.member.first_name} {paiement.member.last_name}".strip()
        else:
            qui = "Vente au comptoir"

        # La session de caisse, quand il y en a une : elle montre la ligne
        # elle-meme, au milieu des autres mouvements du meme tiroir.
        if paiement.cash_register_id:
            url = reverse("pos:register_detail", args=[paiement.cash_register_id])
        else:
            url = f'{reverse("pos:register_history")}?search={quote(requete)}'

        lignes.append({
            "titre": f"{qui} - {paiement.amount_cdf:.0f} CDF",
            "detail": (
                f'{paiement.description or "Sans motif"} - '
                f'{localtime(paiement.created_at):%d/%m/%Y %H:%M}'
            ),
            "url": url,
        })

    return {
        "titre": "Paiements",
        "icone": "payments",
        "total": trouves.count(),
        "lignes": lignes,
    }
