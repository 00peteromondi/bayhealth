from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Notification, StaffConversation, StaffConversationParticipant, StaffMessage, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "Professional Information",
            {"fields": ("role", "phone", "address", "date_of_birth")},
        ),
    )
    list_display = ("username", "email", "first_name", "last_name", "role", "is_staff")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "is_read", "created_at")
    list_filter = ("is_read", "created_at")


@admin.register(StaffConversation)
class StaffConversationAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "purpose", "hospital", "assistant_enabled", "is_active", "last_message_at")
    list_filter = ("kind", "purpose", "assistant_enabled", "is_active", "hospital")
    search_fields = ("title", "description", "join_code")


@admin.register(StaffConversationParticipant)
class StaffConversationParticipantAdmin(admin.ModelAdmin):
    list_display = ("conversation", "user", "role", "joined_at", "last_read_at")
    list_filter = ("role", "joined_at")


@admin.register(StaffMessage)
class StaffMessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "sender", "kind", "created_at")
    list_filter = ("kind", "created_at")
    search_fields = ("body", "sender_label")
