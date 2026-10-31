"""Dashboard sign in, sign up, pending approval and password reset."""
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.debug import sensitive_post_parameters

from .access import REQUEST_GROUP

User = get_user_model()


class SignInForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "That email and password don't match. Check both, or reset your password.",
        "inactive": "This account is switched off. Ask an admin to turn it back on.",
    }
    username = forms.CharField(label="Email", widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "email", "placeholder": "you@vipikenya.com"}))
    password = forms.CharField(label="Password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "placeholder": "Your password"}))

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class SignUpForm(forms.Form):
    name = forms.CharField(label="Full name", max_length=120, widget=forms.TextInput(attrs={"autocomplete": "name", "placeholder": "Wanjiru Njoroge", "autofocus": True}))
    email = forms.EmailField(label="Work email", widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "you@vipikenya.com"}))
    phone = forms.CharField(label="Phone (optional)", max_length=20, required=False, widget=forms.TextInput(attrs={"autocomplete": "tel", "placeholder": "07xx xxx xxx"}))
    password1 = forms.CharField(label="Password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "placeholder": "At least 8 characters"}))
    password2 = forms.CharField(label="Confirm password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "placeholder": "Type it again"}))

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists. Sign in instead, or reset the password.")
        return email

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords don't match.")
        if p1 and not self.errors.get("password1"):
            first, _, last = (data.get("name") or "").strip().partition(" ")
            try:
                validate_password(p1, User(username=data.get("email") or "", email=data.get("email") or "", first_name=first, last_name=last))
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return data


class SignInView(auth_views.LoginView):
    template_name = "dashboard/auth/login.html"
    authentication_form = SignInForm
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        return reverse("dashboard:overview")


@sensitive_post_parameters("password1", "password2")
def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard:overview")
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        first, _, last = d["name"].strip().partition(" ")
        user = User.objects.create_user(username=d["email"], email=d["email"], password=d["password1"],
                                        first_name=first, last_name=last.strip())  # never staff here
        user.groups.add(Group.objects.get_or_create(name=REQUEST_GROUP)[0])
        profile = getattr(user, "profile", None)
        if profile is not None and d["phone"]:
            profile.phone = d["phone"]
            profile.save(update_fields=["phone"])
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Account created. An admin will approve your access.")
        return redirect("dashboard:pending")
    return render(request, "dashboard/auth/signup.html", {"form": form})


def pending(request):
    if not request.user.is_authenticated:
        return redirect("dashboard:login")
    if request.user.is_staff:
        return redirect("dashboard:overview")
    return render(request, "dashboard/auth/pending.html")


logout = auth_views.LogoutView.as_view(next_page=reverse_lazy("dashboard:login"))

password_reset = auth_views.PasswordResetView.as_view(
    template_name="dashboard/auth/reset.html",
    email_template_name="dashboard/auth/reset_email.txt",
    subject_template_name="dashboard/auth/reset_subject.txt",
    success_url=reverse_lazy("dashboard:password_reset_done"))
password_reset_done = auth_views.PasswordResetDoneView.as_view(template_name="dashboard/auth/reset_done.html")
password_reset_confirm = auth_views.PasswordResetConfirmView.as_view(
    template_name="dashboard/auth/reset_confirm.html", success_url=reverse_lazy("dashboard:password_reset_complete"))
password_reset_complete = auth_views.PasswordResetCompleteView.as_view(template_name="dashboard/auth/reset_complete.html")
