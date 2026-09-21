from frappe import _


def get_data():
	return {
		"fieldname": "profile",
		"transactions": [
			{
				"label": _("Connection"),
				"items": [
					"Identity Record",
					"Jurisdiction Profile Release",
				],
			},
		],
	}