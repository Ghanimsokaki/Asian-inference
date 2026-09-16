"""Plan limits, ownership and visibility rules."""
import pytest

import core
import store

pytestmark = pytest.mark.usefixtures("no_hub")

ROWS = [{"input": "a", "output": "b"}]


def test_dataset_slot_limit_is_enforced(user):
    for index in range(2):  # Starter allows 2
        core.create_dataset(user["email"], f"DS {index}", "", ROWS, False, [])

    assert core.at_limit(core.get_user(user["email"]), "datasets") is True
    with pytest.raises(core.PlanLimitError):
        core.create_dataset(user["email"], "DS 3", "", ROWS, False, [])


def test_row_limit_is_enforced(user):
    too_many = [{"input": str(i), "output": "x"} for i in range(51)]
    with pytest.raises(core.PlanLimitError):
        core.create_dataset(user["email"], "Big", "", too_many, False, [])


def test_starter_cannot_publish(user):
    dataset_id = core.create_dataset(user["email"], "DS", "", ROWS, True, [])
    assert store.get_dataset(dataset_id)["public"] is False, "Starter is private-only"

    ok, message = core.set_dataset_visibility(dataset_id, user["email"], True)
    assert ok is False
    assert "Pro and Elite" in message


def test_pro_can_publish(user):
    core.set_plan(user["email"], "pro")
    dataset_id = core.create_dataset(user["email"], "DS", "", ROWS, True, [])
    assert store.get_dataset(dataset_id)["public"] is True


def test_another_user_cannot_delete_your_dataset(user):
    dataset_id = core.create_dataset(user["email"], "DS", "", ROWS, False, [])
    core.register("intruder@example.com", "correct-horse", "Nosy")

    ok, message = core.delete_dataset(dataset_id, "intruder@example.com")
    assert ok is False
    assert "permission" in message
    assert store.get_dataset(dataset_id) is not None

    assert core.delete_dataset(dataset_id, user["email"])[0] is True
    assert store.get_dataset(dataset_id) is None


def test_another_user_cannot_republish_your_model(user):
    core.set_plan(user["email"], "pro")
    model_id = core.create_model(user["email"], "M", "", "base/x", "repo/x", False, [])
    core.register("intruder@example.com", "correct-horse", "Nosy")

    ok, _ = core.set_model_visibility(model_id, "intruder@example.com", True)
    assert ok is False
    assert store.get_model(model_id)["public"] is False


def test_admin_bypasses_slot_limits(monkeypatch):
    import config

    monkeypatch.setattr(config, "ADMIN_EMAIL", "boss@example.com")
    core.register("boss@example.com", "correct-horse", "Boss")

    for index in range(5):
        core.create_dataset("boss@example.com", f"DS {index}", "", ROWS, False, [])
    assert store.count_user_datasets("boss@example.com") == 5


def test_api_key_slot_limit(user):
    ok, _ = core.add_api_key(user, "first", "hf_aaa")
    assert ok is True

    ok, message = core.add_api_key(user, "second", "hf_bbb")
    assert ok is False, "Starter allows a single stored key"
    assert "allows 1" in message


def test_duplicate_api_key_labels_are_refused(user):
    core.set_plan(user["email"], "pro")  # so the slot limit isn't what refuses it
    user = core.get_user(user["email"])
    core.add_api_key(user, "dup", "hf_aaa")
    ok, message = core.add_api_key(user, "dup", "hf_bbb")
    assert ok is False
    assert "label" in message.lower()


def test_empty_dataset_is_refused(user):
    with pytest.raises(ValueError):
        core.create_dataset(user["email"], "Empty", "", [], False, [])
