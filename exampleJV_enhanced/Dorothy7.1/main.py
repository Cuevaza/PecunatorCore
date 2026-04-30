
import datetime
import time
from decimal import Decimal
from accesoAPI import inicializar_cliente

# [MEJORA] Imports de los módulos nuevos: persistencia, riesgo y métricas.
from state_store import StateStore
from risk_manager import RiskManager
from metrics import calcular_y_registrar_metricas

# NOTA: PRICE_FILTER ERROR, ajusta la presicion de las variables Decimal en donde se asigna el precio de las ordenes SELL LIMIT, de manera que satisfaga los filtros que se pueden consultar en "detalles del simbolo", o en "symbol info"
# NOTA: NOTIONAL ERROR, comunmente ocurre debido a que el modulo especificado es demaciado pequeño para satisfacer el nocional, aumentalo hasta que lo satisfaga


# Seteteos configurados
symbol = "XRPUSDT" # Activo trabajado por el Bot........................................
horaFechaLocalInicial = datetime.datetime.now()
tiempoEntreEjecucion = 450 # Segundos
quoteOrderQtyModulo = Decimal("8") # Comunmente USDT
factorPorcentualBeneficio = Decimal("0.05")  # Ejemplo 0.05 para ganar un 5% por comercio
factorPorcentualMargenBajada = Decimal("0.004")  # Ejemplo 0.004 para comprar a mercado un 0.4% mas abajo de la ultima compra a mercado encontrada, esto previene que se concentren muchas compras a mercado al rededor de un rango estrecho de la accione del precio y si se distribuyan las compras mas uniformemente en las caidas prolongadas del precio, cada symbolo puede tener un % de ajuste unico segun su volatilidad y espectro habitual de fluctuacion del precio

# [MEJORA] Variables nuevas para persistencia, riesgo y métricas.
# BOT_NAME identifica este bot en la DB compartida (clave de partición lógica).
BOT_NAME = "dorothy"
# Ruta del SQLite local. Se crea si no existe.
DB_PATH = "./dorothy_state.db"
# Activo de referencia para calcular equity total en USDT.
EQUITY_BASE_ASSET = "USDT"
# Drawdown máximo tolerado (decimal). 0.20 = 20% bajo el peak histórico.
# Si se supera, el bot deja de abrir nuevas compras hasta recuperación.
MAX_DRAWDOWN_PCT = Decimal("0.20")
# Stop-loss por posición. Si el precio cae bajo precio_compra * (1 - STOP_LOSS_PCT)
# se liquida esa posición a mercado. None desactiva esta protección.
STOP_LOSS_PCT = Decimal("0.10")
# Cada cuántos ciclos (no segundos) calcular y persistir métricas (Sharpe, etc.).
METRICS_INTERVAL_CYCLES = 5

# Detalles de Inicio para control y ajuste
print(f"HORA DE INICIO DE LA CORRIDA: {horaFechaLocalInicial}")
print(f"SETEO BASE Dorothy7.1 ----------")
print(f"SIMBOLO: {symbol}")
print(f"TIEMPO ENTRE ITERACION DEL BOT: {tiempoEntreEjecucion}")
print(f"CANTIDAD POR COMPRA: {quoteOrderQtyModulo}")
print(f"PORCENTAJE BENEFICIO: {factorPorcentualBeneficio}")
print(f"PORCENTAJE MARGEN BAJADA: {factorPorcentualMargenBajada}")
# [MEJORA] Mostrar también los nuevos parámetros de riesgo/métricas.
print(f"MAX DRAWDOWN PCT: {MAX_DRAWDOWN_PCT}")
print(f"STOP LOSS PCT (por posicion): {STOP_LOSS_PCT}")
print(f"DB DE ESTADO: {DB_PATH}")
print("DETALLES DEL SIMBOLO:")

client = inicializar_cliente()
symbolInfo = client.get_symbol_info(symbol)
print(symbolInfo)

# [MEJORA] Inicialización de StateStore y RiskManager. El RiskManager carga
# el peak_equity histórico desde la DB para sobrevivir a reinicios del bot.
store = StateStore(DB_PATH, BOT_NAME)
risk = RiskManager(
    max_drawdown_pct=MAX_DRAWDOWN_PCT,
    stop_loss_pct=STOP_LOSS_PCT,
    state_store=store,
)
# Contador de ciclos para disparar el cálculo periódico de métricas.
ciclo_idx = 0


# [MEJORA] Helper que calcula el equity total en USDT (USDT libre + valor de
# todos los assets convertidos a USDT vía tickers). Se usa para el peak y el
# drawdown global. No interfiere con la lógica original del bot.
def calcular_equity_usdt(client_, base=EQUITY_BASE_ASSET):
    info = client_.get_account()
    tickers = client_.get_all_tickers()
    precios = {t["symbol"]: Decimal(t["price"]) for t in tickers}
    equity = Decimal("0")
    capital_libre = Decimal("0")
    for bal in info["balances"]:
        total = Decimal(bal["free"]) + Decimal(bal["locked"])
        if total <= 0:
            continue
        if bal["asset"] == base:
            equity += total
            capital_libre = Decimal(bal["free"])
            continue
        sym_direct = bal["asset"] + base
        if sym_direct in precios:
            equity += total * precios[sym_direct]
    return equity, capital_libre


# Ciclo principal del bot
while True:
    try:
        if __name__ == "__main__":
            client = inicializar_cliente()

            if client:
                # [MEJORA] Tomar snapshot de equity, actualizar peak y verificar
                # si el drawdown global bloquea la apertura de nuevas posiciones.
                equity_actual, capital_libre = calcular_equity_usdt(client)
                risk.register_equity(equity_actual)
                store.record_equity(equity_actual, capital_libre)
                drawdown_actual = risk.current_drawdown(equity_actual)
                trading_bloqueado = risk.is_trading_blocked(equity_actual)
                print(
                    f"[RIESGO] equity={equity_actual} peak={risk.peak_equity} "
                    f"drawdown={drawdown_actual} bloqueado={trading_bloqueado}"
                )

                ordenes_activas = client.get_open_orders(symbol=symbol)
                orden_sell_limit = None
                precio_activacion_mas_bajo = None

                for orden in ordenes_activas:
                    if orden['side'] == 'SELL' and orden['type'] == 'LIMIT':
                        if precio_activacion_mas_bajo is None or Decimal(orden['price']) < precio_activacion_mas_bajo:
                            orden_sell_limit = orden
                            precio_activacion_mas_bajo = Decimal(orden['price'])

                # [MEJORA] Stop-loss por posición: la SELL LIMIT más baja implica
                # un precio de compra ≈ precio_SL / (1 + factorPorcentualBeneficio).
                # Si el precio actual cae bajo ese precio_compra × (1 - STOP_LOSS_PCT),
                # cancelamos la SELL LIMIT y liquidamos a mercado para cortar la pérdida.
                if orden_sell_limit:
                    precio_mercado_chk = Decimal(client.get_symbol_ticker(symbol=symbol)['price'])
                    precio_compra_implicito = precio_activacion_mas_bajo / (Decimal("1") + factorPorcentualBeneficio)
                    if risk.should_stop_loss(precio_compra_implicito, precio_mercado_chk):
                        try:
                            print(
                                f"[STOP-LOSS] precio_compra≈{precio_compra_implicito} "
                                f"actual={precio_mercado_chk} → liquidando posición"
                            )
                            client.cancel_order(symbol=symbol, orderId=orden_sell_limit['orderId'])
                            qty_liquidar = Decimal(orden_sell_limit['origQty'])
                            orden_liq = client.create_order(
                                symbol=symbol,
                                side=client.SIDE_SELL,
                                type=client.ORDER_TYPE_MARKET,
                                quantity=f"{qty_liquidar:.8f}",
                            )
                            precio_liq = Decimal(orden_liq['fills'][0]['price']) if orden_liq.get('fills') else precio_mercado_chk
                            store.record_trade(symbol, "SELL", "MARKET", qty_liquidar, precio_liq, ref="stop_loss")
                            # Forzamos relectura tras liquidar.
                            orden_sell_limit = None
                            precio_activacion_mas_bajo = None
                        except Exception as e:
                            print(f"Error al ejecutar stop-loss: {e}")

                if orden_sell_limit:
                    precio_activacion = Decimal(orden_sell_limit['price'])
                    print(f"Orden SELL LIMIT ACTIVA MAS BAJA ENCONTRADA en {symbol}. Precio de activación: {precio_activacion}")

                    # Obtener precio de mercado actual
                    precio_mercado = Decimal(client.get_symbol_ticker(symbol=symbol)['price'])

                    # Calcular nivel de entrada aceptable
                    nivelEntradaAceptable = precio_activacion * (1 - (factorPorcentualBeneficio + factorPorcentualMargenBajada))
                    print(f"Esperando nivel de entrada aceptable: {nivelEntradaAceptable} Precio Actual de {symbol}: {precio_mercado}")

                    if precio_mercado <= nivelEntradaAceptable:
                        # [MEJORA] No abrir nuevas compras si el drawdown global supera el umbral.
                        if trading_bloqueado:
                            print("[RIESGO] Trading bloqueado por drawdown — se omite compra.")
                        else:
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

                                # [MEJORA] Persistencia: registrar la compra a mercado en la DB.
                                store.record_trade(symbol, "BUY", "MARKET", cantidad_compra, precio_compra, ref=str(orden_compra.get('orderId', '')))

                                orden_venta = client.create_order(
                                    symbol=symbol,
                                    side=client.SIDE_SELL,
                                    type=client.ORDER_TYPE_LIMIT,
                                    timeInForce=client.TIME_IN_FORCE_GTC,
                                    quantity=f"{cantidad_compra:.8f}",
                                    price=f"{precio_venta:.4f}" #...........................
                                )

                                print(f"Orden SELL LIMIT colocada para {symbol}. Detalles: {orden_venta}")
                                # Persistimos también la SELL LIMIT colocada (estado, no fill).
                                store.set_state(
                                    f"last_sell_limit_{symbol}",
                                    f"{cantidad_compra}@{precio_venta}",
                                )

                            except Exception as e:
                                print(f"Error al realizar la compra a mercado o colocar la orden SELL LIMIT 01: {e}")

                else:
                    # [MEJORA] Igual que arriba: respetar el bloqueo por drawdown
                    # antes de abrir la primera escalera.
                    if trading_bloqueado:
                        print("[RIESGO] Trading bloqueado por drawdown — se omite compra inicial.")
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

                            # [MEJORA] Persistencia: registrar la compra inicial.
                            store.record_trade(symbol, "BUY", "MARKET", cantidad_compra, precio_compra, ref=str(orden_compra.get('orderId', '')))

                            orden_venta = client.create_order(
                                symbol=symbol,
                                side=client.SIDE_SELL,
                                type=client.ORDER_TYPE_LIMIT,
                                timeInForce=client.TIME_IN_FORCE_GTC,
                                quantity=f"{cantidad_compra:.8f}",
                                price=f"{precio_venta:.4f}" #.............................
                            )

                            print(f"Orden SELL LIMIT colocada para {symbol}. Detalles: {orden_venta}")
                            store.set_state(
                                f"last_sell_limit_{symbol}",
                                f"{cantidad_compra}@{precio_venta}",
                            )

                        except Exception as e:
                            print(f"Error al realizar la compra a mercado o colocar la orden SELL LIMIT 02: {e}")

            # [MEJORA] Cada METRICS_INTERVAL_CYCLES ciclos calcular y persistir
            # las métricas (Sharpe, win rate, max drawdown). Imprimir resumen.
            ciclo_idx += 1
            if ciclo_idx % METRICS_INTERVAL_CYCLES == 0:
                m = calcular_y_registrar_metricas(store)
                print(
                    f"[METRICAS] trades={m['total_trades']} pnl={m['total_pnl']} "
                    f"win_rate={m['win_rate']} sharpe={m['sharpe']} max_dd={m['max_drawdown']}"
                )

            print(f"Esperando accion del precio a las: {datetime.datetime.now()} --------------------------")
            time.sleep(tiempoEntreEjecucion)


    except Exception as e:
        print(f"Misterious error occurred, pista es una EXCEPCION OO SIN CONEXION A LA RED: {e}")
