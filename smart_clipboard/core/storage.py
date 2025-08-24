"""LanceDB storage backend for clips."""

import os
import time
from typing import Any

import lancedb


class ClipStorage:
    """LanceDB storage backend for clips with vector search capabilities."""

    def __init__(self):
        # Use local storage in user's home directory
        self.db_path = os.path.join(os.getcwd(), ".smart-clipboard", "lancedb")
        os.makedirs(self.db_path, exist_ok=True)

        self.db = None
        self.table = None
        self._initialized = False

    async def _ensure_initialized(self):
        """Lazy initialization of LanceDB connection."""
        if self._initialized:
            return

        try:
            self.db = lancedb.connect(self.db_path)
            await self._init_table()
            self._initialized = True
        except Exception as e:
            print(f"Storage initialization error: {e}")
            raise

    async def _init_table(self):
        """Initialize clips table if not exists."""
        try:
            if "clips" not in self.db.table_names():
                # Create empty table with proper schema
                import pyarrow as pa

                schema = pa.schema([
                    ("id", pa.string()),
                    ("content", pa.string()),
                    ("embedding", pa.list_(pa.float32(), 768)),
                    ("tags", pa.list_(pa.string())),
                    ("timestamp", pa.float64()),
                    ("source", pa.string()),
                    ("is_agent", pa.bool_()),
                ])

                self.table = self.db.create_table("clips", schema=schema)
            else:
                self.table = self.db.open_table("clips")

        except Exception as e:
            print(f"Table initialization error: {e}")
            raise

    async def store(
        self,
        clip_id: str,
        content: str,
        embedding: list[float] | None,
        tags: list[str],
        metadata: dict[str, Any],
    ) -> bool:
        """Store clip with embedding and metadata."""
        await self._ensure_initialized()

        try:
            # Handle missing embedding
            if not embedding:
                embedding = [0.0] * 768

            record = {
                "id": clip_id,
                "content": content,
                "embedding": embedding,
                "tags": tags,
                "timestamp": time.time(),
                "source": metadata.get("source", "unknown"),
                "is_agent": metadata.get("is_agent", False),
            }

            # Check if record already exists
            try:
                existing = (
                    self.table.search().where(f"id = '{clip_id}'").limit(1).to_list()
                )
                if existing:
                    # Update existing record
                    self.table.delete(f"id = '{clip_id}'")
            except Exception:
                pass  # Record doesn't exist, which is fine

            # Add new record
            self.table.add([record])
            return True

        except Exception as e:
            print(f"Storage error: {e}")
            return False

    async def search(
        self, query_embedding: list[float], limit: int = 5
    ) -> list[dict[str, Any]]:
        """Semantic search using vector similarity."""
        await self._ensure_initialized()

        try:
            # Perform vector search
            results = self.table.search(query_embedding).limit(limit).to_list()

            # Format results
            formatted_results = []
            for result in results:
                # Calculate similarity score (distance -> similarity)
                similarity = max(0, 1.0 - result.get("_distance", 1.0))

                formatted_results.append(
                    {
                        "id": result["id"],
                        "content": result["content"],
                        "tags": result.get("tags", []),
                        "score": round(similarity, 3),
                        "metadata": {
                            "source": result.get("source", "unknown"),
                            "timestamp": result.get("timestamp", 0),
                            "is_agent": result.get("is_agent", False),
                        },
                    }
                )

            return formatted_results

        except Exception as e:
            print(f"Search error: {e}")
            return []

    async def list_recent(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get most recent clips ordered by timestamp."""
        await self._ensure_initialized()

        try:
            # Convert to pandas for easier sorting
            df = self.table.to_pandas()

            if len(df) == 0:
                return []

            # Sort by timestamp (most recent first)
            sorted_df = df.nlargest(limit, "timestamp")

            # Format results
            results = []
            for _, row in sorted_df.iterrows():
                results.append(
                    {
                        "id": row["id"],
                        "content": (
                            row["content"][:200] + "..."
                            if len(row["content"]) > 200
                            else row["content"]
                        ),
                        "tags": row.get("tags", []).tolist() if hasattr(row.get("tags", []), 'tolist') else row.get("tags", []),
                        "timestamp": row.get("timestamp", 0),
                        "source": row.get("source", "unknown"),
                    }
                )

            return results

        except Exception as e:
            print(f"List recent error: {e}")
            return []

    async def remove(self, clip_id: str) -> bool:
        """Remove a clip by ID."""
        await self._ensure_initialized()

        try:
            # Check if clip exists
            existing = self.table.search().where(f"id = '{clip_id}'").limit(1).to_list()
            if not existing:
                return False

            # Delete the clip
            self.table.delete(f"id = '{clip_id}'")
            return True

        except Exception as e:
            print(f"Remove error: {e}")
            return False

    async def get_stats(self) -> dict[str, Any]:
        """Get statistics about stored clips."""
        await self._ensure_initialized()

        try:
            df = self.table.to_pandas()

            if len(df) == 0:
                return {
                    "total_clips": 0,
                    "agent_clips": 0,
                    "manual_clips": 0,
                    "avg_content_length": 0,
                    "storage_path": self.db_path,
                }

            agent_clips = len(df[df["is_agent"]])
            manual_clips = len(df[~df["is_agent"]])
            avg_length = df["content"].str.len().mean()

            # Get most common tags
            all_tags = []
            for tags in df["tags"]:
                if isinstance(tags, list):
                    all_tags.extend(tags)

            tag_counts = {}
            for tag in all_tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

            top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

            return {
                "total_clips": len(df),
                "agent_clips": agent_clips,
                "manual_clips": manual_clips,
                "avg_content_length": round(avg_length, 1) if avg_length else 0,
                "top_tags": top_tags,
                "storage_path": self.db_path,
                "oldest_clip": df["timestamp"].min(),
                "newest_clip": df["timestamp"].max(),
            }

        except Exception as e:
            print(f"Stats error: {e}")
            return {"error": str(e)}

    async def get_clip(self, clip_id: str) -> dict[str, Any] | None:
        """Get a specific clip by ID."""
        await self._ensure_initialized()

        try:
            results = self.table.search().where(f"id = '{clip_id}'").limit(1).to_list()

            if not results:
                return None

            clip = results[0]
            return {
                "id": clip["id"],
                "content": clip["content"],
                "tags": clip.get("tags", []),
                "timestamp": clip.get("timestamp", 0),
                "source": clip.get("source", "unknown"),
                "is_agent": clip.get("is_agent", False),
            }

        except Exception as e:
            print(f"Get clip error: {e}")
            return None
