from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.models import User

from .models import Medicine, Order


class PharmacyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="patient_rx", password="SafePass123!", role=User.Role.PATIENT
        )
        self.medicine = Medicine.objects.create(
            name="Antibiotic",
            price=Decimal("10.00"),
            stock_quantity=5,
            requires_prescription=True,
        )

    def test_checkout_decrements_stock(self):
        self.client.login(username="patient_rx", password="SafePass123!")
        self.client.post(reverse("pharmacy:add_to_cart", args=[self.medicine.pk]))
        response = self.client.post(
            reverse("pharmacy:checkout"),
            {
                "prescription_file": SimpleUploadedFile("rx.txt", b"valid prescription"),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.medicine.refresh_from_db()
        self.assertEqual(self.medicine.stock_quantity, 4)
        self.assertEqual(Order.objects.count(), 1)
