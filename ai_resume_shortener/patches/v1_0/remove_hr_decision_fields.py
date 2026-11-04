import frappe


def execute():
	"""Remove the unused HR Decision / HR Feedback Notes custom fields and their columns from Job Applicant."""
	for fieldname in ("custom_hr_decision", "custom_hr_feedback_notes"):
		custom_field = frappe.db.get_value("Custom Field", {"dt": "Job Applicant", "fieldname": fieldname})
		if custom_field:
			frappe.delete_doc("Custom Field", custom_field, ignore_permissions=True, force=True)

		if frappe.db.has_column("Job Applicant", fieldname):
			frappe.db.sql_ddl(f"ALTER TABLE `tabJob Applicant` DROP COLUMN `{fieldname}`")

	frappe.clear_cache(doctype="Job Applicant")
