# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool, PoolMeta


class Sale(metaclass=PoolMeta):
    __name__ = 'sale.sale'

    @classmethod
    def draft(cls, sales):
        Shipment = Pool().get('stock.shipment.out')
        shipments = [shipment for sale in sales if sale.allow_draft
            for shipment in sale.shipments]
        # Component origins must be removed before sale_draft deletes the
        # commercial stock moves they reference.
        Shipment._remove_kit_shipments(shipments)
        super().draft(sales)
