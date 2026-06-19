from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from access.models import AccessLog
from coaching.models import (
    Coach,
    CoachSpecialty,
    CoachingFeedback,
    CoachingFollowUp,
    GroupCoachingProgram,
)
from compte.models import UserGymRole
from machines.models import Machine, MaintenanceLog
from members.models import (
    Member,
    MemberGoal,
    MemberPreRegistration,
    MemberPreRegistrationLink,
    MemberWeightMeasurement,
)
from notifications.models import Notification
from organizations.models import Gym, GymModule, Module, Organization, SensitiveActivityLog
from pos.models import CashRegister, ExchangeRate, Payment
from products.models import Product, StockMovement
from rh.models import (
    Attendance,
    Employee,
    LeaveRequest,
    OvertimeEntry,
    PaymentRecord,
    PayrollAdjustment,
    PayrollContributionRule,
    PayrollSlip,
    PayrollWorkflowLog,
)
from subscriptions.models import (
    MemberSubscription,
    SubscriptionOffer,
    SubscriptionPlan,
    SubscriptionRequest,
)


User = get_user_model()
DEMO_PASSWORD = "12345"

MODULES = [
    ("MEMBERS", "Membres"),
    ("SUBSCRIPTIONS", "Abonnements"),
    ("POS", "Point de vente"),
    ("ACCESS", "Controle d'acces"),
    ("PRODUCTS", "Produits"),
    ("MACHINES", "Machines"),
    ("COACHING", "Coaching"),
    ("RH", "Ressources humaines"),
    ("CORE", "Core"),
    ("COMPTE", "Compte"),
    ("WEBSITE", "Site web"),
    ("NOTIFICATIONS", "Notifications"),
]

DEMO_ORGS = [
    {
        "name": "Fit Elite Group",
        "slug": "demo-fit-elite-group",
        "owner": "owner_elite",
        "email": "owner.elite@demo.gesgym.local",
        "gyms": [
            {"key": "gombe", "name": "Elite Gombe Premium", "slug": "elite-gombe-premium"},
            {"key": "limete", "name": "Elite Limete Express", "slug": "elite-limete-express"},
        ],
    },
    {
        "name": "Urban Fit Studio",
        "slug": "demo-urban-fit-studio",
        "owner": "owner_urban",
        "email": "owner.urban@demo.gesgym.local",
        "gyms": [
            {"key": "bandal", "name": "Urban Bandal Studio", "slug": "urban-bandal-studio"},
        ],
    },
]

STAFF_BY_GYM = {
    "gombe": {
        "manager": ("manager_gombe", "Mira", "Gombe"),
        "reception": ("reception_gombe", "Sarah", "Accueil"),
        "cashier": ("cashier_gombe", "Kevin", "Caisse"),
        "coach": ("coach_gombe", "Junior", "Coach"),
    },
    "limete": {
        "manager": ("manager_limete", "Patrick", "Limete"),
        "reception": ("reception_limete", "Nadia", "Accueil"),
        "cashier": ("cashier_limete", "Joel", "Caisse"),
        "coach": ("coach_limete", "Chris", "Coach"),
    },
    "bandal": {
        "manager": ("manager_bandal", "Aline", "Bandal"),
        "reception": ("reception_bandal", "Grace", "Accueil"),
        "cashier": ("cashier_bandal", "Daniel", "Caisse"),
        "coach": ("coach_bandal", "David", "Coach"),
    },
}

MEMBERS_BY_GYM = {
    "gombe": [
        ("member_gombe_01", "Ariane", "Mbala", "811001001", "active"),
        ("member_gombe_02", "Cedric", "Kanku", "811001002", "active"),
        ("member_gombe_03", "Laura", "Mbuyi", "811001003", "expiring"),
        ("member_gombe_04", "Oscar", "Mafuta", "811001004", "expired"),
        ("member_gombe_05", "Nelly", "Tshimanga", "811001005", "suspended"),
        ("member_gombe_06", "Herve", "Lukusa", "811001006", "active"),
        ("member_gombe_07", "Prisca", "Monga", "811001007", "active"),
        ("member_gombe_08", "Steve", "Beya", "811001008", "expired"),
    ],
    "limete": [
        ("member_limete_01", "Rebecca", "Ilunga", "822001001", "active"),
        ("member_limete_02", "Glody", "Kalala", "822001002", "active"),
        ("member_limete_03", "Jessica", "Mpoyi", "822001003", "expiring"),
        ("member_limete_04", "Mike", "Kazadi", "822001004", "expired"),
        ("member_limete_05", "Diane", "Banza", "822001005", "suspended"),
        ("member_limete_06", "Tony", "Kabongo", "822001006", "active"),
    ],
    "bandal": [
        ("member_bandal_01", "Rachel", "Nsenga", "833001001", "active"),
        ("member_bandal_02", "Samuel", "Mutombo", "833001002", "active"),
        ("member_bandal_03", "Linda", "Matondo", "833001003", "expiring"),
        ("member_bandal_04", "Boris", "Tshibangu", "833001004", "expired"),
        ("member_bandal_05", "Esther", "Makiese", "833001005", "suspended"),
        ("member_bandal_06", "Yannick", "Lutumba", "833001006", "active"),
    ],
}


class Command(BaseCommand):
    help = "Cree un jeu de donnees de demonstration GesGym."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Supprime uniquement les organisations demo avant de les recreer.",
        )
        parser.add_argument(
            "--allow-production",
            action="store_true",
            help="Autorise explicitement le seed demo meme avec DJANGO_DEBUG=False.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["allow_production"]:
            self.stderr.write(
                self.style.ERROR(
                    "Seed demo refuse en production. Relancez avec --allow-production si c'est intentionnel."
                )
            )
            return

        if options["reset"]:
            self._reset_demo_data()

        with transaction.atomic():
            self._ensure_modules()
            credentials = []
            for org_spec in DEMO_ORGS:
                organization = self._upsert_organization(org_spec)
                owner = self._upsert_user(
                    username=org_spec["owner"],
                    first_name="Owner",
                    last_name=organization.name.split()[0],
                    email=org_spec["email"],
                    owned_organization=organization,
                )
                credentials.append((organization.name, "Owner", "-", owner.username, DEMO_PASSWORD))

                for gym_spec in org_spec["gyms"]:
                    gym = self._upsert_gym(organization, gym_spec)
                    self._activate_modules(gym)
                    staff = self._seed_staff(gym, gym_spec["key"], credentials)
                    self._seed_gym_data(gym, gym_spec["key"], staff)

        self.stdout.write(self.style.SUCCESS("Base de demonstration prete."))
        self.stdout.write("")
        self.stdout.write("Acces de demonstration:")
        for organization, role, gym_name, username, password in credentials:
            self.stdout.write(
                f"- {organization} | {gym_name} | {role}: {username} / {password}"
            )

    def _reset_demo_data(self):
        slugs = [org["slug"] for org in DEMO_ORGS]
        gyms = Gym.objects.filter(organization__slug__in=slugs)
        MaintenanceLog.objects.filter(machine__gym__in=gyms).delete()
        SubscriptionRequest.objects.filter(gym__in=gyms).delete()
        PaymentRecord.objects.filter(gym__in=gyms).delete()
        Payment.objects.filter(gym__in=gyms).delete()
        Organization.objects.filter(slug__in=slugs).delete()

        demo_usernames = {org["owner"] for org in DEMO_ORGS}
        for staff in STAFF_BY_GYM.values():
            demo_usernames.update(item[0] for item in staff.values())
        for members in MEMBERS_BY_GYM.values():
            demo_usernames.update(item[0] for item in members)
        User.objects.filter(username__in=demo_usernames).delete()

    def _ensure_modules(self):
        for code, name in MODULES:
            Module.objects.get_or_create(
                code=code,
                defaults={"name": name, "description": f"Module {name}"},
            )

    def _upsert_organization(self, spec):
        organization, _ = Organization.objects.update_or_create(
            slug=spec["slug"],
            defaults={
                "name": spec["name"],
                "address": "Kinshasa, RDC",
                "phone": "+243 900 000 000",
                "email": spec["email"],
                "is_active": True,
            },
        )
        return organization

    def _upsert_gym(self, organization, spec):
        gym, _ = Gym.objects.update_or_create(
            organization=organization,
            slug=spec["slug"],
            defaults={
                "name": spec["name"],
                "subdomain": f"demo-{spec['slug']}",
                "is_active": True,
            },
        )
        MemberPreRegistrationLink.objects.get_or_create(gym=gym)
        return gym

    def _activate_modules(self, gym):
        for module in Module.objects.filter(code__in=[code for code, _ in MODULES]):
            GymModule.objects.update_or_create(
                gym=gym,
                module=module,
                defaults={"is_active": True},
            )

    def _upsert_user(self, *, username, first_name, last_name, email, owned_organization=None):
        user, _ = User.objects.update_or_create(
            username=username,
            defaults={
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "is_active": True,
                "is_staff": False,
                "owned_organization": owned_organization,
            },
        )
        user.set_password(DEMO_PASSWORD)
        user.save()
        return user

    def _seed_staff(self, gym, gym_key, credentials):
        staff = {}
        for role, (username, first_name, last_name) in STAFF_BY_GYM[gym_key].items():
            user = self._upsert_user(
                username=username,
                first_name=first_name,
                last_name=last_name,
                email=f"{username}@demo.gesgym.local",
            )
            UserGymRole.objects.update_or_create(
                user=user,
                gym=gym,
                defaults={"role": role, "is_active": True},
            )
            staff[role] = user
            credentials.append((gym.organization.name, role, gym.name, username, DEMO_PASSWORD))
        return staff

    def _seed_gym_data(self, gym, gym_key, staff):
        today = timezone.localdate()
        manager = staff["manager"]
        cashier = staff["cashier"]
        reception = staff["reception"]

        plans = self._seed_plans(gym)
        members = self._seed_members(gym, gym_key, plans)
        register = self._seed_pos(gym, cashier)
        self._seed_subscription_payments(gym, register, members, cashier)
        self._seed_subscription_requests(gym, members, plans, cashier)
        products = self._seed_products(gym, register, cashier)
        self._seed_access_logs(gym, members, reception)
        coaches = self._seed_coaching(gym, gym_key, members)
        self._seed_member_goals(gym, members, coaches, staff["coach"])
        self._seed_machines(gym, register, manager)
        self._seed_rh(gym, register, manager)
        self._seed_notifications(gym, members, manager)
        self._seed_pre_registrations(gym, members, manager)

        SensitiveActivityLog.objects.get_or_create(
            organization=gym.organization,
            gym=gym,
            action="demo.seeded",
            target_type="Gym",
            target_label=gym.name,
            defaults={"actor": manager, "metadata": {"date": str(today), "products": len(products)}},
        )

    def _seed_plans(self, gym):
        offers = {}
        offer_specs = [
            (
                "Acces plateau",
                SubscriptionOffer.CATEGORY_ACCESS,
                "Acces libre a la salle et aux vestiaires.",
                False,
                False,
            ),
            (
                "Coaching individuel",
                SubscriptionOffer.CATEGORY_COACHING,
                "Suivi coach dedie avec objectifs et bilans.",
                True,
                False,
            ),
            (
                "Programme groupe",
                SubscriptionOffer.CATEGORY_CLASS,
                "Participation aux sessions collectives encadrees.",
                False,
                True,
            ),
            (
                "Suivi premium",
                SubscriptionOffer.CATEGORY_COACHING,
                "Coaching individuel et groupe avec priorite manager.",
                True,
                True,
            ),
        ]
        for name, category, description, individual, group in offer_specs:
            offer, _ = SubscriptionOffer.objects.update_or_create(
                gym=gym,
                name=name,
                defaults={
                    "description": description,
                    "category": category,
                    "grants_individual_coaching": individual,
                    "grants_group_coaching": group,
                    "is_active": True,
                },
            )
            offers[name] = offer

        specs = [
            (
                "Journalier",
                1,
                "5.00",
                SubscriptionPlan.COACHING_MODE_NONE,
                SubscriptionPlan.COACHING_LEVEL_STANDARD,
                ["Acces plateau"],
            ),
            (
                "Mensuel Standard",
                30,
                "30.00",
                SubscriptionPlan.COACHING_MODE_INDIVIDUAL,
                SubscriptionPlan.COACHING_LEVEL_STANDARD,
                ["Acces plateau", "Coaching individuel"],
            ),
            (
                "Trimestriel Plus",
                90,
                "80.00",
                SubscriptionPlan.COACHING_MODE_GROUP,
                SubscriptionPlan.COACHING_LEVEL_PREMIUM,
                ["Acces plateau", "Programme groupe"],
            ),
            (
                "Annuel VIP",
                365,
                "280.00",
                SubscriptionPlan.COACHING_MODE_BOTH,
                SubscriptionPlan.COACHING_LEVEL_INTENSIVE,
                ["Acces plateau", "Coaching individuel", "Programme groupe", "Suivi premium"],
            ),
        ]
        plans = {}
        for name, duration, price, coaching_mode, coaching_level, offer_names in specs:
            plan, _ = SubscriptionPlan.objects.update_or_create(
                gym=gym,
                name=name,
                defaults={
                    "duration_days": duration,
                    "price": Decimal(price),
                    "description": f"Formule demo {name}",
                    "coaching_mode": coaching_mode,
                    "coaching_level": coaching_level,
                    "is_active": True,
                },
            )
            plan.offers.set([offers[offer_name] for offer_name in offer_names])
            plans[name] = plan
        return plans

    def _seed_members(self, gym, gym_key, plans):
        today = timezone.localdate()
        members = []
        for index, (username, first_name, last_name, phone, status) in enumerate(MEMBERS_BY_GYM[gym_key], start=1):
            member, _ = Member.objects.update_or_create(
                gym=gym,
                phone=phone,
                defaults={
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": f"{username}@demo.gesgym.local",
                    "address": f"Adresse demo {index}, {gym.name}",
                    "status": "suspended" if status == "suspended" else "active",
                    "is_active": status != "suspended",
                },
            )
            self._ensure_member_user(member, username)
            MemberSubscription.objects.filter(gym=gym, member=member).delete()

            if status == "expired":
                start = today - timedelta(days=55)
                end = today - timedelta(days=25)
                plan = plans["Mensuel Standard"]
                is_paused = False
            elif status == "expiring":
                start = today - timedelta(days=27)
                end = today + timedelta(days=3 if index % 2 else 7)
                plan = plans["Mensuel Standard"]
                is_paused = False
            elif status == "suspended":
                start = today - timedelta(days=12)
                end = today + timedelta(days=18)
                plan = plans["Mensuel Standard"]
                is_paused = True
            else:
                start = today - timedelta(days=(index % 12))
                end = today + timedelta(days=30 + (index % 20))
                if index in {6, 7}:
                    plan = plans["Annuel VIP"] if index == 6 else plans["Trimestriel Plus"]
                elif index % 5 == 0:
                    plan = plans["Annuel VIP"]
                elif index % 4 == 0:
                    plan = plans["Trimestriel Plus"]
                else:
                    plan = plans["Mensuel Standard"]
                is_paused = False

            if index == 1:
                end = today + timedelta(days=1)
            elif index == 2:
                end = today + timedelta(days=7)
            elif index == 6:
                end = today + timedelta(days=15)

            MemberSubscription.objects.create(
                gym=gym,
                member=member,
                plan=plan,
                start_date=start,
                end_date=end,
                is_active=True,
                is_paused=is_paused,
                paused_at=timezone.now() - timedelta(days=2) if is_paused else None,
                auto_renew=index % 2 == 0,
            )
            if status in {"active", "expiring"} and index % 2 == 0:
                previous = MemberSubscription(
                    gym=gym,
                    member=member,
                    plan=plans["Mensuel Standard"],
                    start_date=start - timedelta(days=35),
                    end_date=start - timedelta(days=5),
                    is_active=False,
                    auto_renew=False,
                )
                previous._skip_active_collision_validation = True
                previous.save()
            members.append(member)
        return members

    def _ensure_member_user(self, member, username):
        user = member.user
        if not user:
            user = self._upsert_user(
                username=username,
                first_name=member.first_name,
                last_name=member.last_name,
                email=member.email or f"{username}@demo.gesgym.local",
            )
            member.user = user
            member.save(update_fields=["user"])
        else:
            user.username = username
            user.first_name = member.first_name
            user.last_name = member.last_name
            user.email = member.email or f"{username}@demo.gesgym.local"
            user.is_active = True
            user.set_password(DEMO_PASSWORD)
            user.save()

    def _seed_pos(self, gym, cashier):
        today = timezone.localdate()
        rate = Decimal("2850.00") if "Gombe" in gym.name else Decimal("2840.00")
        if "Bandal" in gym.name:
            rate = Decimal("2865.00")

        ExchangeRate.objects.update_or_create(
            gym=gym,
            date=today,
            defaults={"rate": rate},
        )

        register = CashRegister.objects.filter(gym=gym, is_closed=False).first()
        if not register:
            register = CashRegister.objects.create(
                gym=gym,
                opened_by=cashier,
                opening_amount=Decimal("150000.00"),
                exchange_rate=rate,
            )

        if not CashRegister.objects.filter(gym=gym, is_closed=True, opened_by=cashier).exists():
            previous = CashRegister.objects.create(
                gym=gym,
                opened_by=cashier,
                closed_by=cashier,
                opening_amount=Decimal("120000.00"),
                exchange_rate=rate - Decimal("10.00"),
                closing_amount=Decimal("485000.00"),
                difference=Decimal("0.00"),
                is_closed=True,
            )
            opened_at = timezone.make_aware(datetime.combine(today - timedelta(days=1), time(hour=8)))
            closed_at = timezone.make_aware(datetime.combine(today - timedelta(days=1), time(hour=21)))
            CashRegister.objects.filter(pk=previous.pk).update(opened_at=opened_at, closed_at=closed_at)

        return register

    def _seed_subscription_payments(self, gym, register, members, cashier):
        for index, member in enumerate(members[:5], start=1):
            subscription = member.active_subscription
            if not subscription:
                continue
            description = f"Demo paiement abonnement {member.first_name} {member.last_name}"
            if Payment.objects.filter(gym=gym, source_app="demo", description=description).exists():
                continue
            payment = Payment.objects.create(
                gym=gym,
                cash_register=register,
                member=member,
                subscription=subscription,
                amount=subscription.plan.price,
                amount_usd=subscription.plan.price,
                currency="USD",
                method="cash" if index % 2 else "mobile_money",
                status="success",
                type="in",
                category="subscription",
                description=description,
                source_app="demo",
                source_model="MemberSubscription",
                source_id=subscription.id,
                created_by=cashier,
            )
            Payment.objects.filter(pk=payment.pk).update(
                created_at=timezone.now() - timedelta(days=index)
            )
        pending_member = members[2] if len(members) > 2 else None
        if pending_member:
            subscription = pending_member.latest_active_subscription
            for status, method, label, age in [
                ("pending", "mobile_money", "Mobile money en attente", 0),
                ("failed", "card", "Carte refusee", 2),
            ]:
                description = f"Demo paiement {label} {pending_member.first_name}"
                payment, created = Payment.objects.get_or_create(
                    gym=gym,
                    source_app="demo",
                    description=description,
                    defaults={
                        "cash_register": register,
                        "member": pending_member,
                        "subscription": subscription,
                        "amount": Decimal("30.00"),
                        "amount_usd": Decimal("30.00"),
                        "currency": "USD",
                        "method": method,
                        "status": status,
                        "type": "in",
                        "category": "subscription",
                        "source_model": "MemberSubscription",
                        "source_id": subscription.id if subscription else None,
                        "created_by": cashier,
                    },
                )
                if created:
                    Payment.objects.filter(pk=payment.pk).update(created_at=timezone.now() - timedelta(days=age))

    def _seed_subscription_requests(self, gym, members, plans, cashier):
        SubscriptionRequest.objects.filter(gym=gym).delete()
        statuses = [
            SubscriptionRequest.STATUS_PENDING,
            SubscriptionRequest.STATUS_AWAITING_PAYMENT,
            SubscriptionRequest.STATUS_PAID,
            SubscriptionRequest.STATUS_CANCELLED,
            SubscriptionRequest.STATUS_FAILED,
        ]
        request_plans = [
            plans["Mensuel Standard"],
            plans["Trimestriel Plus"],
            plans["Annuel VIP"],
            plans["Journalier"],
            plans["Mensuel Standard"],
        ]
        for index, (member, status, plan) in enumerate(zip(members, statuses, request_plans), start=1):
            request = SubscriptionRequest.objects.create(
                gym=gym,
                member=member,
                plan=plan,
                requested_by=member.user,
                status=status,
                price_usd=plan.price,
                aggregator_reference=f"DEMO-SUBREQ-{gym.id}-{index:02d}" if status != SubscriptionRequest.STATUS_PENDING else "",
                notes=f"Demande demo {status}",
            )
            SubscriptionRequest.objects.filter(pk=request.pk).update(
                created_at=timezone.now() - timedelta(days=index),
                updated_at=timezone.now() - timedelta(days=max(index - 1, 0)),
            )

    def _seed_products(self, gym, register, cashier):
        specs = [
            ("Eau minerale 500ml", "1.00", 80, True),
            ("Boisson energetique", "2.50", 35, True),
            ("Proteine Shake", "8.00", 18, True),
            ("Serviette sport", "6.00", 2, True),
            ("Gants musculation", "15.00", 0, True),
            ("Ancienne barre proteinee", "3.00", 4, False),
        ]
        products = []
        for name, price, quantity, is_active in specs:
            product = Product.objects.filter(gym=gym, name=name).first()
            if product:
                product.price = Decimal(price)
                product.quantity = quantity
                product.is_active = is_active
                product.save()
            else:
                product = Product.objects.create(
                    gym=gym,
                    name=name,
                    price=Decimal(price),
                    quantity=quantity,
                    is_active=is_active,
                )
            products.append(product)
            if quantity > 0:
                StockMovement.objects.get_or_create(
                    gym=gym,
                    product=product,
                    movement_type="in",
                    reason="Stock initial demo",
                    defaults={"quantity": quantity},
                )

        for index, product in enumerate(products[:3], start=1):
            description = f"Demo vente produit {product.name}"
            if Payment.objects.filter(gym=gym, source_app="demo", description=description).exists():
                continue
            quantity = index + 1
            amount_usd = Decimal(product.price) * quantity
            Payment.objects.create(
                gym=gym,
                cash_register=register,
                product=product,
                amount=amount_usd,
                amount_usd=amount_usd,
                currency="USD",
                method="cash",
                status="success",
                type="in",
                category="product",
                description=description,
                source_app="demo",
                source_model="Product",
                source_id=product.id,
                created_by=cashier,
            )
            product.update_stock(quantity, "out", "Vente POS demo")
        return products

    def _seed_access_logs(self, gym, members, reception):
        AccessLog.objects.filter(gym=gym, member__in=members).delete()
        base = timezone.localdate()
        hours = [6, 7, 12, 17, 18, 18, 19, 20]
        for day_offset in range(0, 9):
            current_day = base - timedelta(days=day_offset)
            for index, member in enumerate(members):
                if index % 3 == day_offset % 3:
                    checked_at = timezone.make_aware(
                        datetime.combine(current_day, time(hour=hours[index % len(hours)], minute=(index * 7) % 60))
                    )
                    granted = member.computed_status == "active"
                    log = AccessLog.objects.create(
                        gym=gym,
                        member=member,
                        access_granted=granted,
                        denial_reason="" if granted else "Abonnement non valide",
                        device_used="QR Scanner" if index % 2 else "Manuel",
                        scanned_by=reception,
                    )
                    AccessLog.objects.filter(pk=log.pk).update(check_in_time=checked_at)

    def _seed_coaching(self, gym, gym_key, members):
        CoachingFeedback.objects.filter(gym=gym).delete()
        CoachingFollowUp.objects.filter(gym=gym).delete()
        GroupCoachingProgram.objects.filter(gym=gym).delete()

        specialties = ["Musculation", "Perte de poids", "Cardio", "Functional training"]
        for name in specialties:
            CoachSpecialty.objects.update_or_create(
                gym=gym,
                name=name,
                defaults={"is_active": True},
            )

        coach_specs = [
            (f"Coach Principal {gym_key.title()}", "Musculation"),
            (f"Coach Cardio {gym_key.title()}", "Cardio"),
        ]
        coach_user = UserGymRole.objects.filter(gym=gym, role="coach", is_active=True).select_related("user").first()
        for index, (name, specialty) in enumerate(coach_specs):
            coach, _ = Coach.objects.update_or_create(
                gym=gym,
                name=name,
                defaults={
                    "user": coach_user.user if coach_user and index == 0 else None,
                    "phone": f"899{gym.id:03d}{index:03d}",
                    "specialty": specialty,
                    "is_active": True,
                },
            )
            if coach_user and index == 0 and coach.user_id != coach_user.user_id:
                coach.user = coach_user.user
                coach.save(update_fields=["user"])
            coach.members.clear()
            for member in members[index::2][:4]:
                if member.has_individual_coaching_access:
                    coach.assign_member(member)

        coaches = list(Coach.objects.filter(gym=gym).order_by("id"))
        if not coaches:
            return []

        group_coach = coaches[-1]
        program, _ = GroupCoachingProgram.objects.update_or_create(
            gym=gym,
            name=f"Transformation 8 semaines {gym_key.title()}",
            defaults={
                "coach": group_coach,
                "objective": "Perte de poids et endurance",
                "description": "Programme collectif demo avec suivi cardio et nutrition.",
                "capacity": 8,
                "is_active": True,
            },
        )
        program.participants.clear()
        for member in members:
            if member.has_group_coaching_access and not program.is_full:
                program.join_member(member)

        follow_up_types = [
            CoachingFollowUp.INTERACTION_ASSESSMENT,
            CoachingFollowUp.INTERACTION_SESSION,
            CoachingFollowUp.INTERACTION_MESSAGE,
        ]
        tracked_members = [member for coach in coaches for member in coach.members.all()]
        for index, member in enumerate(tracked_members[:6], start=1):
            coach = member.coaches.filter(gym=gym).first()
            follow_up = CoachingFollowUp.objects.create(
                gym=gym,
                coach=coach,
                member=member,
                interaction_type=follow_up_types[index % len(follow_up_types)],
                summary=f"Suivi demo {member.first_name}: charge adaptee et objectif confirme.",
                next_action="Planifier un bilan" if index % 2 else "Envoyer programme maison",
                next_follow_up_at=timezone.localdate() + timedelta(days=index),
            )
            CoachingFollowUp.objects.filter(pk=follow_up.pk).update(
                created_at=timezone.now() - timedelta(days=index)
            )

            feedback = CoachingFeedback.objects.create(
                gym=gym,
                coach=coach,
                member=member,
                group_program=program if program.participants.filter(id=member.id).exists() and coach == program.coach else None,
                overall_rating=2 if index == 1 else 4,
                listening_rating=2 if index == 1 else 4,
                clarity_rating=3 if index == 1 else 5,
                motivation_rating=2 if index == 1 else 4,
                availability_rating=2 if index == 1 else 4,
                comment="Besoin d'un rappel manager" if index == 1 else "Progression visible sur la semaine.",
                wants_contact=index == 1,
            )
            CoachingFeedback.objects.filter(pk=feedback.pk).update(
                created_at=timezone.now() - timedelta(days=max(index - 1, 0))
            )

        return coaches

    def _seed_member_goals(self, gym, members, coaches, coach_user):
        MemberGoal.objects.filter(gym=gym).delete()
        if not members:
            return

        goal_specs = [
            (members[0], MemberGoal.GOAL_LOSE_WEIGHT, Decimal("72.00"), [Decimal("82.00"), Decimal("78.50"), Decimal("75.20")], MemberGoal.STATUS_ACTIVE),
            (members[1], MemberGoal.GOAL_GAIN_WEIGHT, Decimal("86.00"), [Decimal("78.00"), Decimal("81.00"), Decimal("84.00")], MemberGoal.STATUS_ACTIVE),
            (members[2], MemberGoal.GOAL_LOSE_WEIGHT, Decimal("68.00"), [Decimal("75.00"), Decimal("70.00"), Decimal("67.80")], MemberGoal.STATUS_ACHIEVED),
        ]
        for index, (member, goal_type, target_weight, weights, expected_status) in enumerate(goal_specs, start=1):
            goal = MemberGoal.objects.create(
                gym=gym,
                member=member,
                goal_type=goal_type,
                target_weight=target_weight,
                target_date=timezone.localdate() + timedelta(days=45 + index * 15),
                measurement_starter=MemberGoal.STARTER_COACH if index % 2 else MemberGoal.STARTER_MEMBER,
                note=f"Objectif demo {index} avec suivi de progression.",
                created_by=coach_user,
                status=MemberGoal.STATUS_ACTIVE,
            )
            for offset, weight in enumerate(weights):
                MemberWeightMeasurement.objects.create(
                    gym=gym,
                    goal=goal,
                    member=member,
                    weight=weight,
                    measured_at=timezone.localdate() - timedelta(days=(len(weights) - offset) * 7),
                    note="Mesure demo",
                    source=MemberWeightMeasurement.SOURCE_COACH if offset == 0 else MemberWeightMeasurement.SOURCE_MEMBER,
                    recorded_by=coach_user,
                )
            goal.refresh_status_from_progress()
            if goal.status != expected_status:
                goal.status = expected_status
                goal.save(update_fields=["status", "updated_at"])

        if len(members) > 3:
            MemberGoal.objects.create(
                gym=gym,
                member=members[3],
                goal_type=MemberGoal.GOAL_GAIN_WEIGHT,
                target_weight=Decimal("90.00"),
                target_date=timezone.localdate() + timedelta(days=90),
                measurement_starter=MemberGoal.STARTER_COACH,
                note="Objectif annule demo pour verifier les etats historiques.",
                created_by=coach_user,
                status=MemberGoal.STATUS_CANCELLED,
            )

    def _seed_machines(self, gym, register, manager):
        specs = [
            ("Tapis de course Pro", "ok"),
            ("Velo elliptique", "ok"),
            ("Banc developpe couche", "maintenance"),
            ("Presse a jambes", "ok"),
            ("Rameur", "broken"),
            ("Station poulie", "ok"),
        ]
        for index, (name, status) in enumerate(specs, start=1):
            machine, _ = Machine.objects.update_or_create(
                gym=gym,
                name=name,
                defaults={
                    "status": status,
                    "purchase_date": timezone.localdate() - timedelta(days=365 + index * 30),
                },
            )
            if status in {"maintenance", "broken"}:
                description = f"Demo maintenance {machine.name}"
                if not Payment.objects.filter(gym=gym, source_app="demo", description=description).exists():
                    payment = Payment.objects.create(
                        gym=gym,
                        cash_register=register,
                        amount=Decimal("45000.00"),
                        currency="CDF",
                        method="cash",
                        status="success",
                        type="out",
                        category="maintenance",
                        description=description,
                        source_app="demo",
                        source_model="Machine",
                        source_id=machine.id,
                        created_by=manager,
                    )
                    MaintenanceLog.objects.create(
                        machine=machine,
                        description="Controle technique demo et remplacement piece",
                        cost=Decimal("45000.00"),
                        pos_payment=payment,
                    )

    def _seed_rh(self, gym, register, manager):
        today = timezone.localdate()
        PayrollWorkflowLog.objects.filter(slip__gym=gym).delete()
        PayrollSlip.objects.filter(gym=gym).delete()
        LeaveRequest.objects.filter(gym=gym).delete()
        OvertimeEntry.objects.filter(gym=gym).delete()
        PayrollAdjustment.objects.filter(gym=gym).delete()
        PayrollContributionRule.objects.filter(gym=gym).delete()

        specs = [
            ("Chef de salle", "manager", Employee.COMPENSATION_MONTHLY, "0.00", "520000.00"),
            ("Agent accueil", "reception", Employee.COMPENSATION_DAILY, "12000.00", "0.00"),
            ("Caissier", "cashier", Employee.COMPENSATION_DAILY, "13000.00", "0.00"),
            ("Coach plateau", "coach", Employee.COMPENSATION_MONTHLY, "0.00", "450000.00"),
            ("Entretien", "cleaner", Employee.COMPENSATION_DAILY, "9000.00", "0.00"),
        ]
        employees = []
        for index, (name, role, compensation_type, daily_salary, monthly_salary) in enumerate(specs, start=1):
            employee, _ = Employee.objects.update_or_create(
                gym=gym,
                name=f"{name} {gym.name}",
                defaults={
                    "role": role,
                    "phone": f"877{gym.id:03d}{index:03d}",
                    "compensation_type": compensation_type,
                    "daily_salary": Decimal(daily_salary),
                    "monthly_salary": Decimal(monthly_salary),
                    "is_active": True,
                },
            )
            employees.append(employee)

        contribution_specs = [
            ("IPR demo", PayrollContributionRule.PARTY_EMPLOYEE_TAX, PayrollContributionRule.CALC_PERCENTAGE, Decimal("3.00"), Decimal("0.00"), 1),
            ("INSS salarie demo", PayrollContributionRule.PARTY_EMPLOYEE_CONTRIBUTION, PayrollContributionRule.CALC_PERCENTAGE, Decimal("1.50"), Decimal("0.00"), 2),
            ("INSS employeur demo", PayrollContributionRule.PARTY_EMPLOYER_CONTRIBUTION, PayrollContributionRule.CALC_PERCENTAGE, Decimal("5.00"), Decimal("0.00"), 3),
            ("Transport fixe demo", PayrollContributionRule.PARTY_EMPLOYER_CONTRIBUTION, PayrollContributionRule.CALC_FIXED, Decimal("0.00"), Decimal("15000.00"), 4),
        ]
        for name, party, calculation_type, rate_percent, fixed_amount, display_order in contribution_specs:
            PayrollContributionRule.objects.create(
                gym=gym,
                name=name,
                party=party,
                calculation_type=calculation_type,
                rate_percent=rate_percent,
                fixed_amount=fixed_amount,
                display_order=display_order,
                is_active=True,
            )

        for employee_index, employee in enumerate(employees):
            for day_offset in range(0, 12):
                attendance_date = today - timedelta(days=day_offset)
                status = "absent" if (day_offset + employee_index) % 7 == 0 else "present"
                Attendance.objects.update_or_create(
                    gym=gym,
                    employee=employee,
                    date=attendance_date,
                    defaults={"status": status},
                )

        LeaveRequest.objects.create(
            gym=gym,
            employee=employees[0],
            leave_type=LeaveRequest.TYPE_PAID,
            start_date=today - timedelta(days=3),
            end_date=today - timedelta(days=2),
            reason="Conge demo approuve",
            status=LeaveRequest.STATUS_APPROVED,
        )
        LeaveRequest.objects.create(
            gym=gym,
            employee=employees[2],
            leave_type=LeaveRequest.TYPE_UNPAID,
            start_date=today - timedelta(days=1),
            end_date=today,
            reason="Absence administrative demo",
            status=LeaveRequest.STATUS_PENDING,
        )
        OvertimeEntry.objects.create(
            gym=gym,
            employee=employees[1],
            work_date=today - timedelta(days=4),
            hours=Decimal("2.50"),
            rate_multiplier=Decimal("1.50"),
            reason="Fermeture tardive demo",
            status=OvertimeEntry.STATUS_APPROVED,
        )
        OvertimeEntry.objects.create(
            gym=gym,
            employee=employees[3],
            work_date=today - timedelta(days=5),
            hours=Decimal("1.50"),
            rate_multiplier=Decimal("1.25"),
            reason="Session coach supplementaire",
            status=OvertimeEntry.STATUS_PENDING,
        )
        PayrollAdjustment.objects.create(
            gym=gym,
            employee=employees[1],
            year=today.year,
            month=today.month,
            adjustment_type=PayrollAdjustment.TYPE_BONUS,
            label="Prime ponctualite demo",
            amount=Decimal("25000.00"),
        )
        PayrollAdjustment.objects.create(
            gym=gym,
            employee=employees[2],
            year=today.year,
            month=today.month,
            adjustment_type=PayrollAdjustment.TYPE_ADVANCE,
            label="Avance salaire demo",
            amount=Decimal("15000.00"),
        )
        PayrollAdjustment.objects.create(
            gym=gym,
            employee=employees[3],
            year=today.year,
            month=today.month,
            adjustment_type=PayrollAdjustment.TYPE_DEDUCTION,
            label="Retenue equipement demo",
            amount=Decimal("10000.00"),
        )

        employee = employees[1]
        amount = employee.calculate_monthly_salary(today.year, today.month)
        if amount and not PaymentRecord.objects.filter(employee=employee, year=today.year, month=today.month).exists():
            payment = Payment.objects.create(
                gym=gym,
                cash_register=register,
                amount=amount,
                currency="CDF",
                method="cash",
                status="success",
                type="out",
                category="salary",
                description=f"Demo salaire {employee.name}",
                source_app="demo",
                source_model="Employee",
                source_id=employee.id,
                created_by=manager,
            )
            PaymentRecord.objects.create(
                employee=employee,
                gym=gym,
                year=today.year,
                month=today.month,
                amount=amount,
                present_days=employee.attendances.filter(
                    date__year=today.year,
                    date__month=today.month,
                    status="present",
                ).count(),
                payment_method="cash",
                reference="DEMO-RH",
                notes="Paiement demo",
                is_paid=True,
                pos_payment=payment,
            )

        for index, employee in enumerate(employees):
            slip = PayrollSlip.ensure_for_period(employee, today.year, today.month)
            if employee == employees[1]:
                PayrollWorkflowLog.objects.create(slip=slip, actor=manager, action=PayrollWorkflowLog.ACTION_PAY, note="Paiement demo POS")
            elif index == 0:
                slip.review(manager)
                slip.approve(manager)
                slip.save(update_fields=["status", "reviewed_at", "reviewed_by", "approved_at", "approved_by", "updated_at"])
                PayrollWorkflowLog.objects.create(slip=slip, actor=manager, action=PayrollWorkflowLog.ACTION_REVIEW, note="Controle manager demo")
                PayrollWorkflowLog.objects.create(slip=slip, actor=manager, action=PayrollWorkflowLog.ACTION_APPROVE, note="Approbation demo")
            elif index == 2:
                slip.review(manager)
                slip.save(update_fields=["status", "reviewed_at", "reviewed_by", "updated_at"])
                PayrollWorkflowLog.objects.create(slip=slip, actor=manager, action=PayrollWorkflowLog.ACTION_REVIEW, note="Verification demo")

    def _seed_notifications(self, gym, members, manager):
        Notification.objects.filter(gym=gym).delete()
        if not members:
            return

        specs = [
            (members[0], "Abonnement proche expiration", "Votre abonnement expire bientot, passez a la reception.", Notification.CHANNEL_IN_APP, Notification.STATUS_SENT, True, ""),
            (members[1], "Paiement en attente", "Votre paiement mobile money est en attente de confirmation.", Notification.CHANNEL_WHATSAPP, Notification.STATUS_PENDING, False, ""),
            (members[2], "Acces refuse", "Votre dernier acces a ete refuse. Merci de regulariser.", Notification.CHANNEL_SMS, Notification.STATUS_SENT, False, ""),
            (members[3], "Email non livre", "Votre notification email n'a pas pu etre envoyee.", Notification.CHANNEL_EMAIL, Notification.STATUS_FAILED, False, "Adresse email rejetee demo"),
        ]
        for index, (member, title, message, channel, status, is_read, error_message) in enumerate(specs, start=1):
            notification = Notification.objects.create(
                gym=gym,
                member=member,
                title=title,
                message=message,
                channel=channel,
                status=status,
                sent_at=timezone.now() - timedelta(hours=index) if status == Notification.STATUS_SENT else None,
                read_at=timezone.now() - timedelta(minutes=index * 10) if is_read else None,
                sent_by=manager,
                error_message=error_message,
            )
            Notification.objects.filter(pk=notification.pk).update(
                created_at=timezone.now() - timedelta(hours=index + 1)
            )

    def _seed_pre_registrations(self, gym, members, manager):
        link, _ = MemberPreRegistrationLink.objects.get_or_create(gym=gym)
        statuses = [
            (MemberPreRegistration.STATUS_PENDING, None, timezone.now() + timedelta(days=6)),
            (MemberPreRegistration.STATUS_PENDING, None, timezone.now() - timedelta(days=1)),
            (MemberPreRegistration.STATUS_CANCELLED, None, timezone.now() + timedelta(days=4)),
            (MemberPreRegistration.STATUS_CONFIRMED, members[-1] if members else None, timezone.now() + timedelta(days=2)),
        ]
        for index, (status, member, expires_at) in enumerate(statuses, start=1):
            defaults = {
                "link": link,
                "first_name": f"Prospect{index}",
                "last_name": gym.name.split()[0],
                "email": f"prospect{index}.{gym.slug}@demo.gesgym.local",
                "address": f"Adresse prospect {index}",
                "status": status,
                "expires_at": expires_at,
                "member": member,
                "confirmed_at": timezone.now() - timedelta(days=1) if status == MemberPreRegistration.STATUS_CONFIRMED else None,
                "confirmed_by": manager if status == MemberPreRegistration.STATUS_CONFIRMED else None,
            }
            MemberPreRegistration.objects.update_or_create(
                gym=gym,
                phone=f"844{gym.id:03d}{index:03d}",
                defaults=defaults,
            )
