# services/dashboard_service.py
from django.db.models import Count, Sum, Avg, Q
from organizations.models import Gym, Organization
from machines.models import Machine, MaintenanceLog

class OrganizationDashboardService:
    """Service pour agréger les données de toutes les salles d'une organisation"""
    
    def __init__(self, organization_id):
        self.org = get_object_or_404(Organization, id=organization_id)
        self.gyms = self.org.gyms.filter(is_active=True)
    
    def get_machines_summary(self):
        """Résumé des machines pour toute l'organisation"""
        machines = Machine.objects.filter(gym__in=self.gyms)
        
        return {
            'total_machines': machines.count(),
            'machines_by_status': machines.values('status').annotate(count=Count('id')),
            'machines_by_gym': machines.values('gym__name').annotate(
                total=Count('id'),
                ok=Count('id', filter=Q(status='ok')),
                maintenance=Count('id', filter=Q(status='maintenance')),
                broken=Count('id', filter=Q(status='broken'))
            ),
            'total_maintenance_cost': MaintenanceLog.objects.filter(
                machine__in=machines
            ).aggregate(total=Sum('cost'))['total'] or 0,
        }
    
    def get_coaching_summary(self):
        """Résumé du coaching pour toute l'organisation"""
        try:
            from coaching.models import Coach
            coaches = Coach.objects.filter(gym__in=self.gyms, is_active=True)
            
            return {
                'total_coaches': coaches.count(),
                'coaches_by_gym': coaches.values('gym__name').annotate(count=Count('id')),
                'avg_members_per_coach': coaches.annotate(
                    member_count=Count('members')
                ).aggregate(avg=Avg('member_count'))['avg'] or 0,
            }
        except ImportError:
            return {'error': 'Module coaching non installé'}
    
    # Ajouter les mêmes pour RH, Products...