"""Zusatzfeld am Kontakt: Haken "Helpdesk-Kunden anlegen"."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def zusatzfelder_anlegen() -> None:
	"""Idempotent; läuft nach Installation und nach jedem `bench migrate`."""
	create_custom_fields(
		{
			"Contact": [
				{
					"fieldname": "hd_kunde_anlegen",
					"fieldtype": "Check",
					"label": "Helpdesk-Kunden anlegen",
					"description": (
						"Beim Speichern: Hat ein verknüpfter Kunde noch keinen Helpdesk-Kunden, "
						"wird er angelegt und der Kontakt wird Mitglied. Der Haken wird danach zurückgesetzt."
					),
					"insert_after": "links",
					"default": "0",
					"allow_in_quick_entry": 1,
					"no_copy": 1,
					"print_hide": 1,
					"report_hide": 1,
				}
			]
		}
	)
