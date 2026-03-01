from django import forms
from .models import Member

class MemberCreationForm(forms.ModelForm):

    class Meta:
        model = Member
        fields = ['first_name', 'last_name', 'phone', 'email', 'photo']