# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
import random

from frappe.model.document import Document
from frappe import _
from frappe.utils import (
    today, add_days, add_months, getdate, nowdate, get_url, flt
)
from erpnext.accounts.doctype.payment_request.payment_request import make_payment_request

class LeaseAgreement(Document):
    def autoname(self):
        """Generate a unique name using company abbreviation and a Luhn-valid 7-digit number."""
        self._ensure_company_exists()
        abbr = self._get_company_abbreviation()

        for _ in range(100):
            number = generate_luhn_number(7)
            name = f"{abbr}{number}"
            if not frappe.db.exists("Lease Agreement", name):
                self.name = name
                return

        frappe.throw("Unable to generate a unique Lease Agreement name after 100 attempts.")

    def _ensure_company_exists(self):
        """Ensure the company field is populated before generating a name."""
        if not self.company:
            frappe.throw("Company must be set before generating the Lease Agreement name.")

    def _get_company_abbreviation(self):
        """Return the company abbreviation from the Company record."""
        abbr = frappe.db.get_value("Company", self.company, "abbr")
        if not abbr:
            frappe.throw("No abbreviation found for the selected company.")
        return abbr

    def validate(self):
        """Run date validations and ensure the unit is not already leased."""
        self._validate_date_range()
        self._check_for_active_lease()

    def _validate_date_range(self):
        """Ensure end date is after start date."""
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            frappe.throw("End Date must be after Start Date.")

    def _check_for_active_lease(self):
        """Prevent leasing a unit that already has an active lease."""
        if not self.unit:
            return

        existing = frappe.get_all(
            "Lease Agreement",
            filters={
                "unit": self.unit,
                "status": "Active",
                "docstatus": ["!=", 2],
                "name": ["!=", self.name]
            },
            fields=["name"]
        )

        if existing and self.agency_type != "Full Agency":
            lease_url = get_url(f"/app/lease-agreement/{existing[0].name}")
            frappe.throw(_(
                f"Unit {self.unit} is already assigned. See agreement: "
                f"<a href='{lease_url}'>{existing[0].name}</a>."
            ))

    def before_save(self):
        """Set default customer, property assignment, compute dates and calculate totals before saving."""
        self._set_rent_item_if_missing()
        self._set_customer_if_missing()
        self._set_property_assignment_if_missing()
        self._compute_billing_dates()
        self._calculate_chargeable_services_subtotal()
        self._calculate_security_deposits_subtotal()
        self._calculate_grand_total()

    def _set_rent_item_if_missing(self):
        """Set the item field to 'Rent' if it is not already set."""
        if not self.rent_item:
            self.rent_item = "Rent"

    def _set_customer_if_missing(self):
        """Set customer from linked tenant, if not already set."""
        if self.tenant and not self.customer:
            self.customer = frappe.db.get_value("Tenant", self.tenant, "customer")

    def _set_property_assignment_if_missing(self):
        """Set property assignment from available property assignments."""
        if self.property and not self.property_assignment:
            assignment = frappe.get_all(
                "Property Assignment",
                filters={"property": self.property},
                fields=["name"],
                limit_page_length=1
            )
            if assignment:
                self.property_assignment = assignment[0].name

    def _compute_billing_dates(self):
        """Set billing_date for self and all chargeable services without a billing_date."""
        today_date = getdate(today())

        if self.billing_cycle and not self.billing_date:
            self.billing_date = self._get_billing_date(self.billing_cycle, today_date)

        for row in self.chargeable_services:
            if row.billing_cycle and not row.billing_date:
                row.billing_date = self._get_billing_date(row.billing_cycle, today_date)

    def _get_billing_date(self, cycle, base_date=None):
        """Return next billing date based on the billing cycle."""
        base_date = base_date or getdate(today())

        match cycle:
            case "Daily":
                return add_days(base_date, 1)
            case "Monthly":
                return add_months(base_date, 1)
            case "Quarterly":
                return add_months(base_date, 3)
            case "Annually":
                return add_months(base_date, 12)
            case _:
                return None

    def _calculate_chargeable_services_subtotal(self):
        """Compute total for chargeable services and update subtotal field."""
        self.chargeable_services_subtotal = sum(flt(row.rate) for row in self.chargeable_services)

    def _calculate_security_deposits_subtotal(self):
        """Compute total for security deposits and update subtotal field."""
        self.security_deposits_subtotal = sum(flt(row.rate) for row in self.security_deposits)

    def _calculate_grand_total(self):
        """Compute grand total from base rent, chargeable services, and security deposits."""
        self.grand_total = sum([
            flt(self.base_rental_amount),
            flt(self.chargeable_services_subtotal),
            flt(self.security_deposits_subtotal),
        ])

    def on_submit(self):
        """Handle unit occupation, customer setup, and create sales and payment documents."""
        self._mark_unit_as_occupied()
        self._create_price_list_and_update_customer()
        sales_order = self._create_sales_order()
        self._create_payment_request(sales_order)
        self._create_duplicate_if_full_agency()

    def _mark_unit_as_occupied(self):
        """Mark the leased unit as occupied if not already."""
        unit = frappe.get_doc("Unit", self.unit)
        if unit.status != "Occupied":
            unit.status = "Occupied"
            unit.save()
            frappe.msgprint(
                _(f"Unit <b>{unit.name}</b> marked as occupied."),
                alert=True,
                indicator="green"
            )

    def _create_price_list_and_update_customer(self):
        """Ensure price list exists and update customer defaults."""
        price_list = f"{self.customer} Price List"
        self._create_price_list_if_missing(price_list)
        self._update_customer_defaults(self.customer, price_list)

        for row in self.chargeable_services:
            self._sync_item_price(row, price_list, self.customer)

    def _create_price_list_if_missing(self, name):
        """Create a new Price List if one does not already exist."""
        if not frappe.db.exists("Price List", name):
            frappe.get_doc({
                "doctype": "Price List",
                "price_list_name": name,
                "currency": self.billing_currency,
                "selling": 1,
                "buying": 1,
                "enabled": 1
            }).insert(ignore_permissions=True)

            frappe.msgprint(
                _(f"Created new Price List: <b>{name}</b>"),
                alert=True,
                indicator="green"
            )

    def _update_customer_defaults(self, customer_name, price_list):
        """Update the customer's default price list and currency if needed."""
        customer = frappe.get_doc("Customer", customer_name)
        updated = False

        if customer.default_price_list != price_list:
            customer.default_price_list = price_list
            updated = True

        if customer.default_currency != self.billing_currency:
            customer.default_currency = self.billing_currency
            updated = True

        if updated:
            customer.save(ignore_permissions=True)
            frappe.msgprint(
                _(f"Updated customer <b>{customer.name}</b> defaults."),
                alert=True,
                indicator="green"
            )

    def _sync_item_price(self, row, price_list, customer_name):
        """Ensure item price is accurate for each chargeable service."""
        if not row.rate:
            frappe.msgprint(
                _(f"No rate set for item <b>{row.service}</b>. Skipping."),
                alert=True
            )
            return

        item_price_name = frappe.db.exists("Item Price", {
            "item_code": row.service,
            "price_list": price_list
        })

        if item_price_name:
            item_price = frappe.get_doc("Item Price", item_price_name)
            if item_price.price_list_rate != row.rate:
                item_price.price_list_rate = row.rate
                item_price.save(ignore_permissions=True)
                frappe.msgprint(
                    _(f"Updated price for <b>{row.service}</b>."),
                    alert=True,
                    indicator="green"
                )
        else:
            frappe.get_doc({
                "doctype": "Item Price",
                "item_code": row.service,
                "price_list": price_list,
                "price_list_rate": row.rate,
                "currency": self.billing_currency,
                "customer": customer_name
            }).insert(ignore_permissions=True)

            frappe.msgprint(
                _(f"Created price for <b>{row.service}</b>."),
                alert=True,
                indicator="green"
            )

    def _create_sales_order(self):
        """Create a Sales Order with rent, chargeable services, and security deposits."""
        if self.get("__is_duplicate"):
            return

        items = []

        # Add rent item
        if self.rent_item and self.base_rental_amount:
            items.append({
                "item_code": self.rent_item,
                "qty": 1,
                "rate": self.base_rental_amount,
                "delivery_date": nowdate()
            })

        # Add chargeable services
        for row in self.chargeable_services:
            if row.service and row.rate:
                items.append({
                    "item_code": row.service,
                    "qty": 1,
                    "rate": row.rate,
                    "delivery_date": nowdate()
                })

        # Add security deposits
        for row in self.security_deposits:
            if row.security_type and row.rate:
                items.append({
                    "item_code": row.security_type,
                    "qty": 1,
                    "rate": row.rate,
                    "delivery_date": nowdate()
                })

        if not items:
            frappe.msgprint(_("No items to add to Sales Order. Skipping creation."))
            return

        sales_order = frappe.get_doc({
            "doctype": "Sales Order",
            "company": self.company,
            "custom_lease_agreement": self.name,
            "customer": self.customer,
            "currency": self.billing_currency,
            "selling_price_list": f"{self.customer} Price List",
            "transaction_date": nowdate(),
            "delivery_date": nowdate(),
            "items": items
        })
        sales_order.insert(ignore_permissions=True)
        sales_order.submit()

        frappe.msgprint(
            _(f"Sales Order <b>{sales_order.name}</b> created."),
            alert=True,
            indicator="green"
        )
        return sales_order

    def _create_payment_request(self, sales_order):
        """Create a Payment Request and email it to the customer."""
        if self.get("__is_duplicate"):
            return

        email = frappe.db.get_value("Customer", self.customer, "email_id")
        if not email:
            frappe.msgprint(_("Tenant has no email. Payment Request skipped."), alert=True)
            return

        payment_request = make_payment_request(
            dt="Sales Order",
            dn=sales_order.name,
            recipient_id=email,
            return_doc=True,
            submit_doc=False
        )
        payment_request.subject = f"Payment Request for Lease {self.name}"
        payment_request.message = (
            f"<p>Dear {self.customer},</p>"
            f"<p>Please make payment for Account Number <b>{self.name}</b> totaling "
            f"<b>Sh. {self.grand_total:,.0f}</b>.</p><p>Thank you.</p>"
        )
        payment_request.save()
        payment_request.submit()

        frappe.msgprint(
            _(f"Payment Request <b>{payment_request.name}</b> sent to <b>{email}</b>."),
            alert=True,
            indicator="green"
        )

    def _create_duplicate_if_full_agency(self):
        """Duplicate the Lease Agreement for the landlord if this is a full agency case."""
        if self.agency_type != "Full Agency" or self.get("__is_duplicate"):
            return

        landlord_company = frappe.db.get_value("Landlord", self.landlord, "company")
        if not landlord_company:
            frappe.msgprint(_("Landlord is not linked to a company. Skipping duplicate."))
            return

        agent_customer = frappe.db.get_value("Agent", self.agent, "customer")
        if not agent_customer:
            frappe.msgprint(_("Agent is not linked to a customer. Skipping duplicate."))
            return

        duplicate = frappe.copy_doc(self)
        duplicate.customer = agent_customer
        duplicate.company = landlord_company
        duplicate.name = None
        duplicate.set("__is_duplicate", True)
        duplicate.insert(ignore_permissions=True)
        duplicate.submit()

        frappe.msgprint(
            _(f"Duplicate Lease Agreement <b>{duplicate.name}</b> created."),
            alert=True,
            indicator="green"
        )

def generate_luhn_number(num_digits):
    """
    Generate a random number string of specified length that passes the Luhn algorithm.
    The last digit is a check digit.
    """
    if num_digits < 2:
        raise ValueError("Length must be at least 2 to include a check digit.")

    base = [random.randint(0, 9) for _ in range(num_digits - 1)]
    check_digit = calculate_luhn_check_digit(base)
    return ''.join(map(str, base + [check_digit]))

def calculate_luhn_check_digit(digits):
    """
    Calculate the Luhn check digit for a list of digits.
    This digit ensures the full number passes the Luhn checksum.
    """
    total = 0
    reverse_digits = digits[::-1]

    for i, digit in enumerate(reverse_digits):
        if i % 2 == 0:
            doubled = digit * 2
            total += doubled if doubled < 10 else sum(map(int, str(doubled)))
        else:
            total += digit

    return (10 - (total % 10)) % 10
