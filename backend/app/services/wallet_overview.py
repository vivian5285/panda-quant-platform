"""Admin wallet hub overview: config status + on-chain balances."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import PlatformDepositAddress, UserDepositAddress
from app.services.deposit_chains import MONITORED_DEPOSIT_CHAINS, get_rpc_url
from app.services.deposit_secrets import get_deposit_wallet_settings, is_deposit_mnemonic_configured
from app.services.deposit_sweep_config import (
    get_cold_wallet,
    get_gas_funder_private_key,
    get_sweep_settings,
)
from app.services.payout_secrets import get_chain_private_key, get_payout_settings
from app.services.wallet_balance import derive_evm_address, derive_tron_address, fetch_address_balance
from app.config import get_settings

settings = get_settings()
WALLET_CHAINS = list(MONITORED_DEPOSIT_CHAINS)


def _wallet_slot(chain: str, address: str, *, role: str, configured: bool, **extra) -> dict:
    bal = fetch_address_balance(chain, address) if address else None
    out = {
        "role": role,
        "chain": chain,
        "configured": configured,
        "address": address or "",
        "usdt": bal.usdt if bal else None,
        "native": bal.native if bal else None,
        "native_symbol": bal.native_symbol if bal else "",
        "rpc_ready": bal.rpc_ready if bal else False,
        "error": bal.error if bal else None,
        "gas_topup_hint": bal.gas_topup_hint if bal else None,
        "native_low": bal.native_low if bal else False,
    }
    out.update(extra)
    return out


def _resolve_hot_address(chain: str) -> tuple[str, bool]:
    chain = chain.upper()
    pk = get_chain_private_key(chain)
    if not pk:
        return "", False
    try:
        if chain == "TRC20":
            return derive_tron_address(pk), True
        return derive_evm_address(pk), True
    except Exception:
        return "", True


def _resolve_gas_funder_address(chain: str) -> tuple[str, bool, bool]:
    """Returns (address, configured, same_as_hot)."""
    chain = chain.upper()
    hot_pk = get_chain_private_key(chain)
    gas_pk = get_gas_funder_private_key(chain)
    if not gas_pk:
        return "", False, False
    same_as_hot = bool(hot_pk and gas_pk.strip() == hot_pk.strip())
    try:
        if chain == "TRC20":
            return derive_tron_address(gas_pk), True, same_as_hot
        return derive_evm_address(gas_pk), True, same_as_hot
    except Exception:
        return "", True, same_as_hot


def get_wallet_overview(db: Session) -> dict:
    deposit_settings = get_deposit_wallet_settings()
    sweep = get_sweep_settings()
    payout = get_payout_settings()

    user_addr_count = db.query(UserDepositAddress.user_id).distinct().count()
    platform_rows = db.query(PlatformDepositAddress).order_by(
        PlatformDepositAddress.sort_order, PlatformDepositAddress.id
    ).all()

    cold_wallets: list[dict] = []
    hot_wallets: list[dict] = []
    gas_funders: list[dict] = []

    for chain in WALLET_CHAINS:
        cold_addr = get_cold_wallet(chain)
        cold_wallets.append(_wallet_slot(
            chain, cold_addr, role="cold", configured=bool(cold_addr),
        ))

        hot_addr, hot_ok = _resolve_hot_address(chain)
        hot_wallets.append(_wallet_slot(
            chain, hot_addr, role="hot",
            configured=bool(payout.get("chains", {}).get(chain)),
            auto_payout_enabled=bool(payout.get("auto_enabled")),
        ))

        gas_addr, gas_ok, same_as_hot = _resolve_gas_funder_address(chain)
        if same_as_hot and hot_addr:
            slot = _wallet_slot(
                chain, hot_addr, role="gas_funder",
                configured=hot_ok,
                uses_hot_wallet=True,
            )
        else:
            slot = _wallet_slot(
                chain, gas_addr, role="gas_funder",
                configured=gas_ok,
                uses_hot_wallet=False,
            )
        gas_funders.append(slot)

    platform_addresses: list[dict] = []
    for row in platform_rows:
        bal = fetch_address_balance(row.chain, row.address) if row.chain.upper() in WALLET_CHAINS else None
        platform_addresses.append({
            "id": row.id,
            "chain": row.chain,
            "label": row.label or "",
            "address": row.address,
            "is_active": bool(row.is_active),
            "has_qr": bool(row.qr_image_filename),
            "usdt": bal.usdt if bal else None,
            "native": bal.native if bal else None,
            "native_symbol": bal.native_symbol if bal else "",
            "rpc_ready": bal.rpc_ready if bal else False,
            "error": bal.error if bal else ("该链暂不支持链上余额查询" if row.chain.upper() not in WALLET_CHAINS else None),
            "native_low": bal.native_low if bal else False,
        })

    rpc_status = {
        "TRC20": bool(settings.TRON_API_URL.strip()),
        **{c: bool(get_rpc_url(c).strip()) for c in WALLET_CHAINS if c != "TRC20"},
    }

    totals = {"cold_usdt": 0.0, "hot_usdt": 0.0, "platform_usdt": 0.0}
    for w in cold_wallets:
        if w.get("usdt") is not None:
            totals["cold_usdt"] += w["usdt"]
    for w in hot_wallets:
        if w.get("usdt") is not None:
            totals["hot_usdt"] += w["usdt"]
    for w in platform_addresses:
        if w.get("is_active") and w.get("usdt") is not None:
            totals["platform_usdt"] += w["usdt"]
    totals = {k: round(v, 2) for k, v in totals.items()}

    return {
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "chains": WALLET_CHAINS,
        "rpc_status": rpc_status,
        "totals": totals,
        "hd_deposit": {
            "configured": is_deposit_mnemonic_configured(),
            "source": deposit_settings.get("source"),
            "derivation_offset": deposit_settings.get("derivation_offset", settings.DEPOSIT_DERIVATION_OFFSET),
            "users_with_addresses": user_addr_count,
        },
        "sweep": {
            "auto_enabled": sweep.get("auto_enabled"),
            "ready_chains": sweep.get("ready_chains") or [],
            "min_usdt": sweep.get("min_usdt"),
            "require_matched_deposit": sweep.get("require_matched_deposit"),
        },
        "payout": {
            "auto_enabled": payout.get("auto_enabled"),
            "chains": payout.get("chains") or {},
        },
        "cold_wallets": cold_wallets,
        "hot_wallets": hot_wallets,
        "gas_funders": gas_funders,
        "platform_addresses": platform_addresses,
    }
