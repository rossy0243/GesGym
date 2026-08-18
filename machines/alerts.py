"""
Maintenances a venir.

Une maintenance periodique ne se rappelle pas toute seule : sans signal, la
salle la decouvre le jour ou la machine tombe. Le module compare l'echeance
calculee au delai de prevenance choisi par la salle.
"""

from .models import Machine


def lead_days(gym):
    """Delai de prevenance de la salle, en jours."""
    from organizations.models import Gym

    if gym is None:
        return Gym.MAINTENANCE_ALERT_DEFAULT_DAYS
    return gym.maintenance_alert_lead_days


def upcoming_maintenances(gym):
    """
    Machines dont la maintenance approche ou est depassee, de la plus urgente
    a la moins urgente.

    Chaque entree porte la machine, la date d'echeance, les jours restants et
    l'indication d'un retard, pour que l'affichage n'ait plus de calcul a faire.
    """
    if gym is None:
        return []

    delai = lead_days(gym)
    machines = (
        Machine.objects.filter(gym=gym)
        .exclude(maintenance_interval_days=None)
        .prefetch_related("maintenance_logs")
    )

    resultats = []
    for machine in machines:
        if not machine.maintenance_is_due_soon(delai):
            continue

        restant = machine.days_until_maintenance()
        resultats.append({
            "machine": machine,
            "due_on": machine.next_maintenance_on(),
            "days_left": restant,
            "is_overdue": restant < 0,
        })

    resultats.sort(key=lambda ligne: ligne["days_left"])
    return resultats


def maintenance_alert_summary(gym):
    """Resume prêt a afficher dans un bandeau, ou None s'il n'y a rien a dire."""
    lignes = upcoming_maintenances(gym)
    if not lignes:
        return None

    en_retard = [ligne for ligne in lignes if ligne["is_overdue"]]
    return {
        "entries": lignes,
        "total": len(lignes),
        "overdue_count": len(en_retard),
        "upcoming_count": len(lignes) - len(en_retard),
        "lead_days": lead_days(gym),
        "most_urgent": lignes[0],
    }
