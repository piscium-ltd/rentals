# Copyright (c) 2026, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import secrets

import frappe
from frappe.model.document import Document


EMAIL_TEMPLATE = "Party Legal and Compliance Email Verification"


def generate_verification_token():
    return secrets.token_urlsafe(32)


def send_verification_email(doc):
    """Send email verification email for a Party Legal and Compliance Identity."""

    if not doc.email:
        return

    if doc.email_verified:
        return

    template = frappe.get_doc("Email Template", EMAIL_TEMPLATE)

    subject = frappe.render_template(
        template.subject,
        {"doc": doc}
    )

    message = frappe.render_template(
        template.response_html,
        {"doc": doc}
    )

    frappe.sendmail(
        recipients=[doc.email],
        subject=subject,
        message=message,
        reference_doctype=doc.doctype,
        reference_name=doc.name,
        delayed=True
    )


class PartyLegalandComplianceIdentity(Document):

    def before_insert(self):
        if self.email:
            self.email_verification_token = generate_verification_token()
            self.email_verified = 0
            self.lifecycle_status = "Pending Verification"

    def after_insert(self):
        if self.email and not self.email_verified:
            send_verification_email(self)

    def before_save(self):
        if self.is_new():
            return

        if self.has_value_changed("email"):
            if self.email:
                self.email_verification_token = generate_verification_token()
                self.email_verified = 0
                self.lifecycle_status = "Pending Verification"
            else:
                self.email_verification_token = None
                self.email_verified = 0
                self.lifecycle_status = "Pending Verification"

    def on_update(self):
        if (
            self.has_value_changed("email")
            and self.email
            and not self.email_verified
        ):
            send_verification_email(self)


@frappe.whitelist(allow_guest=True)
def verify_email(name, token):
    """Verify the email address and mark the PLCI record as Valid."""

    doc = frappe.get_doc(
        "Party Legal and Compliance Identity",
        name
    )

    if not doc.email_verification_token:
        frappe.throw("This verification link is no longer valid.")

    if not secrets.compare_digest(
        str(doc.email_verification_token),
        str(token)
    ):
        frappe.throw("Invalid email verification link.")

    doc.email_verified = 1
    doc.lifecycle_status = "Valid"
    doc.email_verification_token = None

    doc.save(ignore_permissions=True)

    frappe.db.commit()

    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = "/verify-email-success"