"""Trading regime helpers shared across exchange supervisors."""

VALID_REGIMES = frozenset({1, 2, 3, 4})


def clamp_regime(value, default: int = 3) -> int:
    """Normalize regime to 1–4; invalid values fall back to default."""
    try:
        regime = int(value if value is not None else default)
    except (TypeError, ValueError):
        return default
    return regime if regime in VALID_REGIMES else default
