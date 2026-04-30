from accesoAPI import inicializar_cliente
client = inicializar_cliente()
from decimal import Decimal
import time


# Función para realizar una operación de compra market
def compraMarket(symbol, volumenCompra, puntosBeneficio):
	precioUltimaCompraMarket = None
	volumenUltimaCompraMarket = None
	costoTotalUltimaCompraMarket = None

	try:
		# Paso 1: Compra a mercado
		compra = client.create_order(
			symbol=symbol,
			side=client.SIDE_BUY,
			type=client.ORDER_TYPE_MARKET,
			quantity=volumenCompra
		)
		print("Compra a Mercado realizada:", compra)

		# Guardar el precio y volumen de la compra a mercado
		precioUltimaCompraMarket = Decimal(compra['fills'][0]['price'])
		volumenUltimaCompraMarket = Decimal(compra['fills'][0]['qty'])
		costoTotalUltimaCompraMarket = precioUltimaCompraMarket * volumenUltimaCompraMarket

		# Espera 5 segundos
		time.sleep(5)

		# Paso 2: Obtén el último comercio (buy market)
		trades = client.get_my_trades(symbol=symbol)
		last_buy_trade = next((trade for trade in reversed(trades) if trade['isBuyer']), None)

		if last_buy_trade:
			# Guardar el precio y volumen de la última compra a mercado
			precioUltimaCompraMarket = Decimal(last_buy_trade['price'])
			volumenUltimaCompraMarket = Decimal(last_buy_trade['qty'])
			costoTotalUltimaCompraMarket = precioUltimaCompraMarket * volumenUltimaCompraMarket

		return precioUltimaCompraMarket, volumenUltimaCompraMarket, costoTotalUltimaCompraMarket

	except Exception as e:
		print(f"Error al ejecutar la operación: {e}")
