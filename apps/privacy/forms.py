
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q

from apps.privacy.documents import LANGUAGES

CONSENT_TEXT = (
    "I agree to the Terms of Service and consent to the processing of my personal data as "
    "described in the Privacy Notice, including its transfer to the countries it lists."
)



class SignupForm(forms.Form):
    full_name = forms.CharField(max_length=150)
    #: auth_user.username is varchar(150), and the address is the username.
    email = forms.EmailField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput, min_length=12)
    language = forms.ChoiceField(choices=[(code, code) for code in LANGUAGES], initial="en")
    consent = forms.BooleanField(required=True, label=CONSENT_TEXT)

    def clean_email(self) -> str:
        email = str(self.cleaned_data["email"]).strip().lower()
        taken = Q(username__iexact=email) | Q(email__iexact=email)
        if get_user_model().objects.filter(taken).exists():
            raise forms.ValidationError("An account with this e-mail already exists.", code="taken")
        return email

    def clean_password(self) -> str:
        password = str(self.cleaned_data["password"])
        validate_password(password)
        return password
