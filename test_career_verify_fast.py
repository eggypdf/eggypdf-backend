import unittest
from unittest.mock import patch

import career_routes


class CareerVerificationFastPathTests(unittest.TestCase):
    @patch("career_routes._dodo")
    def test_checkout_verification_uses_linked_payment_directly(self, dodo):
        checkout = {
            "id": "cks_test_123",
            "payment_status": "succeeded",
            "payment_id": "pay_test_456",
        }
        payment = {
            "status": "succeeded",
            "checkout_session_id": "cks_test_123",
            "product_cart": [
                {"product_id": career_routes.DODO_PRODUCT_ID, "quantity": 1}
            ],
        }
        dodo.side_effect = [checkout, payment]

        paid, status = career_routes._verify("cks_test_123")

        self.assertTrue(paid)
        self.assertEqual(status, "succeeded")
        self.assertEqual(dodo.call_count, 2)
        self.assertEqual(dodo.call_args_list[0].args, ("GET", "/checkouts/cks_test_123"))
        self.assertEqual(dodo.call_args_list[1].args, ("GET", "/payments/pay_test_456"))
        self.assertNotIn("/payments", str(dodo.call_args_list[0].kwargs))

    @patch("career_routes._dodo")
    def test_pending_checkout_stops_without_listing_payments(self, dodo):
        dodo.return_value = {
            "id": "cks_test_123",
            "payment_status": "pending",
            "payment_id": None,
        }

        paid, status = career_routes._verify("cks_test_123")

        self.assertFalse(paid)
        self.assertEqual(status, "pending")
        self.assertEqual(dodo.call_count, 1)


if __name__ == "__main__":
    unittest.main()
