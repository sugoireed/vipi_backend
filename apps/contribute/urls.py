from django.contrib.auth import views as auth
from django.urls import path, reverse_lazy

from . import views

app_name = "contribute"
urlpatterns = [
    path("", views.home, name="home"),
    path("people/", views.people, name="people"),
    path("translate/", views.translate, name="translate"),
    path("login/", auth.LoginView.as_view(template_name="contribute/login.html", redirect_authenticated_user=True,
                                          next_page=reverse_lazy("contribute:home")), name="login"),
    path("logout/", auth.LogoutView.as_view(next_page=reverse_lazy("contribute:login")), name="logout"),
    path("set-password/<uidb64>/<token>/", auth.PasswordResetConfirmView.as_view(
        template_name="contribute/set_password.html", success_url=reverse_lazy("contribute:home"),
        post_reset_login=True), name="set_password"),
    path("<str:task>/", views.task, name="task"),
    path("<str:task>/<int:pk>/", views.task, name="item"),
]
