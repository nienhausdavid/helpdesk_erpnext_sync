"""Ergaenzungen zum Kunden-Sync zwischen Helpdesk und ERPNext.

Helpdesk (frappe/helpdesk) verknuepft ERPNext-Kunden mit HD-Kunden, laesst aber Luecken:

- "Sync Customers" legt fehlende HD-Kunden mit der Kundennummer (CUST-2026-00001) an,
  und ein spaeter geaenderter Kundenname kommt im HD-Kunden nicht an.
- Der Verweis Customer.hd_customer wird nur in die Datenbank geschrieben. Ein Formular
  mit aelterem Stand ueberschreibt ihn beim naechsten Speichern mit leer.
- Kontakte werden gar nicht uebertragen.

Das wird hier ergaenzt, ohne Helpdesk-Code zu aendern.
"""

from contextlib import contextmanager

import frappe
from frappe import _
from frappe.model.rename_doc import rename_doc

from helpdesk.integrations.erpnext import api as hd_api
from helpdesk.integrations.erpnext.utils import (
	CASCADE_FLAG,
	map_source_to_target_values,
	set_links,
	should_sync,
)

JOB_ID = "sync_hd_erpnext_customers"
EINSTELLUNGEN = "Helpdesk Sync Einstellungen"
FERTIG_EVENT = "helpdesk_erpnext_sync_fertig"
# gesetzt, solange diese App selbst Kontakte oder HD-Kunden speichert (Schleifenschutz)
EIGEN_FLAG = "helpdesk_erpnext_sync_laeuft"
# Zusatzfeld (Haken) am Kontakt, angelegt von install.py
HAKEN = "hd_kunde_anlegen"


def einstellungen():
	"""Einstellungen; ohne gespeicherte Werte gelten die Feld-Standardwerte."""
	return frappe.get_cached_doc(EINSTELLUNGEN)


@contextmanager
def _flag_gesetzt(name: str):
	"""Flag setzen und danach auf den vorherigen Wert zurueckstellen (auch bei Verschachtelung)."""
	vorher = frappe.flags.get(name)
	frappe.flags[name] = True
	try:
		yield
	finally:
		frappe.flags[name] = vorher


def _eigene_aenderung():
	"""Die Hooks dieser App reagieren nicht auf Aenderungen, die sie selbst ausloest."""
	return _flag_gesetzt(EIGEN_FLAG)


@contextmanager
def _geschuetzt(titel: str, info: str):
	"""Fehler in einem Einzelfall zurueckrollen und protokollieren, damit der Massenlauf weiterlaeuft."""
	sicherung = "helpdesk_erpnext_sync_einzelfall"
	frappe.db.savepoint(sicherung)
	try:
		yield
	except Exception:
		frappe.db.rollback(save_point=sicherung)
		frappe.log_error(title=f"Helpdesk ERPNext Sync: {titel}", message=f"{info}\n{frappe.get_traceback()}")


def _darf_hd_aendern(kunde: str, anlegen: bool = False) -> bool:
	"""Rechte des angemeldeten Benutzers; die Hooks selbst speichern mit ignore_permissions."""
	return bool(
		frappe.has_permission("Customer", "read", kunde)
		and frappe.has_permission("HD Customer", "create" if anlegen else "write")
	)


# --- Massen-Sync und Knopf "Jetzt nacharbeiten" ------------------------------


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
	verweise_reparieren()
	hd_api.sync_all_customers()
	nacharbeiten(verweise=False)  # Verweise wurden vor dem Standard-Sync repariert, danach setzt dieser sie selbst
	frappe.publish_realtime("helpdesk:erpnext-sync-end", user=frappe.session.user, after_commit=True)


@frappe.whitelist()
def jetzt_nacharbeiten() -> None:
	"""Knopf in den Einstellungen: vorhandene Kunden und Kontakte nacharbeiten (Hintergrund-Job)."""
	frappe.only_for("System Manager")
	if not should_sync():
		frappe.throw(
			_("Die ERPNext-Integration in Helpdesk ist nicht aktiv."),
			title=_("Nacharbeiten nicht möglich"),
		)
	frappe.enqueue(_nacharbeiten_job, queue="long", timeout=12000, user=frappe.session.user)


def _nacharbeiten_job(user: str) -> None:
	ergebnis = nacharbeiten()
	frappe.publish_realtime(
		FERTIG_EVENT,
		{"umbenannt": len(ergebnis["umbenannt"]), "mitglieder": ergebnis["mitglieder"]},
		user=user,
		after_commit=True,
	)


def nacharbeiten(verweise: bool = True) -> dict:
	"""Gleicht alles Vorhandene ab. Traegt nur nach, entfernt nie etwas."""
	if verweise:
		verweise_reparieren()
	umbenannt = lesbare_namen_herstellen()
	mitglieder = kontakte_zuordnen()
	return {"umbenannt": umbenannt, "mitglieder": mitglieder}


# --- Kunden: Verweis und Name ------------------------------------------------


def _hd_customer_von(kunde: str) -> str | None:
	"""HD-Kunde zum ERPNext-Kunden. Beide Seiten zaehlen, weil eine davon verloren gehen kann."""
	hd = frappe.db.get_value("Customer", kunde, "hd_customer")
	if hd and frappe.db.exists("HD Customer", hd):
		return hd
	return frappe.db.get_value("HD Customer", {"erpnext_customer": kunde}, "name")


def _erpnext_kunde_von(hd_customer: str) -> str | None:
	kunde = frappe.db.get_value("HD Customer", hd_customer, "erpnext_customer")
	if kunde and frappe.db.exists("Customer", kunde):
		return kunde
	return frappe.db.get_value("Customer", {"hd_customer": hd_customer}, "name")


def verweise_reparieren() -> int:
	"""Verlorene Verweise Customer.hd_customer aus der Helpdesk-Seite wiederherstellen.

	Ohne das legt "Sync Customers" fuer solche Kunden einen zweiten HD-Kunden an.
	"""
	if not should_sync():
		return 0
	repariert = 0
	verweis_von = dict(frappe.get_all("Customer", fields=["name", "hd_customer"], as_list=True))
	for hd in frappe.get_all(
		"HD Customer", filters={"erpnext_customer": ["is", "set"]}, fields=["name", "erpnext_customer"]
	):
		if hd.erpnext_customer not in verweis_von:
			continue
		if verweis_von[hd.erpnext_customer] != hd.name:
			frappe.db.set_value("Customer", hd.erpnext_customer, "hd_customer", hd.name, update_modified=False)
			repariert += 1
	return repariert


def on_customer_update(doc, method=None) -> None:
	"""Customer.on_update: Verweis auf den HD-Kunden halten, geaenderten Namen nachziehen."""
	if not should_sync():
		return
	hd = frappe.db.get_value("HD Customer", {"erpnext_customer": doc.name}, "name")
	if not hd:
		return
	if doc.get("hd_customer") != hd:
		# auch im Dokument setzen: Das Formular bekommt diesen Stand zurueck
		doc.db_set("hd_customer", hd, update_modified=False)

	vorher = doc.get_doc_before_save()
	if not vorher or vorher.customer_name == doc.customer_name or not einstellungen().lesbare_namen:
		return
	# bewusst anders benannte HD-Kunden bleiben, wie sie sind
	if hd not in (vorher.customer_name, doc.name):
		return
	if _hd_kunde_umbenennen(doc.name, hd, doc.customer_name):
		doc.hd_customer = doc.customer_name.strip()


def lesbare_namen_herstellen() -> list[tuple[str, str]]:
	"""HD-Kunden, die nach der ERPNext-Kundennummer heissen, auf den Kundennamen umbenennen."""
	ergebnis = []
	if not should_sync() or not einstellungen().lesbare_namen:
		return ergebnis

	kunden = frappe.get_all(
		"Customer",
		filters={"hd_customer": ["is", "set"]},
		fields=["name", "customer_name", "hd_customer"],
	)
	for kunde in kunden:
		# nur der Fall "HD-Kunde heisst wie die ERPNext-Nummer"; bewusst vergebene Namen bleiben
		if kunde.hd_customer != kunde.name:
			continue
		if _hd_kunde_umbenennen(kunde.name, kunde.hd_customer, kunde.customer_name):
			ergebnis.append((kunde.hd_customer, kunde.customer_name.strip()))
	return ergebnis


def _hd_kunde_umbenennen(kunde: str, alt: str, ziel: str | None) -> bool:
	"""HD-Kunde umbenennen; der ERPNext-Kunde behaelt seine Nummer.

	Die Rename-Kaskade von Helpdesk wird dafuer abgeschaltet, sonst wuerde sie
	auch den ERPNext-Kunden umbenennen.
	"""
	ziel = (ziel or "").strip()
	if not ziel or ziel == alt:
		return False
	if frappe.db.exists("HD Customer", ziel):
		frappe.log_error(
			title="Helpdesk ERPNext Sync: Name schon vergeben",
			message=f"HD-Kunde '{alt}' kann nicht in '{ziel}' umbenannt werden, der Name existiert bereits.",
		)
		return False

	# Ein unzulaessiger Name (Sonderzeichen, zu lang) darf weder das Speichern des Kunden
	# noch den Massenlauf abbrechen: zurueckrollen, protokollieren, weitermachen.
	sicherung = "helpdesk_erpnext_sync_umbenennen"
	frappe.db.savepoint(sicherung)
	try:
		with _flag_gesetzt(CASCADE_FLAG):
			rename_doc("HD Customer", alt, ziel, ignore_permissions=True)
			frappe.db.set_value(
				"HD Customer",
				ziel,
				{"customer_name": ziel, "erpnext_customer": kunde},
				update_modified=False,
			)
			frappe.db.set_value("Customer", kunde, "hd_customer", ziel, update_modified=False)
	except Exception:
		frappe.db.rollback(save_point=sicherung)
		frappe.log_error(
			title="Helpdesk ERPNext Sync: Umbenennen fehlgeschlagen",
			message=f"HD-Kunde '{alt}' -> '{ziel}' (ERPNext-Kunde '{kunde}'):\n{frappe.get_traceback()}",
		)
		return False
	return True


def _hd_customer_sicherstellen(kunde: str) -> str | None:
	"""HD-Kunde zum ERPNext-Kunden; fehlt er, wird er angelegt (nur auf ausdrücklichen Wunsch des Aufrufers)."""
	hd = _hd_customer_von(kunde)
	if hd or not frappe.db.exists("Customer", kunde):
		return hd

	erp = frappe.get_doc("Customer", kunde)
	namen = [kunde]
	lesbar = (erp.customer_name or "").strip()
	if einstellungen().lesbare_namen and lesbar and lesbar != kunde:
		namen.insert(0, lesbar)

	for name in namen:
		if not frappe.db.exists("HD Customer", name):
			hd_doc = frappe.get_doc(
				{
					"doctype": "HD Customer",
					"customer_name": name,
					"erpnext_customer": kunde,
					**map_source_to_target_values(erp),
				}
			)
			hd_doc.flags.ignore_erpnext_sync = True
			hd_doc.insert(ignore_permissions=True)
			set_links(kunde, hd_doc.name)
			return hd_doc.name
		if not _erpnext_kunde_von(name):
			# gleichnamiger, noch unverknuepfter HD-Kunde: verknuepfen statt Dublette (wie der Standard-Sync)
			set_links(kunde, name)
			return name

	frappe.log_error(
		title="Helpdesk ERPNext Sync: HD-Kunde nicht anlegbar",
		message=f"Fuer den Kunden '{kunde}' sind die Namen {namen} in Helpdesk schon an andere Kunden vergeben.",
	)
	return None


# --- Kontakte <-> Kundenmitglieder -------------------------------------------


def kontakte_zuordnen() -> int:
	"""Kundenverweise der Kontakte und Mitglieder der HD-Kunden in beide Richtungen nachtragen."""
	if not should_sync() or not einstellungen().kontakte_zuordnen:
		return 0
	neu = 0
	with _eigene_aenderung():
		hd_von: dict[str, str | None] = {}
		je_hd_kunde: dict[str, list[str]] = {}
		for v in frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": "Contact", "link_doctype": "Customer"},
			fields=["parent", "link_name"],
		):
			if v.link_name not in hd_von:
				hd_von[v.link_name] = _hd_customer_von(v.link_name)  # legt nie neue HD-Kunden an
			if hd_von[v.link_name]:
				je_hd_kunde.setdefault(hd_von[v.link_name], []).append(v.parent)

		for hd_customer, kontakte in je_hd_kunde.items():
			with _geschuetzt("Mitglieder eintragen fehlgeschlagen", f"HD-Kunde '{hd_customer}'"):
				neu += _mitglieder_eintragen(hd_customer, kontakte)

		if einstellungen().mitglieder_nach_erpnext:
			kunde_von: dict[str, str | None] = {}
			for m in frappe.get_all(
				"HD Customer Member",
				filters={"parenttype": "HD Customer"},
				fields=["parent", "contact_name"],
			):
				if m.parent not in kunde_von:
					kunde_von[m.parent] = _erpnext_kunde_von(m.parent)
				kunde = kunde_von[m.parent]
				if not kunde:
					continue
				with _geschuetzt(
					"Kundenverweis setzen fehlgeschlagen", f"Kontakt '{m.contact_name}', Kunde '{kunde}'"
				):
					if _kundenverweis_setzen(m.contact_name, kunde):
						neu += 1
	return neu


def _kundenverweise(contact_doc) -> set[str]:
	if not contact_doc:
		return set()
	return {v.link_name for v in contact_doc.get("links") or [] if v.link_doctype == "Customer" and v.link_name}


def on_contact_update(doc, method=None) -> None:
	"""Contact.on_update: geaenderte Kundenverweise in die Mitglieder der HD-Kunden uebernehmen.

	Reagiert nur auf Aenderungen: neuer Verweis -> Mitglied, entfernter Verweis -> kein Mitglied mehr.
	"""
	if frappe.flags.get(EIGEN_FLAG):
		return
	if not should_sync() or not einstellungen().kontakte_zuordnen:
		if doc.get(HAKEN):
			# sonst loest der Haken unerwartet aus, sobald die Funktion wieder an ist
			doc.db_set(HAKEN, 0, update_modified=False)
			doc.set(HAKEN, 0)
			frappe.msgprint(
				_("Helpdesk-Kunden wurden nicht angelegt: Die Zuordnung von Kontakten ist ausgeschaltet."),
				indicator="orange",
				alert=True,
			)
		return
	jetzt = _kundenverweise(doc)
	vorher = _kundenverweise(doc.get_doc_before_save())
	angelegt, eingetragen, entfernt, verweigert = [], [], [], []
	# Haken am Kontakt: fehlende HD-Kunden aller verknüpften Kunden jetzt anlegen (gilt einmalig)
	anlegen = bool(doc.get(HAKEN))
	with _eigene_aenderung():
		for kunde in sorted(jetzt if anlegen else jetzt - vorher):
			gab_es = _hd_customer_von(kunde)
			if not _darf_hd_aendern(kunde, anlegen=anlegen and not gab_es):
				verweigert.append(kunde)
				continue
			hd_customer = gab_es or (_hd_customer_sicherstellen(kunde) if anlegen else None)
			if not hd_customer:
				continue
			if not gab_es:
				angelegt.append(hd_customer)
			if _mitglied_eintragen(hd_customer, doc.name):
				eingetragen.append(hd_customer)
		for kunde in sorted(vorher - jetzt):
			hd_customer = _hd_customer_von(kunde)
			if hd_customer and not _darf_hd_aendern(kunde):
				verweigert.append(kunde)
				continue
			if hd_customer and _mitglied_entfernen(hd_customer, doc.name):
				entfernt.append(hd_customer)

	if anlegen:
		doc.db_set(HAKEN, 0, update_modified=False)
		doc.set(HAKEN, 0)
	if verweigert:
		frappe.msgprint(
			_("Keine Berechtigung für die Helpdesk-Kunden von: {0}").format(", ".join(verweigert)),
			indicator="orange",
			alert=True,
		)
	if angelegt:
		frappe.msgprint(_("Helpdesk-Kunde angelegt: {0}").format(", ".join(angelegt)), alert=True)
	if eingetragen:
		frappe.msgprint(_("In Helpdesk Mitglied von: {0}").format(", ".join(eingetragen)), alert=True)
	if entfernt:
		frappe.msgprint(_("In Helpdesk kein Mitglied mehr von: {0}").format(", ".join(entfernt)), alert=True)


@frappe.whitelist()
def kontakt_verknuepfen(kunde: str, kontakt: str, hd_kunde_anlegen: int | str = 0) -> None:
	"""Knopf am Kundenformular: bestehenden Kontakt mit dem Kunden verknüpfen (Rechte des Benutzers)."""
	frappe.has_permission("Customer", "read", kunde, throw=True)
	doc = frappe.get_doc("Contact", kontakt)
	doc.check_permission("write")
	if not _hat_kundenverweis(kontakt, kunde):
		doc.append("links", {"link_doctype": "Customer", "link_name": kunde})
	doc.set(HAKEN, 1 if frappe.utils.cint(hd_kunde_anlegen) else 0)
	doc.save()


def on_contact_trash(doc, method=None) -> None:
	"""Contact.on_trash: Mitgliedschaften loesen, sonst blockiert der Verweis im HD-Kunden das Loeschen."""
	if frappe.flags.get(EIGEN_FLAG) or not should_sync() or not einstellungen().kontakte_zuordnen:
		return
	with _eigene_aenderung():
		for hd_customer in frappe.get_all(
			"HD Customer Member",
			filters={"contact_name": doc.name, "parenttype": "HD Customer"},
			pluck="parent",
		):
			_mitglied_entfernen(hd_customer, doc.name)


def on_hd_customer_update(doc, method=None) -> None:
	"""HD Customer.on_update: in Helpdesk geaenderte Mitglieder als Kundenverweis am Kontakt nachziehen."""
	if frappe.flags.get(EIGEN_FLAG) or not should_sync():
		return
	e = einstellungen()
	if not (e.kontakte_zuordnen and e.mitglieder_nach_erpnext):
		return
	alt = doc.get_doc_before_save()
	jetzt = {m.contact_name for m in doc.get("contacts") or []}
	vorher = {m.contact_name for m in alt.get("contacts") or []} if alt else set()
	if jetzt == vorher:
		return
	kunde = _erpnext_kunde_von(doc.name)
	if not kunde:
		return
	with _eigene_aenderung():
		for contact in sorted(jetzt - vorher):
			_kundenverweis_setzen(contact, kunde)
		for contact in sorted(vorher - jetzt):
			_kundenverweis_entfernen(contact, kunde)


def _mitglieder_eintragen(hd_customer: str, kontakte: list[str]) -> int:
	"""Anzahl neu eingetragener Mitglieder (ein Speichern je HD-Kunde). Bestehende, auch Manager, bleiben."""
	vorhanden = set(
		frappe.get_all("HD Customer Member", filters={"parent": hd_customer}, pluck="contact_name")
	)
	neu = [c for c in dict.fromkeys(kontakte) if c not in vorhanden]
	if not neu:
		return 0
	hd = frappe.get_doc("HD Customer", hd_customer)
	manager = 1 if einstellungen().neue_mitglieder_manager else 0
	for contact in neu:
		hd.append("contacts", {"contact_name": contact, "is_manager": manager})
	hd.flags.ignore_erpnext_sync = True
	hd.save(ignore_permissions=True)
	return len(neu)


def _mitglied_eintragen(hd_customer: str, contact: str) -> bool:
	"""True, wenn neu eingetragen. Bestehende Mitglieder (auch Manager) bleiben unveraendert."""
	return bool(_mitglieder_eintragen(hd_customer, [contact]))


def _mitglied_entfernen(hd_customer: str, contact: str) -> bool:
	if not frappe.db.exists("HD Customer Member", {"parent": hd_customer, "contact_name": contact}):
		return False
	hd = frappe.get_doc("HD Customer", hd_customer)
	hd.remove_contact(contact)
	hd.flags.ignore_erpnext_sync = True
	hd.save(ignore_permissions=True)
	return True


def _hat_kundenverweis(contact: str, kunde: str) -> bool:
	return bool(
		frappe.db.exists(
			"Dynamic Link",
			{"parenttype": "Contact", "parent": contact, "link_doctype": "Customer", "link_name": kunde},
		)
	)


def _kundenverweis_setzen(contact: str, kunde: str) -> bool:
	if not frappe.db.exists("Contact", contact) or _hat_kundenverweis(contact, kunde):
		return False
	doc = frappe.get_doc("Contact", contact)
	doc.append("links", {"link_doctype": "Customer", "link_name": kunde})
	doc.save(ignore_permissions=True)
	return True


def _kundenverweis_entfernen(contact: str, kunde: str) -> bool:
	if not frappe.db.exists("Contact", contact) or not _hat_kundenverweis(contact, kunde):
		return False
	doc = frappe.get_doc("Contact", contact)
	doc.set("links", [v for v in doc.links if not (v.link_doctype == "Customer" and v.link_name == kunde)])
	doc.save(ignore_permissions=True)
	return True
