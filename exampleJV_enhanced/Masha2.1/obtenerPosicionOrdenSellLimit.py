from decimal import Decimal
from accesoAPI import inicializar_cliente
client = inicializar_cliente()

def posicionOrdenLimit(symbol):
    try:
        orders = client.get_open_orders(symbol=symbol)
        for order in orders:
            if order["side"] == "SELL" and order["status"] == "NEW":
                DCAPrecioPosicion = Decimal(order["price"])
                DCAVolumenPosicion = Decimal(order["executedQty"])
                DCAcostoTotalPosicion = DCAPrecioPosicion * DCAVolumenPosicion
                print(f"Precio Posicion DCA: {DCAPrecioPosicion}, Cantidad Volumen DCA: {DCAVolumenPosicion}, Costo Total Posicion DCA: {DCAcostoTotalPosicion}")
                return DCAPrecioPosicion, DCAVolumenPosicion, DCAcostoTotalPosicion

        # Si no se encuentra ninguna orden SELL abierta
        print(f"No se encontró ninguna orden SELL LIMIT abierta para {symbol}")
        return None, None, None

    except Exception as e:
        print(f"Error o no existe órdene SELL LIMIT en {symbol}: {e}")
        return None, None, None