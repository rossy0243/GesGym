from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils import timezone
from django.db.models import Sum, Q
from calendar import month_name

from organizations.models import Gym
from .models import Employee, Attendance, PaymentRecord
from .forms import EmployeeForm, AttendanceForm, BulkAttendanceForm, PaymentForm
from datetime import date, timedelta
from decimal import Decimal

@login_required
def employee_list(request, gym_id):
    """Liste des employés"""
    gym = get_object_or_404(Gym, id=gym_id)
    employees = gym.employees.all().order_by('name')
    
    # Filtres
    role_filter = request.GET.get('role')
    if role_filter:
        employees = employees.filter(role=role_filter)
    
    active_filter = request.GET.get('active')
    if active_filter == 'active':
        employees = employees.filter(is_active=True)
    elif active_filter == 'inactive':
        employees = employees.filter(is_active=False)
    
    context = {
        'gym': gym,
        'employees': employees,
        'role_filter': role_filter,
        'active_filter': active_filter,
        'role_choices': Employee.ROLE_CHOICES,
    }
    return render(request, 'rh/employee_list.html', context)

@login_required
def employee_detail(request, gym_id, employee_id):
    """Détail d'un employé avec calcul de salaire"""
    employee = get_object_or_404(Employee, id=employee_id, gym_id=gym_id)
    
    # Mois actuel par défaut
    current_date = timezone.now().date()
    year = int(request.GET.get('year', current_date.year))
    month = int(request.GET.get('month', current_date.month))
    
    # Calcul du salaire du mois sélectionné
    monthly_salary = employee.calculate_monthly_salary(year, month)
    present_days = employee.attendances.filter(
        date__year=year,
        date__month=month,
        status="present"
    ).count()
    
    # Vérifier si déjà payé
    is_paid = PaymentRecord.objects.filter(
        employee=employee,
        year=year,
        month=month,
        is_paid=True
    ).exists()
    
    # Historique des présences du mois
    attendances = employee.attendances.filter(
        date__year=year,
        date__month=month
    ).order_by('-date')
    
    # Historique des paiements
    payments = employee.payments.all().order_by('-year', '-month')
    
    # Mois disponibles (derniers 12 mois)
    available_months = []
    for i in range(12):
        d = current_date - timedelta(days=30*i)
        available_months.append({
            'year': d.year,
            'month': d.month,
            'name': f"{month_name[d.month]} {d.year}"
        })
    
    context = {
        'employee': employee,
        'year': year,
        'month': month,
        'month_name': month_name[month],
        'monthly_salary': monthly_salary,
        'present_days': present_days,
        'is_paid': is_paid,
        'attendances': attendances,
        'payments': payments,
        'available_months': available_months,
    }
    return render(request, 'rh/employee_detail.html', context)

@login_required
def employee_create(request, gym_id):
    """Créer un employé"""
    gym = get_object_or_404(Gym, id=gym_id)
    
    if request.method == 'POST':
        form = EmployeeForm(request.POST)
        if form.is_valid():
            employee = form.save(commit=False)
            employee.gym = gym
            employee.save()
            messages.success(request, f'Employé "{employee.name}" créé avec succès!')
            return redirect('rh:detail', gym_id=gym.id, employee_id=employee.id)
    else:
        form = EmployeeForm()
    
    context = {
        'gym': gym,
        'form': form,
        'title': 'Ajouter un employé',
    }
    return render(request, 'rh/employee_form.html', context)

@login_required
def employee_update(request, gym_id, employee_id):
    """Modifier un employé"""
    employee = get_object_or_404(Employee, id=employee_id, gym_id=gym_id)
    
    if request.method == 'POST':
        form = EmployeeForm(request.POST, instance=employee)
        if form.is_valid():
            form.save()
            messages.success(request, f'Employé "{employee.name}" modifié avec succès!')
            return redirect('rh:detail', gym_id=gym_id, employee_id=employee.id)
    else:
        form = EmployeeForm(instance=employee)
    
    context = {
        'gym': employee.gym,
        'form': form,
        'employee': employee,
        'title': 'Modifier l\'employé',
    }
    return render(request, 'rh/employee_form.html', context)

@login_required
def employee_delete(request, gym_id, employee_id):
    """Désactiver un employé (soft delete)"""
    employee = get_object_or_404(Employee, id=employee_id, gym_id=gym_id)
    
    if request.method == 'POST':
        employee.is_active = False
        employee.save()
        messages.success(request, f'Employé "{employee.name}" désactivé avec succès!')
        return redirect('rh:list', gym_id=gym_id)
    
    context = {
        'employee': employee,
    }
    return render(request, 'rh/employee_confirm_delete.html', context)

@login_required
def attendance_create(request, gym_id):
    """Enregistrer une présence individuelle"""
    gym = get_object_or_404(Gym, id=gym_id)
    
    if request.method == 'POST':
        form = AttendanceForm(request.POST, gym=gym)
        if form.is_valid():
            attendance = form.save(commit=False)
            attendance.gym = gym
            attendance.save()
            messages.success(request, f'Présence enregistrée pour {attendance.employee.name}')
            return redirect('rh:attendance_list', gym_id=gym_id)
    else:
        form = AttendanceForm(gym=gym)
    
    context = {
        'gym': gym,
        'form': form,
        'title': 'Enregistrer une présence',
    }
    return render(request, 'rh/attendance_form.html', context)

@login_required
def attendance_bulk(request, gym_id):
    """Enregistrer les présences en masse pour une date"""
    gym = get_object_or_404(Gym, id=gym_id)
    active_employees = Employee.objects.filter(gym=gym, is_active=True)
    
    if request.method == 'POST':
        form = BulkAttendanceForm(request.POST, gym=gym)
        if form.is_valid():
            attendance_date = form.cleaned_data['date']
            count = 0
            
            for employee in active_employees:
                status = form.cleaned_data.get(f'attendance_{employee.id}')
                if status:
                    # Mettre à jour ou créer
                    Attendance.objects.update_or_create(
                        employee=employee,
                        date=attendance_date,
                        defaults={
                            'status': status,
                            'gym': gym
                        }
                    )
                    count += 1
            
            messages.success(request, f'{count} présences enregistrées pour le {attendance_date}')
            return redirect('rh:attendance_list', gym_id=gym_id)
    else:
        form = BulkAttendanceForm(gym=gym)
        # Date par défaut = aujourd'hui
        form.fields['date'].initial = date.today()
    
    context = {
        'gym': gym,
        'form': form,
        'active_employees': active_employees,
        'title': 'Enregistrement groupé des présences',
    }
    return render(request, 'rh/attendance_bulk.html', context)

@login_required
def attendance_list(request, gym_id):
    """Liste des présences"""
    gym = get_object_or_404(Gym, id=gym_id)
    
    # Filtres
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    employee_id = request.GET.get('employee')
    
    attendances = Attendance.objects.filter(gym=gym)
    
    if date_from:
        attendances = attendances.filter(date__gte=date_from)
    if date_to:
        attendances = attendances.filter(date__lte=date_to)
    if employee_id:
        attendances = attendances.filter(employee_id=employee_id)
    
    attendances = attendances.order_by('-date', 'employee__name')
    
    # Pagination
    paginator = Paginator(attendances, 20)
    page_number = request.GET.get('page')
    attendances_page = paginator.get_page(page_number)
    
    context = {
        'gym': gym,
        'attendances': attendances_page,
        'employees': Employee.objects.filter(gym=gym, is_active=True),
        'date_from': date_from,
        'date_to': date_to,
        'selected_employee': employee_id,
    }
    return render(request, 'rh/attendance_list.html', context)

@login_required
def payroll_dashboard(request, gym_id):
    """Tableau de bord des salaires"""
    gym = get_object_or_404(Gym, id=gym_id)
    current_date = timezone.now().date()
    
    # Mois à afficher (mois courant par défaut)
    year = int(request.GET.get('year', current_date.year))
    month = int(request.GET.get('month', current_date.month))
    
    employees = Employee.objects.filter(gym=gym, is_active=True)
    
    payroll_data = []
    total_salaries = Decimal('0')
    
    for employee in employees:
        salary = employee.calculate_monthly_salary(year, month)
        present_days = employee.attendances.filter(
            date__year=year,
            date__month=month,
            status="present"
        ).count()
        
        is_paid = PaymentRecord.objects.filter(
            employee=employee,
            year=year,
            month=month,
            is_paid=True
        ).exists()
        
        if salary > 0 or present_days > 0:
            payroll_data.append({
                'employee': employee,
                'present_days': present_days,
                'salary': salary,
                'is_paid': is_paid,
            })
            total_salaries += salary
    
    # Mois disponibles
    available_months = []
    for i in range(12):
        d = current_date - timedelta(days=30*i)
        available_months.append({
            'year': d.year,
            'month': d.month,
            'name': f"{month_name[d.month]} {d.year}"
        })
    
    context = {
        'gym': gym,
        'year': year,
        'month': month,
        'month_name': month_name[month],
        'payroll_data': payroll_data,
        'total_salaries': total_salaries,
        'available_months': available_months,
    }
    return render(request, 'rh/payroll_dashboard.html', context)

@login_required
def process_payment(request, gym_id, employee_id, year, month):
    """Traiter le paiement d'un employé"""
    employee = get_object_or_404(Employee, id=employee_id, gym_id=gym_id)
    
    # Vérifier si déjà payé
    existing_payment = PaymentRecord.objects.filter(
        employee=employee,
        year=year,
        month=month
    ).first()
    
    if existing_payment and existing_payment.is_paid:
        messages.warning(request, f'Le salaire de {employee.name} pour {month_name[month]} {year} a déjà été payé!')
        return redirect('rh:payroll_dashboard', gym_id=gym_id)
    
    salary = employee.calculate_monthly_salary(year, month)
    present_days = employee.attendances.filter(
        date__year=year,
        date__month=month,
        status="present"
    ).count()
    
    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.employee = employee
            payment.gym = employee.gym
            payment.year = year
            payment.month = month
            payment.amount = salary
            payment.present_days = present_days
            payment.save()
            
            messages.success(request, f'Paiement de {salary}€ enregistré pour {employee.name}')
            return redirect('rh:payroll_dashboard', gym_id=gym_id)
    else:
        initial = {
            'amount': salary,
        }
        form = PaymentForm()
    
    context = {
        'employee': employee,
        'year': year,
        'month': month,
        'month_name': month_name[month],
        'salary': salary,
        'present_days': present_days,
        'form': form,
    }
    return render(request, 'rh/payment_form.html', context)