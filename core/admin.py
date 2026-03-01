# core/admin.py
from django.contrib import admin
from .models import Gym, Member

admin.site.register(Gym)
admin.site.register(Member)