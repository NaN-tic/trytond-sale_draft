# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import PoolMeta, Pool
from trytond.model import fields
from trytond.pyson import Eval


class Sale(metaclass=PoolMeta):
    __name__ = 'sale.sale'

    allow_draft = fields.Function(
        fields.Boolean("Allow Draft Sale"), 'get_allow_draft')

    @classmethod
    def __setup__(cls):
        super().__setup__()

        cls._transitions |= set((('processing', 'draft'),))
        cls._buttons['draft']['invisible'] = ~Eval('allow_draft', False)
        cls._buttons['draft']['depends'] += ['allow_draft']

    def get_allow_draft(self, name):
        if (self.state in ('draft', 'done')
                or any([m for line in self.lines for m in line.moves
                        if m.state not in ('draft', 'cancelled')])
                or any([x for line in self.lines for x in line.invoice_lines
                        if x.invoice and x.invoice.state not in (
                            'draft', 'cancelled')])):
            return False
        return True

    @classmethod
    def draft(cls, sales):
        pool = Pool()
        Move = pool.get('stock.move')
        Shipment = pool.get('stock.shipment.out')
        ShipmentReturn = pool.get('stock.shipment.out.return')
        InvoiceLine = pool.get('account.invoice.line')
        Invoice = pool.get('account.invoice')
        LineRecreated = pool.get('sale.line-recreated-stock.move')
        LineIgnored = pool.get('sale.line-ignored-stock.move')

        moves = []
        shipments = []
        shipment_return = []
        invoices = []
        invoice_lines = []
        for sale in sales:
            if not sale.allow_draft:
                continue
            moves += [m for line in sale.lines for m in line.moves]
            shipments += sale.shipments
            shipment_return += sale.shipment_returns
            invoices += sale.invoices
            invoice_lines += [il for line in sale.lines
                for il in line.invoice_lines if not il.invoice]
        if moves:
            line_recreateds = LineRecreated.search([
                    ('move', 'in', moves),
                    ])
            LineRecreated.delete(line_recreateds)
            line_ignoreds = LineIgnored.search([
                    ('move', 'in', moves),
                    ])
            LineIgnored.delete(line_ignoreds)
            LineRecreated.delete(line_recreateds)
            Move.delete(moves)
        Shipment.delete(shipments)
        ShipmentReturn.delete(shipment_return)
        InvoiceLine.delete(invoice_lines)
        Invoice.delete(invoices)

        super().draft(sales)
