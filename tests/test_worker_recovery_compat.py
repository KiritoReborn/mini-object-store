import pytest


@pytest.mark.parametrize("index, canonical", [
    ("0", True), ("1", True), ("9", True), ("10", True),
    ("99", True), ("100", True), ("007", False), ("00", False), ("01", False),
])
def test_worker_chunk_ids_are_compatible_with_recovery(monkeypatch, index, canonical):
    monkeypatch.setenv("WORKER_ID", "worker_test")
    from controller.recovery import _CHUNK_ID
    from worker.storage import valid_id

    chunk_id = "550e8400-e29b-41d4-a716-446655440000_" + index
    accepted = valid_id(chunk_id)
    assert accepted is canonical
    if accepted:
        assert _CHUNK_ID.fullmatch(chunk_id) is not None
