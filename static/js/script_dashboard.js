
(function() {
    let dashboardData = {
        kpi: {
            activeMembers: 1247,
            activeTrend: 12,
            expiredMembers: 48,
            expiredTrend: 5,
            dailyRevenue: 2450.50,
            dailyRevenueTrend: 8,
            newMembers: 56,
            newTrend: 18,
            monthlyRevenue: 45280.00,
            monthlyNew: 56,
            monthlyRenewals: 128,
            totalVisits: 4250
        },
        salesChartData: {
            labels: ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Jun', 'Jul', 'Aoû', 'Sep', 'Oct', 'Nov', 'Déc'],
            values: [38500, 40200, 42100, 43800, 45280, 46800, 48100, 49500, 51200, 52800, 54300, 56000]
        },
        alerts: {
            expiry7days: 24,
            expiry3days: 15,
            expiry1day: 12,
            pendingPayments: 3,
            pendingAmount: 450
        }
    };

    let currentSiteFilter = 'all';
    let currentPeriodFilter = 'week';
    let currentDashboardTab = 'global';
    let salesChartInstance = null;
    let analyticsRevenueChartInstance = null;
    let analyticsVisitsByCenterChartInstance = null;

    let analyticsData = {
        revenueByCenter: {
            labels: ['Centre Ville', 'Ngaliema', 'Gombe', 'Matete'],
            values: [22000, 12500, 8200, 5200]
        },
        visitsByCenter: {
            labels: ['Centre Ville', 'Ngaliema', 'Gombe', 'Matete'],
            values: [1850, 1020, 780, 640]
        },
        metrics: {
            churnRate: 4.3,
            arpu: 38.5,
            avgDurationMonths: 6.4
        },
        topPlans: [
            { name: '12 mois', revenue: 21500, share: 38 },
            { name: '6 mois', revenue: 14500, share: 26 },
            { name: '3 mois', revenue: 9800, share: 17 },
            { name: '1 mois', revenue: 6200, share: 11 },
            { name: 'Personnalisé', revenue: 3400, share: 8 }
        ],
        segments: [
            { name: 'Premium matin', clients: 120, revenue: 8200 },
            { name: 'Standard soir', clients: 260, revenue: 14500 },
            { name: 'Corporate', clients: 40, revenue: 9800 },
            { name: 'Famille', clients: 35, revenue: 5200 }
        ]
    };

    function updateDashboard() {
        currentSiteFilter = document.getElementById('siteFilter').value;
        currentPeriodFilter = document.getElementById('periodFilter').value;
        document.getElementById('kpiActiveMembers').innerText = dashboardData.kpi.activeMembers;
        document.getElementById('kpiActiveTrend').innerHTML = '+' + dashboardData.kpi.activeTrend + '%';
        document.getElementById('kpiExpiredMembers').innerText = dashboardData.kpi.expiredMembers;
        document.getElementById('kpiExpiredTrend').innerHTML = '+' + dashboardData.kpi.expiredTrend + '%';
        document.getElementById('kpiDailyRevenue').innerText = dashboardData.kpi.dailyRevenue.toFixed(0) + ' $';
        document.getElementById('kpiDailyRevenueTrend').innerHTML = '+' + dashboardData.kpi.dailyRevenueTrend + '%';
        document.getElementById('kpiNewMembers').innerText = dashboardData.kpi.newMembers;
        document.getElementById('kpiNewTrend').innerHTML = '+' + dashboardData.kpi.newTrend + '%';
        document.getElementById('monthlyRevenue').innerText = (dashboardData.kpi.monthlyRevenue/1000).toFixed(1) + 'K $';
        document.getElementById('monthlyNewClients').innerText = dashboardData.kpi.monthlyNew;
        document.getElementById('monthlyRenewals').innerText = dashboardData.kpi.monthlyRenewals;
        document.getElementById('totalVisits').innerText = (dashboardData.kpi.totalVisits/1000).toFixed(1) + 'K';
        document.getElementById('expiry7days').innerText = dashboardData.alerts.expiry7days + ' abonnements expirent dans 7 jours';
        document.getElementById('expiry3days').innerText = dashboardData.alerts.expiry3days + ' abonnements expirent dans 3 jours';
        document.getElementById('expiry1day').innerText = dashboardData.alerts.expiry1day + ' abonnements expirent demain';
        document.getElementById('pendingPayments').innerText = dashboardData.alerts.pendingPayments + ' transactions (' + dashboardData.alerts.pendingAmount + ' $) en attente';
        updateSalesChart();
    }

    function updateSalesChart() {
        var ctx = document.getElementById('salesChart');
        if (!ctx) return;
        ctx = ctx.getContext('2d');
        if (salesChartInstance) salesChartInstance.destroy();
        salesChartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: dashboardData.salesChartData.labels,
                datasets: [{
                    label: 'Revenus (en USD)',
                    data: dashboardData.salesChartData.values,
                    borderColor: '#3454d1',
                    backgroundColor: 'rgba(52, 84, 209, 0.1)',
                    tension: 0.3,
                    fill: true,
                    pointBackgroundColor: '#3454d1',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    pointRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
                scales: {
                    y: { beginAtZero: true, grid: { color: 'rgba(0,0,0,0.05)' }, ticks: { callback: function(v) { return v + ' $'; } } },
                    x: { grid: { display: false } }
                }
            }
        });
    }

    function showDashboardView(tab) {
        currentDashboardTab = tab;
        var globalSection = document.getElementById('globalDashboardSection');
        var analyticsSection = document.getElementById('analyticsSection');
        var isAnalytics = tab === 'analytics';
        if (globalSection && analyticsSection) {
            globalSection.style.display = isAnalytics ? 'none' : 'block';
            analyticsSection.style.display = isAnalytics ? 'block' : 'none';
        }
        var headerTitle = document.querySelector('.page-header-title h5');
        if (headerTitle) headerTitle.textContent = isAnalytics ? 'Tableau de bord - Vue analytique' : 'Tableau de bord - Vue d\'ensemble';
        if (isAnalytics) updateAnalyticsView(); else updateDashboard();
    }

    function updateAnalyticsView() {
        var active = dashboardData.kpi.activeMembers;
        var activeTrend = dashboardData.kpi.activeTrend;
        var elActive = document.getElementById('analyticsActiveMembers');
        var elActiveTrend = document.getElementById('analyticsActiveTrend');
        var elChurn = document.getElementById('analyticsChurnRate');
        var elArpu = document.getElementById('analyticsARPU');
        var elAvgDur = document.getElementById('analyticsAvgDuration');
        if (elActive) elActive.textContent = active.toLocaleString('fr-FR');
        if (elActiveTrend) elActiveTrend.textContent = '+' + activeTrend + '%';
        if (elChurn) elChurn.textContent = analyticsData.metrics.churnRate.toFixed(1) + ' %';
        if (elArpu) elArpu.textContent = analyticsData.metrics.arpu.toFixed(1) + ' $';
        if (elAvgDur) elAvgDur.textContent = analyticsData.metrics.avgDurationMonths.toFixed(1) + ' mois';
        var plansBody = document.getElementById('analyticsTopPlansBody');
        if (plansBody) plansBody.innerHTML = analyticsData.topPlans.map(function(p) {
            return '<tr><td>' + p.name + '</td><td>' + p.revenue.toLocaleString('fr-FR') + ' $</td><td>' + p.share + '%</td></tr>';
        }).join('');
        var segBody = document.getElementById('analyticsSegmentsBody');
        if (segBody) segBody.innerHTML = analyticsData.segments.map(function(s) {
            return '<tr><td>' + s.name + '</td><td>' + s.clients + '</td><td>' + s.revenue.toLocaleString('fr-FR') + ' $</td></tr>';
        }).join('');
        updateAnalyticsCharts();
    }

    function updateAnalyticsCharts() {
        if (typeof Chart === 'undefined') return;
        var revCanvas = document.getElementById('analyticsRevenueByCenterChart');
        var visitsCanvas = document.getElementById('analyticsVisitsByCenterChart');
        if (!revCanvas || !visitsCanvas) return;
        var revCtx = revCanvas.getContext('2d');
        var visitsCtx = visitsCanvas.getContext('2d');
        if (analyticsRevenueChartInstance) analyticsRevenueChartInstance.destroy();
        if (analyticsVisitsByCenterChartInstance) analyticsVisitsByCenterChartInstance.destroy();
        analyticsRevenueChartInstance = new Chart(revCtx, {
            type: 'bar',
            data: {
                labels: analyticsData.revenueByCenter.labels,
                datasets: [{ label: 'Revenus (USD)', data: analyticsData.revenueByCenter.values, backgroundColor: '#3454d1' }]
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { callback: function(v) { return v + ' $'; } } } } }
        });
        analyticsVisitsByCenterChartInstance = new Chart(visitsCtx, {
            type: 'doughnut',
            data: {
                labels: analyticsData.visitsByCenter.labels,
                datasets: [{ data: analyticsData.visitsByCenter.values, backgroundColor: ['#3454d1', '#10b981', '#f59e0b', '#ef4444'] }]
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
        });
    }

    function refreshDashboard() {
        updateDashboard();
        if (typeof Swal !== 'undefined') {
            Swal.fire({ icon: 'success', title: 'Données actualisées', text: 'Les statistiques ont été mises à jour avec succès!', confirmButtonColor: '#3454d1', timer: 2000, showConfirmButton: false });
        } else { alert('Données mises à jour avec succès!'); }
    }

    function exportChartData() {
        if (typeof Swal !== 'undefined') Swal.fire({ icon: 'info', title: 'Export en cours', text: 'Préparation du rapport d\'évolution des revenus...', confirmButtonColor: '#3454d1' });
        else alert('Export des données du graphique...');
    }

    function setNavSubmenuActive(prefix, tab, defaultTab) {
        var t = tab || defaultTab;
        ['global', 'analytics'].forEach(function(id) {
            var el = document.getElementById(prefix + id);
            if (el) el.classList.toggle('active', id === t);
        });
    }

    document.addEventListener('DOMContentLoaded', function() {
        if (document.querySelector('.b-brand .logo-sm')) document.querySelector('.b-brand .logo-sm').style.display = 'none';
        var urlParams = new URLSearchParams(window.location.search);
        var tabParam = urlParams.get('tab');
        var tab = ['global', 'analytics'].indexOf(tabParam) !== -1 ? tabParam : 'global';
        setNavSubmenuActive('nav-dashboard-', tab, 'global');
        showDashboardView(tab);
    });
})();
