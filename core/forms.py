from django import forms
from .models import Member, Subscription, SubscriptionPlan

class MemberCreationForm(forms.ModelForm):
    class Meta:
        model = Member
        fields = [
            "first_name",
            "last_name",
            "photo",
            "phone",
            "email",
            "status",
            "address",
        ]
        widgets = {
            "address": forms.TextInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }
        
class SubscriptionPlanForm(forms.ModelForm):

    class Meta:
        model = SubscriptionPlan
        fields = [
            "name",
            "duration_days",
            "price",
            "description",
            "is_active"
        ]

        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "duration_days": forms.NumberInput(attrs={"class": "form-control"}),
            "price": forms.NumberInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        
class SubscriptionForm(forms.ModelForm):

    class Meta:
        model = Subscription
        fields = [
            "member",
            "plan",
            "start_date",
            "auto_renew"
        ]

        widgets = {
            "member": forms.Select(attrs={"class":"form-select"}),
            "plan": forms.Select(attrs={"class":"form-select"}),
            "start_date": forms.DateInput(attrs={
                "type":"date",
                "class":"form-control"
            }),
            "auto_renew": forms.CheckboxInput(attrs={"class":"form-check-input"})
        }