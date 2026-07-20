# Copyright (c) 2026, Invento Software Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class AiAnalysisLog(Document):
	pass


def create_ai_log(
	job_applicant: str,
	service_provider: str | None = None,
	model_name: str | None = None,
	status: str = "Failed",
	execution_time: float = 0.0,
	prompt_tokens: int = 0,
	completion_tokens: int = 0,
	total_tokens: int = 0,
	error_message: str | None = None,
	raw_response: str | None = None,
) -> Document | None:
	"""
	Centralized logger for AI resume analysis execution attempts.
	Updates existing Queued log if present, or creates a new log entry.
	"""
	try:
		# If updating a finished job (Success or Failed), try updating existing Queued log first
		if status in ("Success", "Failed"):
			queued_log_name = frappe.db.get_value(
				"Ai Analysis Log",
				{"job_applicant": job_applicant, "status": "Queued"},
				"name",
				order_by="creation desc",
			)
			if queued_log_name:
				doc = frappe.get_doc("Ai Analysis Log", queued_log_name)
				doc.status = status
				if service_provider:
					doc.service_provider = service_provider
				if model_name:
					doc.model_name = model_name
				doc.execution_time = execution_time
				doc.prompt_tokens = prompt_tokens
				doc.completion_tokens = completion_tokens
				doc.total_tokens = total_tokens or (prompt_tokens + completion_tokens)
				doc.error_message = error_message
				doc.raw_response = raw_response
				doc.save(ignore_permissions=True)
				return doc

		doc = frappe.get_doc(
			{
				"doctype": "Ai Analysis Log",
				"job_applicant": job_applicant,
				"service_provider": service_provider or "System",
				"model_name": model_name or "AI Engine",
				"status": status,
				"execution_time": execution_time,
				"prompt_tokens": prompt_tokens,
				"completion_tokens": completion_tokens,
				"total_tokens": total_tokens or (prompt_tokens + completion_tokens),
				"error_message": error_message,
				"raw_response": raw_response,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc
	except Exception as e:
		frappe.log_error(
			message=f"Failed to create/update Ai Analysis Log: {e!s}",
			title="Ai Log Creation Error",
		)
		return None
