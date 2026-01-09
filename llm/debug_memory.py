
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

db_config = {
    "dbname": os.getenv("POSTGRES_DBNAME", "sunday"),
    "user": os.getenv("POSTGRES_USER", "postgres"),
    "password": os.getenv("POSTGRES_PASSWORD", "postgres"),
    "host": os.getenv("POSTGRES_HOST", "127.0.0.1")
}

try:
    conn = psycopg2.connect(**db_config)
    cur = conn.cursor()
    
    print("--- Checking Semantic Memory Table ---")
    cur.execute("SELECT count(*) FROM semantic_memory;")
    count = cur.fetchone()[0]
    print(f"Total Facts: {count}")
    
    if count > 0:
        cur.execute("SELECT subject, predicate, object, content FROM semantic_memory LIMIT 10;")
        rows = cur.fetchall()
        for row in rows:
            print(f"Fact: {row[0]} {row[1]} {row[2]} | Content: {row[3]}")
    else:
        print("Table is empty.")
        
    cur.close()
    conn.close()
except Exception as e:
    print(f"Error: {e}")
