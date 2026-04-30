import datetime
import time
from decimal import Decimal
from accesoAPI import inicializar_cliente
import csv
import os

# [MEJORA] Imports de los módulos nuevos: persistencia, riesgo y métricas.
from state_store import StateStore
from risk_manager import RiskManager
from metrics import calcular_y_registrar_metricas

# Solicitar meta equity al usuario y validar entrada
try:
    meta_equity = Decimal(input("Ingresa la meta de equity a alcanzar en USDT, NOTA IMPORTANTE: colocar 0 o un numero negativo hara que se ejecute venta de todos los activos a mercado por USDT similar a redButton: "))
    print(f"Meta de equity configurada en: {meta_equity} USDT")
except Exception:
    print("Error: Debes ingresar un número válido. Por favor, reinicia el script.")
    exit()

buscandoMeta = True  # Booleano para controlar el ciclo de búsqueda de la meta

# IMPORTANTE definir correctamente el punto de referencia cronológico de la última compra a mercado no eliminar la siguiente linea comentada
# horaFechaLocalReferencia = datetime.datetime.now()
horaFechaLocalReferencia = datetime.datetime(2025, 3, 22, 10, 45, 57, 183693)

# Parámetros básicos
tiempoEntreEjecucion = 600  # Tiempo de espera tras finalizar un ciclo completo (en segundos)
tiempoEntreCompraPotencial = 3  # Tiempo de espera entre cada símbolo revisado (en segundos)
quoteOrderQtyModulo = Decimal("8")  # Cantidad base de volumen de compra a mercado usualmente en USDT
factor_multiplicacion_porcentual = Decimal("0.99")  # Factor de multiplicación porcentual para decidir compras en formato 0.998

# [MEJORA] Variables nuevas para persistencia, riesgo y métricas.
# BOT_NAME identifica este bot en la DB compartida (clave de partición lógica).
BOT_NAME = "thusnelda"
# Ruta del SQLite local. Se crea si no existe.
DB_PATH = "./thusnelda_state.db"
# Activo de referencia para calcular equity total en USDT.
EQUITY_BASE_ASSET = "USDT"
# Drawdown máximo tolerado (decimal). 0.25 = 25% bajo el peak histórico.
# Si se supera, Thusnelda detiene nuevas compras (pero sigue evaluando la
# meta de equity y el ciclo de venta total).
MAX_DRAWDOWN_PCT = Decimal("0.25")
# Stop-loss por símbolo: si el precio actual del símbolo cae bajo el promedio
# de sus compras × (1 - STOP_LOSS_PCT), Thusnelda vende esa posición a mercado.
# None desactiva esta protección.
STOP_LOSS_PCT = Decimal("0.20")
# Cada cuántos ciclos completos (no segundos) calcular y persistir métricas.
METRICS_INTERVAL_CYCLES = 3

# Informar los parámetros configurados
print("# PARAMETROS BASICOS")
print(f"horaFechaLocalReferenciaInicial = {horaFechaLocalReferencia}")
print(f"tiempoEntreEjecucion = {tiempoEntreEjecucion}")
print(f"tiempoEntreCompraPotencial = {tiempoEntreCompraPotencial}")
print(f"quoteOrderQtyModulo = {quoteOrderQtyModulo}")
print(f"factor_multiplicacion_porcentual = {factor_multiplicacion_porcentual}")
# [MEJORA] Mostrar también los nuevos parámetros de riesgo/métricas.
print(f"MAX_DRAWDOWN_PCT = {MAX_DRAWDOWN_PCT}")
print(f"STOP_LOSS_PCT (por simbolo) = {STOP_LOSS_PCT}")
print(f"DB_PATH = {DB_PATH}")

# Leer símbolos desde un archivo externo con validación
def leer_simbolos(archivo):
    if not os.path.exists(archivo):
        print(f"Error: El archivo {archivo} no existe.")
        exit()

    with open(archivo, 'r') as f:
        simbolos = [line.strip() for line in f if line.strip()]

    if not simbolos:
        print(f"Error: El archivo {archivo} está vacío. Por favor, verifica su contenido.")
        exit()

    return simbolos

# [MEJORA] Helper que calcula el equity total en USDT (USDT libre + activos
# valuados a precio de mercado). Reutilizado para drawdown y para la meta.
def calcular_equity_y_capital(client_, asset_prices, base=EQUITY_BASE_ASSET):
    info = client_.get_account()
    capital_libre = Decimal("0")
    equity = Decimal("0")
    for bal in info["balances"]:
        total = Decimal(bal["free"]) + Decimal(bal["locked"])
        if total <= 0:
            continue
        if bal["asset"] == base:
            equity += total
            capital_libre = Decimal(bal["free"])
            continue
        sym_direct = bal["asset"] + base
        if sym_direct in asset_prices:
            equity += total * asset_prices[sym_direct]
    return equity, capital_libre

# Lógica de compra para un símbolo
# [MEJORA] La función ahora recibe `store`, `risk` y `trading_bloqueado` para
# poder bloquear compras por drawdown global y aplicar stop-loss por símbolo
# sin alterar la lógica original.
def procesar_simbolo(client, symbol, store=None, risk=None, trading_bloqueado=False):
    print(f"Revisando símbolo: {symbol}")
    try:
        compras_mercado = client.get_my_trades(symbol=symbol, fromId=0)
        compras_recientes = [
            c for c in compras_mercado
            if datetime.datetime.fromtimestamp(c["time"] / 1000) > horaFechaLocalReferencia
               and c["isBuyer"]
        ]

        # Si no existen compras recientes, realizar una compra inicial como referencia de precio
        if not compras_recientes:
            # [MEJORA] No abrir compra inicial si el drawdown global está activo.
            if trading_bloqueado:
                print(f"[RIESGO] Trading bloqueado por drawdown — se omite compra inicial de {symbol}.")
                return
            print(f"No existen compras recientes para {symbol}. Realizando compra inicial como referencia...")
            try:
                orden_compra_inicial = client.create_order(
                    symbol=symbol,
                    side=client.SIDE_BUY,
                    type=client.ORDER_TYPE_MARKET,
                    quoteOrderQty=quoteOrderQtyModulo,
                )
                print(f"COMPRA inicial realizada para {symbol}. Detalles: {orden_compra_inicial}")
                # [MEJORA] Persistir el trade.
                if store is not None and orden_compra_inicial.get("fills"):
                    qty = Decimal(orden_compra_inicial["executedQty"])
                    px = Decimal(orden_compra_inicial["fills"][0]["price"])
                    store.record_trade(symbol, "BUY", "MARKET", qty, px, ref=str(orden_compra_inicial.get("orderId", "")))
            except Exception as e:
                print(f"Error al realizar la compra inicial para {symbol}: {e}")
            return  # Salir de la función después de la compra inicial

        # Calcular el precio promedio de las últimas 30 compras a mercado (o las existentes)
        precios_compras = [Decimal(c["price"]) for c in compras_recientes][-30:]  # Tomar máximo 30 precios
        precio_promedio = sum(precios_compras) / len(precios_compras)
        print(f"Precio promedio de las últimas compras de {symbol}: {precio_promedio}")

        # Obtener el precio actual del símbolo
        precio_actual = Decimal(client.get_symbol_ticker(symbol=symbol)["price"])
        print(f"Precio actual de {symbol}: {precio_actual}")

        # [MEJORA] Stop-loss por símbolo: si el precio actual cae bajo el
        # promedio × (1 - STOP_LOSS_PCT), liquidamos el balance libre del
        # asset para cortar la pérdida acumulada en este símbolo.
        if risk is not None and risk.should_stop_loss(precio_promedio, precio_actual):
            try:
                base_asset = symbol.replace("USDT", "")
                bal = client.get_asset_balance(asset=base_asset)
                free_balance = Decimal(bal["free"]) if bal else Decimal("0")
                if free_balance > 0:
                    print(
                        f"[STOP-LOSS] {symbol} promedio={precio_promedio} actual={precio_actual} "
                        f"→ liquidando {free_balance} {base_asset} a mercado"
                    )
                    orden_liq = client.order_market_sell(symbol=symbol, quantity=free_balance)
                    if store is not None:
                        precio_liq = (
                            Decimal(orden_liq["fills"][0]["price"])
                            if orden_liq.get("fills")
                            else precio_actual
                        )
                        store.record_trade(symbol, "SELL", "MARKET", free_balance, precio_liq, ref="stop_loss")
                else:
                    print(f"[STOP-LOSS] {symbol} sin balance libre — no se liquida")
                return  # Tras stop-loss no compramos en este ciclo
            except Exception as e:
                print(f"Error al ejecutar stop-loss para {symbol}: {e}")

        # Comparar el precio actual con el precio promedio ajustado por el factor
        precio_limite = precio_promedio * factor_multiplicacion_porcentual
        print(f"Precio límite calculado para {symbol}: {precio_limite}")

        if precio_actual < precio_limite:
            # [MEJORA] No abrir compras si el drawdown global supera el umbral.
            if trading_bloqueado:
                print(f"[RIESGO] Trading bloqueado por drawdown — se omite compra de {symbol}.")
                return
            print(
                f"Precio actual de {symbol}({precio_actual}) está por DEBAJO del límite calculado ({precio_limite}), realizando compra a mercado..."
            )
            try:
                orden_compra = client.create_order(
                    symbol=symbol,
                    side=client.SIDE_BUY,
                    type=client.ORDER_TYPE_MARKET,
                    quoteOrderQty=quoteOrderQtyModulo,
                )
                print(f"COMPRA exitosa de {symbol}. Detalles: {orden_compra}")
                # [MEJORA] Persistir el trade.
                if store is not None and orden_compra.get("fills"):
                    qty = Decimal(orden_compra["executedQty"])
                    px = Decimal(orden_compra["fills"][0]["price"])
                    store.record_trade(symbol, "BUY", "MARKET", qty, px, ref=str(orden_compra.get("orderId", "")))
            except Exception as e:
                print(f"Error al realizar la compra para {symbol}: {e}")
        else:
            print(
                f"Precio actual de {symbol}({precio_actual}) no cumple las condiciones para realizar compra. ESPERANDO acción del precio..."
            )
    except Exception as e:
        print(f"Error al procesar el símbolo {symbol}: {e}")

# Función para vender todos los activos a mercado por USDT
# [MEJORA] Acepta `store` opcional para persistir las ventas finales.
def vender_todos_a_usdt(client, store=None):
    print("Iniciando venta de todos los activos a USDT...")
    try:
        # Obtener balances de la cuenta
        account_info = client.get_account()
        for asset in account_info['balances']:
            free_balance = Decimal(asset['free'])
            if free_balance > 0 and asset['asset'] != "USDT":
                symbol = asset['asset'] + "USDT"
                try:
                    orden_venta = client.order_market_sell(
                        symbol=symbol,
                        quantity=free_balance
                    )
                    print(f"VENTA exitosa de {asset['asset']} al mercado. Detalles: {orden_venta}")
                    # [MEJORA] Persistir el trade.
                    if store is not None and orden_venta.get("fills"):
                        px = Decimal(orden_venta["fills"][0]["price"])
                        store.record_trade(symbol, "SELL", "MARKET", free_balance, px, ref="meta_equity")
                except Exception as e:
                    print(f"Error al vender {asset['asset']}: {e}")
        print("Proceso de venta completado. Todos los activos han sido convertidos a USDT.")
    except Exception as e:
        print(f"Error durante la venta de activos: {e}")

# Inicio del script
if __name__ == "__main__":
    print(f"HORA DE INICIO DE LA CORRIDA--- Thusnelda1.1 --- {horaFechaLocalReferencia}")
    client = inicializar_cliente()

    # Leer la lista de símbolos desde el archivo
    archivo_simbolos = "simbolos.txt"
    simbolos = leer_simbolos(archivo_simbolos)
    print(f"Símbolos cargados desde {archivo_simbolos}: {simbolos}")

    # Configuración del archivo de registro
    registro_archivo = "registro_equity.csv"
    archivo_creado = False  # Bandera para verificar si se creó el archivo

    if not os.path.exists(registro_archivo):
        # Si el archivo no existe, crear uno nuevo con encabezados
        with open(registro_archivo, 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Fecha y hora", "Capital de trabajo (USDT)", "Equity Total excluyendo USDT", "Evento"])
        archivo_creado = True
        print("Archivo de registro creado por primera vez.")

    # [MEJORA] Inicialización de StateStore y RiskManager. El RiskManager carga
    # el peak_equity histórico desde la DB para sobrevivir a reinicios del bot.
    store = StateStore(DB_PATH, BOT_NAME)
    risk = RiskManager(
        max_drawdown_pct=MAX_DRAWDOWN_PCT,
        stop_loss_pct=STOP_LOSS_PCT,
        state_store=store,
    )
    ciclo_idx = 0

    while buscandoMeta:  # Ejecutar mientras se busca la meta
        # [MEJORA] Calcular precios + equity al inicio del ciclo para conocer
        # el estado de drawdown ANTES de iterar símbolos. Reutilizamos los
        # tickers en el cálculo posterior de equity vs meta.
        try:
            ticker_prices_pre = client.get_all_tickers()
            asset_prices_pre = {t["symbol"]: Decimal(t["price"]) for t in ticker_prices_pre}
            equity_actual, capital_libre = calcular_equity_y_capital(client, asset_prices_pre)
            risk.register_equity(equity_actual)
            store.record_equity(equity_actual, capital_libre)
            drawdown_actual = risk.current_drawdown(equity_actual)
            trading_bloqueado = risk.is_trading_blocked(equity_actual)
            print(
                f"[RIESGO] equity={equity_actual} peak={risk.peak_equity} "
                f"drawdown={drawdown_actual} bloqueado={trading_bloqueado}"
            )
        except Exception as e:
            print(f"[RIESGO] Error al evaluar drawdown global: {e}")
            trading_bloqueado = False

        for symbol in simbolos:
            procesar_simbolo(client, symbol, store=store, risk=risk, trading_bloqueado=trading_bloqueado)
            print(f"ESPERANDO {tiempoEntreCompraPotencial} segundos antes de pasar al siguiente símbolo...")
            time.sleep(tiempoEntreCompraPotencial)

        try:
            # Saldo actual de la cuenta en spot del activo base
            saldo_usdt = Decimal(client.get_asset_balance(asset="USDT")["free"])
            print(f"Capital de trabajo disponible en USDT: {saldo_usdt}")

            # Cálculo del equity total excluyendo USDT
            account_info = client.get_account()
            ticker_prices = client.get_all_tickers()
            asset_prices = {ticker['symbol']: Decimal(ticker['price']) for ticker in ticker_prices}

            equityGeneralActualizado = Decimal(0)

            for asset in account_info['balances']:
                total_balance = Decimal(asset['free']) + Decimal(asset['locked'])
                if total_balance > 0 and asset['asset'] != "USDT":
                    symbol = asset['asset'] + "USDT"
                    if symbol in asset_prices:
                        equity_in_usdt = total_balance * asset_prices[symbol]
                        equityGeneralActualizado += equity_in_usdt

            print(f"Equity actual de la cuenta (sin el USDT de Capital de Trabajo): {equityGeneralActualizado} USDT")

            # Comparar equity con la meta
            if (equityGeneralActualizado + saldo_usdt) >= meta_equity:
                print(f"¡Meta alcanzada! Hora: {datetime.datetime.now()} | Equity: {equityGeneralActualizado} USDT")
                vender_todos_a_usdt(client, store=store)
                buscandoMeta = False  # Detener el ciclo principal
                print("El ciclo principal se ha detenido. Todas las operaciones han finalizado.")

            else: print(f"Esperando {tiempoEntreEjecucion} segundos para proximo ciclo")

        except Exception as e:
            print(f"Error al calcular el equity: {e}")

        # [MEJORA] Cálculo periódico de métricas y persistencia en metrics_log.
        ciclo_idx += 1
        if ciclo_idx % METRICS_INTERVAL_CYCLES == 0:
            try:
                m = calcular_y_registrar_metricas(store)
                print(
                    f"[METRICAS] trades={m['total_trades']} pnl={m['total_pnl']} "
                    f"win_rate={m['win_rate']} sharpe={m['sharpe']} max_dd={m['max_drawdown']}"
                )
            except Exception as e:
                print(f"[METRICAS] Error calculando: {e}")

        time.sleep(tiempoEntreEjecucion)
