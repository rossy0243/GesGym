import uuid
from datetime import timedelta

from django.db import models
from django.utils import timezone
from organizations.models import Gym
from members.models import Member
from django.core.exceptions import ValidationError


def validate_device_host(valeur):
    """
    Accepte une adresse IPv4 ou un nom d'hote.

    Le lecteur est joint soit directement sur le reseau local, soit par un
    tunnel qui lui donne un nom public. Les deux formes doivent passer.
    """
    import ipaddress
    import re

    brut = (valeur or "").strip()
    if not brut:
        raise ValidationError("Adresse du lecteur manquante.")

    try:
        ipaddress.IPv4Address(brut)
        return
    except ValueError:
        pass

    # Nom d'hote : etiquettes alphanumeriques separees par des points.
    motif = r"^(?=.{1,253}$)([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
    if not re.match(motif, brut):
        raise ValidationError(
            "Indiquez une adresse IPv4 (192.168.1.87) ou un nom d'hote "
            "(lecteur-kinshasa.exemple.com)."
        )


class AccessDevice(models.Model):
    """
    Lecteur physique de controle d'acces (borne QR / badge) rattache a un gym.

    Le lecteur pousse ses evenements de scan vers l'endpoint webhook identifie
    par ``webhook_token``; l'application repond en autorisant ou refusant.
    """

    BRAND_HIKVISION = "hikvision"
    BRAND_CHOICES = [
        (BRAND_HIKVISION, "Hikvision (ISAPI)"),
    ]

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="access_devices",
        db_index=True,
    )

    name = models.CharField(max_length=100)

    brand = models.CharField(
        max_length=30,
        choices=BRAND_CHOICES,
        default=BRAND_HIKVISION,
    )

    # Adresse IP sur le reseau local, ou nom d'hote quand le lecteur est
    # joint a travers un tunnel : un serveur heberge ne peut pas atteindre une
    # adresse privee, il passe par un nom public que le tunnel resout.
    host = models.CharField(
        max_length=253,
        validators=[validate_device_host],
        verbose_name="Adresse ou nom d'hote",
    )
    port = models.PositiveIntegerField(default=80)
    use_https = models.BooleanField(default=False)

    # Jeton presente au tunnel pour prouver que l'appel vient bien de notre
    # serveur. Sans lui, quiconque connait l'adresse du tunnel atteindrait le
    # lecteur : on aurait remis le materiel sur Internet.
    tunnel_client_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Identifiant du jeton de tunnel",
    )

    tunnel_client_secret = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Secret du jeton de tunnel",
    )

    username = models.CharField(max_length=64, default="admin")
    # Stocke en clair : le lecteur exige les identifiants a chaque appel ISAPI.
    # A n'exposer ni dans l'admin en liste, ni dans les reponses JSON.
    password = models.CharField(max_length=128, blank=True)

    door_number = models.PositiveSmallIntegerField(default=1)

    open_on_granted = models.BooleanField(
        default=True,
        verbose_name="Ouvrir la porte sur acces autorise",
        help_text=(
            "Declenche le relais de ce lecteur quand un QR code valide est "
            "reconnu par l'application."
        ),
    )

    # Renseignes automatiquement lors du test de connexion.
    model_name = models.CharField(max_length=100, blank=True)
    serial_number = models.CharField(max_length=100, blank=True)
    firmware = models.CharField(max_length=100, blank=True)
    mac_address = models.CharField(max_length=32, blank=True)

    webhook_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    is_active = models.BooleanField(default=True)

    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lecteur d'acces"
        verbose_name_plural = "Lecteurs d'acces"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["gym", "host"],
                name="unique_access_device_host_per_gym",
            ),
        ]
        indexes = [
            models.Index(fields=["gym", "is_active"]),
        ]

    @property
    def tunnel_headers(self):
        """
        En-tetes a presenter au tunnel, vides quand le lecteur est sur le LAN.

        Cloudflare Access reconnait un service par ce couple d'en-tetes. Tant
        qu'ils ne sont pas renseignes, on parle au lecteur en direct.
        """
        if not (self.tunnel_client_id and self.tunnel_client_secret):
            return {}
        return {
            "CF-Access-Client-Id": self.tunnel_client_id,
            "CF-Access-Client-Secret": self.tunnel_client_secret,
        }

    def __str__(self):
        return f"{self.name} ({self.host})"

    # Le lecteur bat toutes les 30 secondes des qu'une destination lui est
    # declaree. Deux minutes absorbent un battement manque sans laisser croire
    # qu'un lecteur mort est encore vivant.
    FRAICHEUR_CONTACT = timedelta(minutes=2)

    @property
    def nous_parle(self):
        """
        Le lecteur pousse-t-il encore ses evenements vers l'application ?

        Ce sens-la traverse tout seul : le lecteur sort vers internet comme un
        navigateur. C'est de lui que dependent le journal des passages et la
        frequentation.
        """
        if not self.last_seen_at:
            return False
        return timezone.now() - self.last_seen_at <= self.FRAICHEUR_CONTACT

    @property
    def est_joignable(self):
        """
        L'application a-t-elle reussi son dernier appel vers le lecteur ?

        Ce sens-la exige d'entrer dans le reseau de la salle. Il porte
        l'ouverture a distance, l'enrolement des visages et la propagation des
        dates de validite.
        """
        return not self.last_error

    @property
    def is_online(self):
        """Conserve pour l'existant : les deux sens doivent fonctionner."""
        return self.nous_parle and self.est_joignable


class AccessLog(models.Model):
    """
    Historique des accès des membres (scan QR, entrée gym).
    """

    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="access_logs",
        db_index=True
    )

    # Une ouverture commandee depuis le tableau de bord n'a pas de membre :
    # quelqu'un a ouvert la porte, sans que personne ne se soit presente. La
    # ligne doit exister quand meme, sinon le geste reste invisible.
    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name="access_logs",
        null=True,
        blank=True,
    )

    check_in_time = models.DateTimeField(auto_now_add=True)

    access_granted = models.BooleanField(default=True)

    device_used = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    device = models.ForeignKey(
        "access.AccessDevice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="access_logs",
    )

    # Un membre peut repasser devant le lecteur le meme jour : il est ressorti
    # a sa voiture, il a oublie quelque chose. Le lecteur decide seul et lui
    # ouvre : refuser dans l'application affichait un feu vert sur le terminal
    # pendant que le journal enregistrait un refus. On accorde donc, en
    # marquant le passage pour ne pas le compter deux fois dans la
    # frequentation.
    is_return = models.BooleanField(
        default=False,
        verbose_name="Retour dans la salle",
        help_text="Passage suivant une entree deja accordee le meme jour.",
    )

    # Numero de l'evenement dans la memoire du lecteur. Sert au rattrapage
    # apres une coupure : il permet de relire le journal du materiel sans
    # recreer deux fois le meme passage.
    device_event_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        verbose_name="Numero d'evenement du lecteur",
    )

    denial_reason = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    scanned_by = models.ForeignKey(
        "compte.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="access_scans"
    )

    class Meta:

        indexes = [
            models.Index(fields=["gym"]),
            models.Index(fields=["device", "device_event_id"]),
            models.Index(fields=["member"]),
            models.Index(fields=["check_in_time"]),
            models.Index(fields=["member", "check_in_time"]),
        ]

        ordering = ["-check_in_time"]

    def clean(self):
        if self.member_id and not self.gym_id:
            self.gym = self.member.gym

        if self.member_id and self.gym_id and self.member.gym_id != self.gym_id:
            raise ValidationError("Le membre n'appartient pas a ce gym.")

    def save(self, *args, **kwargs):
        if self.member_id and not self.gym_id:
            self.gym = self.member.gym
        self.full_clean()
        return super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.member} - {self.check_in_time}"
