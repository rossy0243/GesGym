# organizations/migrations/XXXX_add_all_modules.py
from django.db import migrations

def create_all_modules(apps, schema_editor):
    Module = apps.get_model('organizations', 'Module')
    
    # TOUS vos modules (apps) actuels
    all_modules = [
        # Modules principaux
        {'code': 'MEMBERS', 'name': 'Membres', 'description': 'Gestion des adhérents et abonnés'},
        {'code': 'SUBSCRIPTIONS', 'name': 'Abonnements', 'description': 'Gestion des abonnements'},
        {'code': 'POS', 'name': 'Point de vente', 'description': 'Gestion des ventes'},
        {'code': 'ACCESS', 'name': 'Accès', 'description': 'Contrôle d\'accès et badges'},
        {'code': 'NOTIFICATIONS', 'name': 'Notifications', 'description': 'Système de notifications'},
        {'code': 'PRODUCTS', 'name': 'Produits', 'description': 'Gestion des produits et stocks'},
        {'code': 'MACHINES', 'name': 'Machines', 'description': 'Gestion des équipements'},
        {'code': 'COACHING', 'name': 'Coaching', 'description': 'Gestion des coachs'},
        {'code': 'RH', 'name': 'RH', 'description': 'Ressources humaines'},
        {'code': 'WEBSITE', 'name': 'Site web', 'description': 'Gestion du site public'},
        {'code': 'COMPTE', 'name': 'Compte', 'description': 'Gestion des comptes utilisateurs'},
        {'code': 'CORE', 'name': 'Core', 'description': 'Fonctionnalités centrales'},
    ]
    
    for module_data in all_modules:
        Module.objects.get_or_create(
            code=module_data['code'],
            defaults={
                'name': module_data['name'],
                'description': module_data['description']
            }
        )

def remove_all_modules(apps, schema_editor):
    Module = apps.get_model('organizations', 'Module')
    codes = ['MEMBERS', 'SUBSCRIPTIONS', 'POS', 'ACCESS', 'NOTIFICATIONS', 
             'PRODUCTS', 'MACHINES', 'COACHING', 'RH', 'WEBSITE', 'COMPTE', 'CORE']
    Module.objects.filter(code__in=codes).delete()

class Migration(migrations.Migration):
    dependencies = [
        ('organizations', '0001_initial'),  # ⚠️ Remplacez par votre dernière migration
    ]

    operations = [
        migrations.RunPython(create_all_modules, remove_all_modules),
    ]