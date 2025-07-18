// Copyright (c) 2025, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("Property", {
    refresh(frm) {
        update_current_values(frm);
    },
    accounting_model: function(frm) {
        update_current_values(frm);
    }
});

frappe.ui.form.on("Valuation History", {
    valuation_date: function(frm) { update_current_values(frm); },
    valued_amount: function(frm) { update_current_values(frm); },
    valuation_history_add: function(frm) { update_current_values(frm); },
    valuation_history_remove: function(frm) { update_current_values(frm); }
});

function update_current_values(frm) {
    if (frm.doc.accounting_model === "Fair Value Model" && frm.doc.valuation_history && frm.doc.valuation_history.length > 0) {
        let last_row = frm.doc.valuation_history[frm.doc.valuation_history.length - 1];
        frm.set_value('current_fair_value', last_row.valued_amount);
        frm.set_value('last_valuation_date', last_row.valuation_date);
    } else {
        frm.set_value('current_fair_value', null);
        frm.set_value('last_valuation_date', null);
    }
}
