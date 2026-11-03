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

# Kontakte, die in ERPNext an einem Kunden hängen, werden Mitglied des HD-Kunden.
doc_events = {
	"Contact": {
		"on_update": "helpdesk_erpnext_sync.helpdesk_erpnext_sync.sync.on_contact_update",
	},
}
