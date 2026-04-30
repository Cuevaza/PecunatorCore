from accesoAPI import inicializar_cliente
from decimal import Decimal
from solicitarOHLCAPI import obtener_datos_ohlc
from obtenerPosicionOrdenSellLimit import posicionOrdenLimit
from compraMarket import compraMarket
from solicitaBalancesAPI import obtener_balances
from actualizarOrdenSellLimitDCA import actualizarOrdenSellLimit
import time
import traceback
import csv
from datetime import datetime

# [MEJORA] Imports de los módulos nuevos: persistencia, riesgo y métricas.
from state_store import StateStore
from risk_manager import RiskManager
from metrics import calcular_y_registrar_metricas

# Inicializa el cliente de la API de Binance
client = inicializar_cliente()

# Define el símbolo de trading y los activos base y de cotización
symbol = "BTCUSDT"
baseAsset = "BTC"
quoteAsset = "USDT"

# Define el balance mínimo libre requerido para operar
balanceQuoteAssetLibreMinOperar = Decimal(6.0)

# Precisión decimal para los cálculos
prec = 8

# Define el volumen de compra y el factor de beneficio porcentual
volumenCompra = Decimal(0.001)
puntosFactorBeneficioPorcentual = Decimal(0.01)

# Configuración de los timeframes y márgenes para las señales de compra
timeFrameW = "1w"
numPeriodosTimeframeW = 2
numPeriodosMMW = 2
puntosMargenLowW = Decimal(0.03)

timeFrameh = "1h"
numPeriodosTimeFrameh = 2
numPeriodosMMh = 2
puntosMargenLowh = Decimal(0.003)

# Tiempo de espera entre ejecuciones del bucle principal (en segundos)
tiempoEntreEjecucion = 300

# Nombre del archivo CSV
csv_filename = 'trading_bot_stats.csv'

# [MEJORA] Variables nuevas para persistencia, riesgo y métricas.
# BOT_NAME identifica este bot en la DB compartida (clave de partición lógica).
BOT_NAME = "masha"
# Ruta del SQLite local. Se crea si no existe.
DB_PATH = "./masha_state.db"
# Activo de referencia para calcular equity total en USDT.
EQUITY_BASE_ASSET = "USDT"
# Drawdown máximo tolerado (decimal). 0.25 = 25% bajo el peak histórico.
# Si se supera, el bot deja de abrir nuevas compras hasta recuperación.
MAX_DRAWDOWN_PCT = Decimal("0.25")
# Stop-loss por posición: si el precio cae bajo DCA × (1 - STOP_LOSS_PCT),
# Masha cancela la SELL LIMIT del DCA y vende la posición a mercado.
# None desactiva esta protección.
STOP_LOSS_PCT = Decimal("0.15")
# Cada cuántos ciclos calcular y persistir métricas (Sharpe, etc.).
METRICS_INTERVAL_CYCLES = 5

# Escribe los encabezados del archivo CSV si no existe
with open(csv_filename, mode='w', newline='') as file:
    writer = csv.writer(file)
    writer.writerow([
        'Fecha y Hora', 'closeActualw', 'closeActualh', 'precioMMw', 'precioMMh',
        'ultimo_lowW', 'ultimo_lowh', 'balanceQuoteAssetLibre', 'precioUltimaCompraMarket',
        'volumenUltimaCompraMarket', 'costoTotalUltimaCompraMarket', 'nuevoPrecioDCAPosicion',
        'precioDCAConBeneficio'
    ])

#Declarando variables solo para la toma estadistica se pueden eliminar...
precioUltimaCompraMarket = None
nuevoPrecioDCAPosicion = None
precioDCAConBeneficio = None

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


# [MEJORA] Helper para calcular equity total en USDT (USDT libre + activos
# valuados a precio de mercado). Base de la curva de equity y del drawdown.
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


# Bucle principal que se ejecuta continuamente
while True:
    if __name__ == '__main__':
        try:
            # [MEJORA] Snapshot de equity, actualización de peak y chequeo de drawdown.
            equity_actual, capital_libre = calcular_equity_usdt(client)
            risk.register_equity(equity_actual)
            store.record_equity(equity_actual, capital_libre)
            drawdown_actual = risk.current_drawdown(equity_actual)
            trading_bloqueado = risk.is_trading_blocked(equity_actual)
            print(
                f"[RIESGO] equity={equity_actual} peak={risk.peak_equity} "
                f"drawdown={drawdown_actual} bloqueado={trading_bloqueado}"
            )

            # Obtiene los datos de la orden limit que representa la posición actual
            DCAPrecioPosicion, DCAVolumenPosicion, DCAcostoTotalPosicion = posicionOrdenLimit(symbol)

            # [MEJORA] Stop-loss sobre el DCA: si hay posición abierta y el precio
            # actual cae bajo DCA × (1 - STOP_LOSS_PCT), cancelamos la SELL LIMIT
            # y vendemos la posición a mercado. Corta la pérdida en bears prolongados.
            if DCAPrecioPosicion is not None and DCAVolumenPosicion is not None and DCAVolumenPosicion > 0:
                precio_actual_chk = Decimal(client.get_symbol_ticker(symbol=symbol)["price"])
                # El DCA persistido en la SELL LIMIT incluye el +1% de beneficio.
                # Reconstruimos el DCA "limpio" para la comparación de stop-loss.
                dca_limpio = DCAPrecioPosicion / (Decimal("1") + Decimal(puntosFactorBeneficioPorcentual))
                if risk.should_stop_loss(dca_limpio, precio_actual_chk):
                    try:
                        print(
                            f"[STOP-LOSS] DCA={dca_limpio} actual={precio_actual_chk} "
                            f"→ liquidando posición a mercado"
                        )
                        # Cancelar la SELL LIMIT abierta del DCA antes de vender.
                        open_orders = client.get_open_orders(symbol=symbol)
                        for o in open_orders:
                            if o["side"] == "SELL" and o["type"] == "LIMIT":
                                client.cancel_order(symbol=symbol, orderId=o["orderId"])
                        orden_liq = client.order_market_sell(
                            symbol=symbol,
                            quantity=f"{DCAVolumenPosicion:.{prec}f}",
                        )
                        precio_liq = (
                            Decimal(orden_liq["fills"][0]["price"])
                            if orden_liq.get("fills")
                            else precio_actual_chk
                        )
                        store.record_trade(symbol, "SELL", "MARKET", DCAVolumenPosicion, precio_liq, ref="stop_loss")
                        # Reseteamos los valores DCA locales para que el ciclo no
                        # intente reactualizar una orden que ya no existe.
                        DCAPrecioPosicion = None
                        DCAVolumenPosicion = Decimal("0")
                        DCAcostoTotalPosicion = Decimal("0")
                    except Exception as e:
                        print(f"Error al ejecutar stop-loss DCA: {e}")

            # Obtiene la señal de compra del timeframe semanal (W)
            precioMMw, ultimo_lowW, closeActualw = obtener_datos_ohlc(symbol, numPeriodosTimeframeW, timeFrameW, numPeriodosMMW)

            # Obtiene la señal de compra del timeframe horario (H)
            precioMMh, ultimo_lowh, closeActualh = obtener_datos_ohlc(symbol, numPeriodosTimeFrameh, timeFrameh, numPeriodosMMh)

            # Obtiene los balances de la posición y la cuenta del símbolo
            base_free, base_locked, base_total, quote_free, quote_locked, quote_total = obtener_balances(client, symbol, baseAsset, quoteAsset)

            # Determina la señal de compra si se cumplen las condiciones
            if closeActualw < (ultimo_lowW + puntosMargenLowW) < precioMMw and closeActualh < (ultimo_lowh + puntosMargenLowh) < precioMMh:
                # [MEJORA] No abrir nuevas compras si el drawdown global supera el umbral.
                if trading_bloqueado:
                    print("[RIESGO] Trading bloqueado por drawdown — se omite compra.")
                # Ejecuta la compra a mercado si se cumplen las condiciones
                elif quote_free > balanceQuoteAssetLibreMinOperar and closeActualh < precioUltimaCompraMarket:
                    precioUltimaCompraMarket, volumenUltimaCompraMarket, costoTotalUltimaCompraMarket = compraMarket(symbol, volumenCompra, puntosFactorBeneficioPorcentual)

                    # [MEJORA] Registrar la compra a mercado en la DB.
                    if precioUltimaCompraMarket is not None and volumenUltimaCompraMarket is not None:
                        store.record_trade(symbol, "BUY", "MARKET", volumenUltimaCompraMarket, precioUltimaCompraMarket)

                    # Calcula el nuevo precio promedio ponderado (DCA) de la posición
                    sumaCostosTotales = DCAcostoTotalPosicion + costoTotalUltimaCompraMarket
                    sumaVolumenesTotales = DCAVolumenPosicion + volumenUltimaCompraMarket
                    nuevoPrecioDCAPosicion = sumaCostosTotales / sumaVolumenesTotales

                    # Calcula el precio de venta con beneficio
                    precioDCAConBeneficio = nuevoPrecioDCAPosicion * (Decimal(1) + Decimal(puntosFactorBeneficioPorcentual))

                    # Actualiza la orden de venta limit con el nuevo precio y volumen
                    actualizarOrdenSellLimit(symbol, precioDCAConBeneficio, sumaVolumenesTotales)
                    # [MEJORA] Persistir el último DCA conocido (snapshot rápido).
                    store.set_state(f"dca_{symbol}", str(nuevoPrecioDCAPosicion))
                    store.set_state(f"dca_volume_{symbol}", str(sumaVolumenesTotales))
                else:
                    print(f"Balance de {quoteAsset} Insuficiente, APORTA MAS {quoteAsset} AL BALANCE o libera balance Bloqueado")
            else:
                print(f"Precio fuera de Rango de Compra, ESPERANDO ACCION DEL PRECIO")

            # Registra los datos en el archivo CSV
            with open(csv_filename, mode='a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'), closeActualw, closeActualh, precioMMw, precioMMh,
                    ultimo_lowW, ultimo_lowh, base_free, base_locked, base_total, quote_free, quote_locked, quote_total, precioUltimaCompraMarket, nuevoPrecioDCAPosicion, precioDCAConBeneficio
                ])

            # [MEJORA] Cálculo periódico de métricas y persistencia en metrics_log.
            ciclo_idx += 1
            if ciclo_idx % METRICS_INTERVAL_CYCLES == 0:
                m = calcular_y_registrar_metricas(store)
                print(
                    f"[METRICAS] trades={m['total_trades']} pnl={m['total_pnl']} "
                    f"win_rate={m['win_rate']} sharpe={m['sharpe']} max_dd={m['max_drawdown']}"
                )

        except Exception as e:
            print(f"Error durante la ejecución: {e}")
            traceback.print_exc()

        # Espera antes de la siguiente ejecución
        time.sleep(tiempoEntreEjecucion)
