import unittest
from unittest.mock import patch

import career_security_patch


class CareerSecurityPatchTests(unittest.TestCase):
    @patch("career_security_patch.grant_career_pro")
    def test_matching_account_checkout_can_link(self, grant):
        grant.return_value = {"status": "active", "user_id": "user-123"}
        record = {
            "paid": True,
            "checkout_id": "cks_test_123",
            "payment_id": "pay_test_123",
            "metadata": {
                "product": "career_pro",
                "account_user_id": "user-123",
            },
        }
        result = career_security_patch.strict_link_paid_record_to_account(
            record, {"id": "user-123"}
        )
        self.assertEqual(result["status"], "active")
        grant.assert_called_once()

    @patch("career_security_patch.grant_career_pro")
    def test_checkout_from_different_account_is_rejected(self, grant):
        record = {
            "paid": True,
            "checkout_id": "cks_test_123",
            "metadata": {
                "product": "career_pro",
                "account_user_id": "paid-user",
            },
        }
        with self.assertRaises(PermissionError):
            career_security_patch.strict_link_paid_record_to_account(
                record, {"id": "different-user"}
            )
        grant.assert_not_called()

    @patch("career_security_patch.grant_career_pro")
    def test_unbound_legacy_checkout_cannot_grant_new_account(self, grant):
        record = {
            "paid": True,
            "checkout_id": "cks_legacy_123",
            "metadata": {"product": "career_pro"},
        }
        with self.assertRaises(PermissionError):
            career_security_patch.strict_link_paid_record_to_account(
                record, {"id": "new-user"}
            )
        grant.assert_not_called()

    @patch("career_security_patch.current_account_user")
    def test_paid_flow_requires_sign_in(self, current_user):
        current_user.side_effect = PermissionError("Sign in to continue.")
        with self.assertRaises(PermissionError):
            career_security_patch.strict_account_user()


if __name__ == "__main__":
    unittest.main()
