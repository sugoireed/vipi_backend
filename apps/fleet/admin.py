from django.contrib import admin, messages

from .models import Device, DeviceEvent, Kiosk, Rental


@admin.register(Kiosk)
class KioskAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "kind", "city", "capacity", "active")
    list_filter = ("kind", "city", "active")
    prepopulated_fields = {"code": ("name",)}


class EventInline(admin.TabularInline):
    model = DeviceEvent
    extra = 0
    readonly_fields = ("kind", "rental", "kiosk", "by", "note", "created_at")
    can_delete = False


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("serial", "kind", "model", "status", "kiosk", "battery_cycles", "last_seen_at")
    list_filter = ("status", "kind", "kiosk", "model")
    search_fields = ("serial", "notes")
    inlines = [EventInline]
    actions = ["mark_ready", "send_to_maintenance"]

    @admin.action(description="Mark ready (charged & cleaned)")
    def mark_ready(self, request, queryset):
        for d in queryset.filter(status__in=[Device.Status.CHARGING, Device.Status.MAINTENANCE]):
            d.status = Device.Status.AVAILABLE
            d.save()
            d.log(DeviceEvent.Kind.READY, by=request.user)
        self.message_user(request, "Devices marked ready.", messages.SUCCESS)

    @admin.action(description="Send to maintenance")
    def send_to_maintenance(self, request, queryset):
        for d in queryset.exclude(status=Device.Status.RENTED):
            d.status = Device.Status.MAINTENANCE
            d.save()
            d.log(DeviceEvent.Kind.MAINTENANCE, by=request.user)


@admin.register(Rental)
class RentalAdmin(admin.ModelAdmin):
    list_display = ("code", "user", "plan", "pickup_kiosk", "status", "reserved_for", "due_at", "deposit_status", "late_fee_kes")
    list_filter = ("status", "pickup_kiosk", "deposit_status")
    search_fields = ("code", "user__username", "flight")
    filter_horizontal = ("devices",)
    raw_id_fields = ("user", "payment")
    date_hierarchy = "created_at"
