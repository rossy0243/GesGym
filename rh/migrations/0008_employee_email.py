from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rh", "0007_payrollslip_employee_contribution_total_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="email",
            field=models.EmailField(blank=True, db_index=True, max_length=254, null=True),
        ),
    ]
