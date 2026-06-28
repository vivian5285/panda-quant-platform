from sqlalchemy.orm import Session
from app.services.chain_fees import calc_withdraw_net, get_chain_fee, CHAIN_WITHDRAW_FEES_USD
from app.models import RewardAccount, RewardLedger, WithdrawalRequest, WithdrawalStatus, InternalTransfer, User, WithdrawalAddress
from app.services.user_lookup import find_user_by_identifier, display_name
from app.config import get_settings

settings = get_settings()


def get_or_create_reward_account(db: Session, user_id: int) -> RewardAccount:
    account = db.query(RewardAccount).filter(RewardAccount.user_id == user_id).first()
    if not account:
        account = RewardAccount(user_id=user_id)
        db.add(account)
        db.flush()
    return account


def credit_reward(
    db: Session,
    user_id: int,
    amount: float,
    reference_type: str,
    reference_id: int,
    note: str = "",
    count_as_earned: bool = True,
) -> RewardAccount:
    if amount <= 0:
        return get_or_create_reward_account(db, user_id)

    account = get_or_create_reward_account(db, user_id)
    account.balance = round(account.balance + amount, 2)
    if count_as_earned:
        account.total_earned = round(account.total_earned + amount, 2)
    db.add(RewardLedger(
        user_id=user_id,
        entry_type="credit",
        amount=amount,
        balance_after=account.balance,
        reference_type=reference_type,
        reference_id=reference_id,
        note=note,
    ))
    return account


def debit_reward(
    db: Session,
    user_id: int,
    amount: float,
    reference_type: str,
    reference_id: int,
    note: str = "",
    count_as_withdrawn: bool = True,
) -> RewardAccount:
    account = get_or_create_reward_account(db, user_id)
    if account.balance < amount:
        raise ValueError("Insufficient reward balance")
    account.balance = round(account.balance - amount, 2)
    if count_as_withdrawn:
        account.total_withdrawn = round(account.total_withdrawn + amount, 2)
    db.add(RewardLedger(
        user_id=user_id,
        entry_type="debit",
        amount=-amount,
        balance_after=account.balance,
        reference_type=reference_type,
        reference_id=reference_id,
        note=note,
    ))
    return account


def create_withdrawal(
    db: Session,
    user_id: int,
    gross_amount: float,
    chain: str,
    address: str,
    address_book_id: int | None = None,
) -> WithdrawalRequest:
    chain = chain.upper()
    if gross_amount < settings.WITHDRAW_MIN_USD:
        raise ValueError(f"Minimum withdrawal is ${settings.WITHDRAW_MIN_USD}")

    network_fee, amount_net = calc_withdraw_net(gross_amount, chain)
    if amount_net <= 0:
        raise ValueError(f"Amount too small — network fee ${network_fee} exceeds withdrawal amount")

    account = get_or_create_reward_account(db, user_id)
    if account.balance < gross_amount:
        raise ValueError("Insufficient reward balance")

    auto_approved = gross_amount <= settings.WITHDRAW_AUTO_MAX_USD
    needs_review = gross_amount >= settings.WITHDRAW_REVIEW_MIN_USD

    if needs_review:
        status = WithdrawalStatus.PENDING.value
        auto_approved = False
    elif auto_approved:
        status = WithdrawalStatus.AUTO_APPROVED.value
    else:
        status = WithdrawalStatus.PENDING.value

    req = WithdrawalRequest(
        user_id=user_id,
        address_book_id=address_book_id,
        chain=chain,
        address=address,
        amount=round(gross_amount, 2),
        network_fee=network_fee,
        amount_net=amount_net,
        status=status,
        auto_approved=auto_approved,
    )
    db.add(req)
    db.flush()

    debit_reward(
        db, user_id, gross_amount,
        reference_type="withdrawal",
        reference_id=req.id,
        note=f"Withdrawal #{req.id} · {chain} · fee ${network_fee} · net ${amount_net}",
    )
    db.commit()
    db.refresh(req)
    return req


def get_address_book_entry(db: Session, user_id: int, address_book_id: int) -> WithdrawalAddress:
    addr = db.query(WithdrawalAddress).filter(
        WithdrawalAddress.id == address_book_id,
        WithdrawalAddress.user_id == user_id,
    ).first()
    if not addr:
        raise ValueError("Address book entry not found")
    return addr


def complete_withdrawal(db: Session, req: WithdrawalRequest, tx_hash: str, admin_note: str = "") -> WithdrawalRequest:
    req.status = WithdrawalStatus.COMPLETED.value
    req.tx_hash = tx_hash
    req.admin_note = admin_note or req.admin_note
    req.processed_at = __import__("datetime").datetime.utcnow()
    db.commit()
    db.refresh(req)
    return req


def reject_withdrawal(db: Session, req: WithdrawalRequest, admin_note: str = "") -> WithdrawalRequest:
    credit_reward(
        db, req.user_id, req.amount,
        reference_type="withdrawal_refund",
        reference_id=req.id,
        note=f"Withdrawal #{req.id} rejected: {admin_note}",
        count_as_earned=False,
    )
    req.status = WithdrawalStatus.REJECTED.value
    req.admin_note = admin_note
    req.processed_at = __import__("datetime").datetime.utcnow()
    db.commit()
    db.refresh(req)
    return req


def internal_transfer(
    db: Session,
    from_user_id: int,
    recipient_query: str,
    amount: float,
    note: str = "",
) -> InternalTransfer:
    if amount < settings.TRANSFER_MIN_USD:
        raise ValueError(f"Minimum transfer is ${settings.TRANSFER_MIN_USD}")

    to_user = find_user_by_identifier(db, recipient_query)
    if not to_user:
        raise ValueError("Recipient not found")
    if to_user.id == from_user_id:
        raise ValueError("Cannot transfer to yourself")
    if not to_user.is_active:
        raise ValueError("Recipient account is inactive")

    from_user = db.query(User).filter(User.id == from_user_id).first()

    transfer = InternalTransfer(
        from_user_id=from_user_id,
        to_user_id=to_user.id,
        amount=round(amount, 2),
        recipient_query=recipient_query.strip(),
        note=note,
    )
    db.add(transfer)
    db.flush()

    debit_reward(
        db, from_user_id, amount,
        reference_type="internal_transfer_out",
        reference_id=transfer.id,
        note=f"Transfer to {display_name(to_user)} (UID:{to_user.uid})" + (f" — {note}" if note else ""),
        count_as_withdrawn=False,
    )
    credit_reward(
        db, to_user.id, amount,
        reference_type="internal_transfer_in",
        reference_id=transfer.id,
        note=f"Transfer from {display_name(from_user)} (UID:{from_user.uid})" + (f" — {note}" if note else ""),
        count_as_earned=False,
    )
    db.commit()
    db.refresh(transfer)
    return transfer
