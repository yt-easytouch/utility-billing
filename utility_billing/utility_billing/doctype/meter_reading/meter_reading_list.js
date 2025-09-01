frappe.listview_settings['Meter Reading'] = {
    onload: function(listview) {
        listview.page.add_button('Make Entry', () => {
            frappe.prompt([
              {
					label: 'Meter Assign',
					fieldname: 'meter_assign',
					fieldtype: 'Link',
					options: 'Meter Assign',
					reqd: 1,
					get_query: () => {
						return {
							filters: {
								status: 'Open'  // ✅ your filter here
							}
						};
					}
				},
                {
                    label: 'Reading Value',
                    fieldname: 'reading',
                    fieldtype: 'Float',
                    reqd: 1
                },
                {
                    label: 'Photo',
                    fieldname: 'photo',
                    fieldtype: 'Attach Image'
                }
            ], function(values) {
                frappe.call({
                   method: "utility_billing.utility_billing.doctype.meter_reading.meter_reading.inset_data",
                    args: {
                        doc: {
                            doctype: 'Meter Reading',
                            meter_assign: values.meter_assign,
                            reading_value: values.reading,
                            photo: values.photo,
                            status: 'Draft'
                        }
                    },
                    callback: function(r) {
                        if (!r.exc) {
                            frappe.msgprint(__('Meter Reading created'));
                            frappe.set_route('form', 'Meter Reading', r.message.name);
                        }
                    }
                });
            }, 'New Meter Reading');
        });

    listview.page.add_button(__("Generate Invoices (Bulk)"), () => {


      const selected = listview.get_checked_items().map(d => d.name);

      if (!selected.length) {
        frappe.msgprint(__("Select at least one Utility Service Request."));
        return;
      }

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
                method: "utility_billing.utility_billing.doctype.meter_reading.meter_reading.submit_create_invoice",
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
    
    }
};
