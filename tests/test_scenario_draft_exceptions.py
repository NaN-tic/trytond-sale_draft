import unittest
from decimal import Decimal

from proteus import Model, Wizard
from trytond.exceptions import UserWarning
from trytond.modules.account.tests.tools import create_chart, get_accounts
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class TestDraftExceptions(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules('sale_draft')
        create_company()
        company = get_company()
        create_chart(company)
        accounts = get_accounts(company)

        Party = Model.get('party.party')
        customer = Party(name='Customer')
        customer.save()
        Category = Model.get('product.category')
        category = Category(name='Account Category', accounting=True)
        category.account_expense = accounts['expense']
        category.account_revenue = accounts['revenue']
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

        Sale = Model.get('sale.sale')
        for quantity in (2, -2):
            for document in ('shipment', 'invoice'):
                for exception in (None, 'pending', 'ignored', 'recreated'):
                    with self.subTest(quantity=quantity, document=document,
                            exception=exception):
                        sale = Sale(party=customer)
                        sale.invoice_method = 'order'
                        sale.shipment_method = 'order'
                        line = sale.lines.new()
                        line.product = product
                        line.quantity = quantity
                        sale.click('quote')
                        sale.click('confirm')
                        self.assertEqual(sale.state, 'processing')
                        self.assertEqual(sale.invoice_state, 'pending')
                        self.assertEqual(sale.shipment_state, 'waiting')

                        if exception:
                            if document == 'shipment':
                                shipments = (sale.shipments if quantity > 0
                                    else sale.shipment_returns)
                                shipment, = shipments
                                shipment.click('cancel')
                            else:
                                invoice, = sale.invoices
                                invoice.click('cancel')
                            sale.reload()
                            self.assertEqual(
                                getattr(sale, document + '_state'),
                                'exception')
                            if exception != 'pending':
                                wizard = Wizard(
                                    'sale.handle.%s.exception' % document,
                                    [sale])
                                field = ('moves' if document == 'shipment'
                                    else 'invoices')
                                action = ('ignore' if exception == 'ignored'
                                    else 'recreate')
                                records = getattr(
                                    wizard.form, 'domain_' + field)
                                selected = getattr(
                                    wizard.form, action + '_' + field)
                                selected.extend(type(r)(r.id) for r in records)
                                wizard.execute('handle')
                                if document == 'shipment':
                                    self.assertTrue(getattr(sale.lines[0],
                                            'moves_' + exception))
                                else:
                                    self.assertTrue(getattr(sale,
                                            'invoices_' + exception))

                        self.assertEqual(sale.state, 'processing')
                        if document == 'invoice' and exception:
                            # Cancelled invoices block drafting, including
                            # exceptions already ignored or recreated.
                            self.assertFalse(sale.allow_draft)
                            invoice_ids = [i.id for i in sale.invoices]
                            move_ids = [m.id for m in sale.lines[0].moves]
                            sale.click('draft')
                            self.assertEqual(sale.state, 'processing')
                            self.assertEqual(
                                [i.id for i in sale.invoices], invoice_ids)
                            self.assertEqual(
                                [m.id for m in sale.lines[0].moves], move_ids)
                            continue
                        self.assertTrue(sale.allow_draft)
                        sale.click('draft')
                        self.assertEqual(sale.state, 'draft')
                        self.assertEqual(sale.invoice_state, 'none')
                        self.assertEqual(sale.shipment_state, 'none')
                        self.assertFalse(sale.invoices)
                        self.assertFalse(sale.invoices_ignored)
                        self.assertFalse(sale.invoices_recreated)
                        self.assertFalse(sale.shipments)
                        self.assertFalse(sale.shipment_returns)
                        line, = sale.lines
                        self.assertFalse(line.moves)
                        self.assertFalse(line.moves_ignored)
                        self.assertFalse(line.moves_recreated)
                        self.assertFalse(line.invoice_lines)
                        self.assertEqual(line.actual_quantity, 0)
                        self.assertIsNone(sale.total_amount_cache)

                        # Reconfirmation must recreate the full quantities once.
                        sale.click('quote')
                        sale.click('confirm')
                        self.assertEqual(sale.state, 'processing')
                        self.assertEqual(sale.invoice_state, 'pending')
                        self.assertEqual(sale.shipment_state, 'waiting')
                        invoice, = sale.invoices
                        invoice_line, = invoice.lines
                        self.assertEqual(invoice_line.quantity, quantity)
                        line, = sale.lines
                        move, = line.moves
                        self.assertEqual(move.quantity, abs(quantity))

        # Received returns are reversed when there is no issued invoice.
        sale = Sale(party=customer, invoice_method='order')
        line = sale.lines.new()
        line.product = product
        line.quantity = -2
        sale.click('quote')
        sale.click('confirm')
        shipment_return, = sale.shipment_returns
        shipment_return.click('receive')
        sale.reload()
        self.assertEqual(shipment_return.state, 'received')
        self.assertTrue(sale.allow_draft)
        sale.click('draft')
        self.assertEqual(sale.state, 'draft')
        self.assertFalse(sale.invoices)
        self.assertFalse(sale.shipment_returns)
        self.assertEqual(sale.shipment_state, 'none')

        # Completed returns also require explicit acknowledgement.
        sale.click('quote')
        sale.click('confirm')
        shipment_return, = sale.shipment_returns
        shipment_return.click('receive')
        shipment_return.click('do')
        self.assertEqual(shipment_return.state, 'done')
        with self.assertRaises(UserWarning) as caught:
            sale.click('draft')
        self.assertIn(shipment_return.rec_name, caught.exception.message)
        sale.reload()
        shipment_return.reload()
        self.assertEqual(sale.state, 'processing')
        self.assertEqual(shipment_return.state, 'done')
        self.assertTrue(sale.invoices)
        Warning = Model.get('res.user.warning')
        Warning.skip(caught.exception.name, False, config.context)
        sale.click('draft')
        self.assertEqual(sale.state, 'draft')
        self.assertFalse(sale.shipment_returns)
        self.assertFalse(sale.invoices)

        for action in ('ignore', 'recreate', 'receive'):
            with self.subTest(partial_return=action):
                sale = Sale(party=customer)
                sale.invoice_method = 'order'
                sale.shipment_method = 'order'
                for _ in range(2):
                    line = sale.lines.new()
                    line.product = product
                    line.quantity = -1
                sale.click('quote')
                sale.click('confirm')
                shipment_return, = sale.shipment_returns
                moves = list(shipment_return.incoming_moves)

                if action == 'receive':
                    # A draft return can already contain a completed move.
                    moves[0].click('do')
                    sale.click('process')
                    self.assertEqual(sale.shipment_state, 'partially shipped')
                    shipment_return.reload()
                    self.assertEqual(shipment_return.state, 'draft')
                else:
                    shipment_return.click('cancel')
                    sale.reload()
                    wizard = Wizard('sale.handle.shipment.exception', [sale])
                    move = wizard.form.domain_moves[0]
                    getattr(wizard.form, action + '_moves').append(
                        type(move)(move.id))
                    wizard.execute('handle')
                    # One exception is handled while another is still pending.
                    self.assertEqual(sale.shipment_state, 'exception')
                self.assertTrue(sale.allow_draft)
                sale.click('draft')
                self.assertEqual(sale.state, 'draft')
                self.assertEqual(sale.shipment_state, 'none')
                self.assertEqual(sale.invoice_state, 'none')
                self.assertFalse(sale.shipment_returns)
                self.assertFalse(sale.invoices)
                for line in sale.lines:
                    self.assertFalse(line.moves)
                    self.assertFalse(line.moves_ignored)
                    self.assertFalse(line.moves_recreated)
