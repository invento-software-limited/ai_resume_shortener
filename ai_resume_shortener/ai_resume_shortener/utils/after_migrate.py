import frappe


def create_ai_provider_list():
	"""
	Create AI Provider List, Default Prompt Version, Number Cards, Workspace, and Sync Custom Fields
	"""
	try:
		frappe.sync_customizations("ai_resume_shortener")
	except Exception:
		frappe.log_error(
			title="Ai Resume Shortener: custom field sync failed", message=frappe.get_traceback()
		)

	ai_providers = ["Google Gemini", "OpenRouter"]

	for provider in ai_providers:
		if not frappe.db.exists("Ai Provider", provider):
			doc = frappe.get_doc({"doctype": "Ai Provider", "provider_name": provider})
			doc.insert(ignore_permissions=True)

	if not frappe.db.exists("Ai Prompt Version", "v1.0-default"):
		from ai_resume_shortener.ai_resume_shortener.doctype.ai_config.ai_config import (
			STANDARD_DEFAULT_PROMPT,
		)

		doc = frappe.get_doc(
			{
				"doctype": "Ai Prompt Version",
				"version_name": "v1.0-default",
				"is_active": 1,
				"description": "Standard default ATS resume analysis prompt.",
				"prompt_template": STANDARD_DEFAULT_PROMPT,
			}
		)
		doc.insert(ignore_permissions=True)

	create_number_cards()
	create_ai_resume_shortener_workspace()


def create_number_cards():
	"""
	Creates standard Number Cards for the AI Resume Shortener workspace if not exists.
	"""
	cards = [
		{
			"name": "Total Job Applicants",
			"label": "Total Job Applicants",
			"document_type": "Job Applicant",
			"function": "Count",
			"is_public": 1,
			"module": "Ai Resume Shortener",
		},
		{
			"name": "Analyzed Job Applicants",
			"label": "Analyzed Job Applicants",
			"document_type": "Job Applicant",
			"function": "Count",
			"filters_json": '[["Job Applicant", "custom_is_success", "=", 1]]',
			"is_public": 1,
			"module": "Ai Resume Shortener",
		},
		{
			"name": "Pending AI Analysis",
			"label": "Pending AI Analysis",
			"document_type": "Job Applicant",
			"function": "Count",
			"filters_json": '[["Job Applicant", "custom_is_success", "=", 0]]',
			"is_public": 1,
			"module": "Ai Resume Shortener",
		},
		{
			"name": "Total AI Logs",
			"label": "Total AI Logs",
			"document_type": "Ai Analysis Log",
			"function": "Count",
			"is_public": 1,
			"module": "Ai Resume Shortener",
		},
	]

	for card_def in cards:
		if not frappe.db.exists("Number Card", card_def["name"]):
			try:
				doc = frappe.get_doc({"doctype": "Number Card", **card_def})
				doc.insert(ignore_permissions=True)
			except Exception as e:
				frappe.log_error(f"Error creating Number Card {card_def['name']}: {e!s}")


def create_ai_resume_shortener_workspace():
	"""
	Reloads the standard AI Resume Shortener workspace (ai_resume_shortener/workspace/) after the
	Number Cards it references exist. Content is not overwritten here, so desk edits made via
	developer mode + export are kept.
	"""
	try:
		frappe.reload_doc("ai_resume_shortener", "workspace", "ai_resume_shortener", force=True)
	except Exception:
		frappe.log_error(title="Ai Resume Shortener: workspace reload failed", message=frappe.get_traceback())
		return

	if frappe.db.exists("Workspace", "AI Resume Shortener"):
		frappe.db.set_value("Workspace", "AI Resume Shortener", {"public": 1, "is_hidden": 0})
