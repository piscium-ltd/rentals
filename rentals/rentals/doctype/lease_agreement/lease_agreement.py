# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
import random
from frappe.model.document import Document
from frappe import _
from frappe.utils import today, add_days, add_months, add_years, getdate
from erpnext.accounts.doctype.payment_request.payment_request import make_payment_request


class LeaseAgreement(Document):
    def autoname(self):
        if not self.landlord:
            frappe.throw("Landlord must be set before generating name.")

        # Get abbreviation from linked Landlord
        abbr = frappe.db.get_value("Landlord", self.landlord, "abbr")
        if not abbr:
            frappe.throw("Landlord abbreviation not found.")

        for _ in range(100):  # avoid infinite loop
            prime_number = generate_prime_number()
            name = f"{abbr}{prime_number}"
            if not frappe.db.exists("Lease Agreement", name):
                self.name = name
                return

        frappe.throw("Unable to generate unique Lease Agreement name.")

    def validate(self):
        # Check if there's an active lease already assigned to this unit
        active_leases = frappe.get_all(
            "Lease Agreement",
            filters={
                "unit": self.unit,
                "status": "Active",
                "docstatus": ["!=", 2],
                "name": ["!=", self.name]
            },
            fields=["name", "tenant", "start_date", "end_date"]
        )

        if active_leases:
            # Get the first active lease from the result
            active_lease = active_leases[0]
            lease_url = frappe.utils.get_url(f"app/lease-agreement/{active_lease.name}")
            
            # Throw an informative error with a clickable link to the existing lease
            frappe.throw(_(f"Unit {self.unit} is already assigned to a tenant. Please check the existing agreement: <a href='{lease_url}'>{active_lease.name}</a>."))

    def before_save(self):
        # Calculate Grand Total from child table
        total = 0
        base_date = getdate(today())

        for row in self.chargeable_services:
            total += row.rate

            # Only set billing date if not already set
            if not row.billing_date:
                if row.billing_cycle == "Once":
                    row.billing_date = base_date
                elif row.billing_cycle == "Daily":
                    row.billing_date = add_days(base_date, 1)
                elif row.billing_cycle == "Weekly":
                    row.billing_date = add_days(base_date, 7)
                elif row.billing_cycle == "Monthly":
                    row.billing_date = add_months(base_date, 1)
                elif row.billing_cycle == "Annually":
                    row.billing_date = add_years(base_date, 1)
                else:
                    row.billing_date = base_date

        self.grand_total = total

    def on_submit(self):
        # Fetch required documents
        unit_doc = frappe.get_doc("Unit", self.unit)
        landlord_doc = frappe.get_doc("Landlord", self.landlord)
        tenant_doc = frappe.get_doc("Tenant", self.tenant)

        # Mark unit as occupied
        unit_doc.status = "Occupied"
        unit_doc.save()
        frappe.msgprint(_(f"✅ Unit <b>{unit_doc.name}</b> marked as occupied."))

        # Validate required links
        if not landlord_doc.company:
            frappe.msgprint(_("⚠️ Landlord is not linked to a Company."), alert=True)
            return

        if not tenant_doc.customer:
            frappe.msgprint(_("⚠️ Tenant is not linked to a Customer."), alert=True)
            return

        company = landlord_doc.company
        customer_name = self.tenant_name
        price_list_name = f"{customer_name} Price List"

        # Create price list if it doesn't exist
        if not frappe.db.exists("Price List", price_list_name):
            frappe.get_doc({
                "doctype": "Price List",
                "price_list_name": price_list_name,
                "currency": self.billing_currency,
                "selling": 1,
                "enabled": 1
            }).insert(ignore_permissions=True)
            frappe.msgprint(_(f"✅ Created new Price List: <b>{price_list_name}</b>"))

        # Update customer default price list and currency
        customer_doc = frappe.get_doc("Customer", tenant_doc.customer)
        updated = False

        if customer_doc.default_price_list != price_list_name:
            customer_doc.default_price_list = price_list_name
            updated = True

        if customer_doc.default_currency != self.billing_currency:
            customer_doc.default_currency = self.billing_currency
            updated = True

        if updated:
            customer_doc.save(ignore_permissions=True)
            frappe.msgprint(_(f"✅ Updated Customer <b>{customer_doc.name}</b> with default Price List and Currency."))

        # Create or update item prices
        for row in self.chargeable_services:
            item_code = row.service
            rate = row.rate

            if not rate:
                frappe.msgprint(_(f"⚠️ No rate specified for item <b>{item_code}</b>. Skipping."), alert=True)
                continue

            item_price_name = frappe.db.exists("Item Price", {
                "item_code": item_code,
                "price_list": price_list_name
            })

            if item_price_name:
                item_price = frappe.get_doc("Item Price", item_price_name)
                if item_price.price_list_rate != rate:
                    item_price.price_list_rate = rate
                    item_price.save(ignore_permissions=True)
                    frappe.msgprint(_(f"🔁 Updated price for item <b>{item_code}</b> in <b>{price_list_name}</b>."))
            else:
                frappe.get_doc({
                    "doctype": "Item Price",
                    "item_code": item_code,
                    "price_list": price_list_name,
                    "price_list_rate": rate,
                    "currency": self.billing_currency,
                    "customer": customer_name
                }).insert(ignore_permissions=True)
                frappe.msgprint(_(f"✅ Created price for item <b>{item_code}</b> in <b>{price_list_name}</b>."))

        # Create Sales Order
        items = []
        for row in self.chargeable_services:
            if row.rate:
                items.append({
                    "item_code": row.service,
                    "qty": 1,
                    "rate": row.rate,
                    "delivery_date": frappe.utils.nowdate()
                })

        sales_order = frappe.get_doc({
            "doctype": "Sales Order",
            "company": company,
            "custom_lease_agreement": self.name,
            "customer": tenant_doc.customer,
            "currency": self.billing_currency,
            "selling_price_list": price_list_name,
            "transaction_date": frappe.utils.nowdate(),
            "delivery_date": frappe.utils.nowdate(),
            "items": items
        })
        sales_order.insert(ignore_permissions=True)
        sales_order.submit()
        frappe.msgprint(_(f"✅ Sales Order <b>{sales_order.name}</b> created and submitted."))

        # Create Payment Request
        recipient_email = tenant_doc.email
        if not recipient_email:
            frappe.msgprint(_("⚠️ Tenant does not have an email address. Payment Request skipped."), alert=True)
            return

        payment_request = make_payment_request(
            dt="Sales Order",
            dn=sales_order.name,
            recipient_id=recipient_email,
            return_doc=True,
            submit_doc=False
        )

        payment_request.subject = f"Payment Request for Account Number {self.name}"
        payment_request.message = (
            f"""
            <p>Dear {self.tenant_name},</p>
            <p>Requesting payment against Account Number {self.name} for amount Sh. {self.grand_total:,.0f}</p>
            <p>If you have any questions, please get back to us.</p>
            <p>Thank you for your business!</p>
            """
        )

        payment_request.save()
        payment_request.submit()

        frappe.msgprint(_(f"✅ Payment Request <b>{payment_request.name}</b> created and sent to <b>{recipient_email}</b>."))

        # TO DO:
        # 1. Update Price List and Item Price Logic (1PL Per customer per company or just per LA)
        # 2. Add on cancel method
        # 3. THOUGHT -> Landlord (Company) should fetch logged in user??

def is_prime(n):
        if n < 2 or n % 2 == 0:
            return n == 2
        for a in (2, 3, 5, 7, 11):
            if n == a:
                return True
            if pow(a, n - 1, n) != 1:
                return False
        return True

def generate_prime_number():
    for _ in range(1000):  # attempt limit
        number = random.randint(1_000_000, 9_999_999)
        if is_prime(number):
            return str(number)
    frappe.throw("Unable to generate prime number.")
