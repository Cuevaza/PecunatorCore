from decimal import Decimal

def obtener_balances(client, symbolo, baseAsset, quoteAsset):
    # Obtener información de la cuenta
    info_cuenta = client.get_account()

    # Inicializar variables
    base_free = Decimal('0')
    base_locked = Decimal('0')
    base_total = Decimal('0')
    quote_free = Decimal('0')
    quote_locked = Decimal('0')
    quote_total = Decimal('0')

    # Filtrar balances según los parámetros dados
    for balance in info_cuenta['balances']:
        if balance['asset'] == baseAsset:
            base_free = Decimal(balance['free'])
            base_locked = Decimal(balance['locked'])
            base_total = base_free + base_locked
        elif balance['asset'] == quoteAsset:
            quote_free = Decimal(balance['free'])
            quote_locked = Decimal(balance['locked'])
            quote_total = quote_free + quote_locked

    return base_free, base_locked, base_total, quote_free, quote_locked, quote_total