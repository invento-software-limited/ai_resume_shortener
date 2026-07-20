import json
import frappe


def create_ai_provider_list():
	"""
	Create AI Provider List, Default Prompt Version, Number Cards, Workspace, and Sync Custom Fields
	"""
	try:
		frappe.sync_customizations("ai_resume_shortener")
	except Exception:
		pass

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
	Ensures the AI Resume Shortener workspace doc exists in the database and is publicly visible to all roles.
	"""
	try:
		frappe.reload_doc("ai_resume_shortener", "workspace", "ai_resume_shortener", force=True)
	except Exception:
		pass

	workspace_name = "AI Resume Shortener"

	number_cards = [
		{"label": "Total Job Applicants", "number_card_name": "Total Job Applicants"},
		{"label": "Analyzed Job Applicants", "number_card_name": "Analyzed Job Applicants"},
		{"label": "Pending AI Analysis", "number_card_name": "Pending AI Analysis"},
		{"label": "Total AI Logs", "number_card_name": "Total AI Logs"},
	]

	shortcuts = [
		{"color": "Blue", "doc_view": "List", "label": "Job Applicants", "link_to": "Job Applicant", "type": "DocType"},
		{"color": "Green", "doc_view": "List", "label": "AI Configuration", "link_to": "Ai Config", "type": "DocType"},
		{"color": "Orange", "doc_view": "List", "label": "Prompt Versions", "link_to": "Ai Prompt Version", "type": "DocType"},
		{"color": "Purple", "doc_view": "List", "label": "AI Analysis Logs", "link_to": "Ai Analysis Log", "type": "DocType"},
		{"color": "Gray", "doc_view": "List", "label": "AI Providers", "link_to": "Ai Provider", "type": "DocType"},
	]

	links = [
		{"hidden": 0, "is_query_report": 0, "label": "Applicant Intelligence", "type": "Card Break"},
		{"hidden": 0, "is_query_report": 0, "label": "Job Applicant", "link_to": "Job Applicant", "link_type": "DocType", "type": "Link"},
		{"hidden": 0, "is_query_report": 0, "label": "Job Opening", "link_to": "Job Opening", "link_type": "DocType", "type": "Link"},
		{"hidden": 0, "is_query_report": 0, "label": "AI Configuration & Engine", "type": "Card Break"},
		{"hidden": 0, "is_query_report": 0, "label": "Ai Config", "link_to": "Ai Config", "link_type": "DocType", "type": "Link"},
		{"hidden": 0, "is_query_report": 0, "label": "Ai Prompt Version", "link_to": "Ai Prompt Version", "link_type": "DocType", "type": "Link"},
		{"hidden": 0, "is_query_report": 0, "label": "Ai Provider", "link_to": "Ai Provider", "link_type": "DocType", "type": "Link"},
		{"hidden": 0, "is_query_report": 0, "label": "Audit & Analytics", "type": "Card Break"},
		{"hidden": 0, "is_query_report": 0, "label": "Ai Analysis Log", "link_to": "Ai Analysis Log", "link_type": "DocType", "type": "Link"},
	]

	content = json.dumps([
		{"type": "header", "data": {"text": "AI Resume Shortener Intelligence Center", "level": 3}},
		{"type": "number_card", "data": {"number_card_name": "Total Job Applicants"}},
		{"type": "number_card", "data": {"number_card_name": "Analyzed Job Applicants"}},
		{"type": "number_card", "data": {"number_card_name": "Pending AI Analysis"}},
		{"type": "number_card", "data": {"number_card_name": "Total AI Logs"}},
		{"type": "shortcut", "data": {"shortcut_name": "Job Applicants"}},
		{"type": "shortcut", "data": {"shortcut_name": "AI Configuration"}},
		{"type": "shortcut", "data": {"shortcut_name": "Prompt Versions"}},
		{"type": "shortcut", "data": {"shortcut_name": "AI Analysis Logs"}},
		{"type": "shortcut", "data": {"shortcut_name": "AI Providers"}},
		{"type": "card", "data": {"card_name": "Applicant Intelligence"}},
		{"type": "card", "data": {"card_name": "AI Configuration & Engine"}},
		{"type": "card", "data": {"card_name": "Audit & Analytics"}},
	])

	if not frappe.db.exists("Workspace", workspace_name):
		doc = frappe.get_doc({
			"doctype": "Workspace",
			"name": workspace_name,
			"label": workspace_name,
			"title": workspace_name,
			"module": "Ai Resume Shortener",
			"icon": "briefcase",
			"indicator_color": "green",
			"public": 1,
			"is_hidden": 0,
			"content": content,
			"number_cards": number_cards,
			"shortcuts": shortcuts,
			"links": links,
			"roles": [],
		})
		doc.insert(ignore_permissions=True)
	else:
		frappe.db.set_value(
			"Workspace",
			workspace_name,
			{
				"public": 1,
				"is_hidden": 0,
				"module": "Ai Resume Shortener",
				"content": content,
			},
		)

	frappe.db.commit()
	frappe.clear_cache()
