"""
URL configuration for smartclub project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
from django.views.generic import RedirectView
from notifications.views import notification_dashboard
from website.views import landing


urlpatterns = [
    path('', landing, name='landing'),
    path('health/', lambda request: HttpResponse("ok", content_type="text/plain"), name='health'),
    path('login/', RedirectView.as_view(pattern_name='compte:login', permanent=False), name='login'),
    path('admin/', admin.site.urls),
    path('compte/', include('compte.urls')),
    path('members/', include('members.urls')),
    path('subscriptions/', include('subscriptions.urls')),
    path('pos/', include('pos.urls')),
    path('access/', include('access.urls')),
    path('notifications/', notification_dashboard, name='notifications'),
    path('notifications/', include('notifications.urls')),
    path("coaching/", include("coaching.urls")),
    path("machines/", include("machines.urls")),
    path('rh/', include('rh.urls')),
    path('products/', include('products.urls')),
    path('', include('core.urls')),
]
if settings.SERVE_MEDIA:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
