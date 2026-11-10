app_name = "helpdesk_erpnext_sync"
app_title = "Helpdesk ERPNext Sync"
app_publisher = "David Nienhaus"
app_description = "Ergaenzt den Kunden-Sync zwischen Frappe Helpdesk und ERPNext"
app_email = "317006733+nienhausdavid@users.noreply.github.com"
app_license = "mit"

required_apps = ["frappe/erpnext", "frappe/helpdesk"]

# Der "Sync Customers"-Knopf im Helpdesk ruft diese Methode auf. Wir ersetzen sie
# durch eine Variante, die nach dem Standard-Sync nacharbeitet.
override_whitelisted_methods = {
	"helpdesk.integrations.erpnext.api.sync_hd_erpnext_customers": "helpdesk_erpnext_sync.helpdesk_erpnext_sync.sync.sync_hd_erpnext_customers",
}

# Knopf "Kontakt verknüpfen" am Kundenformular
doctype_js = {"Customer": "public/js/kunde.js"}

# Haken "Helpdesk-Kunden anlegen" am Kontakt
after_install = "helpdesk_erpnext_sync.install.zusatzfelder_anlegen"
after_migrate = "helpdesk_erpnext_sync.install.zusatzfelder_anlegen"

# Kunde: Verweis auf den HD-Kunden halten, geänderten Namen nachziehen.
# Kontakt <-> Kundenmitglied: Kundenverweis in ERPNext und Mitgliedschaft in Helpdesk gleich halten.
doc_events = {
	"Customer": {
		"on_update": "helpdesk_erpnext_sync.helpdesk_erpnext_sync.sync.on_customer_update",
	},
	"Contact": {
		"on_update": "helpdesk_erpnext_sync.helpdesk_erpnext_sync.sync.on_contact_update",
		"on_trash": "helpdesk_erpnext_sync.helpdesk_erpnext_sync.sync.on_contact_trash",
	},
	"HD Customer": {
		"on_update": "helpdesk_erpnext_sync.helpdesk_erpnext_sync.sync.on_hd_customer_update",
	},
}
