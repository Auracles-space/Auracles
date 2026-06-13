"""Reputation compute-engine math tests (pure, no DB)."""

from decimal import Decimal

from app.modules.reputation.service import FactorResult, combine_factors


def _cfg(weights, prior="0.5", k="5", min_activity=3):
    """Build a ReputationConfig for engine math tests."""
    from app.modules.reputation.weights import ReputationConfig

    return ReputationConfig(
        "framework",
        {f: Decimal(w) for f, w in weights.items()},
        min_activity,
        Decimal(prior),
        Decimal(k),
        180,
        Decimal("0.20"),
    )


def test_no_evidence_is_provisional_and_near_prior():
    """Zero-evidence subject collapses to prior*100 and is provisional."""
    cfg = _cfg({"reviews": "1.0"})
    res = combine_factors(cfg, {"reviews": FactorResult(Decimal("0"), 0)})
    assert res.is_provisional is True
    # n=0 → score collapses to prior*100 = 50
    assert res.score == Decimal("50.00")


def test_strong_evidence_not_provisional_and_tracks_raw():
    """High-evidence subject sheds the prior and tracks its raw factor value."""
    cfg = _cfg({"reviews": "1.0"}, min_activity=3)
    res = combine_factors(cfg, {"reviews": FactorResult(Decimal("1.0"), 20)})
    assert res.is_provisional is False
    # n=20,k=5,prior=0.5,raw=1.0 → (20/25)*1 + (5/25)*0.5 = 0.9 → 90.00
    assert res.score == Decimal("90.00")


def test_weighted_sum_of_factors():
    """Score is the weighted sum of normalized factors when shrinkage is off."""
    cfg = _cfg({"reviews": "0.5", "attestations": "0.5"}, k="0", min_activity=1)
    res = combine_factors(
        cfg,
        {
            "reviews": FactorResult(Decimal("1.0"), 10),
            "attestations": FactorResult(Decimal("0.0"), 10),
        },
    )
    # k=0 → no shrinkage; raw = 0.5*1 + 0.5*0 = 0.5 → 50.00
    assert res.score == Decimal("50.00")


def test_components_carry_labels():
    """Each factor exposes a public strength label and its clamped value."""
    cfg = _cfg({"reviews": "1.0"}, min_activity=1)
    res = combine_factors(cfg, {"reviews": FactorResult(Decimal("0.9"), 10)})
    assert res.components["reviews"]["label"] in {"strong", "moderate", "weak"}
    assert "value" in res.components["reviews"]
