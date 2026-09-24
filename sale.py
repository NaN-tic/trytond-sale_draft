# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.exceptions import UserWarning
from trytond.i18n import gettext
from trytond.pool import PoolMeta, Pool
from trytond.model import fields
from trytond.pyson import Eval
from trytond.transaction import Transaction


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
        if self.state in ('draft', 'done'):
            return False
        invoices = set(self.invoices + self.invoices_ignored
            + self.invoices_recreated)
        invoices.update(il.invoice for line in self.lines
            for il in line.invoice_lines if il.invoice)
        return all(i.state == 'draft' and not i.number for i in invoices)

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
        Warning = pool.get('res.user.warning')

        moves = set()
        shipments = set()
        shipment_returns = set()
        invoice_lines = set()
        # sale module does not prevent to draft a sale with a shipment
        # so we do it explicitly here
        to_draft = []
        for sale in sales:
            if not sale.allow_draft:
                continue
            to_draft.append(sale)
            moves.update(m for line in sale.lines for m in line.moves)
            shipments.update(sale.shipments)
            shipment_returns.update(sale.shipment_returns)
            invoice_lines.update(il for line in sale.lines
                for il in line.invoice_lines)
        invoices = {il.invoice for il in invoice_lines if il.invoice}

        completed_shipments = sorted(
            (s for s in shipments | shipment_returns if s.state == 'done'),
            key=lambda s: (s.__name__, s.id))
        if completed_shipments:
            warning_name = Warning.format('sale_draft_completed_shipments',
                sorted(to_draft) + completed_shipments)
            if Warning.check(warning_name):
                names = ', '.join(s.rec_name for s in completed_shipments[:5])
                if len(completed_shipments) > 5:
                    names += '...'
                raise UserWarning(warning_name, gettext(
                        'sale_draft.msg_draft_completed_shipments',
                        shipments=names))

        # Include the internal legs of the sale's shipment moves, while
        # preserving moves belonging to other sales in shared shipments.
        pending_moves = list(moves)
        while pending_moves:
            move = pending_moves.pop()
            for outcome in move.outcome_moves:
                if (move.shipment and outcome.shipment == move.shipment
                        and outcome not in moves):
                    moves.add(outcome)
                    pending_moves.append(outcome)
        shipments = [s for s in shipments if set(s.moves) <= moves]
        shipment_returns = [s for s in shipment_returns
            if set(s.moves) <= moves]
        moves = sorted(moves)

        # Draft first so deleting documents cannot process the sale again.
        super().draft(to_draft)
        with Transaction().set_user(0):
            for Relation, field, records in [
                    (LineRecreated, 'move', moves),
                    (LineIgnored, 'move', moves)]:
                if records:
                    Relation.delete(Relation.search([
                                (field, 'in', records),
                                ]))
            # Use stock transitions to reverse completed moves and retain
            # the checks and accounting hooks of the stock modules.
            Shipment.cancel(shipments)
            ShipmentReturn.cancel(shipment_returns)
            Move.cancel(moves)
            Move.delete(moves)
            Shipment.delete(shipments)
            ShipmentReturn.delete(shipment_returns)
            InvoiceLine.delete(list(invoice_lines))
            invoices = Invoice.browse(invoices)
            remaining_invoices = [i for i in invoices if i.lines]
            Invoice.delete([i for i in invoices if not i.lines])
            Invoice.update_taxes(remaining_invoices)
        cls._process_invoice_shipment_states(cls.browse(to_draft))
