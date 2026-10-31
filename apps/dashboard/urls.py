from django.urls import path

from . import auth, views

app_name = "dashboard"
urlpatterns = [
    path("", views.overview, name="overview"),
    # sign in / sign up / reset
    path("login/", auth.SignInView.as_view(), name="login"),
    path("logout/", auth.logout, name="logout"),
    path("signup/", auth.signup, name="signup"),
    path("pending/", auth.pending, name="pending"),
    path("password-reset/", auth.password_reset, name="password_reset"),
    path("password-reset/sent/", auth.password_reset_done, name="password_reset_done"),
    path("password-reset/<uidb64>/<token>/", auth.password_reset_confirm, name="password_reset_confirm"),
    path("password-reset/done/", auth.password_reset_complete, name="password_reset_complete"),
    path("fleet/", views.fleet, name="fleet"),
    path("fleet/<str:serial>/", views.device_action, name="device_action"),
    path("rentals/", views.rentals, name="rentals"),
    path("rentals/<str:code>/", views.rental_action, name="rental_action"),
    path("payments/", views.payments, name="payments"),
    path("payments/<str:reference>/", views.payment_action, name="payment_action"),
    path("usage/", views.usage, name="usage"),
    path("customers/", views.customers, name="customers"),
]
