from django.urls import path

from . import views

app_name = "dashboard"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("fleet/", views.fleet, name="fleet"),
    path("fleet/<str:serial>/", views.device_action, name="device_action"),
    path("rentals/", views.rentals, name="rentals"),
    path("rentals/<str:code>/", views.rental_action, name="rental_action"),
    path("payments/", views.payments, name="payments"),
    path("payments/<str:reference>/", views.payment_action, name="payment_action"),
    path("usage/", views.usage, name="usage"),
    path("customers/", views.customers, name="customers"),
]
