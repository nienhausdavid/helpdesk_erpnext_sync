import frappe
from frappe.tests import IntegrationTestCase
from helpdesk.integrations.erpnext import api as hd_api

from helpdesk_erpnext_sync.helpdesk_erpnext_sync import sync


class TestHelpdeskErpnextSync(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.db.set_single_value("ERPNext HD Settings", "enabled", 1)

	def kunde_ohne_helpdesk(self):
		"""ERPNext-Kunde, der schon vor der Integration existierte (kein HD-Kunde).

		Jeder Test bekommt einen eigenen Namen: die Tests teilen sich eine Transaktion."""
		name = self.kundenname = f"Sync-Testkunde {frappe.generate_hash(length=6)} GmbH"
		kunde = frappe.get_doc({"doctype": "Customer", "customer_name": name, "customer_type": "Company"})
		kunde.flags.ignore_erpnext_sync = True
		kunde.insert(ignore_permissions=True)
		return kunde

	def kontakt(self, kunde, vorname="Tina"):
		return frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": vorname,
				"email_ids": [{"email_id": f"{vorname.lower()}@sync-test.example", "is_primary": 1}],
				"links": [{"link_doctype": "Customer", "link_name": kunde.name}],
			}
		).insert(ignore_permissions=True)

	def test_massen_sync_bekommt_lesbaren_namen(self):
		kunde = self.kunde_ohne_helpdesk()
		hd_api.sync_all_customers()
		# Standardverhalten von Helpdesk: HD-Kunde heisst wie die Kundennummer
		self.assertEqual(frappe.db.get_value("Customer", kunde.name, "hd_customer"), kunde.name)

		umbenannt = sync.lesbare_namen_herstellen()

		self.assertIn((kunde.name, self.kundenname), umbenannt)
		self.assertEqual(frappe.db.get_value("Customer", kunde.name, "hd_customer"), self.kundenname)
		self.assertEqual(frappe.db.get_value("HD Customer", self.kundenname, "erpnext_customer"), kunde.name)
		self.assertEqual(frappe.db.get_value("HD Customer", self.kundenname, "customer_name"), self.kundenname)
		# ERPNext-Kunde behaelt seine Nummer
		self.assertTrue(frappe.db.exists("Customer", kunde.name))
		self.assertTrue(hd_api.in_sync())

	def test_umbenennen_ist_idempotent(self):
		self.kunde_ohne_helpdesk()
		hd_api.sync_all_customers()
		sync.lesbare_namen_herstellen()
		self.assertEqual(sync.lesbare_namen_herstellen(), [])

	def test_vergebener_name_bleibt(self):
		"""Ein bewusst anders benannter HD-Kunde wird nicht angefasst."""
		kunde = self.kunde_ohne_helpdesk()
		hd_api.sync_all_customers()
		frappe.flags.erpnext_hd_cascade_in_progress = True
		try:
			frappe.rename_doc("HD Customer", kunde.name, "Eigener Name", force=True)
		finally:
			frappe.flags.erpnext_hd_cascade_in_progress = False
		frappe.db.set_value("Customer", kunde.name, "hd_customer", "Eigener Name")
		frappe.db.set_value("HD Customer", "Eigener Name", "erpnext_customer", kunde.name)

		self.assertEqual(sync.lesbare_namen_herstellen(), [])
		self.assertTrue(frappe.db.exists("HD Customer", "Eigener Name"))

	def test_kontakt_wird_mitglied(self):
		kunde = self.kunde_ohne_helpdesk()
		hd_api.sync_all_customers()
		sync.lesbare_namen_herstellen()
		kontakt = self.kontakt(kunde)  # Contact.on_update-Hook

		mitglieder = frappe.get_all(
			"HD Customer Member", filters={"parent": self.kundenname}, fields=["contact_name", "is_manager"]
		)
		self.assertEqual([(m.contact_name, m.is_manager) for m in mitglieder], [(kontakt.name, 0)])

	def test_kontakt_zuordnen_nachtraeglich_und_ohne_dubletten(self):
		kunde = self.kunde_ohne_helpdesk()
		kontakt = self.kontakt(kunde)  # noch kein HD-Kunde -> keine Zuordnung
		hd_api.sync_all_customers()
		sync.lesbare_namen_herstellen()
		self.assertFalse(frappe.db.exists("HD Customer Member", {"contact_name": kontakt.name}))

		self.assertGreaterEqual(sync.kontakte_zuordnen(), 1)
		self.assertEqual(sync.kontakte_zuordnen(), 0)  # zweiter Lauf: nichts mehr zu tun
		self.assertEqual(frappe.db.count("HD Customer Member", {"contact_name": kontakt.name}), 1)

	def test_manager_bleibt_manager(self):
		kunde = self.kunde_ohne_helpdesk()
		hd_api.sync_all_customers()
		sync.lesbare_namen_herstellen()
		kontakt = self.kontakt(kunde)
		frappe.db.set_value("HD Customer Member", {"contact_name": kontakt.name}, "is_manager", 1)

		kontakt.reload().save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("HD Customer Member", {"contact_name": kontakt.name}, "is_manager"), 1)

	def test_ohne_integration_nichts_tun(self):
		frappe.db.set_single_value("ERPNext HD Settings", "enabled", 0)
		self.assertEqual(sync.lesbare_namen_herstellen(), [])
		self.assertEqual(sync.kontakte_zuordnen(), 0)

	# --- Einstellungen -------------------------------------------------

	def einstellung(self, **werte):
		"""Wie das gespeicherte Formular: immer alle Felder setzen (Standard: an, an, aus)."""
		alle = {"lesbare_namen": 1, "kontakte_zuordnen": 1, "neue_mitglieder_manager": 0, **werte}
		frappe.db.set_single_value("Helpdesk Sync Einstellungen", alle)
		frappe.clear_document_cache("Helpdesk Sync Einstellungen")

	def test_standardwerte_ohne_gespeicherte_einstellungen(self):
		frappe.db.delete("Singles", {"doctype": "Helpdesk Sync Einstellungen"})
		frappe.clear_document_cache("Helpdesk Sync Einstellungen")
		e = sync.einstellungen()
		self.assertEqual((e.lesbare_namen, e.kontakte_zuordnen, e.neue_mitglieder_manager), (1, 1, 0))

	def test_namen_schalter_aus(self):
		kunde = self.kunde_ohne_helpdesk()
		hd_api.sync_all_customers()
		self.einstellung(lesbare_namen=0)
		self.assertEqual(sync.lesbare_namen_herstellen(), [])
		self.assertEqual(frappe.db.get_value("Customer", kunde.name, "hd_customer"), kunde.name)
		self.einstellung()

	def test_kontakte_schalter_aus(self):
		kunde = self.kunde_ohne_helpdesk()
		hd_api.sync_all_customers()
		sync.lesbare_namen_herstellen()
		self.einstellung(kontakte_zuordnen=0)
		kontakt = self.kontakt(kunde)
		self.assertFalse(frappe.db.exists("HD Customer Member", {"contact_name": kontakt.name}))
		self.assertEqual(sync.kontakte_zuordnen(), 0)
		self.einstellung()

	def test_neue_mitglieder_als_manager(self):
		kunde = self.kunde_ohne_helpdesk()
		hd_api.sync_all_customers()
		sync.lesbare_namen_herstellen()
		self.einstellung(neue_mitglieder_manager=1)
		kontakt = self.kontakt(kunde)
		self.assertEqual(frappe.db.get_value("HD Customer Member", {"contact_name": kontakt.name}, "is_manager"), 1)
		self.einstellung()

	def test_knopf_nur_fuer_system_manager(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				sync.jetzt_nacharbeiten()
		finally:
			frappe.set_user("Administrator")
