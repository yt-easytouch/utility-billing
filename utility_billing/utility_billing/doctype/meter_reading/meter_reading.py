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
    def on_update(self):
        """Whenever Meter Reading is updated, update matching Sales Invoice Meter Reading child rows."""
        # find all Sales Invoices that have meter_readings referencing this meter_reading.name
        linked_invoices = frappe.db.sql(
            """
            SELECT DISTINCT parent 
            FROM `tabSales Invoice Meter Reading`
            WHERE meter_reading = %s
            """,
            self.name,
            as_dict=True
        )

        if not linked_invoices:
            return

        for inv in linked_invoices:
            sales_invoice = frappe.get_doc("Sales Invoice", inv.parent)
            updated = False

            for item in self.items:
                # find child in Sales Invoice Meter Reading that matches by item_code + meter_number + meter_reading name
                matched = next(
                    (
                        m for m in sales_invoice.meter_readings
                        if m.item_code == item.item_code
                        and m.meter_number == item.meter_number
                        and m.meter_reading == self.name
                    ),
                    None
                )

                if matched:
                    # only update if images changed
                    if matched.current_image != item.image or matched.previous_image != item.previous_image:
                        matched.current_image = item.image
                        matched.previous_image = item.previous_image
                        updated = True

            if updated:
                sales_invoice.save(ignore_permissions=True)
                frappe.db.commit()

    # def on_submit(self):
    #     # settings = frappe.get_single("Utility Billing Settings")
    #     # if not self.rates or len(self.rates) == 0:
    #     #     frappe.throw(frappe._("Cannot submit Meter Reading. No rates available."))
    #     # existing_sales_order = frappe.db.exists(
    #     #     {
    #     #         "doctype": "Sales Invoice",
    #     #         "custom_meter_reading": self.name,
    #     #     }
    #     # )
    #     # if not existing_sales_order:
    #     #     if settings.sales_order_creation_state == "Draft":
    #     #         sales_order = create_sales_order(self)
    #     #         sales_order.save()
    #     #     else:
    #     #         sales_order = create_sales_order(self)
    #     #         sales_order.save()
    #     #         sales_order.submit()

    def validate_item_readings(self, item):
        """Validate readings for each item."""
        if item.current_reading is None:
            frappe.throw(
                frappe._(f"Current reading is required for item: {item.item_code}")
            )

        previous_reading, previous_image , previous_meter_reading = get_previous_invoice_reading(
            item_code=item.item_code,
            property_number=self.property,
            meter_number=item.meter_number,
        )
        item.previous_reading = previous_reading
        item.previous_image = previous_image
        item.previous_meter_reading = previous_meter_reading

        item.consumption = item.current_reading - previous_reading

        if item.consumption < 0:
            frappe.throw(
                frappe._(
                    f"Current reading cannot be lower than the previous reading for item: {item.item_code} Previous Rading: {previous_reading}"
                )
            )

def create_sales_order(meter_reading,from_date,to_date,posting_date,due_date):
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
        customer = find_contract_utility_property(meter_reading.property)
        sales_order = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": customer,
                "utility_property": meter_reading.property,
                "custom_meter_reading": meter_reading.name,
                "posting_date": posting_date,
                "due_date": due_date,
                # "custom_billing_type": '',
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
        # prev_reading = get_previous_invoice_reading(
        #     item_code =i.item_code, property_number=meter_reading.property, meter_number = i.meter_number
        # )
        sales_order.append(
            "meter_readings",
            {
                "item_code": i.item_code,
                "meter_number": i.meter_number,
                "meter_reading": meter_reading.name,
                "uom": i.uom,
                "stock_uom": i.stock_uom,
                "current_reading": i.current_reading,
                "previous_reading": i.previous_reading,
                "consumption": i.consumption,
                "current_image": i.image,
                "previous_image": i.previous_image,
            },
        )
    if existing_si:
        sales_order.save(ignore_permissions=True)
    else:
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
def get_previous_invoice_reading(item_code, property_number = None, meter_number=None , date =None):
    """Fetch the latest reading for the specified customer, item, and optional meter number."""

    SalesInvoiceMeterReading = DocType("Meter Reading Item")
    SalesInvoice = DocType("Meter Reading")

    query = (
        frappe.qb.from_(SalesInvoiceMeterReading)
        .join(SalesInvoice)
        .on(SalesInvoice.name == SalesInvoiceMeterReading.parent)
        .select(SalesInvoiceMeterReading.current_reading , SalesInvoiceMeterReading.image , SalesInvoice.name)
        # .where(SalesInvoice.customer == customer)
        .where(SalesInvoice.property == property_number)
        .where(SalesInvoiceMeterReading.item_code == item_code)
        .where(SalesInvoice.docstatus == 1)
    )

    if meter_number:
        query = query.where(SalesInvoiceMeterReading.meter_number == meter_number)
    else:
        query = query.where(SalesInvoiceMeterReading.meter_number.isnull())

    query = query.orderby(SalesInvoiceMeterReading.creation, order=Order.desc)
    result = query.limit(1).run()
    
    # print(str(query))
    # print(str(result))

    if result:
        return result[0][0] , result[0][1] , result[0][2]
    else:
        meter_assign = find_meter_assign(item_code,meter_number)
        if not meter_assign:
            return 0 , None , None
        filters = {
        "parent": meter_assign.utility_service_request,
        "meter_number": meter_number,
        "item_code": item_code
        }
        open_reading = frappe.get_value("OpenMeter Reading", filters, "open_reading")
        value_open_reading = open_reading if open_reading else 0
        return value_open_reading , None , None


@frappe.whitelist()
def find_contract_utility_property(property_number = None):
    """Fetch the latest reading for the specified customer, item, and optional meter number."""

    SalesInvoiceMeterReading = DocType("Contract Utility Property Item")
    SalesInvoice = DocType("Utility Service Request")

    query = (
        frappe.qb.from_(SalesInvoiceMeterReading)
        .join(SalesInvoice)
        .on(SalesInvoice.name == SalesInvoiceMeterReading.parent)
        .select(SalesInvoice.party_name)
        # .where(SalesInvoice.customer == customer)
        .where(SalesInvoiceMeterReading.utility_property == property_number)
        .where(SalesInvoiceMeterReading.is_active == 1)
        .where(SalesInvoice.docstatus == 1)
    )


    query = query.orderby(SalesInvoiceMeterReading.creation, order=Order.desc)
    result = query.limit(1).run()
    

    if result:
        return result[0][0]
    else:
        return  0


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
    serial_no = frappe.get_doc("Serial No", doc.get('serial_no'))
    if not serial_no:
        frappe.throw("Meter Assign not found")

    # Find existing draft Meter Reading for this customer and utility property
    existing_doc_name = frappe.db.get_value('Meter Reading',
                                           filters={
                                                'property': serial_no.custom_utility_property,
                                               'docstatus': '0'
                                           },
                                           fieldname='name') 
    settings = frappe.get_single("Utility Billing Settings")
    price_list = settings.default_price_list

    if existing_doc_name:
        meter_reading = frappe.get_doc('Meter Reading', existing_doc_name)

        # Check if item with item_code and meter_number exists in child table
        existing_item = None
        for item in meter_reading.items:
            if item.item_code == doc.get('item_code') and item.meter_number ==  doc.get('serial_no'):
                existing_item = item
                break
        
        if existing_item:
            # Update existing item reading
            existing_item.current_reading = doc.get('reading_value')
            existing_item.image = doc.get('photo')
        else:
            # Append new item
            meter_reading.append('items', {
                'item_code': doc.get('item_code'),
                'meter_number': doc.get('serial_no'),
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
            "property": serial_no.custom_utility_property,
            "date":  frappe.utils.nowdate(),
            "price_list":  price_list,
            # "utility_property": meter_assign.utility_service_request,
            # "docstatus": "Draft",
            "items": [{
                'item_code': doc.get('item_code'),
                'meter_number': doc.get('serial_no'),
                'current_reading': doc.get('reading_value'),
                'image': doc.get('photo'),
            }]
        })
        new_doc.insert()
        frappe.db.commit()
        return {"message": "New draft created", "docname": new_doc.name}

import frappe, json, os, random, string
from frappe.utils import nowdate, now_datetime

def generate_image_code(length=6):
    """Generate random alphanumeric code like ABC123."""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=length))

@frappe.whitelist()
def bulk_insert(serial_no, readings):
    """
    Handle readings coming from UI (where files are already uploaded).
    Rename uploaded images with unique code + serial + date,
    and make them public.
    """
    readings = frappe.parse_json(readings)
    serial = frappe.get_doc("Serial No", serial_no)
    if not serial:
        frappe.throw("Serial No not found")

    settings = frappe.get_single("Utility Billing Settings")
    price_list = settings.default_price_list

    existing_doc_name = frappe.db.get_value(
        "Meter Reading",
        {"property": serial.custom_utility_property, "docstatus": 0},
        "name"
    )

    if existing_doc_name:
        meter_doc = frappe.get_doc("Meter Reading", existing_doc_name)
        message = "Existing draft updated"
    else:
        meter_doc = frappe.get_doc({
            "doctype": "Meter Reading",
            "property": serial.custom_utility_property,
            "date": nowdate(),
            "price_list": price_list,
            "items": []
        })
        message = "New draft created"

    today_str = now_datetime().strftime("%Y%m%d")

    for row in readings:
        item_code = row.get("item_code")
        current_reading = row.get("reading_value")
        photo = row.get("photo")

        if not item_code or not current_reading:
            continue

        photo_url = None

        # ✅ File was uploaded via UI — handle rename
        if photo and photo.startswith("/files/"):
            file_name = frappe.db.get_value("File", {"file_url": photo}, "name")
            if file_name:
                try:
                    file_doc = frappe.get_doc("File", file_name)
                    old_name = file_doc.file_name
                    old_ext = os.path.splitext(old_name)[1] or ".jpg"

                    # Generate unique image code and new filename
                    image_code = generate_image_code()
                    new_filename = f"IMG-{image_code}-{serial_no}-{today_str}{old_ext}"
                    new_rel_path = f"/files/{new_filename}"

                    old_path = frappe.get_site_path("public", file_doc.file_url.strip("/"))
                    new_path = frappe.get_site_path("public", new_rel_path.strip("/"))

                    if os.path.exists(old_path):
                        os.rename(old_path, new_path)

                    file_doc.file_name = new_filename
                    file_doc.file_url = new_rel_path
                    file_doc.is_private = 0
                    file_doc.save(ignore_permissions=True)

                    photo_url = new_rel_path

                except Exception as e:
                    frappe.log_error(f"File rename failed for {photo}: {e}")
                    photo_url = photo

        # 🔁 Update or append reading item
        existing = next(
            (i for i in meter_doc.items if i.item_code == item_code and i.meter_number == serial_no),
            None
        )

        if existing:
            existing.current_reading = current_reading
            existing.image = photo_url or photo
        else:
            meter_doc.append("items", {
                "item_code": item_code,
                "meter_number": serial_no,
                "current_reading": current_reading,
                "image": photo_url or photo
            })

    meter_doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {"message": message, "docname": meter_doc.name}


@frappe.whitelist()
def submit_create_invoice(docname, year, month, posting_date, due_date , submit=False):
    """Bulk submit Meter Readings and create Sales Invoices."""
    meter_reading = frappe.get_doc("Meter Reading", docname)
    if meter_reading.docstatus == 2:
        frappe.throw(frappe._("Meter Reading {0} is not in Draft state.").format(docname))

    from datetime import datetime
    from datetime import timedelta
    from_date = datetime(int(year), int(month), 1)
    end_date = datetime(int(year), int(month) + 1, 1) if month != '12' else datetime(int(year) + 1, 1, 1)
    to_date = end_date - timedelta(days=1)
    posting_date = posting_date if posting_date else nowdate()
    due_date = due_date if due_date else sales_order.posting_date
    sales_order = create_sales_order(meter_reading,from_date,to_date,posting_date,due_date)
    sales_order.posting_date = posting_date if posting_date else nowdate()
    sales_order.due_date = due_date if due_date else sales_order.posting_date
    sales_order.from_date = from_date
    sales_order.to_date = to_date
    if not sales_order.payment_schedule:
    # if missing, create one row that matches invoice due_date
        sales_order.append("payment_schedule", {
        "due_date": sales_order.due_date or sales_order.posting_date,
        "invoice_portion": 100,
        "payment_amount": sales_order.grand_total
        })
    else:
    # if exists, correct the due_date
        for ps in sales_order.payment_schedule:
            ps.due_date = sales_order.due_date or sales_order.posting_date
            ps.payment_amount = sales_order.grand_total
            ps.invoice_portion = 100
    sales_order.save(ignore_permissions=True)
    # print(sales_order.as_dict())
    # if submit:
    #     sales_order.submit()

    meter_reading.db_set("docstatus", 1)
    
    return {"invoice": sales_order.name }