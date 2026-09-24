import unittest
from decimal import Decimal

from proteus import Model
from trytond.exceptions import UserWarning
from trytond.modules.account.tests.tools import (
    create_chart, create_tax, get_accounts)
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class TestDraftCompletedShipment(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules([
                'sale_draft', 'sale_invoice_grouping', 'sale_shipment_grouping'])
        create_company()
        company = get_company()
        create_chart(company)
        accounts = get_accounts(company)
        tax = create_tax(Decimal('.10'))
        tax.save()

        Category = Model.get('product.category')
        category = Category(name='Account Category', accounting=True)
        category.account_expense = accounts['expense']
        category.account_revenue = accounts['revenue']
        category.customer_taxes.append(tax)
        category.save()
        Uom = Model.get('product.uom')
        unit, = Uom.find([('name', '=', 'Unit')])
        Template = Model.get('product.template')
        template = Template(name='Product', type='goods', salable=True)
        template.default_uom = unit
        template.list_price = Decimal('20')
        template.account_category = category
        template.save()
        product, = template.products
        Product = Model.get('product.product')

        Location = Model.get('stock.location')
        warehouse, = Location.find([('type', '=', 'warehouse')])
        lost_found, = Location.find([('type', '=', 'lost_found')])
        Move = Model.get('stock.move')
        stock = Move(product=product, unit=unit, quantity=10,
            from_location=lost_found, to_location=warehouse.storage_location,
            company=company)
        stock.click('do')

        Party = Model.get('party.party')
        Sale = Model.get('sale.sale')
        Invoice = Model.get('account.invoice')
        Shipment = Model.get('stock.shipment.out')
        Warning = Model.get('res.user.warning')

        def create_sale(customer, quantity=2, invoice_method='order'):
            sale = Sale(party=customer, invoice_method=invoice_method)
            line = sale.lines.new()
            line.product = product
            line.quantity = quantity
            sale.click('quote')
            sale.click('confirm')
            return sale

        def complete_shipment(shipment):
            shipment.click('assign_force')
            shipment.click('pick')
            shipment.click('pack')
            shipment.click('do')
            self.assertEqual(shipment.state, 'done')
            self.assertTrue(all(m.state == 'done' for m in shipment.moves))

        def quantity(location):
            with config.set_context(locations=[location.id]):
                return Product(product.id).quantity

        def draft_with_warning(sale):
            shipment, = sale.shipments
            invoice, = sale.invoices
            stock_quantity = quantity(warehouse)
            move_ids = [m.id for m in shipment.moves]
            invoice_line_ids = [l.id for l in invoice.lines]
            # Dismissing the warning must leave all documents and stock intact.
            for _ in range(2):
                with self.assertRaises(UserWarning) as caught:
                    sale.click('draft')
                self.assertIn(shipment.rec_name, caught.exception.message)
                self.assertIn('cancel this action', caught.exception.message)
                sale.reload()
                shipment.reload()
                invoice.reload()
                self.assertEqual(sale.state, 'processing')
                self.assertEqual(sale.shipments, [shipment])
                self.assertEqual(sale.invoices, [invoice])
                self.assertEqual(shipment.state, 'done')
                self.assertEqual([m.id for m in shipment.moves], move_ids)
                self.assertTrue(all(m.state == 'done' for m in shipment.moves))
                self.assertEqual([l.id for l in invoice.lines], invoice_line_ids)
                self.assertEqual(quantity(warehouse), stock_quantity)
            Warning.skip(caught.exception.name, False, config.context)
            sale.click('draft')

        for group_invoice, group_shipment in (
                (False, False), (True, False), (True, True)):
            with self.subTest(group_invoice=group_invoice,
                    group_shipment=group_shipment):
                customer = Party(name='Customer')
                if group_invoice:
                    customer.sale_invoice_grouping_method = 'standard'
                if group_shipment:
                    customer.sale_shipment_grouping_method = 'standard'
                customer.save()
                sale = create_sale(customer)
                other_sale = create_sale(customer, 3) if group_invoice else None
                sale.reload()
                invoice, = sale.invoices
                shipment, = sale.shipments
                complete_shipment(shipment)
                sale.reload()
                self.assertEqual(sale.state, 'processing')
                self.assertTrue(sale.allow_draft)
                self.assertEqual(sale.shipment_state, 'sent')
                self.assertEqual(invoice.state, 'draft')
                self.assertFalse(invoice.number)
                self.assertEqual(quantity(warehouse),
                    5 if group_shipment else 8)
                self.assertEqual(quantity(warehouse.storage_location),
                    5 if group_shipment else 8)

                if other_sale:
                    other_sale.reload()
                    self.assertEqual(other_sale.invoices, [invoice])
                    other_invoice_line, = other_sale.lines[0].invoice_lines
                    other_move_ids = [m.id for m in other_sale.lines[0].moves]
                    self.assertEqual(invoice.total_amount, Decimal('110'))

                deleted_move_ids = [m.id for m in shipment.moves
                    if not other_sale or m.origin == sale.lines[0]
                    or (isinstance(m.origin, Move)
                        and m.origin.origin == sale.lines[0])]
                draft_with_warning(sale)
                self.assertEqual(sale.state, 'draft')
                self.assertEqual(sale.shipment_state, 'none')
                self.assertEqual(sale.invoice_state, 'none')
                self.assertFalse(sale.shipments)
                self.assertFalse(sale.invoices)
                self.assertFalse(sale.lines[0].moves)
                self.assertFalse(sale.lines[0].invoice_lines)
                self.assertEqual(sale.lines[0].actual_quantity, 0)
                self.assertFalse(Move.find([('id', 'in', deleted_move_ids)]))
                self.assertEqual(quantity(warehouse),
                    7 if group_shipment else 10)
                self.assertEqual(quantity(warehouse.storage_location),
                    7 if group_shipment else 10)
                self.assertEqual(quantity(warehouse.output_location), 0)

                if other_sale:
                    invoice.reload()
                    other_sale.reload()
                    self.assertEqual(invoice.state, 'draft')
                    self.assertEqual(invoice.lines, [other_invoice_line])
                    self.assertEqual(invoice.untaxed_amount, Decimal('60'))
                    self.assertEqual(invoice.tax_amount, Decimal('6'))
                    self.assertEqual(invoice.total_amount, Decimal('66'))
                    self.assertEqual(other_sale.state, 'processing')
                    self.assertEqual(other_sale.invoices, [invoice])
                    self.assertEqual([m.id for m in other_sale.lines[0].moves],
                        other_move_ids)
                else:
                    self.assertFalse(Invoice.find([('id', '=', invoice.id)]))

                if group_shipment:
                    shipment.reload()
                    self.assertEqual(shipment.state, 'done')
                    self.assertEqual(shipment, other_sale.shipments[0])
                    self.assertTrue(all(m.state == 'done'
                            for m in shipment.moves))
                else:
                    self.assertFalse(Shipment.find([('id', '=', shipment.id)]))

                if other_sale:
                    if group_shipment:
                        draft_with_warning(other_sale)
                    else:
                        other_sale.click('draft')
                    self.assertFalse(Invoice.find([('id', '=', invoice.id)]))
                    self.assertEqual(quantity(warehouse), 10)

                # Reconfirmation creates one full delivery and invoice again.
                sale.click('quote')
                sale.click('confirm')
                new_shipment, = sale.shipments
                self.assertNotEqual(new_shipment.id, shipment.id)
                move, = new_shipment.outgoing_moves
                self.assertEqual(move.quantity, 2)
                new_invoice, = sale.invoices
                self.assertEqual(new_invoice.total_amount, Decimal('44'))
                sale.click('draft')

        customer = Party(name='Invoice on Shipment')
        customer.save()
        sale = create_sale(customer, invoice_method='fulfillment')
        self.assertFalse(sale.invoices)
        self.assertTrue(sale.allow_draft)
        sale.click('draft')
        self.assertEqual(sale.state, 'draft')
        self.assertFalse(sale.shipments)
        sale.click('quote')
        sale.click('confirm')
        shipment, = sale.shipments
        complete_shipment(shipment)
        sale.reload()
        invoice, = sale.invoices
        self.assertEqual(invoice.state, 'draft')
        self.assertTrue(sale.allow_draft)
        draft_with_warning(sale)
        self.assertEqual(sale.state, 'draft')
        self.assertFalse(sale.shipments)
        self.assertFalse(sale.invoices)
        self.assertEqual(quantity(warehouse), 10)

        for invoice_state in ('numbered', 'cancelled', 'validated'):
            with self.subTest(blocking_invoice=invoice_state):
                sale = create_sale(customer)
                shipment, = sale.shipments
                complete_shipment(shipment)
                invoice, = sale.invoices
                if invoice_state == 'numbered':
                    Invoice._proxy.write([invoice.id],
                        {'number': 'TEST-001'}, config.context)
                    invoice.reload()
                    self.assertEqual(invoice.state, 'draft')
                    self.assertEqual(invoice.number, 'TEST-001')
                elif invoice_state == 'cancelled':
                    invoice.click('cancel')
                    self.assertFalse(invoice.number)
                else:
                    invoice.click('validate_invoice')
                sale.reload()
                self.assertFalse(sale.allow_draft)
                stock_quantity = quantity(warehouse)
                move_ids = [m.id for m in shipment.moves]
                invoice_line_ids = [l.id for l in invoice.lines]
                sale.click('draft')
                self.assertEqual(sale.state, 'processing')
                self.assertEqual(sale.shipments, [shipment])
                self.assertEqual(sale.invoices, [invoice])
                shipment.reload()
                invoice.reload()
                self.assertEqual(shipment.state, 'done')
                self.assertEqual([m.id for m in shipment.moves], move_ids)
                self.assertEqual([l.id for l in invoice.lines], invoice_line_ids)
                self.assertEqual(quantity(warehouse), stock_quantity)
