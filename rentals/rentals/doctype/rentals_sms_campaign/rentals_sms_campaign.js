// Copyright (c) 2026, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on('Rentals SMS Campaign', {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		if (frm.doc.sms_template) {
			frm.add_custom_button(__('Load Template Message'), () => {
				frappe.call({
					method: 'rentals.sms.templates.get_sms_template_message',
					args: { template_name: frm.doc.sms_template },
					freeze: true,
					freeze_message: __('Loading template...'),
					callback(r) {
						if (r.message && r.message.message) {
							frm.set_value('message', r.message.message);
							frappe.show_alert({ message: __('Template message loaded.'), indicator: 'green' });
						}
					},
				});
			});
		}


		frm.add_custom_button(__('SMS Dashboard'), () => {
			frappe.set_route('query-report', 'Rentals SMS Dashboard', {
				sms_campaign: frm.doc.name,
			});
		}, __('Reports'));

		frm.add_custom_button(__('Delivery Detail'), () => {
			frappe.set_route('query-report', 'Rentals SMS Delivery Detail', {
				sms_campaign: frm.doc.name,
			});
		}, __('Reports'));

		frm.add_custom_button(__('Campaign Performance'), () => {
			frappe.set_route('query-report', 'Rentals SMS Campaign Performance');
		}, __('Reports'));

		const lockedStatuses = ['Queued', 'Sending', 'Cancelled'];
		if (!lockedStatuses.includes(frm.doc.status)) {
			frm.add_custom_button(__('Build Recipients'), () => {
				frappe.call({
					method: 'rentals.sms.campaign.build_campaign_recipients',
					args: { campaign_name: frm.doc.name },
					freeze: true,
					freeze_message: __('Building recipients...'),
					callback(r) {
						frm.reload_doc();
						if (r.message) {
							const msg = r.message.message || 'Campaign recipients built.';
							const skipped = cint(r.message.total_skipped || 0);
							frappe.msgprint(__(skipped ? `${msg} Skipped: ${skipped}` : msg));
						}
					},
				});
			});
		}

		const canSend = !['Queued', 'Sending', 'Completed', 'Cancelled'].includes(frm.doc.status);
		if (canSend && cint(frm.doc.total_recipients || 0) > 0) {
			frm.add_custom_button(__('Send Campaign'), () => {
				frappe.confirm(
					__('Queue this campaign for sending to {0} recipient(s)?', [frm.doc.total_recipients]),
					() => {
						frappe.call({
							method: 'rentals.sms.campaign.enqueue_campaign_send',
							args: { campaign_name: frm.doc.name },
							freeze: true,
							freeze_message: __('Queueing campaign...'),
							callback(r) {
								frm.reload_doc();
								if (r.message) {
									frappe.msgprint(__(r.message.message || 'Campaign queued for sending.'));
								}
							},
						});
					}
				);
			}).addClass('btn-primary');
		}
	},

	target_type(frm) {
		if (!frm.is_new() && (frm.doc.recipients || []).length) {
			frappe.show_alert({
				message: __('Target changed. Rebuild recipients before sending.'),
				indicator: 'orange',
			});
		}
	},

	sms_template(frm) {
		if (frm.doc.sms_template && !frm.doc.message) {
			frappe.call({
				method: 'rentals.sms.templates.get_sms_template_message',
				args: { template_name: frm.doc.sms_template },
				callback(r) {
					if (r.message && r.message.message) {
						frm.set_value('message', r.message.message);
					}
				},
			});
		}
	},
});
