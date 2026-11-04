# Copyright (c) 2026, Invento Software Limited and Contributors
# See license.txt

from io import BytesIO

from frappe.tests import IntegrationTestCase

from ai_resume_shortener.ai_resume_shortener.doctype.ai_config.ai_config import (
	ResumeParseError,
	calculate_request_cost,
	extract_text_from_bytes,
	format_interview_questions,
	normalize_recommendation,
	parse_and_validate_ai_response,
)

# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]


class IntegrationTestAiConfig(IntegrationTestCase):
	def test_normalize_recommendation(self):
		cases = {
			"Highly Recommended": ("Highly Recommended", 5),
			"Recommended": ("Recommended", 4),
			"Consider": ("Consider", 3),
			"Potential": ("Potential", 2),
			"Weak": ("Potential", 2),
			"Reject": ("Reject", 1),
			"Not Recommended": ("Reject", 1),
		}
		for rec, expected in cases.items():
			self.assertEqual(normalize_recommendation({"recommendation": rec, "overall_score": 50}), expected)

		# Unknown label falls back to score
		self.assertEqual(normalize_recommendation({"recommendation": "?", "overall_score": 90})[1], 5)
		self.assertEqual(normalize_recommendation({"recommendation": "?", "overall_score": "10"})[1], 1)

	def test_parse_ai_response(self):
		self.assertEqual(
			parse_and_validate_ai_response('```json\n{"overall_score": 80, "recommendation": "Consider"}\n```'),
			{"overall_score": 80, "recommendation": "Consider"},
		)
		self.assertEqual(
			parse_and_validate_ai_response('Result: {"overall_score": 1, "recommendation": "Reject"} done')[
				"overall_score"
			],
			1,
		)
		self.assertIsNone(parse_and_validate_ai_response('{"overall_score": 80'))
		self.assertIsNone(parse_and_validate_ai_response('{"summary": "missing keys"}'))
		self.assertIsNone(parse_and_validate_ai_response(None))

	def test_extract_text_from_bytes(self):
		import docx

		document = docx.Document()
		document.add_paragraph("Python developer")
		buffer = BytesIO()
		document.save(buffer)

		self.assertEqual(extract_text_from_bytes(buffer.getvalue(), "cv.docx"), "Python developer")
		self.assertEqual(extract_text_from_bytes(b"plain text", "cv.txt"), "plain text")
		with self.assertRaises(ResumeParseError):
			extract_text_from_bytes(b"<!DOCTYPE html><html></html>")
		with self.assertRaises(ResumeParseError):
			extract_text_from_bytes(b"\xd0\xcf\x11\xe0legacy", "cv.doc")

	def test_calculate_request_cost(self):
		cost = calculate_request_cost(
			{"prompt_tokens": 1_000_000, "completion_tokens": 500_000},
			input_cost_per_1m=0.3,
			output_cost_per_1m=2.5,
		)
		self.assertEqual(cost, 1.55)

	def test_format_interview_questions(self):
		html = format_interview_questions(
			{"technical": ["What is <b>Python</b>?", "Explain REST"], "hr": ["Why us?"], "scenario": []}
		)
		self.assertIn(
			"<h4>Technical Questions</h4><p><strong>1.</strong> What is &lt;b&gt;Python&lt;/b&gt;?</p>"
			"<p><strong>2.</strong> Explain REST</p>",
			html,
		)
		self.assertIn("<h4>HR / Culture Questions</h4><p><strong>1.</strong> Why us?</p>", html)
		self.assertNotIn("Scenario", html)
		self.assertEqual(format_interview_questions(None), "")
