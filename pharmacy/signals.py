from datetime import timedelta

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from core.services import send_user_notification

from .models import Order, OrderItem, RefillReminder


@receiver(post_save, sender=OrderItem)
def create_refill_reminder(sender, instance: OrderItem, created: bool, **kwargs):
    if not created:
        return
    reminder_date = timezone.localdate() + timedelta(days=30)
    RefillReminder.objects.get_or_create(
        medicine=instance.medicine,
        patient=instance.order.patient,
        reminder_date=reminder_date,
    )


@receiver(post_save, sender=Order)
def notify_order(sender, instance: Order, created: bool, **kwargs):
    if created:
        send_user_notification(
            instance.patient.user,
            "Pharmacy order created",
            f"Your order #{instance.pk} has been submitted for processing.",
        )
