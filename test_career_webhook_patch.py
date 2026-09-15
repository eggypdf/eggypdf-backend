import base64
import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import patch

from flask import Flask

from career_webhook_patch import verify_dodo_webhook


class CareerWebhookPatchTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def _headers(self, body: bytes, secret_bytes: bytes, webhook_id="msg_test_123"):
        timestamp = str(int(time.time()))
        signed = webhook_id.encode() + b"." + timestamp.encode() + b"." + body
        signature = base64.b64encode(
            hmac.new(secret_bytes, signed, hashlib.sha256).digest()
        ).decode()
        return {
            "webhook-id": webhook_id,
            "webhook-timestamp": timestamp,
            "webhook-signature": f"v1,bad-signature v1,{signature}",
        }

    def test_accepts_space_delimited_standard_webhooks_signature(self):
        body = json.dumps({"type": "subscription.active", "data": {}}).encode()
        secret_bytes = b"eggy-webhook-test-secret"
        secret = "whsec_" + base64.b64encode(secret_bytes).decode()
        headers = self._headers(body, secret_bytes)
        with patch.dict("os.environ", {"DODO_PAYMENTS_WEBHOOK_SECRET": secret}, clear=False):
            with self.app.test_request_context("/", method="POST", data=body, headers=headers):
                self.assertEqual(verify_dodo_webhook(body), "msg_test_123")

    def test_rejects_invalid_signature(self):
        body = b'{"type":"subscription.active"}'
        secret_bytes = b"eggy-webhook-test-secret"
        secret = "whsec_" + base64.b64encode(secret_bytes).decode()
        timestamp = str(int(time.time()))
        headers = {
            "webhook-id": "msg_test_bad",
            "webhook-timestamp": timestamp,
            "webhook-signature": "v1,definitely-not-valid",
        }
        with patch.dict("os.environ", {"DODO_PAYMENTS_WEBHOOK_SECRET": secret}, clear=False):
            with self.app.test_request_context("/", method="POST", data=body, headers=headers):
                with self.assertRaises(PermissionError):
                    verify_dodo_webhook(body)


if __name__ == "__main__":
    unittest.main()
