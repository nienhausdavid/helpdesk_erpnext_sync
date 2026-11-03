# Helpdesk ERPNext Sync

Kleine Zusatz-App für ERPNext v16 + Frappe Helpdesk. Sie ergänzt den eingebauten Kunden-Sync
(*Helpdesk → Einstellungen → ERPNext*), ohne Helpdesk-Code zu ändern.

## Was sie tut

1. **Lesbare Kundennamen.** Die Aktion „Sync Customers“ legt fehlende HD-Kunden mit dem
   ERPNext-Namen an – bei Nummernkreis also `CUST-2026-00001`. Diese App benennt solche
   HD-Kunden danach auf den Kundennamen um. Der ERPNext-Kunde behält seine Nummer.
   Bewusst anders benannte HD-Kunden bleiben unangetastet; ist der Zielname schon vergeben,
   gibt es einen Eintrag im Fehlerprotokoll.
2. **Kontakte als Kundenmitglieder.** Ein Kontakt, der in ERPNext am Kunden hängt, wird
   Mitglied des HD-Kunden (kein Manager). Das passiert beim Speichern des Kontakts und im
   Massen-Sync für vorhandene Kontakte. Bestehende Mitglieder (auch Manager) bleiben, wie sie sind;
   Kontakte werden nie automatisch entfernt.

## Technik

- `hooks.py`: `override_whitelisted_methods` ersetzt `helpdesk.integrations.erpnext.api.sync_hd_erpnext_customers`
  (Aufruf des Knopfs); `doc_events` für `Contact.on_update`.
- `helpdesk_erpnext_sync/helpdesk_erpnext_sync/sync.py`: gesamte Logik.
- Tests: `bench --site <site> run-tests --app helpdesk_erpnext_sync`

## Grenzen

- Kontakte erhalten keinen Benutzer; für die Anmeldung im Portal braucht jeder einen User
  mit gleicher E-Mail-Adresse und der Rolle „Customer“.
- Benennt man einen HD-Kunden in Helpdesk um, zieht Helpdesks Kaskade den ERPNext-Kunden mit.
  Umbenennen daher in ERPNext (nur Anzeigename).
