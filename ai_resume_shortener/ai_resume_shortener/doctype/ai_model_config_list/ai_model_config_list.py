# Copyright (c) 2026, Invento Software Limited and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document
from frappe.model.naming import make_autoname


class AiModelConfigList(Document):
	def autoname(self):
		self.name = make_autoname(self.service_provider)
