
// Copyright (c) 2026, Piscium Solutions LTD and contributors
// For license information, please see license.txt

const PLCI_API =
    "rentals.rentals.doctype.party_legal_and_compliance_identity.party_legal_and_compliance_identity";

frappe.ui.form.on("Party Legal and Compliance Identity", {
    refresh(frm) {

        // Resend verification email
        if (
            !frm.is_new() &&
            frm.doc.email &&
            !frm.doc.email_verified &&
            frappe.model.can_write(frm.doctype)
        ) {
            const resend_button = frm.add_custom_button(
                __("Resend Verification Email"),
                () => {
                    if (frm.__resending_verification) return;

                    frappe.confirm(
                        __("Send a new verification link to {0}?", [
                            frm.doc.email
                        ]),
                        async () => {
                            if (frm.__resending_verification) return;

                            frm.__resending_verification = true;

                            resend_button.prop("disabled", true);
                            resend_button.text(__("Sending..."));

                            try {
                                const response = await frappe.call({
                                    method: `${PLCI_API}.resend_verification_email`,
                                    args: {
                                        name: frm.doc.name
                                    },
                                    freeze: false
                                });

                                if (response.message?.message) {
                                    frappe.show_alert({
                                        message: __("Verification email sent successfully"),
                                        indicator: "green"
                                    }, 5);

                                    await frm.reload_doc();
                                }
                            } catch (error) {
                                console.error(
                                    "Email verification resend failed:",
                                    error
                                );

                                frappe.show_alert({
                                    message: __("Unable to send verification email"),
                                    indicator: "red"
                                }, 5);
                            } finally {
                                frm.__resending_verification = false;

                                resend_button.prop("disabled", false);
                                resend_button.text(
                                    __("Resend Verification Email")
                                );
                            }
                        }
                    );
                }
            );
        }

        // Party Code generation
        if (
            !frm.is_new() ||
            frm.doc.party_code ||
            frm.__party_code_loading
        ) {
            return;
        }

        frm.__party_code_loading = true;

        frappe.call({
            method: `${PLCI_API}.get_new_party_code`
        })
        .then((response) => {
            if (
                response.message &&
                frm.is_new() &&
                !frm.doc.party_code
            ) {
                return frm.set_value(
                    "party_code",
                    response.message
                );
            }
        })
        .finally(() => { frm.__party_code_loading = false; });
    }
});
