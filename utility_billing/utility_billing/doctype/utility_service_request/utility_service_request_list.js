frappe.listview_settings["Utility Service Request"] = {
	add_fields: [
		"customer",
		"utility_property",
		"utility_request_type",
		"per_billed",
		"billing_status",
		"status",
		"name",
	],
	get_indicator: function (doc) {
		if (doc.status === "Closed" || doc.billing_status === "Closed") {
			return [__("Closed"), "green", "billing_status,=,Closed"];
		}
		if (doc.status === "On Hold") {
			return [__("On Hold"), "orange", "status,=,On Hold"];
		}
		if (doc.billing_status === "Not Billed") {
			return [__("Not Billed"), "red", "billing_status,=,Not Billed"];
		}
		if (doc.billing_status === "Partly Billed") {
			return [__("Partly Billed"), "orange", "billing_status,=,Partly Billed"];
		}
		if (doc.billing_status === "Fully Billed") {
			return [__("Fully Billed"), "green", "billing_status,=,Fully Billed"];
		}
	},
	onload(listview) {
    listview.page.add_menu_item(__("Generate Invoices (Bulk)"), () => {

	return 
      const selected = listview.get_checked_items().map(d => d.name);

      if (!selected.length) {
        frappe.msgprint(__("Select at least one Utility Service Request."));
        return;
      }

      const now = new Date();
      const thisYear = now.getFullYear();
      const years = [];
      for (let y = thisYear - 3; y <= thisYear + 3; y++) years.push(y.toString());

      const d = new frappe.ui.Dialog({
        title: __("Generate Sales Invoices"),
        fields: [
          { fieldtype: "Select", label: "Year", fieldname: "year",
            options: years.join("\n"), reqd: true, default: thisYear.toString() },
          { fieldtype: "Select", label: "Month", fieldname: "month",
            options:
              "January|1\nFebruary|2\nMarch|3\nApril|4\nMay|5\nJune|6\n" +
              "July|7\nAugust|8\nSeptember|9\nOctober|10\nNovember|11\nDecember|12",
            reqd: true, default: (now.getMonth() + 1).toString()
          },
          { fieldtype: "Date", label: "Posting Date", fieldname: "posting_date",
            description: __("Defaults to last day of selected month") },
          { fieldtype: "Date", label: "Due Date", fieldname: "due_date",
            description: __("Defaults to Posting Date") },
          { fieldtype: "Check", label: "Submit Invoices", fieldname: "submit" },
        ],
        primary_action_label: __("Generate"),
        async primary_action(values) {
          d.hide();

          frappe.show_progress(
            __("Generating Invoices"),
            0, selected.length,
            __("Starting..."), true
          );

          let done = 0;
          const successes = [];
          const failures = [];

          for (const name of selected) {
            try {
              const r = await frappe.call({
                method: "utility_rental.api.generate_invoice_from_usr",
                args: {
                  docname: name,
                  year: cint(values.year),
                  month: cint(values.month),
                  posting_date: values.posting_date || null,
                  due_date: values.due_date || null,
                  submit: values.submit ? 1 : 0,
                },
                freeze: false,
              });
              successes.push({ usr: name, si: r.message.invoice });
            } catch (e) {
              failures.push({ usr: name, error: e.message || e });
            } finally {
              done += 1;
              frappe.show_progress(
                __("Generating Invoices"),
                done, selected.length,
                __("Processed {0} of {1}", [done, selected.length]),
                true
              );
            }
          }

          frappe.hide_progress();

          let html = "";
          if (successes.length) {
            html += `<p><b>${__("Created")}:</b></p><ul>`;
            successes.forEach(s => {
              html += `<li>${frappe.utils.escape_html(s.usr)} → 
                <a href="#Form/Sales Invoice/${encodeURIComponent(s.si)}">${frappe.utils.escape_html(s.si)}</a></li>`;
            });
            html += "</ul>";
          }
          if (failures.length) {
            html += `<p><b style="color:var(--red-500)">${__("Failed")}:</b></p><ul>`;
            failures.forEach(f => {
              html += `<li>${frappe.utils.escape_html(f.usr)} — ${frappe.utils.escape_html(String(f.error))}</li>`;
            });
            html += "</ul>";
          }

          frappe.msgprint({
            title: __("Bulk Invoice Result"),
            message: html || __("Nothing processed."),
            indicator: failures.length ? "orange" : "green",
            wide: true,
          });

          // Refresh list to show “Partly Billed/Billed” or other status changes
          listview.refresh();
        },
      });

      d.show();
    });

	listview.page.add_button(__("Generate Invoices"), async () => {
		
		// const filters = listview.get_filters(); // current filters

      const now = new Date();
      const thisYear = now.getFullYear();
      const years = [];
      for (let y = thisYear - 1; y <= thisYear + 3; y++) years.push(y.toString());
	
      const d = new frappe.ui.Dialog({
        title: __("Generate Sales Invoices"),
        fields: [
          { fieldtype: "Select", label: "Year", fieldname: "year",
            options: years.join("\n"), reqd: true, default: thisYear.toString() },
          { fieldtype: "Select", label: "Month", fieldname: "month",
            options:
              "1\n2\n3\n4\n5\n6\n" +
			  "7\n8\n9\n10\n11\n12",
            reqd: true, default: (now.getMonth() + 1).toString()
          },
          { fieldtype: "Date", label: "Posting Date", fieldname: "posting_date" },
          { fieldtype: "Date", label: "Due Date", fieldname: "due_date" },
          { fieldtype: "Check", label: "Submit Invoices", fieldname: "submit" },
        ],
        primary_action_label: __("Generate"),
        primary_action(values) {
          d.hide();
          frappe.call({
            method: "utility_billing.utility_billing.doctype.utility_service_request.utility_service_request.bulk_generate_all_invoices",
            args: {
            //   filters,
              year: cint(values.year),
              month: cint(values.month),
              posting_date: values.posting_date || null,
              due_date: values.due_date || null,
              submit: values.submit ? 1 : 0,
            },
            freeze: true,
            freeze_message: __("Generating invoices..."),
            callback(r) {
              if (!r.exc) {
                let msg = "";
                if (r.message.success?.length) {
					msg += `<p><b>Created:</b></p><ul>`;
					r.message.success.forEach(s => {
						s.sis.forEach(si => {
						msg += `<li>${s.usr} → <a href="/app/sales-invoice//${si}">${si}</a></li>`;
						});
					});
					msg += "</ul>";
					}

                if (r.message.failed?.length) {
                  msg += `<p><b style="color:red">Failed:</b></p><ul>`;
                  r.message.failed.forEach(f => {
                    msg += `<li>${f.usr} — ${f.error}</li>`;
                  });
                  msg += "</ul>";
                }
                frappe.msgprint({ title: __("Result"), message: msg, wide: true });
                listview.refresh();
              }
            },
          });
        },
      });
      d.show();
    });

  },

};
