# compte/urls.py
from django.urls import path
from . import views
from .views import CustomLoginView
from django.contrib.auth.views import LogoutView

app_name = 'compte'

urlpatterns = [
    path('login/', CustomLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(next_page='compte:login'), name='logout'),
    path('create-staff/', views.create_staff, name='create_staff'),
]