from django.urls import path

from . import views


app_name = "pharmacy"

urlpatterns = [
    path("", views.home, name="home"),
    path("cart/add/<int:medicine_id>/", views.add_to_cart, name="add_to_cart"),
    path("checkout/", views.checkout, name="checkout"),
    path("order/<int:order_id>/", views.order_confirmation, name="order_confirmation"),
]
