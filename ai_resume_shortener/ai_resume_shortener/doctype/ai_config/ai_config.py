# Copyright (c) 2026, Invento Software Limited and contributors
# For license information, please see license.txt

import hashlib
import json
import re
import time
from io import BytesIO
from typing import Any

import frappe
import requests
from frappe.model.document import Document
from frappe.utils import add_to_date, cint, escape_html, flt, now_datetime, strip_html_tags
from pypdf import PdfReader

try:
	import docx
except ImportError:
	docx = None

from ai_resume_shortener.ai_resume_shortener.doctype.ai_analysis_log.ai_analysis_log import (
	create_ai_log,
)


class AiConfig(Document):
	def validate(self):
		defaults = [row for row in self.model_config_list if row.is_default]
		if len(defaults) > 1:
			frappe.throw("Only one model row can be marked as 'Is Default'.")


PROCESS_METHOD = (
	"ai_resume_shortener.ai_resume_shortener.doctype.ai_config.ai_config.process_single_applicant_by_name"
)
JOB_TIMEOUT = 900
AI_REQUEST_TIMEOUT = 120
STALE_QUEUE_MINUTES = 30
MAX_RESUME_CHARS = 30000
MAX_JOB_DESC_CHARS = 10000
MAX_OUTPUT_TOKENS = 8192
MANAGER_ROLES = ("HR Manager", "System Manager")

# Index = star rating (1-5)
RECOMMENDATION_OPTIONS = ("", "Reject", "Potential", "Consider", "Recommended", "Highly Recommended")


class ResumeParseError(Exception):
	pass


STANDARD_DEFAULT_PROMPT = """You are an expert HR Recruiter, ATS evaluator, and Resume Intelligence System.
Evaluate the candidate's resume against the provided job description.

Requirements:
1. Provide realistic score (0-100), match_percentage (0-100), and confidence_score (0-100).
2. Extract all technical and soft skills present in the resume.
3. Identify matched skills (skills required by job present in resume) and missing skills (skills required by job missing in resume).
4. Identify candidate strengths and weaknesses.
5. Auto-detect resume language.
6. Generate interview questions tailored to the candidate:
   - 10 Technical Questions
   - 5 HR / Culture Questions
   - 3 Scenario / Behavioral Questions
7. Provide recommendation from ONLY these options:
   "Highly Recommended", "Recommended", "Consider", "Potential", "Reject"

Return ONLY valid JSON.
JSON Format:
{{
  "overall_score": 90,
  "match_percentage": 90,
  "confidence_score": 95,
  "education_score": 85,
  "experience_score": 90,
  "skills_score": 95,
  "additional_requirements_score": 85,
  "summary": "Concise summary describing candidate fit.",
  "strengths": ["Strong Python expertise", "AWS Certified"],
  "weaknesses": ["Limited frontend experience"],
  "extracted_skills": ["Python", "AWS", "Docker", "Frappe"],
  "matched_skills": ["Python", "AWS", "Docker"],
  "missing_skills": ["React"],
  "detected_language": "English",
  "recommendation": "Highly Recommended",
  "interview_questions": {{
    "technical": ["Question 1", "Question 2"],
    "hr": ["Question 1", "Question 2"],
    "scenario": ["Question 1", "Question 2"]
  }}
}}

Job Description: {job_desc}
Resume: {resume_text}

Important: Return ONLY valid JSON."""


# ---------------------------------------------------------------------------
# Queue helpers
# ---------------------------------------------------------------------------


def has_active_queued_log(job_applicant_name: str) -> bool:
	"""A Queued log counts as active only if it is recent; older ones belong to crashed/killed jobs."""
	cutoff = add_to_date(now_datetime(), minutes=-STALE_QUEUE_MINUTES)
	return bool(
		frappe.db.exists(
			"Ai Analysis Log",
			{"job_applicant": job_applicant_name, "status": "Queued", "creation": [">", cutoff]},
		)
	)


def expire_stale_queued_logs(job_applicant_name: str) -> None:
	stale_logs = frappe.get_all(
		"Ai Analysis Log",
		filters={"job_applicant": job_applicant_name, "status": "Queued"},
		pluck="name",
	)
	for log_name in stale_logs:
		frappe.db.set_value(
			"Ai Analysis Log",
			log_name,
			{"status": "Failed", "error_message": "Job did not finish (worker crash or timeout)."},
		)


def enqueue_applicant_analysis(job_applicant_name: str, message: str) -> bool:
	"""Creates a Queued log and enqueues the analysis job. Returns False if a job is already queued."""
	if has_active_queued_log(job_applicant_name):
		return False

	expire_stale_queued_logs(job_applicant_name)
	provider, model = get_default_provider_and_model()
	create_ai_log(
		job_applicant=job_applicant_name,
		service_provider=provider,
		model_name=model,
		status="Queued",
		error_message=message,
	)
	frappe.enqueue(
		PROCESS_METHOD,
		queue="default",
		job_applicant_name=job_applicant_name,
		timeout=JOB_TIMEOUT,
		enqueue_after_commit=True,
		now=getattr(frappe.flags, "in_test", False),
	)
	return True


def resume_analysis_scheduler() -> None:
	"""
	Scheduled task running hourly. Enqueues individual background jobs per unanalyzed job applicant.
	Only runs when 'Enable Hourly Auto Analysis' is ticked in Ai Config.
	"""
	if not frappe.db.get_single_value("Ai Config", "enable_auto_analysis"):
		return

	lst_job_applicants = frappe.get_all("Job Applicant", filters={"custom_is_success": 0}, pluck="name")
	for applicant_name in lst_job_applicants:
		enqueue_applicant_analysis(applicant_name, "Hourly scheduled analysis job added to queue")


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------


def get_enabled_providers_for_company(company: str | None) -> list[Any]:
	"""
	Multi-tenant provider selection filtering by company if configured.
	"""
	filters = {"enabled": 1, "parenttype": "Ai Config"}
	if company:
		comp_providers = frappe.get_all(
			"Ai Model Config List", fields=["*"], filters={**filters, "company": company}, order_by="idx asc"
		)
		if comp_providers:
			return comp_providers

	return frappe.get_all("Ai Model Config List", fields=["*"], filters=filters, order_by="idx asc")


def order_providers(providers: list[Any]) -> list[Any]:
	"""Puts the default model first ('Is Default' row, or the legacy 'default' field); rest are failover."""
	legacy_default = frappe.db.get_single_value("Ai Config", "default")
	return sorted(providers, key=lambda p: 0 if (p.get("is_default") or p.name == legacy_default) else 1)


def get_default_provider_and_model() -> tuple[str, str]:
	providers = order_providers(get_enabled_providers_for_company(None))
	if providers:
		return (
			providers[0].get("service_provider") or "Google Gemini",
			providers[0].get("model_name") or "gemini-2.5-flash",
		)
	return "Google Gemini", "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# Whitelisted API
# ---------------------------------------------------------------------------


@frappe.whitelist()
def analyze_single_applicant(job_applicant_name: str) -> dict[str, Any]:
	"""Synchronous analysis (API use). The desk button uses the background queue instead."""
	if not job_applicant_name:
		frappe.throw("Job Applicant name is required.")
	frappe.has_permission("Job Applicant", "write", doc=job_applicant_name, throw=True)
	return process_single_applicant_by_name(job_applicant_name)


@frappe.whitelist()
def enqueue_single_applicant_analysis(job_applicant_name: str) -> dict[str, Any]:
	if not job_applicant_name:
		frappe.throw("Job Applicant name is required.")
	frappe.has_permission("Job Applicant", "write", doc=job_applicant_name, throw=True)

	try:
		if not enqueue_applicant_analysis(job_applicant_name, "Analysis job added to background queue"):
			return {"status": "enqueued", "message": f"Job for {job_applicant_name} is already queued."}
		return {"status": "enqueued", "message": f"Enqueued AI analysis job for {job_applicant_name}"}
	except Exception as e:
		err = f"Enqueue Error: {e!s}"
		create_ai_log(job_applicant=job_applicant_name, status="Failed", error_message=err)
		return {"status": "failed", "reason": err}


@frappe.whitelist()
def enqueue_bulk_applicant_analysis(job_applicant_names: Any) -> dict[str, Any]:
	if isinstance(job_applicant_names, str):
		try:
			job_applicant_names = json.loads(job_applicant_names)
		except Exception:
			job_applicant_names = [job_applicant_names]

	if not isinstance(job_applicant_names, list) or not job_applicant_names:
		frappe.throw("No job applicants specified.")

	enqueued_count = 0
	for name in job_applicant_names:
		frappe.has_permission("Job Applicant", "write", doc=name, throw=True)
		if enqueue_applicant_analysis(name, "Bulk analysis job added to background queue"):
			enqueued_count += 1

	return {
		"status": "enqueued",
		"count": enqueued_count,
		"message": f"Enqueued background analysis for {enqueued_count} applicants.",
	}


@frappe.whitelist()
def get_ranked_candidates(job_title: str | None = None) -> list[dict[str, Any]]:
	"""
	Ranks candidates for a given position based on overall match percentage and overall score.
	"""
	filters = {"custom_is_success": 1}
	if job_title:
		filters["job_title"] = job_title

	# get_list (not get_all) so the user's Job Applicant permissions are applied
	candidates = frappe.get_list(
		"Job Applicant",
		filters=filters,
		fields=[
			"name",
			"applicant_name",
			"job_title",
			"custom_overall_score",
			"custom_match_percentage",
			"custom_recommendation",
			"applicant_rating",
			"custom_ai_provider",
		],
		order_by="custom_match_percentage desc, custom_overall_score desc",
	)

	for idx, cand in enumerate(candidates, start=1):
		cand["rank"] = idx

	return candidates


@frappe.whitelist()
def get_queue_metrics() -> dict[str, Any]:
	"""
	Queue Dashboard API returning Pending, Completed, and Failed applicant counts.
	"""
	frappe.has_permission("Job Applicant", "read", throw=True)
	return {
		"pending": frappe.db.count("Job Applicant", filters={"custom_is_success": 0}),
		"completed": frappe.db.count("Job Applicant", filters={"custom_is_success": 1}),
		"failed": frappe.db.count("Job Applicant", filters={"custom_is_success": -1}),
		"total_logs": frappe.db.count("Ai Analysis Log"),
	}


@frappe.whitelist()
def retry_failed_applicants() -> dict[str, Any]:
	"""
	Enqueues all failed applicants for re-analysis.
	"""
	frappe.only_for(MANAGER_ROLES)
	failed_applicants = frappe.get_all("Job Applicant", filters={"custom_is_success": -1}, pluck="name")
	enqueued_count = 0

	for name in failed_applicants:
		frappe.db.set_value("Job Applicant", name, "custom_is_success", 0)
		if enqueue_applicant_analysis(name, "Retry of failed analysis added to queue"):
			enqueued_count += 1

	return {"status": "success", "enqueued_count": enqueued_count}


@frappe.whitelist()
def benchmark_resume(job_applicant_name: str) -> dict[str, Any]:
	"""
	AI Benchmark Tool: Analyzes a resume across all enabled AI models and returns comparative metrics.
	"""
	frappe.only_for(MANAGER_ROLES)
	frappe.has_permission("Job Applicant", "read", doc=job_applicant_name, throw=True)

	job_applicant = frappe.get_doc("Job Applicant", job_applicant_name)
	try:
		resume_text, _ = get_resume_text_and_hash(job_applicant)
	except ResumeParseError as e:
		frappe.throw(f"Could not extract resume text for benchmark: {e!s}")

	ai_providers = get_enabled_providers_for_company(None)
	if not ai_providers:
		frappe.throw("No enabled AI models configured.")

	benchmark_results = []
	for p in ai_providers:
		ai_model_config = frappe.get_doc("Ai Model Config List", p.name)
		response = get_resume_analysis_ai_response(job_applicant, resume_text, ai_model_config)

		data = parse_and_validate_ai_response(response.get("response"))
		cost = calculate_request_cost(
			ai_response=response,
			input_cost_per_1m=ai_model_config.get("input_cost_per_1m", 0.0),
			output_cost_per_1m=ai_model_config.get("output_cost_per_1m", 0.0),
		)

		benchmark_results.append(
			{
				"provider": response.get("provider"),
				"model_name": response.get("model_name"),
				"status_code": response.get("status_code"),
				"execution_time_sec": response.get("execution_time"),
				"prompt_tokens": response.get("prompt_tokens"),
				"completion_tokens": response.get("completion_tokens"),
				"total_tokens": response.get("total_tokens"),
				"estimated_cost_usd": cost,
				"overall_score": data.get("overall_score") if data else 0,
				"recommendation": normalize_recommendation(data)[0] if data else "Failed",
			}
		)

	return {"job_applicant": job_applicant_name, "benchmark": benchmark_results}


# ---------------------------------------------------------------------------
# Prompt & AI calls
# ---------------------------------------------------------------------------


def get_active_prompt_template() -> tuple[str, str]:
	"""
	Retrieves the active prompt template and version name.
	Checks active Ai Prompt Version first, then Ai Config field, then standard default.
	"""
	active_pv = frappe.db.get_value(
		"Ai Prompt Version",
		{"is_active": 1},
		["version_name", "prompt_template"],
		as_dict=True,
	)
	if active_pv and active_pv.get("prompt_template"):
		return active_pv.prompt_template, active_pv.version_name

	configured_template = frappe.db.get_single_value("Ai Config", "prompt_template")
	if configured_template and configured_template.strip():
		return configured_template.strip(), "v1.0-custom"

	return STANDARD_DEFAULT_PROMPT, "v1.0-default"


def get_configured_prompt(job_desc: str, resume_text: str) -> tuple[str, str]:
	template, version_name = get_active_prompt_template()
	try:
		formatted = template.format(job_desc=job_desc, resume_text=resume_text)
	except (KeyError, IndexError, ValueError):
		# Custom templates often contain raw JSON braces; fall back to plain placeholder replacement
		if "{job_desc}" in template or "{resume_text}" in template:
			formatted = template.replace("{job_desc}", job_desc).replace("{resume_text}", resume_text)
		else:
			formatted = f"{template}\n\nJob Description: {job_desc}\nResume: {resume_text}"
	return formatted, version_name


def get_job_description(job_applicant: Any) -> str:
	job_desc = frappe.db.get_value("Job Opening", job_applicant.get("job_title"), "description") or ""
	return strip_html_tags(job_desc).strip()[:MAX_JOB_DESC_CHARS]


def calculate_request_cost(
	ai_response: dict[str, Any], input_cost_per_1m: float, output_cost_per_1m: float
) -> float:
	prompt_tokens = ai_response.get("prompt_tokens", 0)
	completion_tokens = ai_response.get("completion_tokens", 0)

	input_cost = (prompt_tokens / 1_000_000.0) * (input_cost_per_1m or 0.0)
	output_cost = (completion_tokens / 1_000_000.0) * (output_cost_per_1m or 0.0)

	return round(input_cost + output_cost, 6)


def _error_response(provider: str | None, model_name: str | None, status_code: int, error: str, **extra):
	return {
		"status_code": status_code,
		"response": None,
		"provider": provider,
		"model_name": model_name,
		"execution_time": 0.0,
		"prompt_tokens": 0,
		"completion_tokens": 0,
		"total_tokens": 0,
		"error": error,
		**extra,
	}


def get_resume_analysis_ai_response(
	job_applicant: Any, resume_text: str, ai_model_config: Any
) -> dict[str, Any]:
	prompt, prompt_version = get_configured_prompt(
		get_job_description(job_applicant), resume_text[:MAX_RESUME_CHARS]
	)

	service_provider = ai_model_config.get("service_provider")
	model_name = ai_model_config.get("model_name")
	if not ai_model_config.get("enabled") or not ai_model_config.get("api_key"):
		res = _error_response(service_provider, model_name, 400, "Provider disabled or API key missing")
	elif service_provider == "OpenRouter":
		res = openrouter_resume_analysis(prompt, ai_model_config)
	elif service_provider == "Google Gemini":
		res = google_gemini_resume_analysis(prompt, ai_model_config)
	else:
		res = _error_response(service_provider, model_name, 400, f"Unsupported provider: {service_provider}")

	res["prompt_version"] = prompt_version
	return res


def openrouter_resume_analysis(prompt: str, ai_model_config: Any) -> dict[str, Any]:
	url = "https://openrouter.ai/api/v1/chat/completions"
	api_key = ai_model_config.get_password("api_key")
	model_name = ai_model_config.get("model_name") or "openrouter/free"

	headers = {
		"Authorization": f"Bearer {api_key}",
		"Content-Type": "application/json",
	}

	payload = {
		"model": model_name,
		"messages": [{"role": "user", "content": prompt}],
		"response_format": {"type": "json_object"},
		"max_tokens": MAX_OUTPUT_TOKENS,
		"temperature": 0.2,
	}

	start_time = time.time()
	try:
		response = requests.post(url, headers=headers, json=payload, timeout=AI_REQUEST_TIMEOUT)
		execution_time = round(time.time() - start_time, 3)

		if response.status_code == 200:
			resp_json = response.json()
			content = (resp_json.get("choices") or [{}])[0].get("message", {}).get("content", "")
			usage = resp_json.get("usage") or {}
			prompt_tokens = usage.get("prompt_tokens", 0)
			completion_tokens = usage.get("completion_tokens", 0)

			return {
				"status_code": 200,
				"response": content,
				"provider": "OpenRouter",
				"model_name": model_name,
				"execution_time": execution_time,
				"prompt_tokens": prompt_tokens,
				"completion_tokens": completion_tokens,
				"total_tokens": prompt_tokens + completion_tokens,
				"error": None,
			}
		else:
			return {
				**_error_response(
					"OpenRouter",
					model_name,
					response.status_code,
					f"OpenRouter HTTP {response.status_code}: {response.text[:2000]}",
				),
				"response": response.text,
				"execution_time": execution_time,
			}
	except Exception as e:
		return {
			**_error_response("OpenRouter", model_name, 500, f"OpenRouter Exception: {e!s}"),
			"execution_time": round(time.time() - start_time, 3),
		}


def google_gemini_resume_analysis(prompt: str, ai_model_config: Any) -> dict[str, Any]:
	api_key = ai_model_config.get_password("api_key")
	model_name = ai_model_config.get("model_name") or "gemini-2.5-flash"
	# API key goes in a header, not the URL, so it never ends up in proxy/server logs or tracebacks
	url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"

	payload = {
		"contents": [{"parts": [{"text": prompt}]}],
		"generationConfig": {
			"response_mime_type": "application/json",
			"maxOutputTokens": MAX_OUTPUT_TOKENS,
			"temperature": 0.2,
		},
	}

	start_time = time.time()
	try:
		response = requests.post(
			url,
			headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
			json=payload,
			timeout=AI_REQUEST_TIMEOUT,
		)
		execution_time = round(time.time() - start_time, 3)

		if response.status_code == 200:
			resp_json = response.json()
			content = None
			try:
				content = resp_json["candidates"][0]["content"]["parts"][0]["text"]
			except (KeyError, IndexError, TypeError):
				content = None

			usage = resp_json.get("usageMetadata") or {}
			prompt_tokens = usage.get("promptTokenCount", 0)
			completion_tokens = usage.get("candidatesTokenCount", 0)

			return {
				"status_code": 200,
				"response": content,
				"provider": "Google Gemini",
				"model_name": model_name,
				"execution_time": execution_time,
				"prompt_tokens": prompt_tokens,
				"completion_tokens": completion_tokens,
				"total_tokens": prompt_tokens + completion_tokens,
				"error": None if content else "Empty content in Gemini candidate response",
			}
		else:
			return {
				**_error_response(
					"Google Gemini",
					model_name,
					response.status_code,
					f"Gemini HTTP {response.status_code}: {response.text[:2000]}",
				),
				"response": response.text,
				"execution_time": execution_time,
			}
	except Exception as e:
		return {
			**_error_response("Google Gemini", model_name, 500, f"Gemini Exception: {e!s}"),
			"execution_time": round(time.time() - start_time, 3),
		}


# ---------------------------------------------------------------------------
# Resume extraction
# ---------------------------------------------------------------------------


def calculate_sha256_hash(content: bytes) -> str:
	return hashlib.sha256(content).hexdigest()


def extract_pdf_text(file_content: bytes) -> str:
	pdf_reader = PdfReader(BytesIO(file_content))
	return "\n".join(page.extract_text() or "" for page in pdf_reader.pages)


def extract_docx_text(file_content: bytes) -> str:
	if not docx:
		raise ResumeParseError("python-docx package is not installed on the server.")
	doc = docx.Document(BytesIO(file_content))
	return "\n".join(para.text for para in doc.paragraphs if para.text)


def extract_text_from_bytes(file_content: bytes, file_name: str = "") -> str:
	"""Detects the file type from extension, falling back to magic bytes, and extracts its text."""
	name = (file_name or "").lower()

	if name.endswith(".doc") and not file_content.startswith(b"PK"):
		raise ResumeParseError("Legacy .doc files are not supported. Please upload PDF or DOCX.")
	if name.endswith(".txt"):
		return file_content.decode("utf-8", errors="ignore")
	if name.endswith(".pdf") or file_content.startswith(b"%PDF"):
		return extract_pdf_text(file_content)
	if name.endswith(".docx") or file_content.startswith(b"PK"):
		return extract_docx_text(file_content)
	if file_content.lstrip()[:15].lower().startswith((b"<!doctype html", b"<html")):
		raise ResumeParseError("Resume link returned a web page, not a file. Check the sharing settings.")

	raise ResumeParseError(f"Unsupported resume file type: {file_name or 'unknown'}")


def get_resume_text_and_hash(job_applicant: Any) -> tuple[str, str]:
	"""
	Returns (resume_text, sha256_of_content). Raises ResumeParseError with a readable reason on failure.
	"""
	try:
		if job_applicant.get("resume_link"):
			link = job_applicant.get("resume_link")
			if "docs.google.com" in link:
				resume_text = get_google_doc_text(link)
				file_hash = calculate_sha256_hash(resume_text.encode("utf-8"))
			elif "drive.google.com" in link:
				file_content = read_google_drive(link)
				file_hash = calculate_sha256_hash(file_content)
				resume_text = extract_text_from_bytes(file_content)
			else:
				raise ResumeParseError("Only Google Drive and Google Docs resume links are supported.")

		elif job_applicant.get("resume_attachment"):
			file_doc = frappe.get_doc("File", {"file_url": job_applicant.get("resume_attachment")})
			file_content = file_doc.get_content()
			if isinstance(file_content, str):
				file_content = file_content.encode("utf-8")

			file_hash = calculate_sha256_hash(file_content)
			resume_text = extract_text_from_bytes(file_content, file_doc.file_name)
		else:
			raise ResumeParseError("Missing resume attachment or link.")

	except ResumeParseError:
		raise
	except Exception as e:
		frappe.log_error(
			message=frappe.get_traceback(),
			reference_doctype="Job Applicant",
			reference_name=job_applicant.name,
			title="Resume Hash & Extraction Error",
		)
		raise ResumeParseError(f"Could not read resume: {e!s}")

	resume_text = (resume_text or "").strip()
	if not resume_text:
		raise ResumeParseError(
			"No text found in resume (it may be a scanned image or an empty/protected file)."
		)
	return resume_text, file_hash


def read_google_drive(url: str) -> bytes:
	file_id_match = re.search(r"id=([a-zA-Z0-9_-]+)", url) or re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
	if not file_id_match:
		raise ResumeParseError("Could not find a file ID in the Google Drive link.")

	# drive.usercontent + confirm=t skips the "can't scan for viruses" HTML page for large files
	response = requests.get(
		"https://drive.usercontent.google.com/download",
		params={"id": file_id_match.group(1), "export": "download", "confirm": "t"},
		timeout=30,
	)
	if response.status_code != 200:
		raise ResumeParseError(
			f"Google Drive download failed (HTTP {response.status_code}). Make sure the file is shared publicly."
		)
	return response.content


def get_google_doc_text(doc_url: str) -> str:
	match = re.search(r"/d/([a-zA-Z0-9_-]+)", doc_url)
	if not match:
		raise ResumeParseError("Could not find a document ID in the Google Docs link.")

	url = f"https://docs.google.com/document/d/{match.group(1)}/export?format=txt"
	response = requests.get(url, timeout=30)
	if response.status_code != 200:
		raise ResumeParseError(
			f"Google Docs export failed (HTTP {response.status_code}). Make sure the doc is shared publicly."
		)
	return response.text


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def parse_and_validate_ai_response(ai_response: str | None) -> dict[str, Any] | None:
	if not ai_response or not isinstance(ai_response, str):
		return None

	clean_resp = ai_response.strip()
	clean_resp = re.sub(r"^```(?:json)?\s*", "", clean_resp, flags=re.IGNORECASE)
	clean_resp = re.sub(r"\s*```$", "", clean_resp)

	try:
		data = json.loads(clean_resp)
	except ValueError:
		# Model wrapped the JSON in extra text; try the outermost {...} block
		start, end = clean_resp.find("{"), clean_resp.rfind("}")
		if start == -1 or end <= start:
			return None
		try:
			data = json.loads(clean_resp[start : end + 1])
		except ValueError:
			return None

	if not isinstance(data, dict) or "overall_score" not in data or "recommendation" not in data:
		return None
	return data


def normalize_recommendation(data: dict[str, Any]) -> tuple[str, int]:
	"""
	Maps the AI's recommendation (or score as fallback) onto one of RECOMMENDATION_OPTIONS.
	Returns (recommendation_label, star_rating 1-5).
	"""
	norm = re.sub(r"[^a-z0-9]", "", str(data.get("recommendation") or "").lower())
	# "not recommended" / "reject" must be checked before "recommended"
	if "highly" in norm or norm == "5":
		rating = 5
	elif "reject" in norm or "not" in norm or norm == "1":
		rating = 1
	elif "recommended" in norm or norm == "4":
		rating = 4
	elif "consider" in norm or norm == "3":
		rating = 3
	elif "potential" in norm or "weak" in norm or norm == "2":
		rating = 2
	else:
		score = clamp_score(data.get("overall_score"))
		if score >= 85:
			rating = 5
		elif score >= 70:
			rating = 4
		elif score >= 55:
			rating = 3
		elif score >= 40:
			rating = 2
		else:
			rating = 1
	return RECOMMENDATION_OPTIONS[rating], rating


def clamp_score(value: Any) -> int:
	return max(0, min(100, cint(flt(value))))


def list_to_str(value: Any) -> str:
	if isinstance(value, list):
		return ", ".join(str(v) for v in value)
	return str(value or "")


INTERVIEW_QUESTION_SECTIONS = {
	"technical": "Technical Questions",
	"hr": "HR / Culture Questions",
	"scenario": "Scenario / Behavioral Questions",
}


def format_interview_questions(questions: Any) -> str:
	"""Renders the AI's interview_questions JSON as HTML (heading + numbered list per category)."""
	if isinstance(questions, list):
		questions = {"general": questions}
	if not isinstance(questions, dict):
		return ""

	html = []
	for key, items in questions.items():
		if isinstance(items, str):
			items = [items]
		if not isinstance(items, list) or not items:
			continue
		title = INTERVIEW_QUESTION_SECTIONS.get(key, str(key).replace("_", " ").title() + " Questions")
		# Explicit bold serial numbers (an <ol> can't style its numbers inside the Text Editor)
		lines = "".join(
			f"<p><strong>{idx}.</strong> {escape_html(str(q))}</p>"
			for idx, q in enumerate((q for q in items if q), start=1)
		)
		html.append(f"<h4>{escape_html(title)}</h4>{lines}")
	return "".join(html)


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------


def safe_set_applicant_values(applicant_name: str, update_dict: dict[str, Any]) -> None:
	"""
	Safely sets values on Job Applicant, filtering out fields that don't exist in the database table yet.
	"""
	valid_dict = {}
	for k, v in update_dict.items():
		if frappe.db.has_column("Job Applicant", k):
			valid_dict[k] = v
		else:
			frappe.log_error(
				title="Ai Resume Shortener: missing column",
				message=f"Job Applicant has no column '{k}'. Run 'bench migrate' to sync custom fields.",
			)

	if valid_dict:
		frappe.db.set_value("Job Applicant", applicant_name, valid_dict)


def mark_failed(job_applicant_name: str, err_msg: str) -> dict[str, Any]:
	safe_set_applicant_values(job_applicant_name, {"custom_is_success": -1, "custom_summary": err_msg})
	create_ai_log(job_applicant=job_applicant_name, status="Failed", error_message=err_msg)
	return {"status": "failed", "reason": err_msg}


def process_single_applicant_by_name(job_applicant_name: str) -> dict[str, Any]:
	"""Background job entry point. Never leaves the Queued log hanging, even on unexpected errors."""
	try:
		job_applicant = frappe.get_doc("Job Applicant", job_applicant_name)
		result = process_single_applicant(job_applicant)
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(
			title="AI Resume Analysis Error",
			message=frappe.get_traceback(),
			reference_doctype="Job Applicant",
			reference_name=job_applicant_name,
		)
		if frappe.db.exists("Job Applicant", job_applicant_name):
			result = mark_failed(job_applicant_name, f"Analysis failed: unexpected error: {e!s}")
		else:
			result = {"status": "failed", "reason": f"Job Applicant {job_applicant_name} not found."}

	frappe.publish_realtime(
		"ai_resume_analysis_done",
		{"job_applicant": job_applicant_name, **result},
		user=frappe.session.user,
		after_commit=True,
	)
	return result


def process_single_applicant(job_applicant: Any) -> dict[str, Any]:
	"""
	Enterprise processor for single Job Applicant.
	Handles SHA256 duplicate detection, prompt versioning, provider failover, token cost calculation,
	and AI analysis history table recording.
	"""
	try:
		resume_text, file_hash = get_resume_text_and_hash(job_applicant)
	except ResumeParseError as e:
		return mark_failed(job_applicant.name, f"Analysis failed: {e!s}")

	duplicate = frappe.db.get_value(
		"Job Applicant",
		{"custom_resume_hash": file_hash, "name": ["!=", job_applicant.name]},
		"name",
	)
	if duplicate:
		job_applicant.add_comment(
			"Comment", f"Possible duplicate: same resume file as Job Applicant {duplicate}."
		)

	company = job_applicant.get("company") or frappe.db.get_value(
		"Job Opening", job_applicant.get("job_title"), "company"
	)
	providers_to_try = order_providers(get_enabled_providers_for_company(company))
	if not providers_to_try:
		return mark_failed(job_applicant.name, "Analysis failed: No enabled AI model configurations available.")

	last_error = ""
	for idx, provider_config in enumerate(providers_to_try):
		is_last_provider = idx == (len(providers_to_try) - 1)
		ai_model_config = frappe.get_doc("Ai Model Config List", provider_config.name)

		ai_response = get_resume_analysis_ai_response(job_applicant, resume_text, ai_model_config)

		status_code = ai_response.get("status_code")
		resp_text = ai_response.get("response")
		provider_name = ai_response.get("provider") or ai_model_config.service_provider
		model_name = ai_response.get("model_name") or ai_model_config.model_name
		prompt_version = ai_response.get("prompt_version", "v1.0")
		log_kwargs = {
			"job_applicant": job_applicant.name,
			"service_provider": provider_name,
			"model_name": model_name,
			"execution_time": ai_response.get("execution_time", 0.0),
			"prompt_tokens": ai_response.get("prompt_tokens", 0),
			"completion_tokens": ai_response.get("completion_tokens", 0),
			"total_tokens": ai_response.get("total_tokens", 0),
			"raw_response": resp_text,
		}

		data = parse_and_validate_ai_response(resp_text) if status_code == 200 and resp_text else None
		if not data:
			if status_code == 200 and resp_text:
				last_error = f"Invalid/corrupt JSON structure from {provider_name}"
			else:
				last_error = ai_response.get("error") or f"HTTP {status_code} error from {provider_name}"
			create_ai_log(
				status="Retried" if not is_last_provider else "Failed",
				error_message=last_error,
				**log_kwargs,
			)
			continue

		cost = calculate_request_cost(
			ai_response,
			ai_model_config.get("input_cost_per_1m", 0.0),
			ai_model_config.get("output_cost_per_1m", 0.0),
		)
		overall_score = clamp_score(data.get("overall_score"))
		match_percentage = clamp_score(data.get("match_percentage", overall_score))
		confidence_score = clamp_score(data.get("confidence_score", 90))
		recommendation, numeric_rating = normalize_recommendation(data)

		safe_set_applicant_values(
			job_applicant.name,
			{
				"custom_overall_score": overall_score,
				"custom_match_percentage": match_percentage,
				"custom_confidence_score": confidence_score,
				"custom_education_score": clamp_score(data.get("education_score")),
				"custom_experience_score": clamp_score(data.get("experience_score")),
				"custom_skills_score": clamp_score(data.get("skills_score")),
				"custom_additional_requirements_score": clamp_score(data.get("additional_requirements_score")),
				"custom_is_success": 1,
				"custom_recommendation": recommendation,
				"custom_summary": data.get("summary", ""),
				"custom_strengths": list_to_str(data.get("strengths")),
				"custom_missing_skills": list_to_str(data.get("missing_skills")),
				"custom_extracted_skills": list_to_str(data.get("extracted_skills")),
				"custom_interview_questions": format_interview_questions(data.get("interview_questions")),
				"custom_resume_hash": file_hash,
				"custom_ai_provider": f"{provider_name} ({model_name} - {prompt_version})",
				# Rating fields are stored as a 0-1 fraction (4 stars = 0.8)
				"applicant_rating": numeric_rating / 5,
			},
		)

		# Insert the history row directly so Job Applicant validations/notifications don't block it
		try:
			job_applicant.reload()
			row = job_applicant.append(
				"custom_ai_history",
				{
					"analysis_date": now_datetime(),
					"service_provider": provider_name,
					"model_name": model_name,
					"prompt_version": prompt_version,
					"overall_score": overall_score,
					"match_percentage": match_percentage,
					"confidence_score": confidence_score,
					"recommendation": recommendation,
					"rating": numeric_rating,
					"cost": cost,
					"execution_time": ai_response.get("execution_time", 0.0),
					"summary": data.get("summary", ""),
					"raw_json": resp_text,
				},
			)
			row.db_insert()
		except Exception:
			frappe.log_error(
				title="Error appending to custom_ai_history",
				message=frappe.get_traceback(),
				reference_doctype="Job Applicant",
				reference_name=job_applicant.name,
			)

		create_ai_log(status="Success", **log_kwargs)
		return {"status": "success", "applicant": job_applicant.name}

	final_error = f"Analysis failed: {last_error}"
	safe_set_applicant_values(job_applicant.name, {"custom_is_success": -1, "custom_summary": final_error})
	return {"status": "failed", "reason": final_error}


def process_data(lst_job_applicants: list[Any]) -> None:
	for applicant in lst_job_applicants:
		if isinstance(applicant, dict):
			applicant_doc = frappe.get_doc("Job Applicant", applicant.get("name"))
		else:
			applicant_doc = applicant
		process_single_applicant(applicant_doc)
