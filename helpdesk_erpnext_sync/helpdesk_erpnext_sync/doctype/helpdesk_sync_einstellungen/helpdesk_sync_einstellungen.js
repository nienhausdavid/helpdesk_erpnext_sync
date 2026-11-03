// Ergebnis des Hintergrund-Jobs: global und nur einmal registrieren
window.helpdesk_erpnext_sync = window.helpdesk_erpnext_sync || {};
if (!window.helpdesk_erpnext_sync.listener) {
	window.helpdesk_erpnext_sync.listener = true;
	frappe.realtime.on("helpdesk_erpnext_sync_fertig", (r) => {
		frappe.show_alert(
			{
				message: __("Nacharbeiten fertig: {0} Kunden umbenannt, {1} Kontakte neu eingetragen.", [
					r.umbenannt,
					r.mitglieder,
				]),
				indicator: "green",
			},
			10
		);
	});
}

frappe.ui.form.on("Helpdesk Sync Einstellungen", {
	jetzt_nacharbeiten(frm) {
		if (frm.is_dirty()) {
			frappe.msgprint(__("Bitte zuerst speichern."));
			return;
		}
		frappe.call({
			method: "helpdesk_erpnext_sync.helpdesk_erpnext_sync.sync.jetzt_nacharbeiten",
			callback() {
				frappe.show_alert({ message: __("Nacharbeiten läuft im Hintergrund …"), indicator: "blue" });
			},
		});
	},
});
