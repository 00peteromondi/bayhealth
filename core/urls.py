from django.urls import path, reverse_lazy

from .forms import StyledAuthenticationForm, StyledPasswordResetForm, StyledSetPasswordForm
from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path("terms/", views.terms, name="terms"),
    path("privacy/", views.privacy, name="privacy"),
    path("support/", views.support, name="support"),
    path(
        "login/",
        views.BayAfyaLoginView.as_view(
            template_name="core/login.html",
            authentication_form=StyledAuthenticationForm,
        ),
        name="login",
    ),
    path(
        "password/reset/",
        views.BayAfyaPasswordResetView.as_view(
            template_name="core/password_reset.html",
            email_template_name="core/password_reset_email.html",
            subject_template_name="core/password_reset_subject.txt",
            form_class=StyledPasswordResetForm,
            success_url=reverse_lazy("password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password/reset/done/",
        views.BayAfyaPasswordResetDoneView.as_view(template_name="core/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "password/reset/confirm/<uidb64>/<token>/",
        views.BayAfyaPasswordResetConfirmView.as_view(
            template_name="core/password_reset_confirm.html",
            form_class=StyledSetPasswordForm,
            success_url=reverse_lazy("password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "password/reset/complete/",
        views.BayAfyaPasswordResetCompleteView.as_view(template_name="core/password_reset_complete.html"),
        name="password_reset_complete",
    ),
    path("email/verify/resend/", views.resend_email_verification, name="resend_email_verification"),
    path("email/verify/", views.verify_email, name="email_verification_confirm"),
    path("logout/", views.logout_user, name="logout"),
    path("register/", views.register, name="register"),
    path("profile/", views.profile, name="profile"),
    path("profile/password/change/", views.change_password, name="change_password"),
    path("profile/redeem/", views.redeem_hospital_access, name="redeem_hospital_access"),
    path("hospital/access/update/", views.update_hospital_access_status, name="update_hospital_access_status"),
    path("assistant/access/grant/", views.grant_assistant_record_access, name="grant_assistant_record_access"),
    path("notifications/", views.notifications, name="notifications"),
    path("communications/", views.communications, name="communications"),
    path("communications/direct/", views.create_direct_conversation, name="create_direct_conversation"),
    path("communications/<int:conversation_id>/messages/", views.communication_messages, name="communication_messages"),
    path("communications/<int:conversation_id>/messages/send/", views.send_communication_message, name="send_communication_message"),
    path("communications/team/create/", views.create_team_conversation, name="create_team_conversation"),
    path("communications/team/join/", views.join_team_conversation, name="join_team_conversation"),
    path("communications/team/<int:conversation_id>/delete/", views.delete_team_conversation, name="delete_team_conversation"),
    path("notifications/feed/", views.notifications_feed, name="notifications_feed"),
    path("assistant/suggest/", views.assistant_suggest, name="assistant_suggest"),
    path("assistant/chat/", views.assistant_chat, name="assistant_chat"),
    path("assistant/chat/clear/", views.assistant_chat_clear, name="assistant_chat_clear"),
    path("search/suggestions/", views.entity_suggestions, name="entity_suggestions"),
    path("hospital/switch/", views.switch_hospital, name="switch_hospital"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("service-worker.js", views.service_worker, name="service-worker"),
]
