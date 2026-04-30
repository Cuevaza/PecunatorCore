from  accesoAPI import inicializar_cliente
client = inicializar_cliente()
from datetime import datetime
from decimal import Decimal

def obtener_ultima_compra(symbol):
	# Obtener las operaciones del símbolo especificado
	trades = client.get_my_trades(symbol=symbol)

	# Filtrar las compras a mercado
	compras = [trade for trade in trades if trade['isBuyer']]

	if not compras:
		return None

	# Obtener la última compra
	ultima_compra = compras[-1]

	# Extraer la información relevante
	fecha_operacion = datetime.fromtimestamp(ultima_compra['time'] / 1000)
	precio_compra = Decimal(ultima_compra['price'])
	volumen_compra = Decimal(ultima_compra['qty'])

	return {
		'fecha_operacion': fecha_operacion,
		'precio_compra': precio_compra,
		'volumen_compra': volumen_compra
	}