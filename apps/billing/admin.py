from django.contrib import admin, messages

from .models import Pass, Payment, Plan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "kind", "duration_days", "price_kes", "price_usd", "deposit_kes", "active", "sort")
    list_editable = ("price_kes", "price_usd", "deposit_kes", "active", "sort")
    list_filter = ("kind", "active")
    prepopulated_fields = {"code": ("name",)}


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "user", "plan", "amount_kes", "method", "status", "provider_ref", "created_at")
    list_filter = ("status", "method", "plan")
    search_fields = ("reference", "provider_ref", "phone", "user__username")
    readonly_fields = ("raw", "checkout_request_id", "created_at", "paid_at")
    date_hierarchy = "created_at"
    actions = ["confirm_paid"]

    @admin.action(description="Confirm as paid (cash / card received) and grant pass")
    def confirm_paid(self, request, queryset):
        n = 0
        for p in queryset.exclude(status=Payment.Status.PAID):
            p.mark_paid(provider_ref=f"MANUAL-{request.user.username}")
            n += 1
        self.message_user(request, f"{n} payment(s) confirmed.", messages.SUCCESS)


@admin.register(Pass)
class PassAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "source", "organisation", "starts_at", "ends_at", "cancelled")
    list_filter = ("source", "plan", "cancelled")
    search_fields = ("user__username",)
    raw_id_fields = ("user", "payment")
