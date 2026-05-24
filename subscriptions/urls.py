# subscriptions/urls.py
from django.urls import path
from .views import (
    create_offer,
    create_plan,
    create_subscription,
    delete_plan,
    edit_offer,
    edit_plan,
    plan_list,
)

app_name = 'subscriptions'

urlpatterns = [
    path('subscription-plans/', plan_list, name='subscription_plan_list'),
    path('subscription-plans/create/', create_plan, name='create_subscription_plan'),
    path('subscription-plans/edit/<int:plan_id>/', edit_plan, name='edit_subscription_plan'),
    path('subscription-plans/delete/<int:plan_id>/', delete_plan, name='delete_subscription_plan'),
    path('subscription-offers/create/', create_offer, name='create_subscription_offer'),
    path('subscription-offers/edit/<int:offer_id>/', edit_offer, name='edit_subscription_offer'),
    path('subscriptions/create/', create_subscription, name='create_subscription'),
]
