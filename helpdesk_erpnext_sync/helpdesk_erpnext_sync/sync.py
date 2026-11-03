"""Ergaenzungen zum Kunden-Sync zwischen Helpdesk und ERPNext.

Helpdesk (frappe/helpdesk) synchronisiert Kunden nur dann mit lesbarem Namen,
wenn der ERPNext-Kunde beim Anlegen entsteht. Die Massen-Aktion "Sync Customers"
legt fehlende HD-Kunden dagegen mit dem ERPNext-Namen an - bei Nummernkreis
(CUST-2026-00001) also mit der Kundennummer. Ausserdem werden Kontakte nicht
uebertragen. Beides wird hier ergaenzt, ohne Helpdesk-Code zu aendern.
"""

import frappe
from frappe import _
from frappe.model.rename_doc import rename_doc

from helpdesk.integrations.erpnext import api as hd_api
from helpdesk.integrations.erpnext.utils import CASCADE_FLAG, should_sync

JOB_ID = "sync_hd_erpnext_customers"


@frappe.whitelist()
def sync_hd_erpnext_customers() -> None:
	"""Ersatz fuer helpdesk.integrations.erpnext.api.sync_hd_erpnext_customers."""
	frappe.has_permission("Customer", "write", throw=True)
	frappe.has_permission("HD Customer", "write", throw=True)
	if not should_sync():
		frappe.throw(_("ERPNext integration is not enabled"), title=_("Cannot Sync Customers"))

	frappe.enqueue(
		sync_all_customers,
		queue="long",
		timeout=12000,
		job_id=JOB_ID,
		deduplicate=True,
	)


def sync_all_customers() -> None:
	"""Standard-Sync von Helpdesk, danach Namen und Kontakte nacharbeiten."""
	hd_api.sync_all_customers()
	nacharbeiten()
	frappe.publish_realtime("helpdesk:erpnext-sync-end", user=frappe.session.user, after_commit=True)


def nacharbeiten() -> dict:
	umbenannt = lesbare_namen_herstellen()
	mitglieder = kontakte_zuordnen()
	return {"umbenannt": umbenannt, "mitglieder": mitglieder}


def lesbare_namen_herstellen() -> list[tuple[str, str]]:
	"""HD-Kunden, die nach der ERPNext-Kundennummer heissen, auf den Kundennamen umbenennen.

	Die ERPNext-Kunden bleiben unveraendert: Die Rename-Kaskade von Helpdesk wird
	dafuer abgeschaltet, sonst wuerde sie auch den ERPNext-Kunden umbenennen.
	"""
	ergebnis = []
	if not should_sync():
		return ergebnis

	kunden = frappe.get_all(
		"Customer",
		filters={"hd_customer": ["is", "set"]},
		fields=["name", "customer_name", "hd_customer"],
	)
	for kunde in kunden:
		ziel = (kunde.customer_name or "").strip()
		# nur der Fall "HD-Kunde heisst wie die ERPNext-Nummer"; bewusst vergebene Namen bleiben
		if not ziel or kunde.hd_customer != kunde.name or ziel == kunde.hd_customer:
			continue
		if frappe.db.exists("HD Customer", ziel):
			frappe.log_error(
				title="Helpdesk ERPNext Sync: Name schon vergeben",
				message=f"HD-Kunde '{kunde.hd_customer}' kann nicht in '{ziel}' umbenannt werden, der Name existiert bereits.",
			)
			continue

		frappe.flags[CASCADE_FLAG] = True
		try:
			rename_doc("HD Customer", kunde.hd_customer, ziel, ignore_permissions=True)
			frappe.db.set_value(
				"HD Customer",
				ziel,
				{"customer_name": ziel, "erpnext_customer": kunde.name},
				update_modified=False,
			)
			frappe.db.set_value("Customer", kunde.name, "hd_customer", ziel, update_modified=False)
		finally:
			frappe.flags[CASCADE_FLAG] = False
		ergebnis.append((kunde.hd_customer, ziel))
	return ergebnis


def kontakte_zuordnen() -> int:
	"""Alle Kontakte mit Kundenverweis als Mitglied des HD-Kunden eintragen."""
	if not should_sync():
		return 0
	kontakte = frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Contact", "link_doctype": "Customer"},
		fields=["parent", "link_name"],
	)
	neu = 0
	for k in kontakte:
		hd_customer = frappe.db.get_value("Customer", k.link_name, "hd_customer")
		if hd_customer and _mitglied_eintragen(hd_customer, k.parent):
			neu += 1
	return neu


def on_contact_update(doc, method=None) -> None:
	"""Contact.on_update: Kontakt am ERPNext-Kunden -> Mitglied des HD-Kunden."""
	if not should_sync():
		return
	for link in doc.get("links") or []:
		if link.link_doctype != "Customer":
			continue
		hd_customer = frappe.db.get_value("Customer", link.link_name, "hd_customer")
		if hd_customer:
			_mitglied_eintragen(hd_customer, doc.name)


def _mitglied_eintragen(hd_customer: str, contact: str) -> bool:
	"""True, wenn neu eingetragen. Bestehende Mitglieder (auch Manager) bleiben unveraendert."""
	if frappe.db.exists("HD Customer Member", {"parent": hd_customer, "contact_name": contact}):
		return False
	hd = frappe.get_doc("HD Customer", hd_customer)
	hd.append("contacts", {"contact_name": contact, "is_manager": 0})
	hd.flags.ignore_erpnext_sync = True
	hd.save(ignore_permissions=True)
	return True
