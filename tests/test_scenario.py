import datetime
import unittest
from decimal import Decimal

from proteus import Model
from trytond.modules.account.tests.tools import (create_chart, get_accounts,
    create_fiscalyear)
from trytond.modules.account_invoice.tests.tools import (
    set_fiscalyear_invoice_sequences)
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class Test(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):

        # Install sale_rule
        activate_modules('sale_draft')

        # Create company
        _ = create_company()
        company = get_company()

        # Create chart of accounts
        _ = create_chart(company)
        accounts = get_accounts(company)
        revenue = accounts['revenue']
        revenue = accounts['revenue']
        expense = accounts['expense']

        # Create customer
        Party = Model.get('party.party')
        customer = Party(name='Customer')
        customer.save()

        # Create account categories
        ProductCategory = Model.get('product.category')
        account_category = ProductCategory(name="Account Category")
        account_category.accounting = True
        account_category.account_expense = expense
        account_category.account_revenue = revenue
        account_category.save()

        fiscalyear = set_fiscalyear_invoice_sequences(create_fiscalyear(company))
        fiscalyear.click('create_period')


        # Create products
        ProductUom = Model.get('product.uom')
        ProductTemplate = Model.get('product.template')
        Product = Model.get('product.product')
        unit, = ProductUom.find([('name', '=', 'Unit')])
        template = ProductTemplate()
        template.name = 'Product'
        template.default_uom = unit
        template.type = 'goods'
        template.salable = True
        template.lead_time = datetime.timedelta(0)
        template.list_price = Decimal('20')
        template.account_category = account_category
        template.save()
        product1 = Product()
        product1.template = template
        product1.cost_price = Decimal('8')
        product1.save()
        product2 = Product()
        product2.cost_price = Decimal('8')
        product2.template = template
        product2.save()

        # Create sale to test shipment workflow
        Sale = Model.get('sale.sale')
        sale = Sale()
        sale.party = customer
        sale.shipment_method = 'order'
        sale.invoice_method = 'order'
        sale_line = sale.lines.new()
        sale_line.product = product1
        sale_line.quantity = 2
        sale_line = sale.lines.new()
        sale_line.product = product2
        sale_line.quantity = 2
        sale.save()
        sale.click('quote')
        self.assertEqual(sale.state, 'quotation')

        # Ensure sale can be moved to draft in several states
        sale.click('draft')
        self.assertEqual(sale.state, 'draft')

        sale.click('quote')
        sale.click('confirm')
        self.assertEqual(sale.state, 'processing')
        self.assertEqual(sale.shipments[0].state, 'waiting')
        sale.click('draft')
        self.assertEqual(sale.state, 'draft')

        sale.click('quote')
        sale.click('confirm')
        self.assertEqual(sale.state, 'processing')
        self.assertEqual(sale.shipments[0].state, 'waiting')
        shipment, = sale.shipments
        shipment.click('cancel')
        sale.click('draft')
        self.assertEqual(sale.state, 'draft')
        self.assertEqual(len(sale.shipments), 0)

        # Ensure sale does not move to draft if shipment is assigned
        sale.click('quote')
        sale.click('confirm')
        self.assertEqual(sale.state, 'processing')
        self.assertEqual(sale.shipments[0].state, 'waiting')
        shipment, = sale.shipments
        shipment.click('assign_force')
        self.assertEqual(shipment.state, 'assigned')
        sale.click('draft')
        self.assertEqual(sale.state, 'processing')

        # Create sale to test invoice workflow
        Sale = Model.get('sale.sale')
        sale = Sale()
        sale.party = customer
        sale.shipment_method = 'order'
        sale.invoice_method = 'order'
        sale_line = sale.lines.new()
        sale_line.product = product1
        sale_line.quantity = 2
        sale_line = sale.lines.new()
        sale_line.product = product2
        sale_line.quantity = 2
        sale.save()
        sale.click('quote')
        sale.click('confirm')
        self.assertEqual(sale.state, 'processing')
        self.assertEqual(len(sale.invoices), 1)

        # Ensure sale does not move to draft if invoices is posted
        invoice, = sale.invoices
        invoice.click('post')
        self.assertEqual(invoice.state, 'posted')
        sale.click('draft')
        self.assertEqual(sale.state, 'processing')
