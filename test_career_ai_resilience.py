import unittest
from unittest.mock import Mock, patch

import career_ai_resilience


class CareerAIResilienceTests(unittest.TestCase):
    def _response(self, status, payload=None):
        response = Mock()
        response.status_code = status
        response.ok = 200 <= status < 300
        response.json.return_value = payload or {}
        return response

    @patch("career_ai_resilience.requests.post")
    def test_503_falls_back_to_next_model(self, post):
        good_payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": '{"optimized_summary":"Summary","optimized_bullets":[],"skills_to_highlight":[],"keywords_to_review":[],"optimized_resume":"Jane Doe\\nExperience\\nImproved reporting workflows.","changes":[]}'
                            }
                        ]
                    }
                }
            ]
        }
        post.side_effect = [
            self._response(503),
            self._response(200, good_payload),
        ]

        result = career_ai_resilience._patched_gemini_request(
            "test-key", "gemini-2.5-flash", "rewrite this resume"
        )

        self.assertEqual(post.call_count, 2)
        self.assertEqual(result["_model_used"], "gemini-3.8-flash")
        self.assertTrue(result["optimized_resume"])

    @patch("career_ai_resilience.requests.post")
    def test_authentication_error_does_not_retry(self, post):
        post.return_value = self._response(403)

        with self.assertRaisesRegex(RuntimeError, "not authenticated correctly"):
            career_ai_resilience._patched_gemini_request(
                "bad-key", "gemini-2.5-flash", "rewrite this resume"
            )

        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
