from accesoAPI import inicializar_cliente
client = inicializar_cliente()


# Función para buscar y eliminar una orden sell limit existente y colocar una nueva
def actualizarOrdenSellLimit(symbol, nuevo_precio, nuevo_volumen):
    try:
        # Paso 1: Buscar órdenes sell limit abiertas
        open_orders = client.get_open_orders(symbol=symbol)
        for order in open_orders:
            if order['side'] == 'SELL' and order['type'] == 'LIMIT':
                # Paso 2: Cancelar la orden sell limit existente
                result = client.cancel_order(symbol=symbol, orderId=order['orderId'])
                print(f"Orden SELL LIMIT cancelada: {result}")

        # Paso 3: Colocar una nueva orden sell limit
        nueva_orden = client.create_order(
            symbol=symbol,
            side=client.SIDE_SELL,
            type=client.ORDER_TYPE_LIMIT,
            timeInForce=client.TIME_IN_FORCE_GTC,
            quantity=nuevo_volumen,
            price=nuevo_precio
        )
        print(f"Orden SELL LIMIT Actializada: {nueva_orden}")

    except Exception as e:
        print(f"Error al actualizar la orden SELL LIMIT para {symbol}: {e}")