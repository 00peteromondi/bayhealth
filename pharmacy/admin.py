from django.contrib import admin

from .models import Medicine, Order, OrderItem, RefillReminder


admin.site.register(Medicine)
admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(RefillReminder)
