from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from core.permissions import patient_required
from hospital.models import MedicalRecord
from telemedicine.models import Prescription

from .forms import OrderForm
from .models import Medicine, Order, OrderItem


def _patient_has_bayafya_prescription(patient, medicines):
    medicine_names = [medicine.name.lower() for medicine in medicines if medicine.requires_prescription]
    if not medicine_names:
        return True

    latest_prescription = Prescription.objects.filter(patient=patient).order_by("-issued_at").first()
    if latest_prescription:
        text = f"{latest_prescription.medications} {latest_prescription.instructions}".lower()
        if any(name in text for name in medicine_names):
            return True

    latest_record = MedicalRecord.objects.filter(patient=patient).order_by("-created_at").first()
    if latest_record:
        text = f"{latest_record.prescription} {latest_record.plan} {latest_record.notes}".lower()
        if any(name in text for name in medicine_names):
            return True

    return False


@login_required
def home(request):
    return render(request, "pharmacy/home.html", {"medicines": Medicine.objects.all()})


@login_required
@patient_required
def add_to_cart(request, medicine_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    medicine = get_object_or_404(Medicine, pk=medicine_id)
    if medicine.stock_quantity < 1:
        messages.error(request, f"{medicine.name} is out of stock.")
        return redirect("pharmacy:home")
    cart = request.session.get("cart", {})
    cart[str(medicine.pk)] = cart.get(str(medicine.pk), 0) + 1
    request.session["cart"] = cart
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {
                "ok": True,
                "message": f"{medicine.name} added to cart.",
                "quantity": cart[str(medicine.pk)],
            }
        )
    messages.success(request, f"{medicine.name} added to cart.")
    return redirect("pharmacy:home")


@login_required
@patient_required
def checkout(request):
    patient = getattr(request.user, "patient", None)
    cart = request.session.get("cart", {})
    medicines = Medicine.objects.filter(pk__in=cart.keys())
    cart_rows = []
    total = Decimal("0.00")
    requires_prescription = False

    for medicine in medicines:
        qty = int(cart[str(medicine.pk)])
        subtotal = medicine.price * qty
        total += subtotal
        requires_prescription = requires_prescription or medicine.requires_prescription
        cart_rows.append({"medicine": medicine, "quantity": qty, "subtotal": subtotal})

    if request.method == "POST" and cart_rows and patient:
        form = OrderForm(request.POST, request.FILES)
        if form.is_valid():
            if requires_prescription and not form.cleaned_data["prescription_file"]:
                form.add_error("prescription_file", "Prescription file is required.")
            elif requires_prescription and not _patient_has_bayafya_prescription(patient, [row["medicine"] for row in cart_rows]):
                form.add_error(
                    None,
                    "A doctor-issued BayAfya prescription matching this medicine is required before online purchase can continue.",
                )
            else:
                with transaction.atomic():
                    locked_medicines = {
                        medicine.pk: medicine
                        for medicine in Medicine.objects.select_for_update().filter(
                            pk__in=[row["medicine"].pk for row in cart_rows]
                        )
                    }
                    for row in cart_rows:
                        locked = locked_medicines[row["medicine"].pk]
                        if locked.stock_quantity < row["quantity"]:
                            form.add_error(
                                None,
                                f"Insufficient stock for {locked.name}. Available: {locked.stock_quantity}.",
                            )
                            break
                    else:
                        order = Order.objects.create(
                            patient=patient,
                            total_amount=total,
                            prescription_file=form.cleaned_data["prescription_file"],
                        )
                        for row in cart_rows:
                            locked = locked_medicines[row["medicine"].pk]
                            OrderItem.objects.create(
                                order=order,
                                medicine=locked,
                                quantity=row["quantity"],
                                price=locked.price,
                            )
                            locked.stock_quantity -= row["quantity"]
                            locked.save(update_fields=["stock_quantity"])
                        request.session["cart"] = {}
                        messages.success(request, "Order placed successfully.")
                        return redirect("pharmacy:order_confirmation", order_id=order.pk)
    else:
        form = OrderForm()

    return render(
        request,
        "pharmacy/checkout.html",
        {
            "cart_rows": cart_rows,
            "total": total,
            "form": form,
            "requires_prescription": requires_prescription,
        },
    )


@login_required
def order_confirmation(request, order_id):
    order = get_object_or_404(Order, pk=order_id, patient__user=request.user)
    return render(request, "pharmacy/order_confirmation.html", {"order": order})
