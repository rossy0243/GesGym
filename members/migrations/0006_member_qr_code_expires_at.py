import members.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0005_membergoal_memberweightmeasurement_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="member",
            name="qr_code_expires_at",
            field=models.DateTimeField(
                db_index=True,
                default=members.models.default_member_qr_expiry,
            ),
        ),
    ]
