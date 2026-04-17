from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0002_add_all_modules"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="logo",
            field=models.ImageField(blank=True, null=True, upload_to="organizations/logos/"),
        ),
    ]
