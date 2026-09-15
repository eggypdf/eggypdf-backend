import os
import unittest
from unittest.mock import patch

import career_webhook_routes as webhook


class CareerWebhookV1Tests(unittest.TestCase):
    def test_product_mapping_is_limited_to_configured_career_plans(self):
        with patch.dict(os.environ, {
            'DODO_CAREER_MONTHLY_PRODUCT_ID': 'prod_monthly',
            'DODO_CAREER_YEARLY_PRODUCT_ID': 'prod_yearly',
        }):
            self.assertEqual(webhook._plan_for_product('prod_monthly'), 'monthly')
            self.assertEqual(webhook._plan_for_product('prod_yearly'), 'yearly')
            self.assertIsNone(webhook._plan_for_product('prod_unrelated'))


if __name__ == '__main__':
    unittest.main()
