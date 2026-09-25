from proteus import Model, Wizard
from trytond.exceptions import UserWarning
from trytond.modules.sale_kit.tests import test_scenario_kit_shipments
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class TestKitDraft(test_scenario_kit_shipments.TestKitShipments):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        activate_modules(['sale_kit', 'sale_draft'])
        self.setup_company()
        Shipment = Model.get('stock.shipment.out')
        Move = Model.get('stock.move')
        component = self.make_product('Component')
        kit = self.make_product('Kit')
        kit.kit = True
        kit.explode_kit_in_sales = False
        kit.stock_depends_on_kit_components = True
        kit.kit_fixed_list_price = True
        line = kit.kit_lines.new()
        line.product = component
        line.quantity = 1
        kit.save()
        self.supply(component, 5)

        sale = self.make_sale(kit, 10)
        shipment, = sale.shipments
        child, = sale.kit_component_shipments
        move_ids = [m.id for m in shipment.moves + child.moves]
        self.assertTrue(sale.allow_draft)
        sale.click('draft')
        self.assertEqual(sale.state, 'draft')
        self.assertFalse(Shipment.find([('id', 'in', [shipment.id, child.id])]))
        self.assertFalse(Move.find([('id', 'in', move_ids)]))

        # Reprocessing creates one auxiliary, with no stale reservations.
        sale.click('quote')
        sale.click('confirm')
        shipment, = sale.shipments
        child, = sale.kit_component_shipments
        assign = Wizard('stock.shipment.assign', [shipment])
        self.assertEqual(assign.form_state, 'partial')
        assign.execute('end')
        sale.reload()
        self.assertTrue(sale.allow_draft)
        move_ids = [m.id for m in shipment.moves + child.moves]
        sale.click('draft')
        self.assertEqual(sale.state, 'draft')
        self.assertFalse(Shipment.find([('id', 'in', [shipment.id, child.id])]))
        self.assertFalse(Move.find([('id', 'in', move_ids)]))

        # Assigned kits follow the standard sale_draft eligibility rules.
        sale.lines[0].quantity = 5
        sale.save()
        sale.click('quote')
        sale.click('confirm')
        shipment, = sale.shipments
        Wizard('stock.shipment.assign', [shipment])
        sale.reload()
        self.assertTrue(sale.allow_draft)
        child, = sale.kit_component_shipments
        move_ids = [m.id for m in shipment.moves + child.moves]
        sale.click('draft')
        self.assertEqual(sale.state, 'draft')
        self.assertFalse(Shipment.find([('id', 'in', [shipment.id, child.id])]))
        self.assertFalse(Move.find([('id', 'in', move_ids)]))

        # Completed kits use the standard confirmation before resetting.
        sale.click('quote')
        sale.click('confirm')
        shipment, = sale.shipments
        Wizard('stock.shipment.assign', [shipment])
        self.finish(shipment)
        sale.reload()
        self.assertTrue(sale.allow_draft)
        child, = sale.kit_component_shipments
        move_ids = [m.id for m in shipment.moves + child.moves]
        with self.assertRaises(UserWarning) as caught:
            sale.click('draft')
        sale.reload()
        child.reload()
        self.assertEqual(sale.kit_component_shipments, [child])
        self.assertEqual(child.state, 'done')
        self.assertTrue(all(m.state == 'done' for m in child.moves))

        Warning = Model.get('res.user.warning')
        Warning.skip(caught.exception.name, False, Warning._config.context)
        sale.click('draft')
        self.assertEqual(sale.state, 'draft')
        self.assertFalse(Shipment.find([('id', 'in', [shipment.id, child.id])]))
        self.assertFalse(Move.find([('id', 'in', move_ids)]))
        Product = Model.get('product.product')
        with Product._config.set_context(locations=[self.warehouse.id]):
            self.assertEqual(Product(component.id).quantity, 5)
