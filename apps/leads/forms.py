from django import forms

from .models import DemoRequest


class DemoRequestForm(forms.ModelForm):  # type: ignore[type-arg]
    class Meta:
        model = DemoRequest
        fields = ("full_name", "email", "role", "organisation", "country", "message")
        labels = {
            "full_name": "Name and surname",
            "email": "Email",
            "role": "I am a",
            "organisation": "Organisation (optional)",
            "country": "Country (optional)",
            "message": "What would you like to see? (optional)",
        }
        widgets = {"message": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        role = self.fields["role"]
        assert isinstance(role, forms.ChoiceField)  # nosec B101 - a model choice field
        role.choices = [("", "Choose one"), *DemoRequest.Role.choices]

    def clean_email(self) -> str:
        return str(self.cleaned_data["email"]).strip().lower()
