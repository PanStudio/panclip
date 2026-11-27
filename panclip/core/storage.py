"""LanceDB storage for clips."""

import logging
import re
import time
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa
import pyarrow.compute as pc
from lancedb.expr import Expr, col, lit
from lancedb.query import ColumnOrdering

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 768
CLIP_ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
CLIP_ID = re.compile(CLIP_ID_PATTERN)
NEWEST_FIRST = [
    ColumnOrdering(column_name="timestamp", ascending=False),
    ColumnOrdering(column_name="id", ascending=False),
]
OLDEST_FIRST = [
    ColumnOrdering(column_name="timestamp", ascending=True),
    ColumnOrdering(column_name="id", ascending=True),
]
FIELDS = ["id", "content", "tags", "timestamp", "source"]
SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("content", pa.string()),
        ("embedding", pa.list_(pa.float32(), EMBEDDING_DIM)),
        ("tags", pa.list_(pa.string())),
        ("timestamp", pa.float64()),
        ("source", pa.string()),
        ("is_agent", pa.bool_()),
        ("embedder", pa.string()),
    ]
)


def checked_id(clip_id: str) -> str:
    if not isinstance(clip_id, str) or not CLIP_ID.fullmatch(clip_id):
        raise ValueError("clip id is not a lowercase uuid")
    return clip_id


def id_is(clip_id: str) -> Expr:
    """Predicate matching one clip, with the id bound as an escaped literal."""
    return col("id") == lit(checked_id(clip_id))


class ClipStorage:
    """Clips in a LanceDB table under `<data_dir>/lancedb`."""

    def __init__(self, data_dir: Path):
        self.db_path = data_dir / "lancedb"
        self._table = None

    @property
    def table(self):
        if self._table is None:
            self.db_path.mkdir(parents=True, exist_ok=True, mode=0o700)
            db = lancedb.connect(str(self.db_path))
            self._table = db.create_table("clips", schema=SCHEMA, exist_ok=True)
        return self._table

    def add(self, record: dict[str, Any]) -> None:
        """Append one clip; the write is committed when this returns."""
        checked_id(record["id"])
        embedding = record["embedding"]
        if len(embedding) != EMBEDDING_DIM:
            raise ValueError(
                f"embedding has {len(embedding)} dimensions, the store holds {EMBEDDING_DIM}"
            )
        self.table.add([record])

    def enforce_retention(self, max_clips: int, max_age_days: float) -> int:
        """Delete clips past the age limit, then the oldest past the count limit."""
        removed = 0
        if max_age_days > 0:
            cutoff = time.time() - max_age_days * 86400
            removed += self.table.delete(
                col("timestamp") < lit(cutoff)
            ).num_deleted_rows
        if max_clips > 0:
            excess = self.table.count_rows() - max_clips
            if excess > 0:
                oldest = (
                    self.table.search()
                    .order_by(OLDEST_FIRST)
                    .select(["id", "timestamp"])
                    .limit(excess)
                    .to_list()
                )
                ids = [row["id"] for row in oldest if CLIP_ID.fullmatch(row["id"])]
                removed += self.table.delete(col("id").isin(ids)).num_deleted_rows
        return removed

    def search(
        self, embedding: list[float], embedder: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        """Clips embedded by `embedder`, closest first, with a cosine similarity score."""
        rows = (
            self.table.search(embedding)
            .distance_type("cosine")
            .where(col("embedder") == lit(embedder), prefilter=True)
            .select([*FIELDS, "_distance"])
            .offset(offset)
            .limit(limit)
            .to_list()
        )
        for row in rows:
            row["score"] = round(1.0 - row.pop("_distance", 1.0), 3)
        return rows

    def list_recent(
        self, limit: int, after: tuple[float, str] | None = None
    ) -> list[dict[str, Any]]:
        """Clips newest first, starting after the (timestamp, id) key of a previous page."""
        query = self.table.search()
        if after is not None:
            timestamp, clip_id = after
            query = query.where(
                (col("timestamp") < lit(timestamp)).or_(
                    (col("timestamp") == lit(timestamp)).and_(
                        col("id") < lit(checked_id(clip_id))
                    )
                )
            )
        return query.order_by(NEWEST_FIRST).select(FIELDS).limit(limit).to_list()

    def remove(self, clip_id: str) -> bool:
        return self.table.delete(id_is(clip_id)).num_deleted_rows > 0

    def get_clip(self, clip_id: str) -> dict[str, Any] | None:
        rows = (
            self.table.search().where(id_is(clip_id)).select(FIELDS).limit(1).to_list()
        )
        return rows[0] if rows else None

    def get_stats(self) -> dict[str, Any]:
        """Counts, content length, top tags and time span; never the storage path."""
        columns = ["content", "tags", "timestamp", "is_agent", "embedder"]
        data = self.table.search().select(columns).limit(None).to_arrow()
        total = data.num_rows
        if total == 0:
            return {
                "total_clips": 0,
                "agent_clips": 0,
                "manual_clips": 0,
                "avg_content_length": 0,
                "top_tags": [],
                "clips_by_embedder": {},
                "oldest_clip": None,
                "newest_clip": None,
            }
        agent = pc.sum(pc.cast(data["is_agent"], pa.int64())).as_py() or 0
        tag_counts = pc.value_counts(pc.list_flatten(data["tags"])).to_pylist()
        top = sorted(tag_counts, key=lambda item: (-item["counts"], item["values"]))[
            :10
        ]
        return {
            "total_clips": total,
            "agent_clips": agent,
            "manual_clips": total - agent,
            "avg_content_length": round(
                pc.mean(pc.utf8_length(data["content"])).as_py(), 1
            ),
            "top_tags": [
                {"tag": item["values"], "count": item["counts"]} for item in top
            ],
            "clips_by_embedder": {
                item["values"]: item["counts"]
                for item in pc.value_counts(data["embedder"]).to_pylist()
            },
            "oldest_clip": pc.min(data["timestamp"]).as_py(),
            "newest_clip": pc.max(data["timestamp"]).as_py(),
        }
