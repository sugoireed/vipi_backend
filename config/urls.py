from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

admin.site.site_header = "Vipi! admin"
admin.site.site_title = "Vipi! admin"
admin.site.index_title = "Platform data"

urlpatterns = [
    path("", RedirectView.as_view(url="/dashboard/", permanent=False)),
    path("admin/", admin.site.urls),
    path("api/v1/", include("config.api_urls")),
    path("contribute/", include("apps.contribute.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
]
