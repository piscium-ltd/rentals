// Copyright (c) 2026, Piscium Solutions LTD and contributors
// For license information, please see license.txt


frappe.ui.form.on('Identity Record', {
    setup(frm) {
        configure_location_queries(frm);
        update_location_field_states(frm);
    },

    refresh(frm) {
        configure_location_queries(frm);
        update_location_field_states(frm);
    },

    county(frm) {
        clear_fields(frm, [
            'constituency',
            'ward',
            'location',
            'sub_location'
        ]);

        update_location_field_states(frm);
    },

    constituency(frm) {
        clear_fields(frm, [
            'ward',
            'location',
            'sub_location'
        ]);

        update_location_field_states(frm);
    },

    ward(frm) {
        clear_fields(frm, [
            'location',
            'sub_location'
        ]);

        update_location_field_states(frm);
    },

    location(frm) {
        clear_fields(frm, [
            'sub_location'
        ]);

        update_location_field_states(frm);
    },

    surname_as_document(frm) {
        set_full_name(frm);
    },

    first_name_as_document(frm) {
        set_full_name(frm);
    },

    middle_names_as_document(frm) {
        set_full_name(frm);
    }
});


function configure_location_queries(frm) {
    frm.set_query('constituency', () => ({
        filters: {
            county: frm.doc.county
        }
    }));

    frm.set_query('ward', () => ({
        filters: {
            constituency: frm.doc.constituency
        }
    }));

    frm.set_query('location', () => ({
        filters: {
            ward: frm.doc.ward
        }
    }));

    frm.set_query('sub_location', () => ({
        filters: {
            location: frm.doc.location
        }
    }));
}


function clear_fields(frm, fields) {
    fields.forEach(fieldname => {
        if (frm.fields_dict[fieldname] && frm.doc[fieldname]) {
            frm.set_value(fieldname, null);
        }
    });
}


function update_location_field_states(frm) {
    if (frm.fields_dict.constituency) {
        frm.toggle_enable(
            'constituency',
            Boolean(frm.doc.county)
        );
    }

    if (frm.fields_dict.ward) {
        frm.toggle_enable(
            'ward',
            Boolean(frm.doc.constituency)
        );
    }

    if (frm.fields_dict.location) {
        frm.toggle_enable(
            'location',
            Boolean(frm.doc.ward)
        );
    }

    if (frm.fields_dict.sub_location) {
        frm.toggle_enable(
            'sub_location',
            Boolean(frm.doc.location)
        );
    }
}


function set_full_name(frm) {
    let names = [
        frm.doc.first_name_as_document,
        frm.doc.middle_names_as_document,
        frm.doc.surname_as_document
    ].filter(Boolean);

    frm.set_value('full_name_as_document', names.join(' '));
}

