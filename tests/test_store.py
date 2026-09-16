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
