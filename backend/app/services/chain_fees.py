"""Exchange-standard USDT network withdrawal fees (USD equivalent)."""

CHAIN_WITHDRAW_FEES_USD: dict[str, float] = {
    "TRC20": 1.0,
    "ERC20": 3.2,
    "BEP20": 0.8,
    "ARBITRUM": 0.1,
    "POLYGON": 0.1,
    "SOL": 1.0,
}

INTERNAL_TRANSFER_FEE_USD = 0.0

EXCHANGE_SOURCES = (
    "Binance", "OKX", "Bybit", "Bitget", "Gate.io", "Huobi", "KuCoin", "其他交易所",
)
WALLET_SOURCES = (
    "MetaMask", "Trust Wallet", "TokenPocket", "imToken", "Ledger", "其他钱包",
)


def get_chain_fee(chain: str) -> float:
    return CHAIN_WITHDRAW_FEES_USD.get(chain.upper(), 1.0)


def calc_withdraw_net(gross_amount: float, chain: str) -> tuple[float, float]:
    """Return (network_fee, net_received). Binance-style: fee deducted from gross."""
    fee = get_chain_fee(chain)
    net = round(max(0, gross_amount - fee), 2)
    return fee, net
