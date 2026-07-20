# Copyright (c) 2026, Invento Software Limited and contributors
# For license information, please see license.txt

import hashlib
import json
import re
import time
from io import BytesIO
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import frappe
import requests
from frappe.model.document import Document
from pypdf import PdfReader

try:
	import docx
except ImportError:
	docx = None

from ai_resume_shortener.ai_resume_shortener.doctype.ai_analysis_log.ai_analysis_log import (
	create_ai_log,
)


class AiConfig(Document):
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


def resume_analysis_scheduler() -> None:
	"""
	Scheduled task running hourly. Enqueues individual background jobs per unanalyzed job applicant.
	"""
	lst_job_applicants = frappe.get_all("Job Applicant", filters={"custom_is_success": 0}, fields=["name"])
	if not lst_job_applicants:
		return

	provider, model = get_default_provider_and_model()

	for applicant in lst_job_applicants:
		if frappe.db.exists("Ai Analysis Log", {"job_applicant": applicant.name, "status": "Queued"}):
			continue

		create_ai_log(
			job_applicant=applicant.name,
			service_provider=provider,
			model_name=model,
			status="Queued",
			error_message="Hourly scheduled analysis job added to queue",
		)
		frappe.enqueue(
			"ai_resume_shortener.ai_resume_shortener.doctype.ai_config.ai_config.process_single_applicant_by_name",
			queue="default",
			job_applicant_name=applicant.name,
			timeout=300,
			now=getattr(frappe.flags, "in_test", False),
		)


def get_default_provider_and_model() -> tuple[str, str]:
	try:
		default_config = frappe.get_all(
			"Ai Model Config List",
			fields=["service_provider", "model_name"],
			filters={"enabled": 1},
			order_by="idx asc",
			limit=1,
		)
		if default_config:
			provider = default_config[0].get("service_provider") or "Google Gemini"
			model = default_config[0].get("model_name") or "gemini-2.5-flash"
			return provider, model
	except Exception:
		pass
	return "Google Gemini", "gemini-2.5-flash"


@frappe.whitelist()
def analyze_single_applicant(job_applicant_name: str) -> Dict[str, Any]:
	if not job_applicant_name:
		frappe.throw("Job Applicant name is required.")
	return process_single_applicant_by_name(job_applicant_name)


@frappe.whitelist()
def enqueue_single_applicant_analysis(job_applicant_name: str) -> Dict[str, Any]:
	if not job_applicant_name:
		frappe.throw("Job Applicant name is required.")

	if frappe.db.exists("Ai Analysis Log", {"job_applicant": job_applicant_name, "status": "Queued"}):
		return {"status": "enqueued", "message": f"Job for {job_applicant_name} is already queued."}

	provider, model = get_default_provider_and_model()
	create_ai_log(
		job_applicant=job_applicant_name,
		service_provider=provider,
		model_name=model,
		status="Queued",
		error_message="Analysis job added to background queue",
	)

	try:
		frappe.enqueue(
			"ai_resume_shortener.ai_resume_shortener.doctype.ai_config.ai_config.process_single_applicant_by_name",
			queue="default",
			job_applicant_name=job_applicant_name,
			timeout=300,
			now=getattr(frappe.flags, "in_test", False),
		)
		return {"status": "enqueued", "message": f"Enqueued AI analysis job for {job_applicant_name}"}
	except Exception as e:
		err = f"Enqueue Error: {e!s}"
		create_ai_log(
			job_applicant=job_applicant_name,
			service_provider=provider,
			model_name=model,
			status="Failed",
			error_message=err,
		)
		return {"status": "failed", "reason": err}


@frappe.whitelist()
def enqueue_bulk_applicant_analysis(job_applicant_names: Any) -> Dict[str, Any]:
	if isinstance(job_applicant_names, str):
		try:
			job_applicant_names = json.loads(job_applicant_names)
		except Exception:
			job_applicant_names = [job_applicant_names]

	if not isinstance(job_applicant_names, list) or not job_applicant_names:
		frappe.throw("No job applicants specified.")

	provider, model = get_default_provider_and_model()
	enqueued_count = 0
	for name in job_applicant_names:
		if frappe.db.exists("Ai Analysis Log", {"job_applicant": name, "status": "Queued"}):
			continue

		create_ai_log(
			job_applicant=name,
			service_provider=provider,
			model_name=model,
			status="Queued",
			error_message="Bulk analysis job added to background queue",
		)
		frappe.enqueue(
			"ai_resume_shortener.ai_resume_shortener.doctype.ai_config.ai_config.process_single_applicant_by_name",
			queue="default",
			job_applicant_name=name,
			timeout=300,
			now=getattr(frappe.flags, "in_test", False),
		)
		enqueued_count += 1

	return {
		"status": "enqueued",
		"count": enqueued_count,
		"message": f"Enqueued background analysis for {enqueued_count} applicants.",
	}


@frappe.whitelist()
def get_ranked_candidates(job_title: Optional[str] = None) -> List[Dict[str, Any]]:
	"""
	Ranks candidates for a given position based on overall match percentage and overall score.
	"""
	filters = {"custom_is_success": 1}
	if job_title:
		filters["job_title"] = job_title

	candidates = frappe.get_all(
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
def get_queue_metrics() -> Dict[str, Any]:
	"""
	Queue Dashboard API returning Pending, Completed, and Failed applicant counts.
	"""
	pending_count = frappe.db.count("Job Applicant", filters={"custom_is_success": 0})
	completed_count = frappe.db.count("Job Applicant", filters={"custom_is_success": 1})
	failed_count = frappe.db.count("Job Applicant", filters={"custom_is_success": -1})
	total_logs = frappe.db.count("Ai Analysis Log")

	return {
		"pending": pending_count,
		"completed": completed_count,
		"failed": failed_count,
		"total_logs": total_logs,
	}


@frappe.whitelist()
def retry_failed_applicants() -> Dict[str, Any]:
	"""
	Enqueues all failed applicants for re-analysis.
	"""
	failed_applicants = frappe.get_all("Job Applicant", filters={"custom_is_success": -1}, fields=["name"])
	enqueued_count = 0

	for app in failed_applicants:
		frappe.db.set_value("Job Applicant", app.name, "custom_is_success", 0)
		frappe.enqueue(
			"ai_resume_shortener.ai_resume_shortener.doctype.ai_config.ai_config.process_single_applicant_by_name",
			queue="long",
			job_applicant_name=app.name,
			timeout=300,
			now=getattr(frappe.flags, "in_test", False),
		)
		enqueued_count += 1

	return {"status": "success", "enqueued_count": enqueued_count}


@frappe.whitelist()
def benchmark_resume(job_applicant_name: str) -> Dict[str, Any]:
	"""
	AI Benchmark Tool: Analyzes a resume across all enabled AI models and returns comparative metrics.
	"""
	job_applicant = frappe.get_doc("Job Applicant", job_applicant_name)
	resume_text, _ = get_resume_text_and_hash(job_applicant)
	if not resume_text:
		frappe.throw("Could not extract resume text for benchmark.")

	ai_providers = frappe.get_all("Ai Model Config List", fields=["*"], filters={"enabled": 1})
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
				"recommendation": data.get("recommendation") if data else "Failed",
			}
		)

	return {"job_applicant": job_applicant_name, "benchmark": benchmark_results}


def process_single_applicant_by_name(job_applicant_name: str) -> Dict[str, Any]:
	job_applicant = frappe.get_doc("Job Applicant", job_applicant_name)
	return process_single_applicant(job_applicant)


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
	except Exception:
		formatted = f"{template}\n\nJob Description: {job_desc}\nResume: {resume_text}"
	return formatted, version_name


def calculate_request_cost(ai_response: Dict[str, Any], input_cost_per_1m: float, output_cost_per_1m: float) -> float:
	prompt_tokens = ai_response.get("prompt_tokens", 0)
	completion_tokens = ai_response.get("completion_tokens", 0)

	input_cost = (prompt_tokens / 1_000_000.0) * (input_cost_per_1m or 0.0)
	output_cost = (completion_tokens / 1_000_000.0) * (output_cost_per_1m or 0.0)

	return round(input_cost + output_cost, 6)


def get_resume_analysis_ai_response(job_applicant: Any, resume_text: str, ai_model_config: Any) -> Dict[str, Any]:
	job_desc = frappe.db.get_value("Job Opening", job_applicant.get("job_title"), "description") or ""
	prompt, prompt_version = get_configured_prompt(job_desc, resume_text)

	service_provider = ai_model_config.get("service_provider")
	if not ai_model_config.get("enabled") or not ai_model_config.get("api_key"):
		return {
			"status_code": 400,
			"response": None,
			"provider": service_provider,
			"model_name": ai_model_config.get("model_name"),
			"prompt_version": prompt_version,
			"execution_time": 0.0,
			"prompt_tokens": 0,
			"completion_tokens": 0,
			"total_tokens": 0,
			"error": "Provider disabled or API key missing",
		}

	if service_provider == "OpenRouter":
		res = openrouter_resume_analysis(prompt, ai_model_config)
	elif service_provider == "Google Gemini":
		res = google_gemini_resume_analysis(prompt, ai_model_config)
	else:
		res = {
			"status_code": 400,
			"response": None,
			"provider": service_provider,
			"model_name": ai_model_config.get("model_name"),
			"prompt_version": prompt_version,
			"execution_time": 0.0,
			"prompt_tokens": 0,
			"completion_tokens": 0,
			"total_tokens": 0,
			"error": f"Unsupported provider: {service_provider}",
		}

	res["prompt_version"] = prompt_version
	return res


def openrouter_resume_analysis(prompt: str, ai_model_config: Any) -> Dict[str, Any]:
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
		"max_tokens": 2000,
		"temperature": 0.2,
	}

	start_time = time.time()
	try:
		response = requests.post(url, headers=headers, json=payload, timeout=60)
		execution_time = round(time.time() - start_time, 3)

		if response.status_code == 200:
			resp_json = response.json()
			content = resp_json.get("choices", [{}])[0].get("message", {}).get("content", "")
			usage = resp_json.get("usage", {})
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
				"status_code": response.status_code,
				"response": response.text,
				"provider": "OpenRouter",
				"model_name": model_name,
				"execution_time": execution_time,
				"prompt_tokens": 0,
				"completion_tokens": 0,
				"total_tokens": 0,
				"error": f"OpenRouter HTTP {response.status_code}: {response.text}",
			}
	except Exception as e:
		execution_time = round(time.time() - start_time, 3)
		return {
			"status_code": 500,
			"response": None,
			"provider": "OpenRouter",
			"model_name": model_name,
			"execution_time": execution_time,
			"prompt_tokens": 0,
			"completion_tokens": 0,
			"total_tokens": 0,
			"error": f"OpenRouter Exception: {e!s}",
		}


def google_gemini_resume_analysis(prompt: str, ai_model_config: Any) -> Dict[str, Any]:
	api_key = ai_model_config.get_password("api_key")
	model_name = ai_model_config.get("model_name") or "gemini-2.5-flash"
	url = (
		"https://generativelanguage.googleapis.com/v1beta/"
		f"models/{model_name}:generateContent?key={api_key}"
	)

	payload = {
		"contents": [{"parts": [{"text": prompt}]}],
		"generationConfig": {"response_mime_type": "application/json"},
	}

	start_time = time.time()
	try:
		response = requests.post(
			url,
			headers={"Content-Type": "application/json"},
			json=payload,
			timeout=60,
		)
		execution_time = round(time.time() - start_time, 3)

		if response.status_code == 200:
			resp_json = response.json()
			content = None
			try:
				content = resp_json["candidates"][0]["content"]["parts"][0]["text"]
			except (KeyError, IndexError):
				content = None

			usage = resp_json.get("usageMetadata", {})
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
				"status_code": response.status_code,
				"response": response.text,
				"provider": "Google Gemini",
				"model_name": model_name,
				"execution_time": execution_time,
				"prompt_tokens": 0,
				"completion_tokens": 0,
				"total_tokens": 0,
				"error": f"Gemini HTTP {response.status_code}: {response.text}",
			}
	except Exception as e:
		execution_time = round(time.time() - start_time, 3)
		return {
			"status_code": 500,
			"response": None,
			"provider": "Google Gemini",
			"model_name": model_name,
			"execution_time": execution_time,
			"prompt_tokens": 0,
			"completion_tokens": 0,
			"total_tokens": 0,
			"error": f"Gemini Exception: {e!s}",
		}


def extract_docx_text(file_content: bytes) -> str:
	if not docx:
		raise RuntimeError("python-docx package is not installed.")
	doc = docx.Document(BytesIO(file_content))
	full_text = [para.text for para in doc.paragraphs if para.text]
	return "\n".join(full_text)


def calculate_sha256_hash(content: bytes) -> str:
	return hashlib.sha256(content).hexdigest()


def get_resume_text_and_hash(job_applicant: Any) -> tuple[str, str]:
	try:
		resume_text = ""
		file_hash = ""

		if job_applicant.get("resume_link"):
			link = job_applicant.get("resume_link")
			if "drive.google.com" in link:
				resume_text = read_google_drive(link)
			elif "docs.google.com" in link:
				resume_text = get_google_doc_text(link)
			file_hash = hashlib.sha256(link.encode("utf-8")).hexdigest()

		elif job_applicant.get("resume_attachment"):
			file_doc = frappe.get_doc("File", {"file_url": job_applicant.get("resume_attachment")})
			file_content = file_doc.get_content()

			if isinstance(file_content, str):
				file_content = file_content.encode("utf-8")

			file_hash = calculate_sha256_hash(file_content)
			file_name = (file_doc.file_name or "").lower()

			if file_name.endswith(".pdf"):
				pdf_reader = PdfReader(BytesIO(file_content))
				resume_text = "".join([page.extract_text() or "" for page in pdf_reader.pages])
			elif file_name.endswith(".docx") or file_name.endswith(".doc"):
				try:
					resume_text = extract_docx_text(file_content)
				except Exception:
					pass
			elif file_name.endswith(".txt"):
				resume_text = file_content.decode("utf-8", errors="ignore")
			else:
				try:
					pdf_reader = PdfReader(BytesIO(file_content))
					resume_text = "".join([page.extract_text() or "" for page in pdf_reader.pages])
				except Exception:
					pass

		return resume_text.strip(), file_hash
	except Exception as e:
		frappe.log_error(
			message=f"Error in get_resume_text_and_hash: {e!s}",
			reference_doctype="Job Applicant",
			reference_name=job_applicant.name,
			title="Resume Hash & Extraction Error",
		)
		return "", ""


def read_google_drive(url: str) -> str:
	file_id_match = re.search(r"id=([a-zA-Z0-9_-]+)", url) or re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
	if file_id_match:
		file_id = file_id_match.group(1)
		download = f"https://drive.google.com/uc?export=download&id={file_id}"
		response = requests.get(download, timeout=30)
		file_content = response.content
		if isinstance(file_content, str):
			file_content = file_content.encode()
		try:
			pdf_reader = PdfReader(BytesIO(file_content))
			return "".join([page.extract_text() or "" for page in pdf_reader.pages])
		except Exception:
			return ""
	return ""


def get_google_doc_text(doc_url: str) -> str:
	try:
		doc_id = doc_url.split("/d/")[1].split("/")[0]
		domain = urlparse(doc_url).netloc.lower()
		if "docs.google.com" not in domain:
			return ""
		url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
		response = requests.get(url, timeout=30)
		return response.text if response.status_code == 200 else ""
	except Exception:
		return ""


def parse_and_validate_ai_response(ai_response: Optional[str]) -> Optional[Dict[str, Any]]:
	if not ai_response or not isinstance(ai_response, str):
		return None
	try:
		clean_resp = ai_response.strip()
		clean_resp = re.sub(r"^```json\s*", "", clean_resp, flags=re.IGNORECASE)
		clean_resp = re.sub(r"^```\s*", "", clean_resp)
		clean_resp = re.sub(r"\s*```$", "", clean_resp)

		data = json.loads(clean_resp)
		if not isinstance(data, dict):
			return None

		if "overall_score" not in data or "recommendation" not in data:
			return None

		return data
	except Exception:
		return None


def get_enabled_providers_for_company(company: Optional[str]) -> List[Any]:
	"""
	Multi-tenant provider selection filtering by company if configured.
	"""
	if company:
		comp_providers = frappe.get_all(
			"Ai Model Config List", fields=["*"], filters={"enabled": 1, "company": company}
		)
		if comp_providers:
			return comp_providers

	return frappe.get_all("Ai Model Config List", fields=["*"], filters={"enabled": 1})


def safe_set_applicant_values(applicant_name: str, update_dict: Dict[str, Any]) -> None:
	"""
	Safely sets values on Job Applicant, filtering out fields that don't exist in the database table yet.
	"""
	valid_dict = {}
	for k, v in update_dict.items():
		if frappe.db.has_column("Job Applicant", k):
			valid_dict[k] = v

	if valid_dict:
		frappe.db.set_value("Job Applicant", applicant_name, valid_dict)


def process_single_applicant(job_applicant: Any) -> Dict[str, Any]:
	"""
	Enterprise processor for single Job Applicant.
	Handles SHA256 duplicate detection, prompt versioning, provider failover, token cost calculation,
	and AI analysis history table recording.
	"""
	if not job_applicant.get("resume_attachment") and not job_applicant.get("resume_link"):
		err_msg = "Analysis failed: Missing resume attachment or link."
		safe_set_applicant_values(
			job_applicant.name,
			{"custom_is_success": -1, "custom_summary": err_msg},
		)
		create_ai_log(job_applicant=job_applicant.name, status="Failed", error_message=err_msg)
		return {"status": "failed", "reason": err_msg}

	resume_text, file_hash = get_resume_text_and_hash(job_applicant)
	if not resume_text:
		err_msg = "Analysis failed: Could not parse text from resume file/link."
		safe_set_applicant_values(
			job_applicant.name,
			{"custom_is_success": -1, "custom_summary": err_msg},
		)
		create_ai_log(job_applicant=job_applicant.name, status="Failed", error_message=err_msg)
		return {"status": "failed", "reason": err_msg}

	# Check for Duplicate Resume Hash (Column Safe)
	if file_hash and frappe.db.has_column("Job Applicant", "custom_resume_hash"):
		try:
			duplicate = frappe.db.get_value(
				"Job Applicant",
				{"custom_resume_hash": file_hash, "name": ["!=", job_applicant.name]},
				"name",
			)
			if duplicate:
				frappe.log_error(
					message=f"Duplicate resume detected. Same hash as applicant {duplicate}",
					reference_doctype="Job Applicant",
					reference_name=job_applicant.name,
					title="Duplicate CV Detected",
				)
		except Exception:
			pass

	ai_provider_lst = get_enabled_providers_for_company(job_applicant.get("company"))
	if not ai_provider_lst:
		err_msg = "Analysis failed: No enabled AI model configurations available."
		frappe.db.set_value(
			"Job Applicant",
			job_applicant.name,
			{"custom_is_success": -1, "custom_summary": err_msg},
		)
		create_ai_log(job_applicant=job_applicant.name, status="Failed", error_message=err_msg)
		return {"status": "failed", "reason": err_msg}

	default_provider_name = frappe.db.get_single_value("Ai Config", "default")
	providers_to_try = []
	for p in ai_provider_lst:
		if p.name == default_provider_name:
			providers_to_try.insert(0, p)
		else:
			providers_to_try.append(p)

	success = False
	last_error = ""

	recommendation_rating_map = {
		"Highly Recommended": 5,
		"Recommended": 4,
		"Consider": 3,
		"Potential": 2,
		"Reject": 1,
	}

	for idx, provider_config in enumerate(providers_to_try):
		is_last_provider = idx == (len(providers_to_try) - 1)
		ai_model_config = frappe.get_doc("Ai Model Config List", provider_config.name)

		ai_response = get_resume_analysis_ai_response(job_applicant, resume_text, ai_model_config)

		status_code = ai_response.get("status_code")
		resp_text = ai_response.get("response")
		provider_name = ai_response.get("provider") or ai_model_config.service_provider
		model_name = ai_response.get("model_name") or ai_model_config.model_name
		prompt_version = ai_response.get("prompt_version", "v1.0")

		cost = calculate_request_cost(
			ai_response,
			ai_model_config.get("input_cost_per_1m", 0.0),
			ai_model_config.get("output_cost_per_1m", 0.0),
		)

		if status_code == 200 and resp_text:
			data = parse_and_validate_ai_response(resp_text)
			if data:
				overall_score = data.get("overall_score", 0)
				recommendation_str = data.get("recommendation", "Consider")

				# Flexibly determine 1-5 star rating from recommendation OR overall_score
				norm_rec = re.sub(r"[^a-zA-Z0-9]", "", str(recommendation_str)).lower()
				if "highly" in norm_rec or norm_rec == "5":
					numeric_rating = 5
				elif "recommended" in norm_rec or norm_rec == "4":
					numeric_rating = 4
				elif "consider" in norm_rec or norm_rec == "3":
					numeric_rating = 3
				elif "potential" in norm_rec or norm_rec == "2":
					numeric_rating = 2
				elif "reject" in norm_rec or "not" in norm_rec or norm_rec == "1":
					numeric_rating = 1
				else:
					if overall_score >= 85:
						numeric_rating = 5
					elif overall_score >= 70:
						numeric_rating = 4
					elif overall_score >= 55:
						numeric_rating = 3
					elif overall_score >= 40:
						numeric_rating = 2
					else:
						numeric_rating = 1

				strengths_str = ", ".join(data.get("strengths", [])) if isinstance(data.get("strengths"), list) else str(data.get("strengths") or "")
				missing_str = ", ".join(data.get("missing_skills", [])) if isinstance(data.get("missing_skills"), list) else str(data.get("missing_skills") or "")
				extracted_skills_str = ", ".join(data.get("extracted_skills", [])) if isinstance(data.get("extracted_skills"), list) else str(data.get("extracted_skills") or "")

				interview_questions_str = json.dumps(data.get("interview_questions", {}), indent=2)

				# Update Main Job Applicant Doc safely
				safe_set_applicant_values(
					job_applicant.name,
					{
						"custom_overall_score": overall_score,
						"custom_match_percentage": data.get("match_percentage", overall_score),
						"custom_confidence_score": data.get("confidence_score", 90),
						"custom_education_score": data.get("education_score", 0),
						"custom_experience_score": data.get("experience_score", 0),
						"custom_skills_score": data.get("skills_score", 0),
						"custom_additional_requirements_score": data.get("additional_requirements_score", 0),
						"custom_is_success": 1,
						"custom_recommendation": recommendation_str,
						"custom_summary": data.get("summary", ""),
						"custom_strengths": strengths_str,
						"custom_missing_skills": missing_str,
						"custom_extracted_skills": extracted_skills_str,
						"custom_interview_questions": interview_questions_str,
						"custom_resume_hash": file_hash,
						"custom_ai_provider": f"{provider_name} ({model_name} - {prompt_version})",
						"applicant_rating": numeric_rating,
					},
				)

				# Append to Job Applicant AI History Child Table safely
				try:
					job_applicant.reload()
					setattr(job_applicant, "applicant_rating", numeric_rating)
					if hasattr(job_applicant, "rating"):
						setattr(job_applicant, "rating", numeric_rating)

					if hasattr(job_applicant, "custom_ai_history"):
						job_applicant.append(
							"custom_ai_history",
							{
								"analysis_date": frappe.utils.now_datetime(),
								"service_provider": provider_name,
								"model_name": model_name,
								"prompt_version": prompt_version,
								"overall_score": overall_score,
								"match_percentage": data.get("match_percentage", overall_score),
								"confidence_score": data.get("confidence_score", 90),
								"recommendation": recommendation_str,
								"rating": numeric_rating,
								"cost": cost,
								"execution_time": ai_response.get("execution_time", 0.0),
								"summary": data.get("summary", ""),
								"raw_json": resp_text,
							},
						)
					job_applicant.save(ignore_permissions=True)
					frappe.db.commit()
				except Exception as e:
					frappe.log_error(f"Error appending to custom_ai_history: {e!s}")

				# Centralized Audit Log
				create_ai_log(
					job_applicant=job_applicant.name,
					service_provider=provider_name,
					model_name=model_name,
					status="Success",
					execution_time=ai_response.get("execution_time", 0.0),
					prompt_tokens=ai_response.get("prompt_tokens", 0),
					completion_tokens=ai_response.get("completion_tokens", 0),
					total_tokens=ai_response.get("total_tokens", 0),
					raw_response=resp_text,
				)

				success = True
				break
			else:
				last_error = f"Invalid/corrupt JSON structure from {provider_name}"
				create_ai_log(
					job_applicant=job_applicant.name,
					service_provider=provider_name,
					model_name=model_name,
					status="Retried" if not is_last_provider else "Failed",
					execution_time=ai_response.get("execution_time", 0.0),
					prompt_tokens=ai_response.get("prompt_tokens", 0),
					completion_tokens=ai_response.get("completion_tokens", 0),
					total_tokens=ai_response.get("total_tokens", 0),
					error_message=last_error,
					raw_response=resp_text,
				)
		else:
			last_error = ai_response.get("error") or f"HTTP {status_code} error from {provider_name}"
			create_ai_log(
				job_applicant=job_applicant.name,
				service_provider=provider_name,
				model_name=model_name,
				status="Retried" if not is_last_provider else "Failed",
				execution_time=ai_response.get("execution_time", 0.0),
				error_message=last_error,
				raw_response=resp_text,
			)

	if not success:
		final_error = f"Analysis failed: {last_error}"
		frappe.db.set_value(
			"Job Applicant",
			job_applicant.name,
			{"custom_is_success": -1, "custom_summary": final_error},
		)
		return {"status": "failed", "reason": final_error}

	return {"status": "success", "applicant": job_applicant.name}


def process_data(lst_job_applicants: List[Any]) -> None:
	for applicant in lst_job_applicants:
		if isinstance(applicant, dict):
			applicant_doc = frappe.get_doc("Job Applicant", applicant.get("name"))
		else:
			applicant_doc = applicant
		process_single_applicant(applicant_doc)
