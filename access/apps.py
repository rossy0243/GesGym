from django.apps import AppConfig


class AccessConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'access'

    def ready(self):
        # Le depart d'un employe demande le retrait de son visage des lecteurs.
        from . import signals  # noqa: F401
