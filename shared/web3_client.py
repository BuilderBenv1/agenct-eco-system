from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from shared.config import settings


def get_web3() -> Web3:
    w3 = Web3(Web3.HTTPProvider(settings.AVALANCHE_RPC_URL))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


w3 = get_web3()
