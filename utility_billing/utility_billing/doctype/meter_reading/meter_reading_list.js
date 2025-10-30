frappe.listview_settings['Meter Reading'] = {
  onload: function (listview) {

    listview.page.add_button('Make Entry', () => {

      // 🧠 Load only last item code from localStorage
      const last_item_code = localStorage.getItem('last_item_code') || '';

      frappe.prompt([
        {
          label: 'Item Code',
          fieldname: 'item_code',
          fieldtype: 'Link',
          options: 'Item',
          reqd: 1,
          default: last_item_code,  // ✅ prefill last selected item
          get_query: () => ({
            filters: {
              reading_required: 1,
              is_utility_item: 1
            }
          })
        },
        {
          label: 'Serial No',
          fieldname: 'serial_no',
          fieldtype: 'Link',
          options: 'Serial No',
          reqd: 1,
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
          fieldtype: 'Attach Image',
          attach_options: {
            private: 0 // ✅ make upload public by default
          }
        }
      ], function (values) {

        // 💾 Save last used item code for next time
        localStorage.setItem('last_item_code', values.item_code || '');

        // 📡 Create Meter Reading
        frappe.call({
          method: "utility_billing.utility_billing.doctype.meter_reading.meter_reading.inset_data",
          args: {
            doc: {
              doctype: 'Meter Reading',
              serial_no: values.serial_no,
              item_code: values.item_code,
              reading_value: values.reading,
              photo: values.photo,
              status: 'Draft'
            }
          },
          callback: function (r) {
            if (!r.exc) {
              frappe.msgprint(__('Meter Reading created'));
              frappe.set_route('form', 'Meter Reading', r.message.name);
            }
          }
        });

      }, 'New Meter Reading');
    });

    listview.page.add_button('Make Entry (Bulk)', () => {

      const d = new frappe.ui.Dialog({
        title: 'New Meter Reading',
        fields: [
          {
            label: 'Serial No',
            fieldname: 'serial_no',
            fieldtype: 'Link',
            options: 'Serial No',
            reqd: 1,
            change: async function () {
              const serial_no = d.get_value('serial_no');
              if (!serial_no) return;

              const container = d.get_field('readings_section').$wrapper;
              container.empty();

              // 🔍 Fetch related utility items
              const items = await frappe.db.get_list('Item', {
                filters: { is_utility_item: 1, reading_required: 1 },
                fields: ['name', 'item_name']
              });

              if (items.length) {
                items.forEach(item => {
                  container.append(`
                    <div class="form-group" style="margin-bottom:10px;">
                      <label><b>${frappe.utils.escape_html(item.item_name)}</b></label>
                      <div style="display:flex; gap:5px; align-items:center;">
                        <input type="number" class="form-control reading-input"
                               placeholder="Enter reading for ${item.item_name}"
                               data-item="${item.name}" style="flex:1;">
                        <input type="file" accept="image/*" class="form-control photo-input"
                               data-item="${item.name}" style="flex:1;">
                      </div>
                    </div>
                  `);
                });
              } else {
                container.append(`<p class="text-muted">No utility items found for this Serial No.</p>`);
              }
            }
          },
          {
            fieldtype: 'HTML',
            fieldname: 'readings_section',
            label: 'Readings'
          }
        ],
        primary_action_label: 'Create',
        primary_action: async function () {
          const serial_no = d.get_value('serial_no');
          if (!serial_no) {
            frappe.msgprint(__('Please select Serial No.'));
            return;
          }

          const readings = [];
          const wrapper = d.get_field('readings_section').$wrapper;

          const reading_inputs = wrapper.find('.reading-input');
          for (const input of reading_inputs) {
            const $input = $(input);
            const item = $input.data('item');
            const value = parseFloat($input.val()) || 0;
            const photoInput = wrapper.find(`.photo-input[data-item='${item}']`)[0];
            let photo_url = null;

            // 🖼 Upload file to Frappe
            if (photoInput && photoInput.files.length > 0) {
              const file = photoInput.files[0];
              const form_data = new FormData();
              form_data.append('file', file, file.name);
              form_data.append('is_private', 0); // make it public
              // ❌ No doctype/docname to avoid "Attached To Name" error

              const resp = await fetch('/api/method/upload_file', {
                method: 'POST',
                body: form_data,
                headers: { 'X-Frappe-CSRF-Token': frappe.csrf_token }
              });

              const data = await resp.json();
              if (data.message && data.message.file_url) {
                photo_url = data.message.file_url;
              }
            }

            readings.push({
              item_code: item,
              reading_value: value,
              photo: photo_url
            });
          }

          if (!readings.length) {
            frappe.msgprint(__('Please enter at least one reading.'));
            return;
          }

          // 📡 Send to backend
          await frappe.call({
            method: "utility_billing.utility_billing.doctype.meter_reading.meter_reading.bulk_insert",
            args: { serial_no, readings },
            callback: function (r) {
              if (!r.exc) {
                frappe.msgprint(__('Meter Readings created successfully'));
                d.hide();
                listview.refresh();
              }
            }
          });
        }
      });

      d.show();
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
          {
            fieldtype: "Select", label: "Year", fieldname: "year",
            options: years.join("\n"), reqd: true, default: thisYear.toString()
          },
          {
            fieldtype: "Select", label: "Month", fieldname: "month",
            options:
              "1\n2\n3\n4\n5\n6\n" +
              "7\n8\n9\n10\n11\n12",
            reqd: true, default: (now.getMonth() + 1).toString()
          },
          {
            fieldtype: "Date", label: "Posting Date", fieldname: "posting_date",
            description: __("Defaults to last day of selected month")
          },
          {
            fieldtype: "Date", label: "Due Date", fieldname: "due_date",
            description: __("Defaults to Posting Date")
          },
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
