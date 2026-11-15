from django import forms


def style_fields(form):
    """Apply Bootstrap classes to every widget on a form."""
    for field in form.fields.values():
        w = field.widget
        if isinstance(w, forms.CheckboxInput):
            w.attrs.setdefault("class", "form-check-input")
        elif isinstance(w, (forms.Select, forms.SelectMultiple)):
            w.attrs.setdefault("class", "form-select")
        elif isinstance(w, forms.CheckboxSelectMultiple):
            pass
        elif isinstance(w, forms.ClearableFileInput):
            w.attrs.setdefault("class", "form-control")
        else:
            w.attrs.setdefault("class", "form-control")
    return form


class BootstrapModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_fields(self)


class BootstrapForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_fields(self)


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        kwargs.setdefault("format", "%Y-%m-%d")
        super().__init__(**kwargs)


class TimeInput(forms.TimeInput):
    input_type = "time"

    def __init__(self, **kwargs):
        kwargs.setdefault("format", "%H:%M")
        super().__init__(**kwargs)
