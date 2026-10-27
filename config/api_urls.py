from django.urls import path

from apps.accounts import api as accounts
from apps.billing import api as billing
from apps.esim import api as esim
from apps.fleet import api as fleet
from apps.translate import api as translate

urlpatterns = [
    path("health/", translate.Health.as_view()),
    path("auth/register/", accounts.RegisterView.as_view()),
    path("auth/login/", accounts.LoginView.as_view()),
    path("me/", accounts.MeView.as_view()),
    path("plans/", billing.PlanList.as_view()),
    path("passes/", billing.MyPasses.as_view()),
    path("purchase/", billing.PurchaseView.as_view()),
    path("payments/<str:reference>/", billing.PaymentDetail.as_view()),
    path("payments/<str:reference>/simulate-paid/", billing.PaymentSimulate.as_view()),
    path("payments/mpesa/callback", billing.MpesaCallback.as_view()),
    path("kiosks/", fleet.KioskList.as_view()),
    path("rentals/", fleet.RentalsView.as_view()),
    path("translate/", translate.TranslateView.as_view()),
    path("esim/bundles/", esim.BundleList.as_view()),
    path("esim/orders/", esim.OrdersView.as_view()),
    path("esim/orders/<str:reference>/", esim.OrderDetail.as_view()),
    path("esim/orders/<str:reference>/qr.png", esim.OrderQr.as_view()),
]
