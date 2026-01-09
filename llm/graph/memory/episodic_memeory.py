import os
import time
import math
import uuid
import json
from datetime import datetime, timedelta
import psycopg2
from pgvector.psycopg2 import register_vector
from llm.helpers.embeddings import get_embeddings
from dotenv import load_dotenv

class EpisodicMemory:
    def __init__(self, db_config=None):
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

        self.embeddings = get_embeddings()
        self.vector_dim = 768 
        
        self._initialize_db()

    def _get_connection(self):
        conn = psycopg2.connect(**self.db_config)
        return conn

    def _initialize_db(self):
        """Sets up the schema and enables pgvector extension."""
        conn = self._get_connection()
        conn.autocommit = True
        cur = conn.cursor()
        
        try:
            # Enable pgvector extension
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            
            # Create the table with the requested schema
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS episodic_memory (
                    id UUID PRIMARY KEY,
                    content TEXT NOT NULL,
                    embedding VECTOR({self.vector_dim}),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    importance FLOAT CHECK (importance >= 0 AND importance <= 1),
                    decay_rate FLOAT DEFAULT 0.01,
                    source_turns INT,
                    tags TEXT[],
                    role TEXT DEFAULT 'user',
                    expires_at TIMESTAMPTZ
                );
            """)
            
            # Ensure role column exists (for existing tables)
            cur.execute("ALTER TABLE episodic_memory ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'user';")
            # Ensure expires_at column exists
            cur.execute("ALTER TABLE episodic_memory ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;")
            
            # Create an HNSW index for faster similarity search
            cur.execute("""
                CREATE INDEX IF NOT EXISTS episodic_memory_embedding_idx 
                ON episodic_memory USING hnsw (embedding vector_cosine_ops);
            """)
            
        finally:
            cur.close()
            conn.close()

    def add_memory(self, content: str, importance: float, role: str = "user", source_turns: int = 1, tags: list = None, expiry_days: float = None):
        """
        Writes a summarized memory to the DB.
        Step 2 & 3 of your strategy (Summarize & Score) happen before calling this.
        """
        if tags is None:
            tags = []
            
        # Generate embedding
        vector = self.embeddings.embed_query(content)
        memory_id = uuid.uuid4()
        
        # Calculate expiration date if provided
        expires_at = None
        if expiry_days:
            expires_at = datetime.now() + timedelta(days=expiry_days)
        
        conn = self._get_connection()
        conn.autocommit = True
        cur = conn.cursor()
        
        try:
            cur.execute("""
                INSERT INTO episodic_memory 
                (id, content, embedding, importance, source_turns, tags, role, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (str(memory_id), content, vector, importance, source_turns, tags, role, expires_at))
        finally:
            cur.close()
            conn.close()

    def retrieve_memories(self, query: str, k: int = 5, alpha=0.5, beta=0.2, gamma=0.3):
        """
        Retrieval Strategy:
        1. Hard filters (importance > threshold) - handled in SQL
        2. Semantic Search (Cosine Similarity) - handled in SQL
        3. Re-ranking (Similarity + Recency + Importance) - handled in Python
        """
        query_vector = self.embeddings.embed_query(query)
        
        conn = self._get_connection()

        register_vector(conn)
        cur = conn.cursor()
        
        try:
            # Fetch candidates based on vector similarity first (get 3x k to allow for re-ranking)
            # We also fetch raw data to calculate the final score
            # 1 - (embedding <=> query) gives cosine similarity
            cur.execute(f"""
                SELECT 
                    id, 
                    content, 
                    created_at, 
                    importance, 
                    decay_rate,
                    role,
                    1 - (embedding <=> %s::vector) as similarity
                FROM episodic_memory
                WHERE importance > 0.1 
                AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY embedding <=> %s::vector ASC
                LIMIT %s
            """, (query_vector, query_vector, k * 3))
            
            rows = cur.fetchall()
            
            scored_memories = []
            now = datetime.now(rows[0][2].tzinfo) if rows else datetime.now()

            for row in rows:
                m_id, content, created_at, importance, decay_rate, role, similarity = row
            
                age_days = (now - created_at).total_seconds() / 86400.0
                recency_score = math.exp(-decay_rate * age_days)
            
                final_score = (alpha * similarity) + (beta * recency_score) + (gamma * importance)
                
                scored_memories.append({
                    "content": content,
                    "role": role,
                    "score": final_score,
                    "date": created_at.strftime("%Y-%m-%d"),
                    "debug": f"Sim:{similarity:.2f} Imp:{importance:.2f} Age:{age_days:.1f}d Role:{role}"
                })
            
            # Sort by final hybrid score
            scored_memories.sort(key=lambda x: x["score"], reverse=True)
            
            return scored_memories[:k]
            
        finally:
            cur.close()
            conn.close()

    def cleanup_memories(self, threshold: float = 0.05):
        """
        Decay Strategy:
        Remove memories where effective importance drops below threshold.
        effective_importance = importance * e^(-decay_rate * age)
        """
        conn = self._get_connection()
        conn.autocommit = True
        cur = conn.cursor()
        
        try:
            # We can do this calculation directly in SQL
            cur.execute("""
                DELETE FROM episodic_memory
                WHERE (importance * exp(-decay_rate * (EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400))) < %s
                OR (expires_at IS NOT NULL AND expires_at < NOW())
            """, (threshold,))
            
            deleted_count = cur.rowcount
            return deleted_count
        finally:
            cur.close()
            conn.close()
