from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("compte", "0005_alter_usergymrole_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="force_password_change",
            field=models.BooleanField(
                default=False,
                help_text="Oblige l'utilisateur a definir un nouveau mot de passe a la prochaine connexion.",
            ),
        ),
    ]
