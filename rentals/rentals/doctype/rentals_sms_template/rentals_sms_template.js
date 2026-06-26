// Copyright (c) 2026, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on('Rentals SMS Template', {
	refresh(frm) {
		frm.add_custom_button(__('Preview Template'), () => {
			frappe.call({
				method: 'rentals.sms.templates.preview_sms_template',
				args: {
					template_name: frm.doc.name,
				},
				freeze: true,
				freeze_message: __('Rendering preview...'),
				callback(r) {
					if (r.message) {
						frm.set_value('preview_message', r.message.message || '');
						frappe.msgprint({
							title: __('SMS Preview'),
							message: frappe.utils.escape_html(r.message.message || ''),
							indicator: 'blue',
						});
					}
				},
			});
		});
	},
});
