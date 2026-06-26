// Copyright (c) 2026, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on('Rentals SMS Settings', {
	refresh(frm) {
		frm.add_custom_button(__('Preview SMS Cleanup'), () => {
			frappe.call({
				method: 'rentals.api.preview_sms_cleanup',
				callback(r) {
					show_sms_cleanup_result(r.message || r);
				},
			});
		}, __('SMS Cleanup'));

		frm.add_custom_button(__('Dry Run Cleanup'), () => {
			frappe.call({
				method: 'rentals.api.run_sms_cleanup',
				args: { dry_run: 1 },
				callback(r) {
					show_sms_cleanup_result(r.message || r);
				},
			});
		}, __('SMS Cleanup'));

		frm.add_custom_button(__('Run Cleanup Now'), () => {
			frappe.confirm(
				__('Run SMS cleanup now using the current retention settings? Archived mode is recommended.'),
				() => {
					frappe.call({
						method: 'rentals.api.run_sms_cleanup',
						args: { dry_run: 0 },
						callback(r) {
							show_sms_cleanup_result(r.message || r);
						},
					});
				}
			);
		}, __('SMS Cleanup'));
	},
});

function show_sms_cleanup_result(result) {
	const smsLog = result.sms_log || {};
	const inboundLog = result.inbound_log || {};
	const html = `
		<div>
			<p><b>${frappe.utils.escape_html(result.message || 'SMS cleanup result')}</b></p>
			<table class="table table-bordered">
				<tr><th>${__('Area')}</th><th>${__('Eligible / Processed')}</th><th>${__('Retention Days')}</th><th>${__('Oldest Eligible')}</th></tr>
				<tr><td>${__('SMS Log')}</td><td>${smsLog.eligible_records ?? smsLog.processed ?? 0}</td><td>${smsLog.retention_days || ''}</td><td>${smsLog.oldest_eligible_record || ''}</td></tr>
				<tr><td>${__('Inbound Log')}</td><td>${inboundLog.eligible_records ?? inboundLog.processed ?? 0}</td><td>${inboundLog.retention_days || ''}</td><td>${inboundLog.oldest_eligible_record || ''}</td></tr>
			</table>
			<p class="text-muted">${__('Mode')}: ${frappe.utils.escape_html(result.cleanup_mode || '')}</p>
		</div>
	`;
	frappe.msgprint({ title: __('SMS Cleanup'), message: html, wide: true });
}
