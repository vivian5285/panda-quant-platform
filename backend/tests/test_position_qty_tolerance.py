"""Position qty drift tolerance — ignore normal ETH mark-price noise."""

from app.core.position_qty_tolerance import qty_change_significant


def test_minor_drift_not_significant():
    assert qty_change_significant(1.365, 1.363) is False
    assert qty_change_significant(1.363, 1.365) is False


def test_large_drift_is_significant():
    assert qty_change_significant(2.954, 1.489) is True


def test_deepcoin_one_contract_within_small_book():
    # 8 vs 9 张 on a small book — within ~2% + 1-contract floor
    assert qty_change_significant(9, 8, is_contracts=True) is False


def test_deepcoin_material_trim_significant():
    assert qty_change_significant(15, 8, is_contracts=True) is True
