import os
import unittest
from unittest.mock import patch

from flask import Flask

import career_billing_routes as billing
import career_subscription_routes as subscription


class BillingV1Tests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(billing.billing_bp)
        self.app.register_blueprint(subscription.subscription_bp)
        self.client = self.app.test_client()
        self.env = patch.dict(os.environ, {
            "DODO_CAREER_MONTHLY_PRODUCT_ID": "prod_monthly",
            "DODO_CAREER_YEARLY_PRODUCT_ID": "prod_yearly",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_plans_lock_expected_pricing(self):
        data = self.client.get('/api/billing/plans').get_json()
        self.assertEqual(data['default_plan'], 'yearly')
        self.assertEqual(data['monthly']['price_usd'], 6.99)
        self.assertEqual(data['yearly']['price_usd'], 48)
        self.assertEqual(data['monthly']['credits'], 2000)
        self.assertEqual(data['yearly']['credits'], 2000)

    @patch.object(billing, '_entitlement_full')
    @patch.object(billing, 'wallet')
    @patch.object(billing, '_save_subscription_fields')
    @patch.object(billing, '_subscription_record')
    @patch.object(billing, '_payment_record')
    @patch.object(billing, '_checkout_record')
    @patch.object(billing, '_user')
    def test_checkout_verification_binds_account_and_product(self, user, checkout, payment, sub, save, wallet, entitlement):
        user.return_value = {'id': 'user-1', 'email': 'u@example.com'}
        checkout.return_value = {'payment_status': 'succeeded', 'payment_id': 'pay_1'}
        payment.return_value = {
            'status': 'succeeded',
            'checkout_session_id': 'cks_1',
            'subscription_id': 'sub_1',
            'metadata': {'account_user_id': 'user-1'},
        }
        sub.return_value = {
            'subscription_id': 'sub_1',
            'product_id': 'prod_yearly',
            'status': 'active',
            'metadata': {'account_user_id': 'user-1'},
        }
        entitlement.return_value = {'status': 'active'}
        wallet.return_value = {'balance': 2000, 'monthly_allowance': 2000}

        response = self.client.get('/api/billing/checkout/cks_1')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['paid'])
        self.assertTrue(data['active'])
        self.assertEqual(data['plan'], 'yearly')
        save.assert_called_once()

    @patch.object(billing, '_payment_record')
    @patch.object(billing, '_checkout_record')
    @patch.object(billing, '_user')
    def test_checkout_rejects_different_account(self, user, checkout, payment):
        user.return_value = {'id': 'user-1'}
        checkout.return_value = {'payment_status': 'succeeded', 'payment_id': 'pay_1'}
        payment.return_value = {
            'status': 'succeeded',
            'checkout_session_id': 'cks_1',
            'subscription_id': 'sub_1',
            'metadata': {'account_user_id': 'user-2'},
        }
        response = self.client.get('/api/billing/checkout/cks_1')
        self.assertEqual(response.status_code, 403)
        self.assertIn('different EggyPDF account', response.get_json()['error'])

    @patch.object(billing, '_subscription_record')
    @patch.object(billing, '_payment_record')
    @patch.object(billing, '_checkout_record')
    @patch.object(billing, '_user')
    def test_checkout_rejects_wrong_product(self, user, checkout, payment, sub):
        user.return_value = {'id': 'user-1'}
        checkout.return_value = {'payment_status': 'succeeded', 'payment_id': 'pay_1'}
        payment.return_value = {
            'status': 'succeeded',
            'checkout_session_id': 'cks_1',
            'subscription_id': 'sub_1',
            'metadata': {'account_user_id': 'user-1'},
        }
        sub.return_value = {'subscription_id': 'sub_1', 'product_id': 'prod_other', 'status': 'active'}
        response = self.client.get('/api/billing/checkout/cks_1')
        self.assertEqual(response.status_code, 403)
        self.assertIn('not an EggyPDF Career Pro plan', response.get_json()['error'])

    @patch.object(subscription, '_patch_local')
    @patch.object(subscription.career_routes, '_dodo')
    @patch.object(subscription, '_entitlement')
    @patch.object(subscription, 'current_account_user')
    def test_cancel_stops_next_renewal_not_current_access(self, current_user, entitlement, dodo, patch_local):
        current_user.return_value = {'id': 'user-1'}
        entitlement.return_value = {
            'status': 'active',
            'source': 'dodo',
            'plan': 'yearly',
            'dodo_subscription_id': 'sub_123',
            'current_period_end': '2027-09-15T00:00:00Z',
            'cancel_at_period_end': False,
        }
        dodo.return_value = {
            'subscription_id': 'sub_123',
            'status': 'active',
            'cancel_at_next_billing_date': True,
            'next_billing_date': '2027-09-15T00:00:00Z',
        }
        response = self.client.post('/api/billing/subscription/cancel-renewal', json={})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['cancel_at_period_end'])
        self.assertEqual(data['access_ends_at'], '2027-09-15T00:00:00Z')
        dodo.assert_called_once_with('PATCH', '/subscriptions/sub_123', json={'cancel_at_next_billing_date': True})
        patch_local.assert_called_once_with('user-1', period_end='2027-09-15T00:00:00Z')


if __name__ == '__main__':
    unittest.main()
