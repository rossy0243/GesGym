from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.forms import SetPasswordForm

from core.creation_emails import organization_sender


User = get_user_model()


def _password_reset_organization_name(user):
    organization = getattr(user, "owned_organization", None)
    if organization:
        return organization.name

    member = getattr(user, "member_profile", None)
    if member and member.gym_id:
        return member.gym.organization.name

    role = (
        user.gym_roles.filter(
            is_active=True,
            gym__is_active=True,
            gym__organization__is_active=True,
        )
        .select_related("gym__organization")
        .first()
    )
    if role and role.gym_id:
        return role.gym.organization.name

    return ""


class CustomAuthenticationForm(AuthenticationForm):
    remember_me = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(
            attrs={
                "class": "rounded border-gray-300 text-[#004e92] focus:ring-[#004e92]",
            }
        ),
    )

    username = forms.CharField(
        widget=forms.TextInput(attrs={
            "class": "w-full px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#004e92] ",
            "placeholder": "Nom d'utilisateur",
            "autocomplete": "username",
            "autofocus": "autofocus",
        })
    )

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "w-full px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#004e92]",
            "placeholder": "Mot de passe",
            "autocomplete": "current-password",
        })
    )


class StyledPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs.update({
            "class": "w-full px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#004e92]",
            "placeholder": "Adresse email",
            "autocomplete": "email",
        })

    def send_mail(
        self,
        subject_template_name,
        email_template_name,
        context,
        from_email,
        to_email,
        html_email_template_name=None,
    ):
        organization_name = _password_reset_organization_name(context["user"])
        context["brand_name"] = organization_name or "SmartClub Pro"
        super().send_mail(
            subject_template_name,
            email_template_name,
            context,
            organization_sender(organization_name),
            to_email,
            html_email_template_name=html_email_template_name,
        )


class StyledSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].widget.attrs.update({
            "class": "w-full px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#004e92]",
            "placeholder": "Nouveau mot de passe",
            "autocomplete": "new-password",
        })
        self.fields["new_password2"].widget.attrs.update({
            "class": "w-full px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#004e92]",
            "placeholder": "Confirmer le nouveau mot de passe",
            "autocomplete": "new-password",
        })


class CreateUserForm(forms.Form):
    first_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    
    ROLE_CHOICES = (
        ('manager', 'Manager'),
        ('coach', 'Coach'),
        ('reception', 'Réceptionniste'),
        ('cashier', 'Caissier'),
    )
    role = forms.ChoiceField(choices=ROLE_CHOICES, widget=forms.Select(attrs={'class': 'form-control'}))


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        widgets = {
            "first_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Prenom",
            }),
            "last_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Nom",
            }),
            "email": forms.EmailInput(attrs={
                "class": "form-control",
                "placeholder": "Email",
            }),
        }


class UserPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].widget.attrs.update({
            "class": "form-control",
            "placeholder": "Mot de passe actuel",
        })
        self.fields["new_password1"].widget.attrs.update({
            "class": "form-control",
            "placeholder": "Nouveau mot de passe",
        })
        self.fields["new_password2"].widget.attrs.update({
            "class": "form-control",
            "placeholder": "Confirmer le nouveau mot de passe",
        })


class ForcedPasswordChangeForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].widget.attrs.update({
            "class": "form-control",
            "placeholder": "Nouveau mot de passe",
        })
        self.fields["new_password2"].widget.attrs.update({
            "class": "form-control",
            "placeholder": "Confirmer le nouveau mot de passe",
        })
