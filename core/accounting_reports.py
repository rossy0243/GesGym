import csv
import io
import zipfile
from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from xml.sax.saxutils import escape

from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_date

from access.models import AccessLog
from members.models import Member
from pos.models import CashRegister, Payment
from subscriptions.models import MemberSubscription


MONEY_QUANTIZER = Decimal("0.01")

PERIOD_CHOICES = {
    "today": "Aujourd'hui",
    "yesterday": "Hier",
    "week": "Cette semaine",
    "month": "Ce mois",
    "year": "Cette annee",
    "custom": "Personnalisee",
}

REPORT_SECTIONS = {
    "journalier": "Journalier",
    "mensuel": "Mensuel",
    "personnalise": "Personnalise",
}

CUSTOM_DATA_TYPES = OrderedDict(
    [
        ("transactions", "Transactions POS"),
        ("members", "Membres"),
        ("access", "Acces"),
        ("subscriptions", "Abonnements"),
        ("registers", "Sessions de caisse"),
    ]
)

CUSTOM_COLUMNS = OrderedDict(
    [
        ("date", "Date"),
        ("dataset", "Type"),
        ("client", "Client / Responsable"),
        ("description", "Libelle"),
        ("amount_cdf", "Montant CDF"),
        ("method", "Methode"),
        ("status", "Statut"),
        ("reference", "Reference"),
        ("source", "Source"),
    ]
)

CUSTOM_GROUPINGS = OrderedDict(
    [
        ("none", "Aucun"),
        ("day", "Par jour"),
        ("week", "Par semaine"),
        ("month", "Par mois"),
        ("type", "Par type de donnee"),
    ]
)

DEFAULT_CUSTOM_TYPES = ["transactions"]
DEFAULT_CUSTOM_COLUMNS = ["date", "dataset", "client", "description", "amount_cdf", "status"]

CATEGORY_INCOME_ACCOUNTS = {
    "subscription": ("7060", "Ventes abonnements"),
    "product": ("7070", "Ventes produits"),
    "other": ("7580", "Produits divers"),
}

CATEGORY_EXPENSE_ACCOUNTS = {
    "salary": ("6410", "Salaires"),
    "maintenance": ("6150", "Maintenance"),
    "expense": ("6280", "Charges diverses"),
    "other": ("6580", "Charges diverses"),
}

TREASURY_ACCOUNTS = {
    "cash": ("5710", "Caisse"),
    "mobile_money": ("5125", "Mobile money"),
    "card": ("5120", "Banque"),
    "bank_transfer": ("5120", "Banque"),
    "check": ("5130", "Cheques a encaisser"),
}


def money(value):
    return Decimal(value or "0").quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP)


def format_money(value):
    return f"{money(value):,.2f}".replace(",", " ")


def format_date(value):
    return value.strftime("%d/%m/%Y") if value else ""


def format_datetime(value):
    return timezone.localtime(value).strftime("%d/%m/%Y %H:%M") if value else ""


def local_date(value):
    return timezone.localtime(value).date() if value else None


def get_report_period(params, today=None, default_period="month"):
    today = today or timezone.localdate()
    default_period = default_period if default_period in PERIOD_CHOICES else "month"
    period = params.get("period", default_period)
    period = period if period in PERIOD_CHOICES else "month"

    if period == "today":
        start_date = end_date = today
    elif period == "yesterday":
        start_date = end_date = today - timedelta(days=1)
    elif period == "week":
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
    elif period == "year":
        start_date = today.replace(month=1, day=1)
        end_date = today.replace(month=12, day=31)
    elif period == "custom":
        start_date = parse_date(params.get("date_from") or "")
        end_date = parse_date(params.get("date_to") or "")
        if not start_date or not end_date:
            start_date = today.replace(day=1)
            end_date = today
            period = "month"
        elif start_date > end_date:
            start_date, end_date = end_date, start_date
    else:
        start_date = today.replace(day=1)
        end_date = today

    if period == "custom":
        label = f"Du {format_date(start_date)} au {format_date(end_date)}"
    else:
        label = PERIOD_CHOICES[period]

    return {
        "key": period,
        "label": label,
        "start_date": start_date,
        "end_date": end_date,
        "date_from": start_date.isoformat(),
        "date_to": end_date.isoformat(),
    }


def get_report_section(params):
    section = params.get("section", "journalier")
    return section if section in REPORT_SECTIONS else "journalier"


def query_list(params, name, allowed, default):
    values = []
    if hasattr(params, "getlist"):
        values = params.getlist(name)
    elif params.get(name):
        values = str(params.get(name)).split(",")
    values = [value for value in values if value in allowed]
    return values or list(default)


def payment_queryset(gym, start_date, end_date):
    return (
        Payment.objects.filter(
            gym=gym,
            status="success",
            created_at__date__range=(start_date, end_date),
        )
        .select_related("member", "cash_register", "created_by", "subscription__plan", "product")
        .order_by("created_at", "id")
    )


def account_label(account):
    code, name = account
    return f"{code} - {name}"


def accounts_for_payment(payment):
    treasury_account = TREASURY_ACCOUNTS.get(payment.method, TREASURY_ACCOUNTS["cash"])
    if payment.type == "in":
        counterpart = CATEGORY_INCOME_ACCOUNTS.get(payment.category, CATEGORY_INCOME_ACCOUNTS["other"])
        return treasury_account, counterpart

    counterpart = CATEGORY_EXPENSE_ACCOUNTS.get(payment.category, CATEGORY_EXPENSE_ACCOUNTS["other"])
    return counterpart, treasury_account


def user_label(user):
    if not user:
        return ""
    full_name = user.get_full_name()
    return full_name or user.username


def member_label(member):
    if not member:
        return ""
    return f"{member.first_name} {member.last_name}".strip()


def source_label(payment):
    parts = [payment.source_app, payment.source_model]
    label = " / ".join(part for part in parts if part)
    if payment.source_id:
        label = f"{label} #{payment.source_id}" if label else f"#{payment.source_id}"
    if not label and payment.product_id:
        label = f"products / Product #{payment.product_id}"
    if not label and payment.subscription_id:
        label = f"subscriptions / MemberSubscription #{payment.subscription_id}"
    return label


def piece_reference(payment):
    if payment.transaction_id:
        return payment.transaction_id
    return f"POS-{payment.id:06d}"


def add_summary_bucket(bucket, key, label, payment):
    if key not in bucket:
        bucket[key] = {
            "key": key,
            "label": label,
            "count": 0,
            "entries_cdf": Decimal("0.00"),
            "exits_cdf": Decimal("0.00"),
            "net_cdf": Decimal("0.00"),
        }

    amount = money(payment.amount_cdf)
    bucket[key]["count"] += 1
    if payment.type == "in":
        bucket[key]["entries_cdf"] += amount
        bucket[key]["net_cdf"] += amount
    else:
        bucket[key]["exits_cdf"] += amount
        bucket[key]["net_cdf"] -= amount


def build_register_summaries(gym, start_date, end_date):
    registers = (
        CashRegister.objects.filter(
            gym=gym,
            payments__status="success",
            payments__created_at__date__range=(start_date, end_date),
        )
        .distinct()
        .order_by("opened_at", "id")
    )
    rows = []

    for register in registers:
        period_payments = register.payments.filter(
            gym=gym,
            status="success",
            created_at__date__range=(start_date, end_date),
        )
        entries = money(
            period_payments.filter(type="in").aggregate(total=Sum("amount_cdf"))["total"]
        )
        exits = money(
            period_payments.filter(type="out").aggregate(total=Sum("amount_cdf"))["total"]
        )
        opened_in_period = start_date <= local_date(register.opened_at) <= end_date
        opening_amount = money(register.opening_amount) if opened_in_period else Decimal("0.00")
        theoretical_balance = opening_amount + entries - exits

        rows.append(
            {
                "session": register.session_code or f"Caisse #{register.id}",
                "opened_at": format_datetime(register.opened_at),
                "closed_at": format_datetime(register.closed_at),
                "opened_by": user_label(register.opened_by),
                "closed_by": user_label(register.closed_by),
                "exchange_rate": money(register.exchange_rate),
                "opening_amount": opening_amount,
                "entries_cdf": entries,
                "exits_cdf": exits,
                "theoretical_balance": theoretical_balance,
                "closing_amount": money(register.closing_amount) if register.closing_amount is not None else "",
                "difference": money(register.difference) if register.difference is not None else "",
                "status": "Fermee" if register.is_closed else "Ouverte",
            }
        )

    return rows


def build_accounting_report(gym, period_data):
    category_labels = dict(Payment.CATEGORY_CHOICES)
    method_labels = dict(Payment.PAYMENT_METHODS)
    type_labels = dict(Payment.TRANSACTION_TYPE)

    payments = payment_queryset(gym, period_data["start_date"], period_data["end_date"])
    journal_rows = []
    category_summary = OrderedDict()
    method_summary = OrderedDict()
    total_entries = Decimal("0.00")
    total_exits = Decimal("0.00")
    total_usd_reference = Decimal("0.00")

    for payment in payments:
        amount_cdf = money(payment.amount_cdf)
        amount_usd = money(payment.amount_usd) if payment.amount_usd is not None else ""
        debit_account, credit_account = accounts_for_payment(payment)

        if payment.type == "in":
            total_entries += amount_cdf
        else:
            total_exits += amount_cdf

        if payment.amount_usd is not None:
            total_usd_reference += money(payment.amount_usd)

        add_summary_bucket(
            category_summary,
            payment.category,
            category_labels.get(payment.category, payment.category),
            payment,
        )
        add_summary_bucket(
            method_summary,
            payment.method,
            method_labels.get(payment.method, payment.method),
            payment,
        )

        journal_rows.append(
            {
                "date": format_datetime(payment.created_at),
                "piece": piece_reference(payment),
                "journal": "POS",
                "organization": gym.organization.name,
                "gym": gym.name,
                "cash_session": payment.cash_register.session_code if payment.cash_register else "",
                "type": type_labels.get(payment.type, payment.type),
                "category": category_labels.get(payment.category, payment.category),
                "description": payment.description or "",
                "member": member_label(payment.member),
                "method": method_labels.get(payment.method, payment.method),
                "currency": payment.currency,
                "origin_amount": money(payment.amount),
                "exchange_rate": money(payment.exchange_rate),
                "amount_usd": amount_usd,
                "amount_cdf": amount_cdf,
                "debit_account": account_label(debit_account),
                "credit_account": account_label(credit_account),
                "source": source_label(payment),
                "created_by": user_label(payment.created_by),
            }
        )

    register_rows = build_register_summaries(
        gym,
        period_data["start_date"],
        period_data["end_date"],
    )
    net_total = total_entries - total_exits

    return {
        "organization": gym.organization.name,
        "gym": gym.name,
        "period": period_data,
        "generated_at": format_datetime(timezone.now()),
        "journal_rows": journal_rows,
        "category_summary": list(category_summary.values()),
        "method_summary": list(method_summary.values()),
        "register_rows": register_rows,
        "total_entries_cdf": total_entries,
        "total_exits_cdf": total_exits,
        "net_total_cdf": net_total,
        "total_usd_reference": total_usd_reference,
        "transaction_count": len(journal_rows),
        "register_count": len(register_rows),
    }


def custom_row(
    *,
    date,
    sort_date,
    dataset,
    client="",
    description="",
    amount_cdf="",
    method="",
    status="",
    reference="",
    source="",
):
    return {
        "date": date,
        "sort_date": sort_date,
        "dataset": dataset,
        "client": client,
        "description": description,
        "amount_cdf": amount_cdf,
        "method": method,
        "status": status,
        "reference": reference,
        "source": source,
    }


def build_transaction_rows(gym, period_data):
    method_labels = dict(Payment.PAYMENT_METHODS)
    type_labels = dict(Payment.TRANSACTION_TYPE)
    category_labels = dict(Payment.CATEGORY_CHOICES)
    rows = []

    for payment in payment_queryset(gym, period_data["start_date"], period_data["end_date"]):
        rows.append(
            custom_row(
                date=format_datetime(payment.created_at),
                sort_date=local_date(payment.created_at),
                dataset="Transaction POS",
                client=member_label(payment.member),
                description=payment.description or category_labels.get(payment.category, payment.category),
                amount_cdf=money(payment.amount_cdf),
                method=method_labels.get(payment.method, payment.method),
                status=type_labels.get(payment.type, payment.type),
                reference=piece_reference(payment),
                source=source_label(payment) or "pos",
            )
        )

    return rows


def build_member_rows(gym, period_data):
    rows = []
    members = Member.objects.filter(
        gym=gym,
        created_at__date__range=(period_data["start_date"], period_data["end_date"]),
    ).order_by("created_at", "id")

    for member in members:
        rows.append(
            custom_row(
                date=format_datetime(member.created_at),
                sort_date=local_date(member.created_at),
                dataset="Membre",
                client=member_label(member),
                description=member.phone or member.email or "",
                status=member.get_status_display(),
                reference=f"MEM-{member.id:06d}",
                source="members",
            )
        )

    return rows


def build_access_rows(gym, period_data):
    rows = []
    logs = (
        AccessLog.objects.filter(
            gym=gym,
            check_in_time__date__range=(period_data["start_date"], period_data["end_date"]),
        )
        .select_related("member", "scanned_by")
        .order_by("check_in_time", "id")
    )

    for log in logs:
        rows.append(
            custom_row(
                date=format_datetime(log.check_in_time),
                sort_date=local_date(log.check_in_time),
                dataset="Acces",
                client=member_label(log.member),
                description=log.denial_reason or log.device_used or "Controle acces",
                status="Autorise" if log.access_granted else "Refuse",
                reference=f"ACC-{log.id:06d}",
                source="access",
            )
        )

    return rows


def build_subscription_rows(gym, period_data):
    rows = []
    subscriptions = (
        MemberSubscription.objects.filter(
            gym=gym,
            start_date__range=(period_data["start_date"], period_data["end_date"]),
        )
        .select_related("member", "plan")
        .prefetch_related("payments")
        .order_by("start_date", "id")
    )

    for subscription in subscriptions:
        amount_cdf = money(
            subscription.payments.filter(status="success", type="in").aggregate(total=Sum("amount_cdf"))["total"]
        )
        if subscription.is_paused:
            status = "En pause"
        elif subscription.is_active:
            status = "Actif"
        else:
            status = "Cloture"

        rows.append(
            custom_row(
                date=format_date(subscription.start_date),
                sort_date=subscription.start_date,
                dataset="Abonnement",
                client=member_label(subscription.member),
                description=subscription.plan.name if subscription.plan else "Formule supprimee",
                amount_cdf=amount_cdf if amount_cdf else "",
                status=status,
                reference=f"SUB-{subscription.id:06d}",
                source="subscriptions",
            )
        )

    return rows


def build_register_rows(gym, period_data):
    rows = []
    registers = (
        CashRegister.objects.filter(
            gym=gym,
            payments__status="success",
            payments__created_at__date__range=(period_data["start_date"], period_data["end_date"]),
        )
        .distinct()
        .order_by("opened_at", "id")
    )

    for register in registers:
        period_payments = register.payments.filter(
            gym=gym,
            status="success",
            created_at__date__range=(period_data["start_date"], period_data["end_date"]),
        )
        entries = money(period_payments.filter(type="in").aggregate(total=Sum("amount_cdf"))["total"])
        exits = money(period_payments.filter(type="out").aggregate(total=Sum("amount_cdf"))["total"])
        rows.append(
            custom_row(
                date=format_datetime(register.opened_at),
                sort_date=local_date(register.opened_at),
                dataset="Session de caisse",
                client=user_label(register.opened_by),
                description=register.session_code or f"Caisse #{register.id}",
                amount_cdf=entries - exits,
                method="POS",
                status="Fermee" if register.is_closed else "Ouverte",
                reference=register.session_code or f"Caisse #{register.id}",
                source="pos.CashRegister",
            )
        )

    return rows


CUSTOM_ROW_BUILDERS = {
    "transactions": build_transaction_rows,
    "members": build_member_rows,
    "access": build_access_rows,
    "subscriptions": build_subscription_rows,
    "registers": build_register_rows,
}


def group_custom_rows(rows, grouping):
    if grouping == "none":
        return rows

    buckets = OrderedDict()
    for row in rows:
        sort_date = row.get("sort_date")
        if grouping == "day":
            key = sort_date.isoformat() if sort_date else "sans-date"
            label = format_date(sort_date) if sort_date else "Sans date"
        elif grouping == "week":
            if sort_date:
                iso_year, iso_week, _ = sort_date.isocalendar()
                key = f"{iso_year}-W{iso_week:02d}"
                label = f"Semaine {iso_week:02d}/{iso_year}"
            else:
                key = "sans-date"
                label = "Sans date"
        elif grouping == "month":
            key = sort_date.strftime("%Y-%m") if sort_date else "sans-date"
            label = sort_date.strftime("%m/%Y") if sort_date else "Sans date"
        else:
            key = row["dataset"]
            label = row["dataset"]

        if key not in buckets:
            buckets[key] = {
                "date": label,
                "dataset": "Regroupement",
                "client": "",
                "description": label,
                "amount_cdf": Decimal("0.00"),
                "method": "",
                "status": "0 ligne",
                "reference": key,
                "source": f"group:{grouping}",
                "sort_date": sort_date,
                "count": 0,
            }

        buckets[key]["count"] += 1
        amount = row.get("amount_cdf")
        if isinstance(amount, Decimal):
            buckets[key]["amount_cdf"] += amount

    grouped_rows = []
    for bucket in buckets.values():
        bucket["status"] = f"{bucket['count']} ligne" + ("s" if bucket["count"] > 1 else "")
        grouped_rows.append(bucket)

    return grouped_rows


def build_custom_report(gym, params, period_data, limit=None):
    selected_types = query_list(params, "types", CUSTOM_DATA_TYPES.keys(), DEFAULT_CUSTOM_TYPES)
    selected_columns = query_list(params, "columns", CUSTOM_COLUMNS.keys(), DEFAULT_CUSTOM_COLUMNS)
    grouping = params.get("grouping", "none")
    grouping = grouping if grouping in CUSTOM_GROUPINGS else "none"

    rows = []
    for data_type in selected_types:
        rows.extend(CUSTOM_ROW_BUILDERS[data_type](gym, period_data))

    rows.sort(key=lambda item: (item.get("sort_date") or period_data["start_date"], item.get("reference") or ""))
    rows = group_custom_rows(rows, grouping)
    total_count = len(rows)
    preview_rows = rows[:limit] if limit else rows
    headers = [{"key": key, "label": CUSTOM_COLUMNS[key]} for key in selected_columns]
    for row in preview_rows:
        row["cells"] = [row.get(header["key"], "") for header in headers]

    return {
        "available_types": [{"key": key, "label": label} for key, label in CUSTOM_DATA_TYPES.items()],
        "available_columns": [{"key": key, "label": label} for key, label in CUSTOM_COLUMNS.items()],
        "available_groupings": [{"key": key, "label": label} for key, label in CUSTOM_GROUPINGS.items()],
        "selected_types": selected_types,
        "selected_columns": selected_columns,
        "grouping": grouping,
        "headers": headers,
        "rows": preview_rows,
        "total_count": total_count,
        "preview_count": len(preview_rows),
        "period": period_data,
    }


def custom_report_table_rows(custom_report):
    headers = [header["label"] for header in custom_report["headers"]]
    rows = [headers]
    for row in custom_report["rows"]:
        rows.append([row.get(header["key"], "") for header in custom_report["headers"]])
    return rows


def build_custom_csv_export(custom_report):
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Rapport personnalise GesGym"])
    writer.writerow(["Periode", custom_report["period"]["label"]])
    writer.writerow(["Types", ", ".join(CUSTOM_DATA_TYPES[item] for item in custom_report["selected_types"])])
    writer.writerow(["Regroupement", CUSTOM_GROUPINGS[custom_report["grouping"]]])
    writer.writerow([])
    for row in custom_report_table_rows(custom_report):
        writer.writerow(row)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def build_custom_xlsx_export(custom_report):
    report_rows = [
        ["Rapport personnalise GesGym"],
        ["Periode", custom_report["period"]["label"]],
        ["Types", ", ".join(CUSTOM_DATA_TYPES[item] for item in custom_report["selected_types"])],
        ["Regroupement", CUSTOM_GROUPINGS[custom_report["grouping"]]],
        [],
    ]
    report_rows.extend(custom_report_table_rows(custom_report))

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '</Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Personnalise" sheetId="1" r:id="rId1"/></sheets>'
            '</workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>',
        )
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml(report_rows))
        archive.writestr(
            "xl/styles.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
            '<borders count="1"><border/></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
            '</styleSheet>',
        )

    return stream.getvalue()


def accounting_filename(gym, period_data, extension):
    start = period_data["start_date"].strftime("%Y%m%d")
    end = period_data["end_date"].strftime("%Y%m%d")
    slug = "".join(char.lower() if char.isalnum() else "-" for char in gym.slug).strip("-")
    return f"rapport-comptable-{slug}-{start}-{end}.{extension}"


def summary_sheet_rows(report):
    return [
        ["Rapport comptable GesGym"],
        ["Organisation", report["organization"]],
        ["Gym", report["gym"]],
        ["Periode", report["period"]["label"]],
        ["Du", format_date(report["period"]["start_date"])],
        ["Au", format_date(report["period"]["end_date"])],
        ["Genere le", report["generated_at"]],
        [],
        ["Indicateur", "Valeur"],
        ["Transactions validees", report["transaction_count"]],
        ["Sessions de caisse", report["register_count"]],
        ["Entrees CDF", report["total_entries_cdf"]],
        ["Sorties CDF", report["total_exits_cdf"]],
        ["Solde net CDF", report["net_total_cdf"]],
        ["Reference USD", report["total_usd_reference"]],
        [],
        ["Regle comptable", "Toutes les lignes proviennent du POS et utilisent le montant CDF fige au taux de la caisse."],
    ]


def journal_sheet_rows(report):
    rows = [[
        "Date",
        "Piece",
        "Journal",
        "Organisation",
        "Gym",
        "Session caisse",
        "Type",
        "Categorie",
        "Libelle",
        "Membre",
        "Methode",
        "Devise origine",
        "Montant origine",
        "Taux USD-CDF",
        "Reference USD",
        "Montant CDF",
        "Compte debit",
        "Compte credit",
        "Source",
        "Saisi par",
    ]]
    for row in report["journal_rows"]:
        rows.append([
            row["date"],
            row["piece"],
            row["journal"],
            row["organization"],
            row["gym"],
            row["cash_session"],
            row["type"],
            row["category"],
            row["description"],
            row["member"],
            row["method"],
            row["currency"],
            row["origin_amount"],
            row["exchange_rate"],
            row["amount_usd"],
            row["amount_cdf"],
            row["debit_account"],
            row["credit_account"],
            row["source"],
            row["created_by"],
        ])
    return rows


def summary_table_rows(title, rows):
    table = [[title], ["Libelle", "Nombre", "Entrees CDF", "Sorties CDF", "Solde net CDF"]]
    for row in rows:
        table.append([
            row["label"],
            row["count"],
            row["entries_cdf"],
            row["exits_cdf"],
            row["net_cdf"],
        ])
    return table


def register_sheet_rows(report):
    rows = [[
        "Session",
        "Ouverture",
        "Cloture",
        "Ouvert par",
        "Cloture par",
        "Taux USD-CDF",
        "Fonds ouverture CDF",
        "Entrees CDF",
        "Sorties CDF",
        "Solde theorique CDF",
        "Montant cloture CDF",
        "Ecart CDF",
        "Statut",
    ]]
    for row in report["register_rows"]:
        rows.append([
            row["session"],
            row["opened_at"],
            row["closed_at"],
            row["opened_by"],
            row["closed_by"],
            row["exchange_rate"],
            row["opening_amount"],
            row["entries_cdf"],
            row["exits_cdf"],
            row["theoretical_balance"],
            row["closing_amount"],
            row["difference"],
            row["status"],
        ])
    return rows


def build_csv_export(report):
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")

    for row in summary_sheet_rows(report):
        writer.writerow(row)

    writer.writerow([])
    writer.writerow(["Journal comptable"])
    for row in journal_sheet_rows(report):
        writer.writerow(row)

    writer.writerow([])
    for row in summary_table_rows("Synthese par categorie", report["category_summary"]):
        writer.writerow(row)

    writer.writerow([])
    for row in summary_table_rows("Synthese par methode", report["method_summary"]):
        writer.writerow(row)

    writer.writerow([])
    writer.writerow(["Sessions de caisse"])
    for row in register_sheet_rows(report):
        writer.writerow(row)

    return ("\ufeff" + output.getvalue()).encode("utf-8")


def column_name(index):
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def xml_cell(value, row_index, column_index):
    reference = f"{column_name(column_index)}{row_index}"
    if value is None or value == "":
        return f'<c r="{reference}"/>'
    if isinstance(value, Decimal):
        return f'<c r="{reference}"><v>{value}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{reference}"><v>{value}</v></c>'
    text = escape(str(value))
    return f'<c r="{reference}" t="inlineStr"><is><t>{text}</t></is></c>'


def worksheet_xml(rows):
    rendered_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = "".join(xml_cell(value, row_index, column_index) for column_index, value in enumerate(row, start=1))
        rendered_rows.append(f'<row r="{row_index}">{cells}</row>')

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(rendered_rows)}</sheetData>'
        '</worksheet>'
    )


def build_xlsx_export(report):
    sheets = OrderedDict(
        [
            ("Synthese", summary_sheet_rows(report)),
            ("Journal", journal_sheet_rows(report)),
            ("Categories", summary_table_rows("Synthese par categorie", report["category_summary"])),
            ("Methodes", summary_table_rows("Synthese par methode", report["method_summary"])),
            ("Caisses", register_sheet_rows(report)),
        ]
    )
    stream = io.BytesIO()

    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        overrides = [
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
        ]
        workbook_sheets = []
        workbook_rels = []

        for index, (sheet_name, rows) in enumerate(sheets.items(), start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", worksheet_xml(rows))
            overrides.append(
                f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
            workbook_sheets.append(
                f'<sheet name="{escape(sheet_name)}" sheetId="{index}" r:id="rId{index}"/>'
            )
            workbook_rels.append(
                f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
            )

        workbook_rels.append(
            f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        )

        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'{"".join(overrides)}'
            '</Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            '</Relationships>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets>{"".join(workbook_sheets)}</sheets>'
            '</workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{"".join(workbook_rels)}'
            '</Relationships>',
        )
        archive.writestr(
            "xl/styles.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
            '<borders count="1"><border/></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
            '</styleSheet>',
        )
        archive.writestr(
            "docProps/core.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<dc:title>Rapport comptable GesGym</dc:title>'
            '<dc:creator>GesGym</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{timezone.now().isoformat()}</dcterms:created>'
            '</cp:coreProperties>',
        )
        archive.writestr(
            "docProps/app.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
            'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
            '<Application>GesGym</Application>'
            '</Properties>',
        )

    return stream.getvalue()
