from django import forms
from .models import Member

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
        ]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }