"""Block explorer URLs for on-chain transaction hashes."""

EXPLORER_TX: dict[str, str] = {
    "TRC20": "https://tronscan.org/#/transaction/{tx}",
    "ERC20": "https://etherscan.io/tx/{tx}",
    "BEP20": "https://bscscan.com/tx/{tx}",
    "ARBITRUM": "https://arbiscan.io/tx/{tx}",
    "POLYGON": "https://polygonscan.com/tx/{tx}",
    "SOL": "https://solscan.io/tx/{tx}",
}


def tx_explorer_url(chain: str, tx_hash: str | None) -> str | None:
    if not tx_hash:
        return None
    template = EXPLORER_TX.get(chain.upper())
    if not template:
        return None
    return template.format(tx=tx_hash.strip())
