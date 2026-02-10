import os
import uuid
import json
import psycopg2
from pgvector.psycopg2 import register_vector
from llm.helpers.embeddings import get_embeddings
from dotenv import load_dotenv

class SemanticMemory:
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
        self.vector_dim = 3072 
        self._initialize_db()

    def _get_connection(self):
        conn = psycopg2.connect(**self.db_config)
        return conn

    def _initialize_db(self):
        conn = self._get_connection()
        conn.autocommit = True
        cur = conn.cursor()
        try:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            
            # 1. Entities Table
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS entities (
                    id UUID PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT, -- person, org, tool, location, project
                    description TEXT,
                    embedding VECTOR({self.vector_dim}),
                    attributes JSONB DEFAULT '{{}}',
                    last_updated TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            # Index for entity resolution — HNSW caps at 2000 dims, skip if higher
            if self.vector_dim <= 2000:
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS entities_embedding_idx 
                    ON entities USING hnsw (embedding vector_cosine_ops);
                """)
            
            # 2. Relationships Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS entity_relationships (
                    id UUID PRIMARY KEY,
                    from_entity UUID REFERENCES entities(id),
                    relation TEXT,
                    to_entity UUID REFERENCES entities(id),
                    confidence FLOAT,
                    source TEXT,
                    last_updated TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(from_entity, relation, to_entity)
                );
            """)
            
            # Keep the old semantic_memory table for unstructured facts if needed, 
            # or we can migrate. For now, let's keep it as a fallback/cache.
            
        finally:
            cur.close()
            conn.close()

    def get_or_create_entity(self, name: str, type: str, description: str = ""):
        """
        Resolves an entity by name/embedding or creates a new one.
        """
        vector = self.embeddings.embed_query(name + " " + description)
        conn = self._get_connection()
        conn.autocommit = True
        cur = conn.cursor()
        
        try:
            # 1. Try to find existing entity by exact name match (case insensitive)
            cur.execute("SELECT id FROM entities WHERE LOWER(name) = LOWER(%s)", (name,))
            row = cur.fetchone()
            if row:
                return row[0]
            
            # 2. Try semantic search (fuzzy match) - strict threshold
            # If "Climate KIC" exists, "Climate-KIC" should match it.
            register_vector(conn)
            cur.execute(f"""
                SELECT id, name, 1 - (embedding <=> %s::vector) as similarity
                FROM entities
                WHERE 1 - (embedding <=> %s::vector) > 0.9
                ORDER BY similarity DESC
                LIMIT 1
            """, (vector, vector))
            row = cur.fetchone()
            if row:
                return row[0]

            # 3. Create new entity
            new_id = uuid.uuid4()
            cur.execute("""
                INSERT INTO entities (id, name, type, description, embedding)
                VALUES (%s, %s, %s, %s, %s)
            """, (str(new_id), name, type, description, vector))
            return str(new_id)
            
        finally:
            cur.close()
            conn.close()

    def add_relationship(self, from_name: str, from_type: str, relation: str, to_name: str, to_type: str, confidence: float = 1.0):
        """
        Links two entities. Creates them if they don't exist.
        """
        from_id = self.get_or_create_entity(from_name, from_type)
        to_id = self.get_or_create_entity(to_name, to_type)
        
        conn = self._get_connection()
        conn.autocommit = True
        cur = conn.cursor()
        
        try:
            rel_id = uuid.uuid4()
            cur.execute("""
                INSERT INTO entity_relationships (id, from_entity, relation, to_entity, confidence)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (from_entity, relation, to_entity) 
                DO UPDATE SET confidence = EXCLUDED.confidence, last_updated = NOW()
            """, (str(rel_id), from_id, relation, to_id, confidence))
        finally:
            cur.close()
            conn.close()

    def retrieve_relevant_knowledge(self, query: str, k: int = 5):
        """
        Retrieves entities and their relationships relevant to the query.
        """
        query_vector = self.embeddings.embed_query(query)
        conn = self._get_connection()
        register_vector(conn)
        cur = conn.cursor()
        
        try:
            # Find relevant entities first
            cur.execute(f"""
                SELECT id, name, type, description
                FROM entities
                WHERE 1 - (embedding <=> %s::vector) > 0.4
                ORDER BY embedding <=> %s::vector ASC
                LIMIT %s
            """, (query_vector, query_vector, k))
            
            entities = cur.fetchall()
            if not entities:
                return []
            
            entity_ids = [str(e[0]) for e in entities]
            placeholders = ','.join(['%s'] * len(entity_ids))
            
            # Find relationships connected to these entities
            # We join back to entities table to get names
            cur.execute(f"""
                SELECT 
                    e1.name AS from_name, 
                    r.relation, 
                    e2.name AS to_name,
                    r.confidence
                FROM entity_relationships r
                JOIN entities e1 ON r.from_entity = e1.id
                JOIN entities e2 ON r.to_entity = e2.id
                WHERE r.from_entity IN ({placeholders}) OR r.to_entity IN ({placeholders})
            """, entity_ids + entity_ids)
            
            results = []
            for row in cur.fetchall():
                results.append({
                    "content": f"{row[0]} {row[1]} {row[2]}",
                    "confidence": row[3]
                })
            return results
            
        finally:
            cur.close()
            conn.close()

    # Keep legacy method for compatibility if needed, or redirect
    def retrieve_facts(self, query: str, k: int = 5, threshold: float = 0.5):
        return self.retrieve_relevant_knowledge(query, k)
