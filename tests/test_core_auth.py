"""Accounts, passwords and rate limiting."""
import core
import store


def test_password_hashing_is_salted_and_verifiable():
    first = core.hash_password("correct-horse")
    second = core.hash_password("correct-horse")

    assert first != second, "each hash must use a fresh salt"
    assert first.startswith("pbkdf2_sha256$")
    assert core.verify_password("correct-horse", first) == (True, False)
    assert core.verify_password("wrong", first) == (False, False)


def test_legacy_hashes_verify_and_are_upgraded_on_login():
    legacy = core._legacy_hash("correct-horse")
    store.create_user("old@example.com", "Old", legacy, "starter", 500)

    valid, needs_rehash = core.verify_password("correct-horse", legacy)
    assert (valid, needs_rehash) == (True, True)

    ok, _, user = core.login("old@example.com", "correct-horse")
    assert ok
    assert user["pw_hash"].startswith("pbkdf2_sha256$"), "hash should be upgraded in place"


def test_registration_validation():
    assert core.register("not-an-email", "correct-horse", "Pat")[0] is False
    assert core.register("a@example.com", "short", "Pat")[0] is False
    assert core.register("a@example.com", "correct-horse", "  ")[0] is False
    assert core.register("a@example.com", "correct-horse", "Pat")[0] is True


def test_emails_are_normalised(user):
    ok, _, found = core.login("  MEMBER@Example.COM ", "correct-horse")
    assert ok
    assert found["email"] == "member@example.com"


def test_duplicate_registration_is_refused(user):
    ok, message = core.register("member@example.com", "another-pass", "Impostor")
    assert ok is False
    assert "already registered" in message


def test_flagged_accounts_cannot_sign_in(user):
    store.update_user(user["email"], flagged=True, flag_reason="spam")
    ok, message, _ = core.login(user["email"], "correct-horse")
    assert ok is False
    assert "suspended" in message.lower()


def test_login_is_rate_limited(user):
    for _ in range(10):
        core.login(user["email"], "wrong-password")
    ok, message, _ = core.login(user["email"], "correct-horse")
    assert ok is False
    assert "wait" in message.lower()


def test_change_password(user):
    assert core.change_password(user["email"], "wrong", "brand-new-pass")[0] is False
    assert core.change_password(user["email"], "correct-horse", "brand-new-pass")[0] is True
    assert core.login(user["email"], "brand-new-pass")[0] is True
