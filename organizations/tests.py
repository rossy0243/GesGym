from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.db import IntegrityError
from django.test import RequestFactory, TestCase

from compte.models import User
from organizations.admin import DEFAULT_MODULE_CODES, OrganizationAdmin, ensure_default_gym_modules
from organizations.models import Gym, GymModule, Module, Organization
from organizations.module_packs import ensure_gym_modules_for_pack, get_pack_module_codes
from smartclub.access_control import module_is_active, permission_flags


class OrganizationModuleSetupTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.organization = Organization.objects.create(name="Org Test", slug="org-test")
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Test",
            slug="gym-test",
            subdomain="gym-test",
        )

    def test_ensure_default_gym_modules_creates_expected_default_modules_once(self):
        for code in DEFAULT_MODULE_CODES:
            Module.objects.get_or_create(code=code, defaults={"name": code.title()})

        ensure_default_gym_modules(self.gym)
        ensure_default_gym_modules(self.gym)

        active_codes = set(
            GymModule.objects.filter(gym=self.gym, is_active=True).values_list("module__code", flat=True)
        )
        self.assertEqual(active_codes, set(DEFAULT_MODULE_CODES))
        self.assertEqual(GymModule.objects.filter(gym=self.gym).count(), len(DEFAULT_MODULE_CODES))

    def test_gym_slug_can_be_reused_across_organizations_but_not_within_same_organization(self):
        other_org = Organization.objects.create(name="Other Org", slug="other-org")
        Gym.objects.create(
            organization=other_org,
            name="Gym Clone",
            slug="gym-test",
            subdomain="gym-clone",
        )

        with self.assertRaises(IntegrityError):
            Gym.objects.create(
                organization=self.organization,
                name="Gym Duplicate",
                slug="gym-test",
                subdomain="gym-duplicate",
            )

    def test_ensure_gym_modules_for_club_pack_activates_only_expected_modules(self):
        self.organization.subscription_pack = Organization.PACK_CLUB
        self.organization.save(update_fields=["subscription_pack"])

        for code in DEFAULT_MODULE_CODES:
            Module.objects.get_or_create(code=code, defaults={"name": code.title()})

        ensure_gym_modules_for_pack(self.gym)

        active_codes = set(
            GymModule.objects.filter(gym=self.gym, is_active=True).values_list("module__code", flat=True)
        )
        self.assertEqual(active_codes, set(get_pack_module_codes(Organization.PACK_CLUB)))

    def test_admin_switch_to_premium_pack_resyncs_existing_gyms(self):
        second_gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Second",
            slug="gym-second",
            subdomain="gym-second",
        )
        for code in DEFAULT_MODULE_CODES:
            Module.objects.get_or_create(code=code, defaults={"name": code.title()})

        self.organization.subscription_pack = Organization.PACK_CLUB
        self.organization.save(update_fields=["subscription_pack"])
        ensure_gym_modules_for_pack(self.gym, Organization.PACK_CLUB)
        ensure_gym_modules_for_pack(second_gym, Organization.PACK_CLUB)

        admin_instance = OrganizationAdmin(Organization, AdminSite())
        request = self.factory.post("/")
        request.user = User.objects.create_superuser(
            username="org-admin",
            password="superpass123",
            email="org-admin@example.com",
        )
        setattr(request, "session", {})
        setattr(request, "_messages", FallbackStorage(request))

        admin_instance.switch_to_premium_pack(request, Organization.objects.filter(pk=self.organization.pk))

        self.organization.refresh_from_db()
        self.assertEqual(self.organization.subscription_pack, Organization.PACK_PREMIUM)
        for gym in [self.gym, second_gym]:
            active_codes = set(
                GymModule.objects.filter(gym=gym, is_active=True).values_list("module__code", flat=True)
            )
            self.assertEqual(active_codes, set(get_pack_module_codes(Organization.PACK_PREMIUM)))


class OrganizationAccessContextTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.organization = Organization.objects.create(name="Org Context", slug="org-context")
        self.gym = Gym.objects.create(
            organization=self.organization,
            name="Gym Context",
            slug="gym-context",
            subdomain="gym-context",
        )
        self.owner = User.objects.create_user(
            username="owner-context",
            password="pass12345",
            owned_organization=self.organization,
        )
        self.module, _ = Module.objects.get_or_create(code="MEMBERS", defaults={"name": "Members"})
        GymModule.objects.create(gym=self.gym, module=self.module, is_active=True)

    def test_module_is_active_checks_current_gym_only(self):
        request = self.factory.get("/")
        request.user = self.owner
        request.gym = self.gym
        request.organization = self.organization
        request.is_owner = True
        request.role = "owner"

        self.assertTrue(module_is_active(request, "MEMBERS"))

        GymModule.objects.filter(gym=self.gym, module=self.module).update(is_active=False)
        self.assertFalse(module_is_active(request, "MEMBERS"))

    def test_permission_flags_grant_owner_dashboard_capabilities(self):
        request = self.factory.get("/")
        request.user = self.owner
        request.gym = self.gym
        request.organization = self.organization
        request.is_owner = True
        request.role = "owner"

        flags = permission_flags(request)

        self.assertTrue(flags["can_dashboard"])
        self.assertTrue(flags["can_members"])
        self.assertTrue(flags["can_products"])
