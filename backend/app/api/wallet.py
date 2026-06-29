from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    PlatformDepositAddress, Settlement, PaymentStatus, SUPPORTED_CHAINS,
    WithdrawalAddress, WithdrawalRequest, User, InternalTransfer,
    UserDepositAddress, SettlementDeposit,
)
from app.schemas import (
    DepositAddressOut, SettlementOut, SettlementPaymentSubmit,
    RewardAccountOut, RewardLedgerOut,
    WithdrawalAddressCreate, WithdrawalAddressOut,
    WithdrawalCreate, WithdrawalOut, WithdrawSettingsOut, ChainFeeOut,
    InternalTransferCreate, InternalTransferOut, TransferRecipientPreview,
    UserDepositAddressOut, SettlementDepositOut,
)
from app.api.deps import get_current_user
from app.services.settlement import submit_settlement_payment
from app.services.user_lookup import find_user_by_identifier, mask_user_public, display_name
from app.services.wallet import (
    get_or_create_reward_account, create_withdrawal, internal_transfer,
    get_address_book_entry,
)
from app.services.chain_fees import (
    CHAIN_WITHDRAW_FEES_USD, INTERNAL_TRANSFER_FEE_USD,
    calc_withdraw_net, EXCHANGE_SOURCES, WALLET_SOURCES,
)
from app.services.platform_runtime import get_withdraw_thresholds
from app.services.deposit_qr import resolve_deposit_qr_path
from app.services.auto_payout import process_auto_payout
from app.services.user_deposit_wallet import ensure_user_deposit_addresses
from app.config import get_settings

router = APIRouter(tags=["wallet"])
settings = get_settings()


@router.get("/deposit-addresses", response_model=list[DepositAddressOut])
def list_deposit_addresses(db: Session = Depends(get_db)):
    rows = db.query(PlatformDepositAddress).filter(
        PlatformDepositAddress.is_active == True
    ).order_by(PlatformDepositAddress.sort_order, PlatformDepositAddress.id).all()
    return [DepositAddressOut.from_model(a) for a in rows]


@router.get("/my-deposit-addresses", response_model=list[UserDepositAddressOut])
def my_deposit_addresses(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Per-user unique USDT deposit addresses (Binance-style)."""
    rows = ensure_user_deposit_addresses(db, user)
    db.commit()
    return [
        UserDepositAddressOut(
            chain=r.chain,
            address=r.address,
            address_group=r.address_group,
            is_unique=True,
        )
        for r in rows
    ]


@router.get("/settlement-deposits", response_model=list[SettlementDepositOut])
def my_settlement_deposits(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(SettlementDeposit).filter(
        SettlementDeposit.user_id == user.id
    ).order_by(SettlementDeposit.detected_at.desc()).limit(50).all()


@router.get("/deposit-addresses/{addr_id}/qr")
def get_deposit_qr_image(addr_id: int, db: Session = Depends(get_db)):
    addr = db.query(PlatformDepositAddress).filter(
        PlatformDepositAddress.id == addr_id,
        PlatformDepositAddress.is_active == True,
    ).first()
    if not addr or not addr.qr_image_filename:
        raise HTTPException(404, "QR image not found")
    path = resolve_deposit_qr_path(addr.qr_image_filename)
    media = "image/png"
    low = addr.qr_image_filename.lower()
    if low.endswith(".jpg") or low.endswith(".jpeg"):
        media = "image/jpeg"
    elif low.endswith(".webp"):
        media = "image/webp"
    elif low.endswith(".gif"):
        media = "image/gif"
    return FileResponse(path, media_type=media)


@router.post("/settlements/{settlement_id}/pay", response_model=SettlementOut)
def pay_settlement(
    settlement_id: int,
    req: SettlementPaymentSubmit,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if req.chain.upper() not in SUPPORTED_CHAINS:
        raise HTTPException(400, f"Unsupported chain. Supported: {', '.join(SUPPORTED_CHAINS)}")

    s = db.query(Settlement).filter(
        Settlement.id == settlement_id,
        Settlement.user_id == user.id,
    ).first()
    if not s:
        raise HTTPException(404, "Settlement not found")
    if s.payment_status not in (PaymentStatus.PENDING.value, PaymentStatus.REJECTED.value):
        raise HTTPException(400, "Settlement payment already submitted")

    return submit_settlement_payment(db, s, req.chain, req.tx_hash, req.amount)


@router.get("/reward-account", response_model=RewardAccountOut)
def reward_account(user=Depends(get_current_user), db: Session = Depends(get_db)):
    account = get_or_create_reward_account(db, user.id)
    db.commit()
    return RewardAccountOut(
        balance=account.balance,
        total_earned=account.total_earned,
        total_withdrawn=account.total_withdrawn,
    )


@router.get("/reward-ledger", response_model=list[RewardLedgerOut])
def reward_ledger(limit: int = 50, user=Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models import RewardLedger
    return db.query(RewardLedger).filter(
        RewardLedger.user_id == user.id
    ).order_by(RewardLedger.created_at.desc()).limit(limit).all()


@router.get("/withdraw/settings", response_model=WithdrawSettingsOut)
def withdraw_settings():
    thresholds = get_withdraw_thresholds()
    return WithdrawSettingsOut(
        auto_max_usd=thresholds["auto_max_usd"],
        review_min_usd=thresholds["review_min_usd"],
        min_usd=thresholds["min_usd"],
        supported_chains=list(SUPPORTED_CHAINS),
        chain_fees=[ChainFeeOut(chain=k, fee_usd=v) for k, v in CHAIN_WITHDRAW_FEES_USD.items()],
        internal_transfer_fee=INTERNAL_TRANSFER_FEE_USD,
        exchange_sources=list(EXCHANGE_SOURCES),
        wallet_sources=list(WALLET_SOURCES),
    )


@router.get("/withdraw/fee-preview")
def fee_preview(chain: str, amount: float):
    if chain.upper() not in SUPPORTED_CHAINS:
        raise HTTPException(400, "Unsupported chain")
    fee, net = calc_withdraw_net(amount, chain)
    return {"chain": chain.upper(), "gross_amount": amount, "network_fee": fee, "amount_net": net}


@router.get("/withdraw/addresses", response_model=list[WithdrawalAddressOut])
def list_withdraw_addresses(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(WithdrawalAddress).filter(
        WithdrawalAddress.user_id == user.id
    ).order_by(WithdrawalAddress.is_default.desc(), WithdrawalAddress.id.desc()).all()


@router.post("/withdraw/addresses", response_model=WithdrawalAddressOut)
def add_withdraw_address(
    req: WithdrawalAddressCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.verification import verify_security_dual

    try:
        verify_security_dual(db, user, req.email_code, req.phone_code)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if req.chain.upper() not in SUPPORTED_CHAINS:
        raise HTTPException(400, f"Unsupported chain. Supported: {', '.join(SUPPORTED_CHAINS)}")
    if req.address_type not in ("exchange", "wallet"):
        raise HTTPException(400, "address_type must be exchange or wallet")

    existing = db.query(WithdrawalAddress).filter(
        WithdrawalAddress.user_id == user.id,
        WithdrawalAddress.chain == req.chain.upper(),
        WithdrawalAddress.address == req.address.strip(),
    ).first()
    if existing:
        raise HTTPException(400, "This address is already in your address book")

    if req.is_default:
        db.query(WithdrawalAddress).filter(
            WithdrawalAddress.user_id == user.id
        ).update({"is_default": False})

    addr = WithdrawalAddress(
        user_id=user.id,
        chain=req.chain.upper(),
        address=req.address.strip(),
        address_type=req.address_type,
        source_name=req.source_name.strip(),
        label=req.label.strip() or req.source_name.strip(),
        memo=req.memo.strip() if req.memo else None,
        is_default=req.is_default,
    )
    db.add(addr)
    db.commit()
    db.refresh(addr)
    return addr


@router.post("/withdraw/addresses/{address_id}/default")
def set_default_address(
    address_id: int,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    addr = db.query(WithdrawalAddress).filter(
        WithdrawalAddress.id == address_id,
        WithdrawalAddress.user_id == user.id,
    ).first()
    if not addr:
        raise HTTPException(404, "Address not found")
    db.query(WithdrawalAddress).filter(WithdrawalAddress.user_id == user.id).update({"is_default": False})
    addr.is_default = True
    db.commit()
    return {"status": "ok"}


@router.delete("/withdraw/addresses/{address_id}")
def delete_withdraw_address(
    address_id: int,
    email_code: str,
    phone_code: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.verification import verify_security_dual

    try:
        verify_security_dual(db, user, email_code, phone_code)
    except ValueError as e:
        raise HTTPException(400, str(e))

    addr = db.query(WithdrawalAddress).filter(
        WithdrawalAddress.id == address_id,
        WithdrawalAddress.user_id == user.id,
    ).first()
    if not addr:
        raise HTTPException(404, "Address not found")
    db.delete(addr)
    db.commit()
    return {"status": "ok"}


@router.post("/withdraw", response_model=WithdrawalOut)
def request_withdrawal(
    req: WithdrawalCreate,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.utils.auth import verify_password
    from app.services.verification import verify_security_dual

    if not user.withdraw_password_hash:
        raise HTTPException(400, "请先设置提现密码")
    if not verify_password(req.withdraw_password, user.withdraw_password_hash):
        raise HTTPException(400, "提现密码错误")
    try:
        verify_security_dual(db, user, req.email_code, req.phone_code)
    except ValueError as e:
        raise HTTPException(400, str(e))

    try:
        if req.address_book_id:
            entry = get_address_book_entry(db, user.id, req.address_book_id)
            chain, address = entry.chain, entry.address
            book_id = entry.id
        elif req.chain and req.address:
            if req.chain.upper() not in SUPPORTED_CHAINS:
                raise HTTPException(400, f"Unsupported chain")
            chain, address = req.chain.upper(), req.address.strip()
            book_id = None
        else:
            raise HTTPException(400, "Select an address from address book or provide chain + address")

        withdrawal = create_withdrawal(db, user.id, req.amount, chain, address, book_id)
        if withdrawal.auto_approved:
            background_tasks.add_task(process_auto_payout, withdrawal.id)
        return withdrawal
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/withdrawals", response_model=list[WithdrawalOut])
def my_withdrawals(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(WithdrawalRequest).filter(
        WithdrawalRequest.user_id == user.id
    ).order_by(WithdrawalRequest.created_at.desc()).limit(50).all()


@router.get("/transfer/lookup", response_model=TransferRecipientPreview)
def lookup_transfer_recipient(
    recipient: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target = find_user_by_identifier(db, recipient)
    if not target:
        raise HTTPException(404, "Recipient not found")
    if target.id == user.id:
        raise HTTPException(400, "Cannot transfer to yourself")
    return TransferRecipientPreview(**mask_user_public(target))


@router.post("/transfer", response_model=InternalTransferOut)
def create_internal_transfer(
    req: InternalTransferCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        transfer = internal_transfer(db, user.id, req.recipient, req.amount, req.note)
        to_user = db.query(User).filter(User.id == transfer.to_user_id).first()
        return InternalTransferOut(
            id=transfer.id,
            amount=transfer.amount,
            recipient_query=transfer.recipient_query,
            to_uid=to_user.uid,
            to_display_name=display_name(to_user),
            note=transfer.note,
            created_at=transfer.created_at,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/transfers", response_model=list[InternalTransferOut])
def my_transfers(user=Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(InternalTransfer).filter(
        InternalTransfer.from_user_id == user.id
    ).order_by(InternalTransfer.created_at.desc()).limit(50).all()
    result = []
    for t in rows:
        to_user = db.query(User).filter(User.id == t.to_user_id).first()
        result.append(InternalTransferOut(
            id=t.id,
            amount=t.amount,
            recipient_query=t.recipient_query,
            to_uid=to_user.uid if to_user else "",
            to_display_name=display_name(to_user) if to_user else "",
            note=t.note,
            created_at=t.created_at,
        ))
    return result
