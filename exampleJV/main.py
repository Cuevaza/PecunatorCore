
import datetime
import time
from decimal import Decimal
from accesoAPI import inicializar_cliente

# NOTA: PRICE_FILTER ERROR, ajusta la presicion de las variables Decimal en donde se asigna el precio de las ordenes SELL LIMIT, de manera que satisfaga los filtros que se pueden consultar en "detalles del simbolo", o en "symbol info"
# NOTA: NOTIONAL ERROR, comunmente ocurre debido a que el modulo especificado es demaciado pequeño para satisfacer el nocional, aumentalo hasta que lo satisfaga


# Seteteos configurados
symbol = "XRPUSDT" # Activo trabajado por el Bot........................................
horaFechaLocalInicial = datetime.datetime.now()
tiempoEntreEjecucion = 450 # Segundos
quoteOrderQtyModulo = Decimal("8") # Comunmente USDT
factorPorcentualBeneficio = Decimal("0.05")  # Ejemplo 0.05 para ganar un 5% por comercio
factorPorcentualMargenBajada = Decimal("0.004")  # Ejemplo 0.004 para comprar a mercado un 0.4% mas abajo de la ultima compra a mercado encontrada, esto previene que se concentren muchas compras a mercado al rededor de un rango estrecho de la accione del precio y si se distribuyan las compras mas uniformemente en las caidas prolongadas del precio, cada symbolo puede tener un % de ajuste unico segun su volatilidad y espectro habitual de fluctuacion del precio

# Detalles de Inicio para control y ajuste
print(f"HORA DE INICIO DE LA CORRIDA: {horaFechaLocalInicial}")
print(f"SETEO BASE Dorothy7.0 ----------")
print(f"SIMBOLO: {symbol}")
print(f"TIEMPO ENTRE ITERACION DEL BOT: {tiempoEntreEjecucion}")
print(f"CANTIDAD POR COMPRA: {quoteOrderQtyModulo}")
print(f"PORCENTAJE BENEFICIO: {factorPorcentualBeneficio}")
print(f"PORCENTAJE MARGEN BAJADA: {factorPorcentualMargenBajada}")
print("DETALLES DEL SIMBOLO:")

client = inicializar_cliente()
symbolInfo = client.get_symbol_info(symbol)
print(symbolInfo)

# Ciclo principal del bot
while True:
    try:
        if __name__ == "__main__":
            client = inicializar_cliente()

            if client:
                ordenes_activas = client.get_open_orders(symbol=symbol)
                orden_sell_limit = None
                precio_activacion_mas_bajo = None

                for orden in ordenes_activas:
                    if orden['side'] == 'SELL' and orden['type'] == 'LIMIT':
                        if precio_activacion_mas_bajo is None or Decimal(orden['price']) < precio_activacion_mas_bajo:
                            orden_sell_limit = orden
                            precio_activacion_mas_bajo = Decimal(orden['price'])

                if orden_sell_limit:
                    precio_activacion = Decimal(orden_sell_limit['price'])
                    print(f"Orden SELL LIMIT ACTIVA MAS BAJA ENCONTRADA en {symbol}. Precio de activación: {precio_activacion}")

                    # Obtener precio de mercado actual
                    precio_mercado = Decimal(client.get_symbol_ticker(symbol=symbol)['price'])

                    # Calcular nivel de entrada aceptable
                    nivelEntradaAceptable = precio_activacion * (1 - (factorPorcentualBeneficio + factorPorcentualMargenBajada))
                    print(f"Esperando nivel de entrada aceptable: {nivelEntradaAceptable} Precio Actual de {symbol}: {precio_mercado}")

                    if precio_mercado <= nivelEntradaAceptable:
                        try:
                            orden_compra = client.create_order(
                                symbol=symbol,
                                side=client.SIDE_BUY,
                                type=client.ORDER_TYPE_MARKET,
                                quoteOrderQty=quoteOrderQtyModulo
                            )
                            print(f"Compra a mercado exitosa para {symbol}. Detalles: {orden_compra}")
                            time.sleep(1)

                            precio_compra = Decimal(orden_compra['fills'][0]['price'])
                            cantidad_compra = Decimal(orden_compra['executedQty'])
                            precio_venta = precio_compra * (1 + factorPorcentualBeneficio)

                            orden_venta = client.create_order(
                                symbol=symbol,
                                side=client.SIDE_SELL,
                                type=client.ORDER_TYPE_LIMIT,
                                timeInForce=client.TIME_IN_FORCE_GTC,
                                quantity=f"{cantidad_compra:.8f}",
                                price=f"{precio_venta:.4f}" #...........................
                            )

                            print(f"Orden SELL LIMIT colocada para {symbol}. Detalles: {orden_venta}")

                        except Exception as e:
                            print(f"Error al realizar la compra a mercado o colocar la orden SELL LIMIT 01: {e}")

                else:
                    try:
                        print(f"Ninguna orden SELL LIMIT encontrada, se procede a comprar a mercado")
                        orden_compra = client.create_order(
                            symbol=symbol,
                            side=client.SIDE_BUY,
                            type=client.ORDER_TYPE_MARKET,
                            quoteOrderQty=quoteOrderQtyModulo
                        )
                        print(f"Compra a mercado exitosa para {symbol}. Detalles: {orden_compra}")
                        time.sleep(1)

                        precio_compra = Decimal(orden_compra['fills'][0]['price'])
                        cantidad_compra = Decimal(orden_compra['executedQty'])
                        precio_venta = precio_compra * (1 + factorPorcentualBeneficio)

                        orden_venta = client.create_order(
                            symbol=symbol,
                            side=client.SIDE_SELL,
                            type=client.ORDER_TYPE_LIMIT,
                            timeInForce=client.TIME_IN_FORCE_GTC,
                            quantity=f"{cantidad_compra:.8f}",
                            price=f"{precio_venta:.4f}" #.............................
                        )

                        print(f"Orden SELL LIMIT colocada para {symbol}. Detalles: {orden_venta}")

                    except Exception as e:
                        print(f"Error al realizar la compra a mercado o colocar la orden SELL LIMIT 02: {e}")

            print(f"Esperando accion del precio a las: {datetime.datetime.now()} --------------------------")
            time.sleep(tiempoEntreEjecucion)


    except Exception as e:
        print(f"Misterious error occurred, pista es una EXCEPCION OO SIN CONEXION A LA RED: {e}")
