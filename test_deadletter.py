# message-broker/test_deadletter.py
import json
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import MessageBroker


def make_dl_item(idx: int):
    """Helper to make a dead letter payload dict"""
    return {
        "id": f"dl-{idx}",
        "source_service": "producer-x",
        "target_service": "consumer-y",
        "topic": "test.topic",
        "payload": {"value": idx},
        "reason": "simulated failure",
        "attempt_count": idx,
        "timestamp_ms": int(time.time() * 1000) + idx
    }

def test_rest_list_deadletters_by_topic(tmp_path, monkeypatch):
    data_dir = str(tmp_path / "broker_data")
    temp_broker = MessageBroker.DurableQueueBroker(data_dir=data_dir)

    # Monkeypatch repository-level broker with our isolated broker
    monkeypatch.setattr(MessageBroker, "broker", temp_broker)

    client = TestClient(MessageBroker.app)

    # publish two items to topic A and one item to topic B
    items_a = [make_dl_item(101), make_dl_item(102)]
    items_b = [make_dl_item(201)]

    for it in items_a:
        res = client.post("/deadletter/publish", json=it)
        assert res.status_code == 200
    for it in items_b:
        res = client.post("/deadletter/publish", json=it)
        assert res.status_code == 200

    # List for topic 'test.topic' (default topic in make_dl_item)
    res = client.get("/deadletter/list/test.topic?limit=50")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 3  # earlier tests may add items to same topic; if isolated tmp_path used, should be exactly 3
    ids = {it["id"] for it in data["items"]}
    assert "dl-101" in ids and "dl-102" in ids and "dl-201" in ids

    # If you want a per-topic only that returns exactly the ones for that specific topic name
    # Use a different topic name to ensure isolation:
    other_topic_item = make_dl_item(999)
    other_topic_item["topic"] = "other.topic"
    res2 = client.post("/deadletter/publish", json=other_topic_item)
    assert res2.status_code == 200

    res3 = client.get("/deadletter/list/other.topic?limit=50")
    assert res3.status_code == 200
    data3 = res3.json()
    ids3 = {it["id"] for it in data3["items"]}
    assert "dl-999" in ids3


def test_publish_and_list_deadletter_class(tmp_path):
    # Use isolated data directory
    data_dir = str(tmp_path / "broker_data")
    broker = MessageBroker.DurableQueueBroker(data_dir=data_dir)

    item = make_dl_item(1)
    broker.publish_dead_letter(item["topic"], item)

    items = broker.list_dead_letters(limit=10)
    assert isinstance(items, list)
    assert len(items) == 1
    assert items[0]["id"] == item["id"]
    assert items[0]["payload"] == {"value": 1}


def test_deadletter_persistence_across_reloads(tmp_path):
    data_dir = str(tmp_path / "broker_data")

    # Create a broker, publish several dead letters
    broker1 = MessageBroker.DurableQueueBroker(data_dir=data_dir)
    for i in range(3):
        broker1.publish_dead_letter("persist.topic", make_dl_item(i))

    # New broker instance should load persisted dead letters from disk
    broker2 = MessageBroker.DurableQueueBroker(data_dir=data_dir)
    all_items = broker2.list_dead_letters(limit=10)

    # ensure all items persisted and loaded
    assert len(all_items) >= 3
    ids = {it["id"] for it in all_items}
    assert {"dl-0", "dl-1", "dl-2"}.issubset(ids)


def test_rest_publish_and_list_endpoints(tmp_path, monkeypatch):
    """
    Replace the global `broker` with a broker pointing at tmp_path so tests don't touch
    repo data, then hit the REST endpoints using FastAPI TestClient.
    """
    data_dir = str(tmp_path / "broker_data")
    temp_broker = MessageBroker.DurableQueueBroker(data_dir=data_dir)

    # Monkeypatch the global broker object used by the API routes
    monkeypatch.setattr(MessageBroker, "broker", temp_broker)

    client = TestClient(MessageBroker.app)

    dl = make_dl_item(42)
    # Publish via HTTP endpoint
    res = client.post("/deadletter/publish", json=dl)
    assert res.status_code == 200
    assert res.json().get("ok") is True

    # List via HTTP endpoint
    res2 = client.get("/deadletter/list?limit=50")
    assert res2.status_code == 200
    j = res2.json()
    assert "items" in j
    assert j["count"] >= 1
    # find our id in returned items
    found_ids = [it["id"] for it in j["items"]]
    assert dl["id"] in found_ids