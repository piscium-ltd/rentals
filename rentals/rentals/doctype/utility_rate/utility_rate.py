# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class UtilityRate(Document):
	def validate(self):
		# Check if a Utility Rate already exists for the same Utility Provider
		existing_rate = frappe.get_all('Utility Rate', filters={'utility_provider': self.utility_provider}, limit_page_length=1)
		
		if existing_rate:
			existing_rate_name = existing_rate[0].name
			# Generate the link to the existing rate
			rate_url = frappe.utils.get_url(f"app/utility-rate/{existing_rate_name}")
			
			# Throw an error with a clickable link to the existing utility rate
			frappe.throw(_(f"This Utility Provider already has a rate. Please update the existing rate: <a href='{rate_url}'>{existing_rate_name}</a>."))
