# Copyright (c) 2024, Navari and contributors
# For license information, please see license.txt
import frappe
from erpnext.controllers.accounts_controller import AccountsController
from frappe.model.document import Document
from frappe.query_builder import DocType
from frappe.utils import nowdate
from pypika import Order

from ...utils.create_meter_reading_rates import create_meter_reading_rates


class MeterReading(Document):
    def validate(self):
        for item in self.items:
            self.validate_item_readings(item)
        create_meter_reading_rates(self, self.price_list, self.date)

    def on_submit(self):
        settings = frappe.get_single("Utility Billing Settings")
        if not self.rates or len(self.rates) == 0:
            frappe.throw(frappe._("Cannot submit Meter Reading. No rates available."))
        existing_sales_order = frappe.db.exists(
            {
                "doctype": "Sales Invoice",
                "custom_meter_reading": self.name,
            }
        )
        if not existing_sales_order:
            if settings.sales_order_creation_state == "Draft":
                sales_order = create_sales_order(self)
                sales_order.save()
            else:
                sales_order = create_sales_order(self)
                sales_order.save()
                sales_order.submit()

    def validate_item_readings(self, item):
        """Validate readings for each item."""
        if item.current_reading is None:
            frappe.throw(
                frappe._(f"Current reading is required for item: {item.item_code}")
            )

        previous_reading = get_previous_invoice_reading(
            item_code=item.item_code,
            customer=self.customer,
            meter_number=item.meter_number,
        )
        item.previous_reading = previous_reading

        item.consumption = item.current_reading - previous_reading

        if item.consumption < 0:
            frappe.throw(
                frappe._(
                    f"Current reading cannot be lower than the previous reading for item: {item.item_code}"
                )
            )

def create_sales_order(meter_reading,from_date,to_date):
    """Create a Sales Order based on the Meter Reading."""
    # sales_order = frappe.get_doc(
    #     {
    #         "doctype": "Sales Order",
    #         "customer": meter_reading.customer,
    #         "meter_readings": [],
    #         "items": [],
    #         "order_type": "Sales",
    #         "selling_price_list": meter_reading.price_list,
    #     }
    # ) 
    existing_si = frappe.get_all(
                    "Sales Invoice",
                    filters={
                        "docstatus": 0,  # draft only
                        # "utility_service_request": usr.name,
                        "utility_property": meter_reading.property,
                        # "custom_billing_type": billing_type,
                        # Optional: check overlapping date ranges
                        "from_date": ("<=", from_date),
                        "to_date": (">=", to_date),
                    },
                    fields=["name"],
                    order_by="creation desc",
                    limit=1
                )

    if existing_si:
        sales_order = frappe.get_doc("Sales Invoice", existing_si[0].name)

    else:
        sales_order = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": meter_reading.customer,
                "utility_property": meter_reading.property,
                "custom_meter_reading": meter_reading.name,
                "custom_billing_type": 'Utility',
                "set_posting_time": 1,
                "meter_readings": [],
                "items": [],
                # "order_type": "Sales",
                "selling_price_list": meter_reading.price_list,
            }
        )
    
    accounting_dimensions = frappe.get_all("Accounting Dimension", pluck="document_type")
    for dim in accounting_dimensions:
        dim_field = frappe.scrub(dim)
        if hasattr(meter_reading, dim_field):
            setattr(sales_order, dim_field, getattr(meter_reading, dim_field))

    for field in ["project", "cost_center"]:
        if hasattr(meter_reading, field):
            setattr(sales_order, field, getattr(meter_reading, field))

    for rate in meter_reading.rates:
        rate_dict = rate.as_dict()
        rate_dict["delivery_date"] = nowdate()
        sales_order.append("items", rate_dict)

    for i in meter_reading.items:
        prev_reading = get_previous_invoice_reading(
            i.item_code, meter_reading.customer, i.meter_number
        )
        sales_order.append(
            "meter_readings",
            {
                "item_code": i.item_code,
                "meter_number": i.meter_number,
                "meter_reading": meter_reading.name,
                "uom": i.uom,
                "stock_uom": i.stock_uom,
                "current_reading": i.current_reading,
                "previous_reading": prev_reading,
                "consumption": i.consumption,
            },
        )

    sales_order.insert()
    AccountsController.append_taxes_from_item_tax_template(sales_order)

    return sales_order


@frappe.whitelist()
def get_open_reading(item_code, customer, meter_number=None):
    """Fetch the latest reading for the specified customer, item, and optional meter number."""

    SalesInvoiceMeterReading = DocType("Sales Invoice Meter Reading")
    SalesInvoice = DocType("Sales Invoice")

    query = (
        frappe.qb.from_(SalesInvoiceMeterReading)
        .join(SalesInvoice)
        .on(SalesInvoice.name == SalesInvoiceMeterReading.parent)
        .select(SalesInvoiceMeterReading.current_reading)
        .where(SalesInvoice.customer == customer)
        .where(SalesInvoiceMeterReading.item_code == item_code)
        .where(SalesInvoice.docstatus == 1)
    )

    if meter_number:
        query = query.where(SalesInvoiceMeterReading.meter_number == meter_number)
    else:
        query = query.where(SalesInvoiceMeterReading.meter_number.isnull())

    query = query.orderby(SalesInvoiceMeterReading.creation, order=Order.desc)
    result = query.limit(1).run()

    return result[0][0] if result else 0



@frappe.whitelist()
def get_previous_invoice_reading(item_code, customer, meter_number=None , date =None):
    """Fetch the latest reading for the specified customer, item, and optional meter number."""

    SalesInvoiceMeterReading = DocType("Sales Invoice Meter Reading")
    SalesInvoice = DocType("Sales Invoice")

    query = (
        frappe.qb.from_(SalesInvoiceMeterReading)
        .join(SalesInvoice)
        .on(SalesInvoice.name == SalesInvoiceMeterReading.parent)
        .select(SalesInvoiceMeterReading.current_reading)
        .where(SalesInvoice.customer == customer)
        .where(SalesInvoiceMeterReading.item_code == item_code)
        .where(SalesInvoice.docstatus == 1)
    )

    if meter_number:
        query = query.where(SalesInvoiceMeterReading.meter_number == meter_number)
    else:
        query = query.where(SalesInvoiceMeterReading.meter_number.isnull())

    query = query.orderby(SalesInvoiceMeterReading.creation, order=Order.desc)
    result = query.limit(1).run()
    
    if result:
        return result[0][0]
    else:
        meter_assign = find_meter_assign(item_code,meter_number)
        if not meter_assign:
            return 0
        filters = {
        "parent": meter_assign.utility_service_request,
        "meter_number": meter_number,
        "item_code": item_code
        }
        open_reading = frappe.get_value("OpenMeter Reading", filters, "open_reading")
        return open_reading if open_reading else 0

def find_meter_assign(item_code=None, meter_number=None):
    filters = {
        "status": "Open"
    }
    if item_code:
        filters["item_code"] = item_code
    if meter_number:
        filters["serial_no"] = meter_number
    result = frappe.get_all(
        "Meter Assign",
        filters=filters,
        fields=["customer","utility_service_request","serial_no", "item_code", "status", "postdate"],
        limit=1,
        order_by="creation asc"
    )

    return result[0] if result else None

@frappe.whitelist()
def get_customer_details(customer):
    """Fetch all customer details, including the default price list and other fields."""

    customer_doc = frappe.get_doc("Customer", customer)

    if not customer_doc.default_price_list:
        customer_doc.default_price_list = frappe.db.get_value(
            "Customer Group", customer_doc.customer_group, "default_price_list"
        )

    return customer_doc.as_dict()


@frappe.whitelist()
def get_serial_numbers_from_warranty_claims(customer):
    """
    Fetch serial numbers from closed Warranty Claims for the given customer and item.
    """
    serial_numbers = frappe.get_all(
        "Warranty Claim",
        filters={
            "customer": customer,
            "status": "Open",
        },
        fields=["serial_no"],
    )
    serial_list = []
    for claim in serial_numbers:
        if claim.get("serial_no"):
            serial_list.extend(claim["serial_no"].split("\n"))

    return list(set(serial_list))

@frappe.whitelist()
def inset_data(doc):
    import json
    doc = json.loads(doc)
    # return doc

    # Validate meter_assign
    meter_assign = frappe.get_doc("Meter Assign", doc.get('meter_assign'))
    if not meter_assign:
        frappe.throw("Meter Assign not found")

    # Find existing draft Meter Reading for this customer and utility property
    existing_doc_name = frappe.db.get_value('Meter Reading',
                                           filters={
                                               'customer': meter_assign.customer,
                                            #    'utility_property': meter_assign.utility_service_request,
                                               'docstatus': '0'
                                           },
                                           fieldname='name') 
    price_list = frappe.db.get_value('Utility Service Request',
                                           filters={
                                               'name': meter_assign.utility_service_request,
                                           },
                                           fieldname='price_list')

    if existing_doc_name:
        meter_reading = frappe.get_doc('Meter Reading', existing_doc_name)

        # Check if item with item_code and meter_number exists in child table
        existing_item = None
        for item in meter_reading.items:
            if item.item_code == meter_assign.item_code and item.meter_number ==  meter_assign.serial_no:
                existing_item = item
                break
        
        if existing_item:
            # Update existing item reading
            existing_item.current_reading = doc.get('reading_value')
            existing_item.image = doc.get('photo')
        else:
            # Append new item
            meter_reading.append('items', {
                'item_code': meter_assign.item_code,
                'meter_number': meter_assign.serial_no,
                'current_reading': doc.get('reading_value'),
                'image': doc.get('photo'),
            })

        meter_reading.save()
        frappe.db.commit()
        return {"message": "Existing draft updated", "docname": meter_reading.name}

    else:
        # Create new Meter Reading draft with the first item
        new_doc = frappe.get_doc({
            "doctype": "Meter Reading",
            "customer": meter_assign.customer,
            "utility_property": meter_assign.utility_property,
            "date":  frappe.utils.nowdate(),
            "price_list":  price_list,
            # "utility_property": meter_assign.utility_service_request,
            # "docstatus": "Draft",
            "items": [{
                'item_code': meter_assign.item_code,
                'meter_number': meter_assign.serial_no,
                'current_reading': doc.get('reading_value'),
                'image': doc.get('photo'),
            }]
        })
        new_doc.insert()
        frappe.db.commit()
        return {"message": "New draft created", "docname": new_doc.name}

@frappe.whitelist()
def submit_create_invoice(docname, year, month, posting_date, due_date , submit=False):
    """Bulk submit Meter Readings and create Sales Invoices."""
    meter_reading = frappe.get_doc("Meter Reading", docname)
    if meter_reading.docstatus != 0:
        frappe.throw(frappe._("Meter Reading {0} is not in Draft state.").format(docname))

    from datetime import datetime
    from datetime import timedelta
    from_date = datetime(int(year), int(month), 1)
    end_date = datetime(int(year), int(month) + 1, 1) if month != '12' else datetime(int(year) + 1, 1, 1)
    to_date = end_date - timedelta(days=1)
    sales_order = create_sales_order(meter_reading,from_date,to_date)
    sales_order.posting_date = posting_date if posting_date else nowdate()
    sales_order.due_date = due_date if due_date else sales_order.posting_date
    sales_order.from_date = from_date
    sales_order.to_date = to_date
    sales_order.save()
    # if submit:
    #     sales_order.submit()

    meter_reading.db_set("docstatus", 1)
    
    return {"invoice": sales_order.name }