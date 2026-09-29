import unittest
from unittest.mock import Mock, patch

import career_ai


class CareerCoverLetterFallbackTests(unittest.TestCase):
    def _response(self, status, payload=None):
        response = Mock()
        response.status_code = status
        response.ok = 200 <= status < 300
        response.json.return_value = payload or {}
        return response

    def _success_payload(self):
        letter = (
            "Dear Hiring Manager,\n\n"
            "I am applying for the role based on the experience described in my resume. "
            "My background includes building web applications, collaborating with teams, "
            "and improving product workflows while keeping the work grounded in user needs.\n\n"
            "The responsibilities in this position align with the work already reflected in "
            "my resume. I would welcome the opportunity to discuss how that experience can "
            "support your team and its current priorities.\n\nSincerely,\nApplicant"
        )
        return {
            "candidates": [{
                "content": {"parts": [{"text": (
                    '{"cover_letter":' + __import__('json').dumps(letter) +
                    ',"subject_line":"Application for the role",'
                    '"strengths_used":["Web application experience"],'
                    '"unsupported_requirements":[]}'
                )}]}
            }]
        }

    @patch.dict("os.environ", {"GEMINI_API": "test-key", "GEMINI_MODEL": "legacy-model"}, clear=False)
    @patch("career_ai.time.sleep", return_value=None)
    @patch("career_ai.requests.post")
    def test_transient_failure_falls_back_to_next_model(self, post, _sleep):
        post.side_effect = [
            self._response(503),
            self._response(503),
            self._response(200, self._success_payload()),
        ]

        result = career_ai.generate_cover_letter_with_gemini(
            "Web developer with JavaScript experience and team collaboration.",
            "Seeking a web developer to build and maintain user-facing applications.",
            role="Web Developer",
        )

        self.assertEqual(post.call_count, 3)
        self.assertTrue(result["cover_letter"])
        self.assertEqual(result["model"], "gemini-3.8-flash")

    @patch.dict("os.environ", {"GEMINI_API": "test-key"}, clear=False)
    @patch("career_ai.requests.post")
    def test_bad_api_key_stops_immediately(self, post):
        post.return_value = self._response(401)
        with self.assertRaisesRegex(RuntimeError, "not authenticated correctly"):
            career_ai.generate_cover_letter_with_gemini(
                "Resume text with enough factual information.",
                "Job description with enough information.",
            )
        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
