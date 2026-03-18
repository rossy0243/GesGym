from django.db import models


class GymQuerySet(models.QuerySet):

    def for_gym(self, gym):
        """
        Filtre les données pour un gym spécifique.
        Sécurité multi-tenant.
        """
        return self.filter(gym=gym)


class GymManager(models.Manager):

    def get_queryset(self):
        return GymQuerySet(self.model, using=self._db)

    def for_gym(self, gym):
        return self.get_queryset().for_gym(gym)