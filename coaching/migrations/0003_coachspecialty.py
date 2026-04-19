from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("coaching", "0002_coach_members"),
        ("organizations", "0004_organization_contact_sensitiveactivitylog"),
    ]

    operations = [
        migrations.CreateModel(
            name="CoachSpecialty",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "gym",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="coach_specialties",
                        to="organizations.gym",
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
                "indexes": [
                    models.Index(fields=["gym", "is_active"], name="coaching_co_gym_id_e3fa02_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("gym", "name"), name="unique_coach_specialty_per_gym"),
                ],
            },
        ),
    ]
