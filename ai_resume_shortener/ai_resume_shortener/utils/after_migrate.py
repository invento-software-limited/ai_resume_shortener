import frappe


def create_ai_provider_list():
	"""
	Create AI Provider List if not exists
	"""
	ai_providers = ["Google Gemini", "OpenRouter"]

	for provider in ai_providers:
		if not frappe.db.exists("Ai Provider", provider):
			doc = frappe.get_doc({"doctype": "Ai Provider", "provider_name": provider})
			doc.insert(ignore_permissions=True)
