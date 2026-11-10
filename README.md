# Helpdesk ERPNext Sync

Kleine Zusatz-App für ERPNext v16 + Frappe Helpdesk. Sie ergänzt den eingebauten Kunden-Sync
(*Helpdesk → Einstellungen → ERPNext*), ohne Helpdesk-Code zu ändern.

## Was sie tut

1. **Lesbare Kundennamen.** HD-Kunden heißen wie der Kunde, nicht wie die ERPNext-Kundennummer
   (`CUST-2026-00001`). Das gilt nach „Sync Customers“ und wenn der Kundenname in ERPNext geändert wird.
   Bewusst anders benannte HD-Kunden bleiben unangetastet; ist der Zielname vergeben, gibt es einen
   Eintrag im Fehlerprotokoll.
2. **Verweis halten.** Der Verweis ERPNext-Kunde → HD-Kunde geht nicht mehr verloren, wenn ein Formular
   mit älterem Stand gespeichert wird.
3. **Kontakte als Kundenmitglieder.** Wird ein Kontakt im ERPNext-Kontaktformular mit einem Kunden
   verknüpft, wird er Mitglied des HD-Kunden (kein Manager). Wird die Verknüpfung entfernt oder der
   Kontakt gelöscht, endet die Mitgliedschaft. Umgekehrt: Wird in Helpdesk ein Mitglied hinzugefügt oder
   entfernt, wird der Kontakt in ERPNext verknüpft bzw. gelöst.
4. **HD-Kunden beim Kontakt anlegen.** Im Kontaktformular gibt es den Haken **„Helpdesk-Kunden anlegen“**.
   Beim Speichern wird für jeden verknüpften Kunden ohne HD-Kunden einer angelegt (lesbarer Name, verknüpft),
   der Kontakt wird Mitglied, der Haken springt zurück. Ohne Haken wird nie ein HD-Kunde angelegt.

Der Massen-Lauf („Sync Customers“ / „Jetzt nacharbeiten“) trägt nur nach und entfernt nichts.

## Einstellungen

Desk → *Helpdesk Sync Einstellungen* (`/app/helpdesk-sync-einstellungen`, nur System Manager):

| Schalter | Standard | Wirkung |
|---|---|---|
| Lesbare Kundennamen in Helpdesk | an | Umbenennung nach „Sync Customers“ und bei Namensänderung |
| Kontakte automatisch als Kundenmitglieder eintragen | an | Hooks auf `Contact.on_update`/`on_trash`, Massen-Sync |
| Mitglieder aus Helpdesk nach ERPNext übernehmen | an | Hook auf `HD Customer.on_update` |
| Neue Mitglieder als Manager eintragen | aus | Gilt nur für neu eingetragene Mitglieder |

Der Knopf **Jetzt nacharbeiten** wendet die eingeschalteten Funktionen auf alle vorhandenen Kunden und
Kontakte an (Hintergrund-Job, Ergebnis als Hinweis). Voraussetzung: Die ERPNext-Integration in Helpdesk ist aktiv.

## Technik

- `hooks.py`: `override_whitelisted_methods` ersetzt `helpdesk.integrations.erpnext.api.sync_hd_erpnext_customers`
  (Aufruf des Knopfs); `doc_events` für `Customer`, `Contact`, `HD Customer`;
  `after_install`/`after_migrate` legen das Zusatzfeld `Contact.hd_kunde_anlegen` an (`install.py`).
- `helpdesk_erpnext_sync/helpdesk_erpnext_sync/sync.py`: gesamte Logik.
- Tests: `bench --site <site> run-tests --app helpdesk_erpnext_sync`

## Grenzen

- Kontakte erhalten keinen Benutzer; für die Anmeldung im Portal braucht jeder einen User
  mit gleicher E-Mail-Adresse und der Rolle „HD Customer“ (Manager: „HD Customer Manager“).
- Benennt man einen HD-Kunden in Helpdesk um, zieht Helpdesks Kaskade den ERPNext-Kunden mit.
  Umbenennen daher in ERPNext (nur Anzeigename).
