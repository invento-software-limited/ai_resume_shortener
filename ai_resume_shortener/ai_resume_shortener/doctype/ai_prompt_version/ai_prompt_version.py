# Copyright (c) 2026, Invento Software Limited and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class AiPromptVersion(Document):
	def validate(self):
		if self.is_active:
			# Deactivate other prompt versions
			frappe.db.sql(
				"UPDATE `tabAi Prompt Version` SET is_active = 0 WHERE name != %s",
				self.name,
			)
