import os
from pathlib import Path
from typing import Any, Dict, Optional

import psycopg2
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")


def get_db_config() -> Dict[str, Any]:
    return {
        "dbname": os.getenv("POSTGRES_DBNAME", "sunday"),
        "user": os.getenv("POSTGRES_USER", "postgres"),
        "password": os.getenv("POSTGRES_PASSWORD", "postgres"),
        "host": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
    }


def get_connection(db_config: Optional[Dict[str, Any]] = None):
    return psycopg2.connect(**(db_config or get_db_config()))
