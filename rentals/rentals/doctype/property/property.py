# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import today, nowdate


class Property(Document):
    def validate(self):
        """Update Current Fair Value and Last Valuation Date from the last child row."""
        if self.accounting_model == "Fair Value Model" and self.valuation_history:
            last_entry = self.valuation_history[-1]  # Last row in child table
            self.current_fair_value = last_entry.valued_amount
            self.last_valuation_date = last_entry.valuation_date

    def after_insert(self):
        """Create and link an Asset record when a new Property is created."""
        company = frappe.db.get_value("Landlord", self.landlord, "company")
        try:
            # Ensure Asset Category accounts table has a row for this company
            self.ensure_company_in_asset_category(company)

            # Create Asset
            asset = frappe.get_doc({
                "doctype": "Asset",
                "item_code": "Rental Property",
                "asset_name": self.name,
                "asset_category": "Investment Property",
                "company": company,
                "location": self.location,
                "is_existing_asset": 1,
                "available_for_use_date": today(),
                "gross_purchase_amount": self.current_fair_value or 1,
            })

            # Set depreciation details if Cost Model
            if self.accounting_model == "Cost Model":
                asset.calculate_depreciation = 1
                asset.append("finance_books", {
                    "depreciation_method": "Straight Line",
                    "frequency_of_depreciation": 1,
                    "total_number_of_depreciations": 1,
                    "depreciation_start_date": today()
                })

            asset.insert(ignore_permissions=True)
            asset.submit()

            # Link Asset to Property
            self.db_set("asset", asset.name)

            frappe.msgprint(
                f"✅ Property created successfully and linked to Asset <b>{asset.name}</b>",
                indicator="green", alert=True
            )

        except Exception:
            frappe.log_error(frappe.get_traceback(), f"Property.after_insert: Asset creation failed for {self.name}")
            frappe.throw("Failed to create and link Asset. Please check logs.")

    def on_update(self):
        """Automates Journal Entry for fair value adjustments."""
        if self.is_new() or self.accounting_model != "Fair Value Model":
            return

        previous_doc = self.get_doc_before_save()
        if not previous_doc:
            return

        previous_fair_value = previous_doc.current_fair_value or 0
        current_fair_value = self.current_fair_value or 0
        change_in_value = current_fair_value - previous_fair_value

        if abs(change_in_value) < 0.01:
            return

        company = frappe.db.get_value("Landlord", self.landlord, "company")
        company_abbr = frappe.db.get_value("Company", company, "abbr")

        gain_loss_account = f"Gain/Loss on Asset Disposal - {company_abbr}"
        asset_account = f"Buildings - {company_abbr}"

        try:
            je = frappe.new_doc("Journal Entry")
            je.voucher_type = "Journal Entry"
            je.posting_date = nowdate()
            je.company = company
            je.remark = f"Fair value adjustment for property {self.name}"

            if change_in_value > 0:
                # Increase in value: Debit Asset, Credit Gain
                je.append("accounts", {"account": asset_account, "debit_in_account_currency": abs(change_in_value)})
                je.append("accounts", {"account": gain_loss_account, "credit_in_account_currency": abs(change_in_value)})
            else:
                # Decrease in value: Credit Asset, Debit Loss
                je.append("accounts", {"account": asset_account, "credit_in_account_currency": abs(change_in_value)})
                je.append("accounts", {"account": gain_loss_account, "debit_in_account_currency": abs(change_in_value)})

            je.insert(ignore_permissions=True)
            je.submit()

            frappe.msgprint(f"Journal Entry <b>{je.name}</b> created for fair value adjustment.", indicator="green", alert=True)

        except Exception:
            frappe.log_error(frappe.get_traceback(), f"Property.on_update: Journal Entry creation failed for {self.name}")

    def ensure_company_in_asset_category(self, company):
        """Ensure the given company has a row in 'accounts' child table of Asset Category 'Investment Property'."""
        category_name = "Investment Property"
        category = frappe.get_doc("Asset Category", category_name)

        # Check if company already exists in accounts child table
        exists = any(acc.company_name == company for acc in category.accounts)
        if exists:
            return category.name  # Nothing to do

        # Get company abbreviation for account naming
        company_abbr = frappe.db.get_value("Company", company, "abbr")

        # Add new row in accounts child table
        category.append("accounts", {
            "company_name": company,
            "fixed_asset_account": f"Buildings - {company_abbr}",
            "accumulated_depreciation_account": f"Accumulated Depreciation - {company_abbr}",
            "depreciation_expense_account": f"Depreciation - {company_abbr}",
            "capital_work_in_progress_account": f"CWIP Account - {company_abbr}",
        })

        category.save(ignore_permissions=True)

        frappe.msgprint(f"✅ Added accounts for company {company} in Asset Category '{category_name}'", indicator="green", alert=True)

        return category.name
