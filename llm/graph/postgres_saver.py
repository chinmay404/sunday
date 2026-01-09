import json
import pickle
import psycopg2
import os
from typing import Any, Optional, Iterator
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint, CheckpointMetadata, CheckpointTuple
from dotenv import load_dotenv

class PostgresSaver(BaseCheckpointSaver):
    def __init__(self, db_config=None):
        super().__init__()
        load_dotenv()
        if db_config is None:
            self.db_config = {
                "dbname": os.getenv("POSTGRES_DBNAME", "sunday"),
                "user": os.getenv("POSTGRES_USER", "postgres"),
                "password": os.getenv("POSTGRES_PASSWORD", "postgres"),
                "host": os.getenv("POSTGRES_HOST", "127.0.0.1")
            }
        else:
            self.db_config = db_config
        self._init_table()

    def _get_connection(self):
        return psycopg2.connect(**self.db_config)

    def _init_table(self):
        conn = self._get_connection()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    thread_id TEXT,
                    checkpoint_id TEXT,
                    parent_checkpoint_id TEXT,
                    checkpoint BYTEA,
                    metadata JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (thread_id, checkpoint_id)
                );
            """)
        conn.close()

    def _thread_id_from_config(self, config: RunnableConfig) -> str:
        configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
        return str(configurable.get("thread_id", "default"))

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        thread_id = self._thread_id_from_config(config)
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT checkpoint, metadata, parent_checkpoint_id, checkpoint_id
                    FROM checkpoints 
                    WHERE thread_id = %s 
                    ORDER BY created_at DESC 
                    LIMIT 1
                """, (thread_id,))
                row = cur.fetchone()
                
            if row:
                checkpoint_data, metadata, parent_id, checkpoint_id = row
                return CheckpointTuple(
                    config=config,
                    checkpoint=pickle.loads(checkpoint_data),
                    metadata=metadata,
                    parent_config={"configurable": {"thread_id": thread_id, "checkpoint_id": parent_id}} if parent_id else None
                )
        except Exception as e:
            print(f"Error getting checkpoint: {e}")
        finally:
            conn.close()
        return None

    def put(self, config: RunnableConfig, checkpoint: Checkpoint, metadata: CheckpointMetadata, new_versions: dict) -> RunnableConfig:
        thread_id = self._thread_id_from_config(config)
        checkpoint_id = checkpoint["id"]
        parent_id = config.get("configurable", {}).get("checkpoint_id") if isinstance(config, dict) else None
        
        conn = self._get_connection()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO checkpoints (thread_id, checkpoint_id, parent_checkpoint_id, checkpoint, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (thread_id, checkpoint_id) DO UPDATE 
                    SET checkpoint = EXCLUDED.checkpoint, metadata = EXCLUDED.metadata
                """, (
                    thread_id, 
                    checkpoint_id, 
                    parent_id, 
                    pickle.dumps(checkpoint), 
                    json.dumps(metadata)
                ))
        except Exception as e:
            print(f"Error saving checkpoint: {e}")
        finally:
            conn.close()
            
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id
            }
        }
        
    def list(self, config: Optional[RunnableConfig], *, filter: Optional[dict] = None, before: Optional[RunnableConfig] = None, limit: Optional[int] = None) -> Iterator[CheckpointTuple]:
        thread_id = self._thread_id_from_config(config or {})
        limit = limit or 10
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT checkpoint, metadata, parent_checkpoint_id, checkpoint_id
                    FROM checkpoints
                    WHERE thread_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (thread_id, limit))
                rows = cur.fetchall()
                for row in rows:
                    checkpoint_data, metadata, parent_id, checkpoint_id = row
                    yield CheckpointTuple(
                        config={"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}},
                        checkpoint=pickle.loads(checkpoint_data),
                        metadata=metadata,
                        parent_config={"configurable": {"thread_id": thread_id, "checkpoint_id": parent_id}} if parent_id else None
                    )
        except Exception as e:
            print(f"Error listing checkpoints: {e}")
        finally:
            conn.close()

    # LangGraph will call put_writes for intermediate channel writes; we do not persist them yet.
    def put_writes(self, config: RunnableConfig, writes, task_id: str, task_path: str = "") -> None:
        # No-op implementation to satisfy BaseCheckpointSaver requirements.
        return None
