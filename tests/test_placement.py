import pytest


def test_placement_is_distinct_alive_least_loaded_and_deterministic():
    from controller.placement import choose_workers
    workers = [
        {"worker_id": "w2", "status": "ALIVE", "chunk_count": 0},
        {"worker_id": "w1", "status": "ALIVE", "chunk_count": 0},
        {"worker_id": "w3", "status": "ALIVE", "chunk_count": 3},
        {"worker_id": "dead", "status": "DEAD", "chunk_count": 0},
        {"worker_id": "joining", "status": "JOINING", "chunk_count": 0},
    ]
    assert [w["worker_id"] for w in choose_workers(workers, set(), 2)] == ["w1", "w2"]
    assert [w["worker_id"] for w in choose_workers(workers, {"w1"}, 2)] == ["w2", "w3"]


def test_placement_fails_instead_of_silently_under_replicating():
    from controller.placement import InsufficientWorkers, choose_workers
    with pytest.raises(InsufficientWorkers):
        choose_workers([{"worker_id": "w1", "status": "ALIVE", "chunk_count": 0}], set(), 2)


def test_placement_excludes_an_alive_record_with_expired_heartbeat():
    from controller.placement import InsufficientWorkers, choose_workers
    with pytest.raises(InsufficientWorkers):
        choose_workers([{"worker_id": "w1", "status": "ALIVE", "chunk_count": 0,
                         "last_heartbeat": "2000-01-01T00:00:00+00:00"}], set(), 1)
