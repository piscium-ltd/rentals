// Copyright (c) 2026, Piscium Solutions LTD and contributors
// For license information, please see license.txt


frappe.ui.form.on('Identity Record', {
    surname_as_document: function(frm) {
        set_full_name(frm);
    },

    first_name_as_document: function(frm) {
        set_full_name(frm);
    },

    middle_names_as_document: function(frm) {
        set_full_name(frm);
    }
});

function set_full_name(frm) {
    let names = [
        frm.doc.first_name_as_document,
        frm.doc.middle_names_as_document,
        frm.doc.surname_as_document
    ].filter(Boolean);

    frm.set_value('full_name_as_document', names.join(' '));
}