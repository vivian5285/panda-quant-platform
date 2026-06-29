"""Per-user HD deposit addresses (Binance-style unique recharge addresses)."""
from __future__ import annotations

import logging

from eth_account import Account
from sqlalchemy.orm import Session
from tronpy.keys import PrivateKey

from app.config import get_settings
from app.models import User, UserDepositAddress, SUPPORTED_CHAINS

logger = logging.getLogger(__name__)
settings = get_settings()

EVM_CHAINS = ("ERC20", "BEP20", "ARBITRUM", "POLYGON")
Account.enable_unaudited_hdwallet_features()


def _derivation_index(user_id: int) -> int:
    return settings.DEPOSIT_DERIVATION_OFFSET + user_id


def _mnemonic_configured() -> bool:
    return bool(settings.DEPOSIT_HD_MNEMONIC.strip())


def derive_evm_address(mnemonic: str, index: int) -> tuple[str, str]:
    acct = Account.from_mnemonic(
        mnemonic.strip(),
        account_path=f"m/44'/60'/0'/0/{index}",
    )
    return acct.address, acct.key.hex()


def derive_tron_address(mnemonic: str, index: int) -> str:
    _, pk_hex = derive_evm_address(mnemonic, index)
    return PrivateKey(bytes.fromhex(pk_hex)).public_key.to_base58check_address()


def ensure_user_deposit_addresses(db: Session, user: User) -> list[UserDepositAddress]:
    """Create or return per-user unique USDT deposit addresses."""
    existing = db.query(UserDepositAddress).filter(
        UserDepositAddress.user_id == user.id
    ).all()
    if existing:
        return existing

    if not _mnemonic_configured():
        logger.warning("[DepositWallet] DEPOSIT_HD_MNEMONIC not set — skip address generation for user %s", user.id)
        return []

    mnemonic = settings.DEPOSIT_HD_MNEMONIC.strip()
    index = _derivation_index(user.id)
    evm_address, _ = derive_evm_address(mnemonic, index)
    tron_address = derive_tron_address(mnemonic, index)

    created: list[UserDepositAddress] = []
    for chain in EVM_CHAINS:
        row = UserDepositAddress(
            user_id=user.id,
            chain=chain,
            address=evm_address,
            address_group="EVM",
            derivation_index=index,
        )
        db.add(row)
        created.append(row)

    trc = UserDepositAddress(
        user_id=user.id,
        chain="TRC20",
        address=tron_address,
        address_group="TRC20",
        derivation_index=index,
    )
    db.add(trc)
    created.append(trc)

    db.flush()
    logger.info(
        "[DepositWallet] user=%s uid=%s evm=%s trc20=%s index=%s",
        user.id, user.uid, evm_address, tron_address, index,
    )
    return created


def backfill_all_user_deposit_addresses(db: Session) -> int:
    if not _mnemonic_configured():
        return 0
    users = db.query(User).filter(User.is_active == True).all()
    count = 0
    for user in users:
        before = db.query(UserDepositAddress).filter(UserDepositAddress.user_id == user.id).count()
        if before == 0:
            ensure_user_deposit_addresses(db, user)
            count += 1
    if count:
        db.commit()
    return count


def user_deposit_address_map(db: Session, user_id: int) -> dict[str, str]:
    rows = db.query(UserDepositAddress).filter(UserDepositAddress.user_id == user_id).all()
    return {r.chain: r.address for r in rows}


def find_user_by_deposit_address(db: Session, address: str) -> User | None:
    if not address:
        return None
    normalized = address.strip()
    row = db.query(UserDepositAddress).filter(
        UserDepositAddress.address == normalized
    ).first()
    if not row:
        if normalized.startswith("0x"):
            row = db.query(UserDepositAddress).filter(
                UserDepositAddress.address == normalized.lower()
            ).first()
    if not row:
        return None
    return db.query(User).filter(User.id == row.user_id).first()
