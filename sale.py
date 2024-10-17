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

    @classmethod
    def get_allow_draft(cls, sales, name):
        res = dict((x.id, False) for x in sales)

        for sale in sales:
            if sale.state in ('draft', 'done'):
                continue
            moves = [m.id for line in sale.lines for m in line.moves
                + line.moves_ignored
                if m.state != 'draft']
            moves_recreated = [m.id for line in sale.lines
                for m in line.moves_recreated]
            if ((moves and not moves_recreated)
                        or (moves and moves_recreated
                            and sorted(moves) != sorted(moves_recreated))):
                continue
            invoices = [i for i in sale.invoices + sale.invoices_ignored
                if i.state != 'draft']
            invoice_recreateds = [i for i in sale.invoices_recreated]
            if ((invoices and not invoice_recreateds)
                        or (invoices and invoice_recreateds
                            and sorted(invoices) != sorted(invoice_recreateds))):
                continue
            # in case not continue, set to True
            res[sale.id] = True
        return res

    @classmethod
    def draft(cls, sales):
        pool = Pool()
        Move = pool.get('stock.move')
        Shipment = pool.get('stock.shipment.out')
        ShipmentReturn = pool.get('stock.shipment.out.return')
        InvoiceLine = pool.get('account.invoice.line')
        Invoice = pool.get('account.invoice')
        LineRecreated = pool.get('sale.line-recreated-stock.move')

        moves = []
        shipments = []
        shipment_return = []
        invoices = []
        invoice_lines = []
        for sale in sales:
            if not sale.allow_draft:
                continue
            moves.extend([m for line in sale.lines for m in line.moves])
            shipments.extend([s for s in sale.shipments])
            shipment_return.extend([s for s in sale.shipment_returns])
            invoices.extend([i for i in sale.invoice])
            invoice_lines.extend([il for line in sale.lines
                for il in line.invoice_lines if not il.invoice])
        if moves:
            line_recreateds = LineRecreated.search([
                    ('move', 'in', moves),
                    ])
            if line_recreateds:
                LineRecreated.delete(line_recreateds)
            Move.delete(moves)
        if shipments:
            Shipment.delete(shipments)
        if shipment_return:
            ShipmentReturn.delete(shipment_return)
        if invoice_lines:
            InvoiceLine.delete(invoice_lines)
        if invoices:
            Invoice.delete(invoices)

        super().draft(sales)
