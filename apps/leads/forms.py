from collections.abc import Mapping

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

    def __init__(self, *args: object, audience: str | None = None, **kwargs: object) -> None:
        kwargs.setdefault("label_suffix", "")
        raw_initial = kwargs.get("initial")
        base_initial = dict(raw_initial) if isinstance(raw_initial, Mapping) else {}
        if audience == "student":
            base_initial.setdefault("role", DemoRequest.Role.STUDENT)
            kwargs["initial"] = base_initial
        elif audience == "agency":
            base_initial.setdefault("role", DemoRequest.Role.AGENCY)
            kwargs["initial"] = base_initial
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        role = self.fields["role"]
        assert isinstance(role, forms.ChoiceField)  # nosec B101 - a model choice field
        role.choices = [("", "Choose one"), *DemoRequest.Role.choices]
        if audience == "student":
            self.fields["organisation"].label = "Current university (optional)"
            self.fields["message"].label = (
                "Target master's field, countries, or scholarships (optional)"
            )
        elif audience == "agency":
            self.fields["organisation"].label = "Agency or university name"
            self.fields["message"].label = (
                "Annual student volume & white-label workflow needs (optional)"
            )

    def clean_email(self) -> str:
        return str(self.cleaned_data["email"]).strip().lower()
