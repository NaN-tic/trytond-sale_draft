# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import sale
from . import kit


def register():
    Pool.register(
        sale.Sale,
        module='sale_draft', type_='model')
    Pool.register(
        kit.Sale,
        module='sale_draft', type_='model', depends=['sale_kit'])
