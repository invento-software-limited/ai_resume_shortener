# Copyright (c) 2026, Invento Software Limited and contributors
# For license information, please see license.txt

import json
import re
from io import BytesIO
from urllib.parse import urlparse

import frappe
import requests
from bs4 import BeautifulSoup
from frappe.model.document import Document
from pypdf import PdfReader


class AiConfig(Document):
	pass


def resume_analysis_scheduler():
	lst_job_applicants = frappe.get_all("Job Applicant", filters={"custom_is_success": 0}, fields=["*"])
	if len(lst_job_applicants) < 1:
		frappe.log_error("No job applicants found for analysis.", "Job Applicant Ai Analysis Error")
		return

	if len(lst_job_applicants) > 0 and len(lst_job_applicants) < 50:
		process_data(lst_job_applicants)
	elif len(lst_job_applicants) >= 50:
		print("Enqueuing job applicants for analysis...")
		frappe.enqueue(
			"ai_resume_shortener.ai_resume_shortener.doctype.ai_config.ai_config.process_data",
			queue="long",
			lst_job_applicants=lst_job_applicants,
		)
	else:
		frappe.log_error(
			"No job applicants found for analysis.",
			"Job Applicant Ai Analysis Error",
			reference_doctype="Job Applicant",
			reference_name="N/A",
		)


def get_resume_analysis_ai_response(job_applicant, resume_text, ai_model_config):
	job_desc = frappe.db.get_value("Job Opening", job_applicant.get("job_title"), "description") or ""

	if (
		ai_model_config.get("service_provider") == "OpenRouter"
		and ai_model_config.get("api_key")
		and ai_model_config.get("enabled")
	):
		return openrouter_resume_analysis(job_desc, resume_text, ai_model_config)

	elif (
		ai_model_config.get("service_provider") == "Google Gemini"
		and ai_model_config.get("api_key")
		and ai_model_config.get("enabled")
	):
		return google_gemini_resume_analysis(job_desc, resume_text, ai_model_config)
	else:
		frappe.log_error(
			message=f"Unsupported AI provider: {ai_model_config.get('service_provider')}",
			reference_doctype="Job Applicant",
			reference_name=job_applicant.name,
			title="AI Model Analysis Error",
		)
		return {
			"status_code": 400,
			"response": None,
			"provider": ai_model_config.get("service_provider"),
		}


def openrouter_resume_analysis(job_desc, resume_text, ai_model_config):
	url = "https://openrouter.ai/api/v1/chat/completions"

	api_key = ai_model_config.get_password("api_key")

	headers = {
		"Authorization": f"Bearer {api_key}",
		"Content-Type": "application/json",
	}

	payload = {
		"model": "openrouter/free",
		"messages": [
			{
				"role": "user",
				"content": f""" You are an expert HR Recruiter and ATS (Applicant Tracking System) evaluator.
				Your task is to compare the candidate's resume with the provided job description and evaluate
				how well the candidate matches the position. Evaluation Rules: - Compare education, work
				experience, technical skills, soft skills, certifications, and additional requirements.
				- Give realistic scores between 0 and 100.
				- Do not give perfect scores unless the resume fully satisfies the job requirements.
				- If information is missing, reduce the relevant score.
				- The overall score should reflect the weighted average of all categories. Return ONLY valid JSON.
				JSON Format: {{ "overall_score": 0, "education_score": 0, "experience_score": 0, "skills_score": 0,
				"additional_requirements_score": 0, "summary": "Write a concise professional summary (3-4 sentences)
				describing how well the candidate matches the job, highlighting key strengths and any noticeable gaps.",
				"strengths": [ "" ], "missing_skills": [ "" ],
				"recommendation": "Highly Recommended | Recommended | Consider | Not Recommended" }}
				Job Description: {job_desc} Resume: {resume_text}
				Important: - Return ONLY valid JSON.
				- Do not include Markdown.
				- Do not include explanations outside the JSON.
				- Ensure the JSON is parseable using json.loads(). """,
			}
		],  # Keep your prompt,
		"max_tokens": 1500,
		"temperature": 0.2,
	}
	try:
		response = requests.post(url, headers=headers, json=payload, timeout=100)
		return {
			"status_code": response.status_code,
			"response": response.json().get("choices", [{}])[0].get("message", {}).get("content", ""),
			"provider": "OpenRouter",
		}
	except Exception as e:
		frappe.log_error(
			message=f"Error in OpenRouter API request: {e!s}",
			reference_doctype="Job Applicant",
			reference_name="N/A",
			title="OpenRouter API Error",
		)
		return {
			"status_code": 500,
			"response": None,
			"provider": "OpenRouter",
		}


def google_gemini_resume_analysis(job_desc, resume_text, ai_model_config):
	api_key = ai_model_config.get_password("api_key")
	url = (
		"https://generativelanguage.googleapis.com/v1beta/"
		f"models/gemini-2.5-flash:generateContent?key={api_key}"
	)
	try:
		response = requests.post(
			url,
			headers={"Content-Type": "application/json"},
			json={
				"contents": [
					{
						"parts": [
							{
								"text": f""" You are an expert HR Recruiter and ATS (Applicant Tracking System) evaluator.
						Your task is to compare the candidate's resume with the provided job description and evaluate
						how well the candidate matches the position. Evaluation Rules: - Compare education, work
						experience, technical skills, soft skills, certifications, and additional requirements.
						- Give realistic scores between 0 and 100.
						- Do not give perfect scores unless the resume fully satisfies the job requirements.
						- If information is missing, reduce the relevant score.
						- The overall score should reflect the weighted average of all categories. Return ONLY valid JSON.
						JSON Format: {{ "overall_score": 0, "education_score": 0, "experience_score": 0, "skills_score": 0,
						"additional_requirements_score": 0, "summary": "Write a concise professional summary (3-4 sentences)
						describing how well the candidate matches the job, highlighting key strengths and any noticeable gaps.",
						"strengths": [ "" ], "missing_skills": [ "" ],
						"recommendation": "Highly Recommended | Recommended | Consider | Not Recommended" }}
						Job Description: {job_desc} Resume: {resume_text}
						Important: - Return ONLY valid JSON.
						- Do not include Markdown.
						- Do not include explanations outside the JSON.
						- Ensure the JSON is parseable using json.loads(). """
							}
						]
					}
				]
			},
			timeout=100,
		)

		return {
			"status_code": response.status_code,
			"response": response.json()["candidates"][0]["content"]["parts"][0]["text"]
			if response.status_code == 200
			else None,
			"provider": "Google Gemini",
		}
	except Exception as e:
		frappe.log_error(
			message=f"Error in Google Gemini API request: {e!s}",
			reference_doctype="Job Applicant",
			reference_name="N/A",
			title="Google Gemini API Error",
		)
		return {
			"status_code": 500,
			"response": None,
			"provider": "Google Gemini",
		}


def get_resume_text(job_applicant):
	try:
		resume_text = ""

		if job_applicant.get("resume_link"):
			if "drive.google.com" in job_applicant.get("resume_link"):
				resume_text = read_google_drive(job_applicant.get("resume_link"))

			elif "docs.google.com" in job_applicant.get("resume_link"):
				resume_text = get_google_doc_text(job_applicant.get("resume_link"))
			else:
				frappe.log_error(
					message="Unsupported resume link. Please provide a Google Drive or Google Docs link.",
					reference_doctype="Job Applicant",
					reference_name=job_applicant.name,
					title="Resume Link Error",
				)
		if job_applicant.get("resume_attachment"):
			file_doc = frappe.get_doc("File", {"file_url": job_applicant.get("resume_attachment")})
			file_content = file_doc.get_content()

			# Ensure file_content is in bytes
			if isinstance(file_content, str):
				file_content = file_content.encode()

			# Extract text
			pdf_reader = PdfReader(BytesIO(file_content))
			resume_text = "".join([page.extract_text() for page in pdf_reader.pages])

		return resume_text
	except Exception as e:
		frappe.log_error(
			message=f"Error in get_resume_text: {e!s}",
			reference_doctype="Job Applicant",
			reference_name=job_applicant.name,
			title="Job Applicant Resume Text Error",
		)


def read_google_drive(url):
	file_id_match = re.search(r"id=([a-zA-Z0-9_-]+)", url) or re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
	if file_id_match:
		file_id = file_id_match.group(1)
		download = f"https://drive.google.com/uc?export=download&id={file_id}"

		response = requests.get(download)

		file_content = response.content
		if isinstance(file_content, str):
			file_content = file_content.encode()

			# Extract text
		pdf_reader = PdfReader(BytesIO(file_content))
		resume_text = "".join([page.extract_text() for page in pdf_reader.pages])

		# response.raise_for_status()

		return resume_text
	return ""


def get_google_doc_text(doc_url):
	doc_id = doc_url.split("/d/")[1].split("/")[0]
	domain = urlparse(doc_url).netloc.lower()

	if "docs.google.com" not in domain:
		frappe.log_error(
			message="Invalid Google Docs URL. Please provide a valid Google Docs link.",
			reference_doctype="Job Applicant",
			reference_name=doc_url,
			title="Google Doc URL Error",
		)

		# 2. GOOGLE DRIVE FILE LINK CONVERSION (Fixes open?id=...

	url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"

	response = requests.get(url)
	if response.status_code != 200:
		frappe.log_error(
			message=f"Failed to fetch Google Doc. Status code: {response.status_code}",
			reference_doctype="Job Applicant",
			reference_name=doc_url,
			title="Google Doc Fetch Error",
		)
	return response.text or ""


def parse_ai_response(ai_response: str):
	try:
		response = ai_response.strip()
		# Remove markdown code block if present
		response = re.sub(r"^```json\s*", "", response, flags=re.IGNORECASE)
		response = re.sub(r"^```\s*", "", response)
		response = re.sub(r"\s*```$", "", response)

		return json.loads(response)
	except Exception:
		return ""


def process_data(lst_job_applicants):
	ai_provider_lst = frappe.get_all("Ai Model Config List", fields=["*"], filters={"enabled": 1})
	ai_model_track = 0
	if len(ai_provider_lst) < 1:
		frappe.log_error(
			message="No enabled AI model configurations found.",
			reference_doctype="Job Applicant",
			reference_name="N/A",
			title="AI Model Configuration Error",
		)
		return
	for idx in range(len(ai_provider_lst)):
		if (
			ai_provider_lst[idx].name == frappe.db.get_single_value("Ai Config", "default")
			and ai_provider_lst[idx].enabled == 1
		):
			ai_model_track = idx
			break

	for job_applicant in lst_job_applicants:
		if not job_applicant.get("resume_attachment") and not job_applicant.get("resume_link"):
			frappe.log_error(
				title="Resume Missing Error",
				message=f"Job Applicant '{job_applicant.name}' is missing both a resume attachment and a resume link.",
				reference_doctype="Job Applicant",
				reference_name=job_applicant.name,
			)
			continue  # Skip to the next job applicant
		resume_text = get_resume_text(job_applicant)

		ai_model_config = frappe.get_doc("Ai Model Config List", ai_provider_lst[ai_model_track].name)
		ai_response = get_resume_analysis_ai_response(job_applicant, resume_text, ai_model_config)

		if ai_response.get("status_code") != 200:
			ai_model_track += 1
			if ai_model_track >= len(ai_provider_lst):
				ai_model_track = 0

			frappe.log_error(
				title="AI Model Analysis Error",
				message=f"AI model analysis failed for {job_applicant.name}. Status code: {ai_response.get('status_code')}. Response: {ai_response.get('response')}",
				reference_doctype="Job Applicant",
				reference_name=job_applicant.name,
			)
			continue  # Skip to the next job applicant

		elif ai_response.get("status_code") == 200:
			data = parse_ai_response(ai_response.get("response")) if ai_response.get("response") else None
			applicant_rating = {
				"Highly Recommended": 0.9,
				"Recommended": 0.8,
				"Consider": 0.6,
				"Not Recommended": 0.4,
			}

			if data and isinstance(data, dict):
				frappe.db.set_value(
					"Job Applicant",
					job_applicant.name,
					{
						"custom_overall_score": data.get("overall_score", 0),
						"custom_education_score": data.get("education_score", 0),
						"custom_experience_score": data.get("experience_score", 0),
						"custom_skills_score": data.get("skills_score", 0),
						"custom_additional_requirements_score": data.get("additional_requirements_score", 0),
						"custom_is_success": 1,
						"custom_recommendation": data.get("recommendation", ""),
						"custom_summary": data.get("summary", ""),
						"custom_strengths": ", ".join(data.get("strengths")) if data.get("strengths") else "",
						"custom_missing_skills": ", ".join(data.get("missing_skills"))
						if data.get("missing_skills")
						else "",
						"custom_ai_provider": ai_response.get("provider"),
						"applicant_rating": applicant_rating.get(data.get("recommendation", ""), 0),
					},
				)
				print(f"Analysis created successfully for {job_applicant.name}")
			# frappe.msgprint(f"Analysis created successfully for {job_applicant.name}")
