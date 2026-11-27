import stat
import time
import uuid

import pytest

from panclip.core.intelligence import offline_embedding
from panclip.core.storage import ClipStorage

EMBEDDER = "offline/test"


@pytest.fixture
def storage(tmp_path):
    return ClipStorage(tmp_path)


def add(storage, content, timestamp=None, embedder=EMBEDDER, tags=()):
    record = {
        "id": str(uuid.uuid4()),
        "content": content,
        "embedding": offline_embedding(content),
        "tags": list(tags),
        "timestamp": time.time() if timestamp is None else timestamp,
        "source": "agent",
        "is_agent": True,
        "embedder": embedder,
    }
    storage.add(record)
    return record["id"]


def test_store_directory_is_private(storage, tmp_path):
    add(storage, "hello")
    assert stat.S_IMODE((tmp_path / "lancedb").stat().st_mode) == 0o700


def test_crafted_id_is_refused_and_deletes_nothing(storage):
    for i in range(3):
        add(storage, f"clip {i}")
    for crafted in ["x' OR '1'='1", "' OR id IS NOT NULL OR '", "%"]:
        with pytest.raises(ValueError):
            storage.remove(crafted)
    assert storage.table.count_rows() == 3


def test_remove_deletes_exactly_one(storage):
    keep, drop = add(storage, "keep"), add(storage, "drop")
    assert storage.remove(drop)
    assert not storage.remove(drop)
    assert [row["id"] for row in storage.list_recent(10)] == [keep]


def test_search_only_compares_vectors_from_the_same_embedder(storage):
    mine = add(storage, "alpha")
    add(storage, "alpha", embedder="other/model")
    rows = storage.search(offline_embedding("alpha"), EMBEDDER, 10, 0)
    assert [row["id"] for row in rows] == [mine]
    assert rows[0]["score"] == 1.0


def test_list_pages_by_key(storage):
    now = time.time()
    ids = [add(storage, f"clip {i}", timestamp=now + i) for i in range(5)]
    first = storage.list_recent(2)
    second = storage.list_recent(2, (first[-1]["timestamp"], first[-1]["id"]))
    assert [row["id"] for row in first + second] == ids[::-1][:4]


def test_retention_drops_oldest_and_expired(storage):
    now = time.time()
    add(storage, "ancient", timestamp=now - 10 * 86400)
    ids = [add(storage, f"clip {i}", timestamp=now + i) for i in range(4)]
    assert storage.enforce_retention(max_clips=2, max_age_days=5) == 3
    assert {row["id"] for row in storage.list_recent(10)} == set(ids[2:])


def test_stats_never_include_the_path(storage, tmp_path):
    add(storage, "abc", tags=["x"])
    stats = storage.get_stats()
    assert stats["total_clips"] == 1
    assert stats["top_tags"] == [{"tag": "x", "count": 1}]
    assert str(tmp_path) not in repr(stats)
