from django.contrib import admin, messages

from .models import EsimBundle, EsimOrder
from .services import provision


@admin.register(EsimBundle)
class EsimBundleAdmin(admin.ModelAdmin):
    list_display = ("plan", "data_gb", "validity_days", "coverage", "provider", "provider_package_id")
    list_filter = ("provider",)


@admin.register(EsimOrder)
class EsimOrderAdmin(admin.ModelAdmin):
    list_display = ("reference", "user", "bundle", "status", "provider", "iccid", "data_used_mb", "data_total_mb", "created_at")
    list_filter = ("status", "provider", "bundle")
    search_fields = ("reference", "iccid", "user__username")
    readonly_fields = ("lpa", "provider_order_id", "attempts", "error", "ready_at", "usage_checked_at", "created_at")
    raw_id_fields = ("user", "payment")
    actions = ["retry_provisioning"]

    @admin.action(description="Retry provisioning (paid orders only)")
    def retry_provisioning(self, request, queryset):
        n = 0
        for o in queryset.filter(status=EsimOrder.Status.FAILED, payment__status="paid"):
            o.attempts = 0
            o.save(update_fields=["attempts"])
            provision(o)
            n += 1
        self.message_user(request, f"Retried {n} order(s).", messages.INFO)
