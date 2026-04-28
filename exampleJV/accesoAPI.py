import config
from binance.client import Client

def inicializar_cliente():
    """
    Inicializa y devuelve una instancia del cliente de Binance con las claves de API proporcionadas.
    """
    api_key = config.api_key
    api_secret = config.api_secret
    client = Client(api_key, api_secret)
    return client