"""Storage layer behaviour."""
import pytest

import store


def test_unknown_user_fields_are_rejected_not_ignored():
    store.create_user("a@example.com", "A", "hash", "starter", 500)
    with pytest.raises(ValueError, match="Unknown user field"):
        store.update_user("a@example.com", not_a_column="x")


def test_deleting_a_user_cascades():
    store.create_user("a@example.com", "A", "hash", "starter", 500)
    store.insert_dataset("d1", "a@example.com", "DS", "", [{"x": 1}], False, [])
    store.insert_model("m1", "a@example.com", "M", "", "base", "repo", False, [])
    store.insert_api_key("a@example.com", "k", "secret")

    store.delete_user("a@example.com")

    assert store.get_dataset("d1") is None
    assert store.get_model("m1") is None
    assert store.user_api_keys("a@example.com") == []


def test_rate_limit_window():
    assert [store.rate_limit_hit("s", "act", 3) for _ in range(5)] == [
        True, True, True, False, False
    ]
    assert store.rate_limit_hit("other", "act", 3) is True, "limits are per subject"


def test_dataset_rows_can_be_skipped_for_listings():
    store.create_user("a@example.com", "A", "hash", "starter", 500)
    store.insert_dataset("d1", "a@example.com", "DS", "", [{"x": 1}] * 10, True, ["t"])

    listed = store.public_datasets(with_rows=False)[0]
    assert "rows" not in listed
    assert listed["row_count"] == 10
    assert store.get_dataset("d1")["rows"] == [{"x": 1}] * 10


def test_webhook_ids_are_claimed_once():
    assert store.mark_webhook_processed("evt_1", "stripe") is True
    assert store.mark_webhook_processed("evt_1", "stripe") is False


def test_legacy_json_is_imported(tmp_path):
    import json

    legacy = tmp_path / "db.json"
    legacy.write_text(json.dumps({
        "users": {
            "old@example.com": {
                "email": "old@example.com", "name": "Old", "pw_hash": "legacyhash",
                "plan": "pro", "tokens": 1234, "created": "2025-01-01T00:00:00",
                "token_log": [{"ts": "2025-01-01T00:00:00", "delta": 500,
                               "reason": "signup", "balance": 500}],
                "api_keys": {"hf": {"key": "hf_x", "created": "2025-01-01T00:00:00"}},
            }
        },
        "datasets": {
            "d1": {"owner": "old@example.com", "name": "Legacy DS",
                   "rows": [{"a": "1"}], "public": True, "tags": ["old"]}
        },
        "models": {},
        "support_tickets": [],
    }))

    assert store.migrate_legacy_json(legacy) == 1

    user = store.get_user("old@example.com")
    assert user["plan"] == "pro"
    assert user["tokens"] == 1234
    assert store.get_dataset("d1")["rows"] == [{"a": "1"}]
    assert store.user_api_keys("old@example.com")[0]["key_value"] == "hf_x"
    assert not legacy.exists(), "the imported file should be renamed"


def test_migration_is_a_no_op_without_a_file(tmp_path):
    assert store.migrate_legacy_json(tmp_path / "absent.json") == 0


def _write_legacy(path, email="old@example.com"):
    import json

    path.write_text(json.dumps({
        "users": {
            email: {
                "email": email, "name": "Old", "pw_hash": "legacyhash",
                "plan": "pro", "tokens": 1234, "created": "2025-01-01T00:00:00",
            }
        },
        "datasets": {}, "models": {}, "support_tickets": [],
    }))


def test_concurrent_migrations_do_not_crash(tmp_path):
    """Production hit FileNotFoundError here.

    Every Streamlit session calls bootstrap() from its own thread. Checking
    exists() first and renaming last let all of them pass the check and every
    loser blow up on the rename, killing the app at import time.
    """
    import threading

    legacy = tmp_path / "db.json"
    _write_legacy(legacy)

    results, errors = [], []
    barrier = threading.Barrier(8)

    def run():
        barrier.wait()  # maximise the overlap
        try:
            results.append(store.migrate_legacy_json(legacy))
        except Exception as exc:  # noqa: BLE001 - the whole point of the test
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"migration raised under concurrency: {errors}"
    assert sum(1 for r in results if r > 0) == 1, "exactly one thread should import"
    assert store.get_user("old@example.com") is not None
    assert not legacy.exists()


def test_bootstrap_survives_a_broken_legacy_file(tmp_path, monkeypatch):
    import core

    broken = tmp_path / "db.json"
    broken.write_text("{ this is not json")
    monkeypatch.setattr(store, "LEGACY_DB_JSON", broken)

    core.bootstrap()  # must not raise
    assert store.count_users() == 0


def test_bootstrap_never_raises(monkeypatch):
    import core

    def boom(*_a, **_k):
        raise OSError("disk gone")

    monkeypatch.setattr(store, "migrate_legacy_json", boom)
    core.bootstrap()  # a failed import must not take the app down


def test_restore_from_supabase_hydrates_an_empty_db(monkeypatch):
    import supabase_backend

    monkeypatch.setattr(supabase_backend, "is_configured", lambda: True)
    monkeypatch.setattr(supabase_backend, "primary_enabled", lambda: False)
    monkeypatch.setattr(
        supabase_backend,
        "fetch_bootstrap_snapshot",
        lambda: {
            "users": [{
                "email": "remote@example.com", "name": "Remote", "pw_hash": "hash",
                "plan": "pro", "tokens": 900, "flagged": False, "flag_reason": "",
                "platform_api_key": None, "traakteer_id": "", "stripe_customer_id": None,
                "stripe_subscription_id": None, "created": "2026-01-01T00:00:00",
                "updated": "2026-01-01T00:00:00", "last_reset": "2026-01-01T00:00:00",
            }],
            "datasets": [{
                "id": "ds1", "owner": "remote@example.com", "name": "DS",
                "description": "", "rows": [{"a": 1}], "row_count": 1,
                "public": False, "tags": ["demo"], "downloads": 0, "likes": 0,
                "storage_backend": "local", "storage_repo": None, "storage_path": None,
                "created": "2026-01-01T00:00:00", "updated": "2026-01-01T00:00:00",
            }],
            "models": [],
            "api_keys": [{
                "user_email": "remote@example.com", "label": "registry",
                "key_value": "hf_remote", "uses": 0, "last_used": None,
                "created_at": "2026-01-01T00:00:00",
            }],
            "support_tickets": [],
            "token_logs": [{
                "user_email": "remote@example.com", "delta": 500, "reason": "signup",
                "balance": 500, "created_at": "2026-01-01T00:00:00",
            }],
            "billing_events": [{
                "user_email": "remote@example.com", "event_type": "invoice.paid",
                "details": {"amount": 9.99}, "created_at": "2026-01-01T00:00:00",
            }],
            "auth_sessions": [{
                "token_hash": "hash1",
                "user_email": "remote@example.com",
                "created_at": "2026-01-01T00:00:00",
                "expires_at": "2026-06-01T00:00:00",
                "last_seen_at": "2026-01-01T00:00:00",
            }],
        },
    )

    assert store.restore_from_supabase() == 1
    assert store.get_user("remote@example.com")["plan"] == "pro"
    assert store.get_dataset("ds1")["rows"] == [{"a": 1}]
    assert store.user_api_keys("remote@example.com")[0]["key_value"] == "hf_remote"
    assert store.token_history("remote@example.com")[0]["reason"] == "signup"
    assert store.billing_history("remote@example.com")[0]["event_type"] == "invoice.paid"
    assert store.get_auth_session("hash1")["user_email"] == "remote@example.com"


def test_get_user_prefers_supabase_when_primary_backend_is_enabled(monkeypatch):
    import supabase_backend

    store.create_user("local@example.com", "Local", "hash", "starter", 500)
    monkeypatch.setattr(supabase_backend, "primary_enabled", lambda: True)
    monkeypatch.setattr(
        supabase_backend,
        "get_user",
        lambda email: {
            "email": email, "name": "Remote", "pw_hash": "hash", "plan": "pro",
            "tokens": 999, "flagged": False, "flag_reason": "", "platform_api_key": None,
            "traakteer_id": "", "stripe_customer_id": None, "stripe_subscription_id": None,
            "created": "2026-01-01T00:00:00", "updated": "2026-01-01T00:00:00",
            "last_reset": "2026-01-01T00:00:00",
        },
    )

    assert store.get_user("local@example.com")["plan"] == "pro"


def test_token_history_prefers_supabase_when_primary_backend_is_enabled(monkeypatch):
    import supabase_backend

    monkeypatch.setattr(supabase_backend, "primary_enabled", lambda: True)
    monkeypatch.setattr(
        supabase_backend,
        "token_history",
        lambda email, limit=100: [{"delta": 1, "reason": "remote", "balance": 10, "created_at": "x"}],
    )

    assert store.token_history("member@example.com")[0]["reason"] == "remote"


def test_announcements_can_be_set_and_cleared():
    store.set_announcement("Hello builders", "emir.erningpraja@example.com", active=True)
    announcement = store.get_announcement()
    assert announcement["message"] == "Hello builders"
    assert announcement["active"] is True

    store.clear_announcement()
    cleared = store.get_announcement()
    assert cleared["active"] is False
    assert cleared["message"] == ""


def test_auth_sessions_can_be_created_touched_and_deleted():
    store.create_user("a@example.com", "A", "hash", "starter", 500)
    assert store.create_auth_session("tokhash", "a@example.com", "2099-01-01T00:00:00+00:00") is True
    session = store.get_auth_session("tokhash")
    assert session is not None
    assert session["user_email"] == "a@example.com"

    assert store.touch_auth_session("tokhash", "2099-02-01T00:00:00+00:00") is True
    updated = store.get_auth_session("tokhash")
    assert updated["expires_at"] == "2099-02-01T00:00:00+00:00"

    assert store.delete_auth_session("tokhash") is True
    assert store.get_auth_session("tokhash") is None
