from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0004_organization_contact_sensitiveactivitylog"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="subscription_pack",
            field=models.CharField(
                choices=[("club", "Pack Club"), ("premium", "Pack Premium")],
                default="premium",
                max_length=20,
            ),
        ),
    ]
