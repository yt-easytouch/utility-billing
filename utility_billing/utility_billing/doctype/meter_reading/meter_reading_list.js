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
    }
};
