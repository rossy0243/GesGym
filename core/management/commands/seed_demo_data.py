from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from access.models import AccessLog
from coaching.models import Coach, CoachSpecialty
from compte.models import UserGymRole
from machines.models import Machine, MaintenanceLog
from members.models import Member, MemberPreRegistration, MemberPreRegistrationLink
from organizations.models import Gym, GymModule, Module, Organization, SensitiveActivityLog
from pos.models import CashRegister, ExchangeRate, Payment
from products.models import Product, StockMovement
from rh.models import Attendance, Employee, PaymentRecord
from subscriptions.models import MemberSubscription, SubscriptionPlan


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

    def handle(self, *args, **options):
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
        products = self._seed_products(gym, register, cashier)
        self._seed_access_logs(gym, members, reception)
        self._seed_coaching(gym, gym_key, members)
        self._seed_machines(gym, register, manager)
        self._seed_rh(gym, register, manager)
        self._seed_pre_registrations(gym)

        SensitiveActivityLog.objects.get_or_create(
            organization=gym.organization,
            gym=gym,
            action="demo.seeded",
            target_type="Gym",
            target_label=gym.name,
            defaults={"actor": manager, "metadata": {"date": str(today), "products": len(products)}},
        )

    def _seed_plans(self, gym):
        specs = [
            ("Journalier", 1, "5.00"),
            ("Mensuel Standard", 30, "30.00"),
            ("Trimestriel Plus", 90, "80.00"),
            ("Annuel VIP", 365, "280.00"),
        ]
        plans = {}
        for name, duration, price in specs:
            plan, _ = SubscriptionPlan.objects.update_or_create(
                gym=gym,
                name=name,
                defaults={
                    "duration_days": duration,
                    "price": Decimal(price),
                    "description": f"Formule demo {name}",
                    "is_active": True,
                },
            )
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
                end = today + timedelta(days=3)
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
                plan = plans["Trimestriel Plus"] if index % 4 == 0 else plans["Mensuel Standard"]
                is_paused = False

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

        UserGymRole.objects.update_or_create(
            user=user,
            gym=member.gym,
            defaults={"role": "accountant", "is_active": True},
        )

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

    def _seed_products(self, gym, register, cashier):
        specs = [
            ("Eau minerale 500ml", "1.00", 80),
            ("Boisson energetique", "2.50", 35),
            ("Proteine Shake", "8.00", 18),
            ("Serviette sport", "6.00", 12),
            ("Gants musculation", "15.00", 6),
        ]
        products = []
        for name, price, quantity in specs:
            product = Product.objects.filter(gym=gym, name=name).first()
            if product:
                product.price = Decimal(price)
                product.quantity = quantity
                product.is_active = True
                product.save()
            else:
                product = Product.objects.create(gym=gym, name=name, price=Decimal(price), quantity=quantity)
            products.append(product)
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
        for index, (name, specialty) in enumerate(coach_specs):
            coach, _ = Coach.objects.update_or_create(
                gym=gym,
                name=name,
                defaults={
                    "phone": f"899{gym.id:03d}{index:03d}",
                    "specialty": specialty,
                    "is_active": True,
                },
            )
            coach.members.clear()
            for member in members[index::2][:4]:
                coach.assign_member(member)

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
        specs = [
            ("Chef de salle", "manager", "18000.00"),
            ("Agent accueil", "reception", "12000.00"),
            ("Caissier", "cashier", "13000.00"),
            ("Coach plateau", "coach", "15000.00"),
            ("Entretien", "cleaner", "9000.00"),
        ]
        employees = []
        for index, (name, role, salary) in enumerate(specs, start=1):
            employee, _ = Employee.objects.update_or_create(
                gym=gym,
                name=f"{name} {gym.name}",
                defaults={
                    "role": role,
                    "phone": f"877{gym.id:03d}{index:03d}",
                    "daily_salary": Decimal(salary),
                    "is_active": True,
                },
            )
            employees.append(employee)

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

    def _seed_pre_registrations(self, gym):
        link, _ = MemberPreRegistrationLink.objects.get_or_create(gym=gym)
        for index in range(1, 3):
            MemberPreRegistration.objects.update_or_create(
                gym=gym,
                phone=f"844{gym.id:03d}{index:03d}",
                defaults={
                    "link": link,
                    "first_name": f"Prospect{index}",
                    "last_name": gym.name.split()[0],
                    "email": f"prospect{index}.{gym.slug}@demo.gesgym.local",
                    "address": f"Adresse prospect {index}",
                    "status": MemberPreRegistration.STATUS_PENDING,
                    "expires_at": timezone.now() + timedelta(days=7 - index),
                },
            )
