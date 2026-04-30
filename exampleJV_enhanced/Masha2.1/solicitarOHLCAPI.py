from accesoAPI import inicializar_cliente
client = inicializar_cliente()
from decimal import Decimal
from datetime import datetime
import numpy as np


# Función para obtener precios históricos
def obtener_datos_ohlc(symbol, num_periodos, timeframe, num_periodos_mm):
    binance_client = inicializar_cliente()

    # Define el tiempo de inicio en función del timeframe
    if "m" in timeframe:
        time_unit = "minutes"
    elif "h" in timeframe:
        time_unit = "hours"
    elif "d" in timeframe:
        time_unit = "days"
    elif "w" in timeframe:
        time_unit = "weeks"
    elif "M" in timeframe:
        time_unit = "months"
    else:
        raise ValueError("Timeframe no válido")

    # Obtiene los datos históricos OHLC
    start_time = f"{num_periodos} {time_unit} ago UTC"
    klines = binance_client.get_historical_klines(symbol, timeframe, start_time)

    # Obtiene información del símbolo
    exchange_info = binance_client.get_exchange_info()
    symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == symbol), None)
    if not symbol_info:
        print(f"El símbolo {symbol} no se encontró en la información de Binance.")
        return

    # Extrae los valores OHLC y conviértelos a Decimal con una precisión de 12 decimales
    lista_info_simbolo = []
    for kline in klines:
        timestamp, open_price, high_price, low_price, close_price, *_ = kline
        ohlc = {
            "timestamp": int(timestamp) // 1000,
            "open": str(open_price),
            "high": str(high_price),
            "low": str(low_price),
            "close": str(close_price),
            "symbol": symbol,
            "baseAsset": symbol_info['baseAsset'],
            "quotedAsset": symbol_info['quoteAsset']
        }
        lista_info_simbolo.append(ohlc)

    # Calcular la media móvil como (High + Low) / 2
    valores = [(Decimal(info["high"]) + Decimal(info["low"])) / 2 for info in lista_info_simbolo]
    mean_valores = np.mean(valores[-num_periodos_mm:])
    precioMM = Decimal(str(mean_valores))

    # Obtener el valor Low de la última barra
    ultimo_low = Decimal(lista_info_simbolo[-1]["low"])
    closeActual = Decimal(lista_info_simbolo[-1]["close"])


    # Imprime la información con timestamp en formato legible
    print(f"***CICLO INICIADO solicitud OHLC*** símbolo: {symbol}---timeframe: {timeframe}, períodos: {num_periodos}")
    for info in lista_info_simbolo:
        fecha_hora = datetime.utcfromtimestamp(info['timestamp']).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{fecha_hora}  | oOo: {info['open']} nHn: {info['high']} lLl: {info['low']} cCc: {info['close']} | Base Asset: {info['baseAsset']} | Quoted Asset: {info['quotedAsset']}")

    return precioMM, ultimo_low , closeActual
