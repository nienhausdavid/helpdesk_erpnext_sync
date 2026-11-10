// Kundenformular: Knopf "Kontakt verknüpfen" neben "+ Kontakt" (Adresse & Kontakt).
frappe.ui.form.on("Customer", {
	refresh(frm) {
		if (frm.is_new()) return;
		const wrapper = frm.fields_dict.contact_html && frm.fields_dict.contact_html.wrapper;
		if (!wrapper) return;
		const einfuegen = () => {
			$(wrapper)
				.find(".btn-contact")
				.each(function () {
					const $nachbar = $(this).next(".hd-kontakt-verknuepfen");
					if ($nachbar.length) return;
					const $knopf = $(
						`<button class="btn btn-default btn-sm hd-kontakt-verknuepfen">${frappe.utils.escape_html(
							__("Kontakt verknüpfen")
						)}</button>`
					).on("click", () => kontakt_verknuepfen(frm));
					$(this).after($knopf);
				});
		};
		einfuegen();
		// Die Kontaktliste wird von Frappe nachgeladen und neu gezeichnet
		if (wrapper._hd_beobachter) wrapper._hd_beobachter.disconnect();
		wrapper._hd_beobachter = new MutationObserver(einfuegen);
		wrapper._hd_beobachter.observe(wrapper, { childList: true, subtree: true });
	},
});

function kontakt_verknuepfen(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Bestehenden Kontakt verknüpfen"),
		fields: [
			{ fieldname: "kontakt", fieldtype: "Link", options: "Contact", label: __("Kontakt"), reqd: 1 },
			{
				fieldname: "hd_kunde_anlegen",
				fieldtype: "Check",
				label: __("Helpdesk-Kunden anlegen"),
				description: __("Falls dieser Kunde noch keinen Helpdesk-Kunden hat."),
			},
		],
		primary_action_label: __("Verknüpfen"),
		primary_action(werte) {
			frappe.call({
				method: "helpdesk_erpnext_sync.helpdesk_erpnext_sync.sync.kontakt_verknuepfen",
				args: { kunde: frm.doc.name, kontakt: werte.kontakt, hd_kunde_anlegen: werte.hd_kunde_anlegen ? 1 : 0 },
				freeze: true,
				callback() {
					d.hide();
					frm.reload_doc();
				},
			});
		},
	});
	d.show();
}
