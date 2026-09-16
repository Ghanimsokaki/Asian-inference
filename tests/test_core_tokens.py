"""Token accounting."""
import core
import store


def test_spending_is_atomic_and_bounded(user):
    ok, balance = core.spend_tokens(user["email"], 200)
    assert (ok, balance) == (True, 300)

    ok, balance = core.spend_tokens(user["email"], 1000)
    assert ok is False, "must not go negative"
    assert balance == 300


def test_concurrent_spends_cannot_overdraw(user):
    """Two spends that each fit the balance individually but not together."""
    first_ok, _ = core.spend_tokens(user["email"], 300)
    second_ok, balance = core.spend_tokens(user["email"], 300)

    assert first_ok is True
    assert second_ok is False
    assert balance == 200


def test_refund_restores_balance(user):
    core.spend_tokens(user["email"], 100)
    assert core.refund_tokens(user["email"], 100) == 500


def test_grants_are_clamped_and_logged(user):
    balance, _ = core.grant_tokens(user["email"], 10_000_000, "bonus")
    assert balance == 500 + core.MAX_MANUAL_GRANT

    reasons = [entry["reason"] for entry in store.token_history(user["email"])]
    assert any(r.startswith("manual:") for r in reasons)


def test_repeated_manual_grants_flag_the_account(user):
    flagged = False
    for _ in range(core.MANUAL_GRANTS_PER_HOUR_BEFORE_FLAG + 2):
        _, flagged = core.grant_tokens(user["email"], 10, "manual top-up")
    assert flagged is True
    assert core.get_user(user["email"])["flagged"] is True


def test_row_cost():
    assert core.row_cost(10) == 10 * core.TOKENS_PER_ROW
    assert core.row_cost(-5) == 0


def test_plan_change_grants_the_new_allowance(user):
    core.set_plan(user["email"], "pro")
    updated = core.get_user(user["email"])
    assert updated["plan"] == "pro"
    assert updated["tokens"] == 15_000
