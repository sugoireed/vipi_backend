from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from .models import Organisation, Profile

User = get_user_model()


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    extra = 0


admin.site.unregister(User)


@admin.register(User)
class VipiUserAdmin(UserAdmin):
    inlines = [ProfileInline]
    list_display = ("username", "first_name", "last_name", "phone", "country", "is_staff", "date_joined")
    search_fields = ("username", "email", "first_name", "last_name", "profile__phone")

    @admin.display(description="Phone")
    def phone(self, obj):
        return obj.profile.phone

    @admin.display(description="Country")
    def country(self, obj):
        return obj.profile.country


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "seats", "price_per_seat_kes", "monthly_value_kes", "contact_name", "active")
    list_filter = ("kind", "active")
    search_fields = ("name", "contact_name", "contact_email")
