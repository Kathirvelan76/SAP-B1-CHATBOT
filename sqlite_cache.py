import sqlite3
from datetime import datetime
import os

DB_PATH = "copilot_cache.db"

def init_db():
    """Creates the SQLite database and the cache table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Query_Cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            normalized_question TEXT UNIQUE,
            sql_query TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_cached_sql(question: str):
    """Fetches the cached SQL for a specific question. Returns None if not found."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT sql_query FROM Query_Cache WHERE normalized_question = ?", (question,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return result[0]  # Return the SQL string
    return None

def save_cached_sql(question: str, sql_query: str):
    """Saves the question and generated SQL into the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        # We use INSERT OR IGNORE so if the question already exists, it won't crash
        cursor.execute("""
            INSERT OR IGNORE INTO Query_Cache (normalized_question, sql_query, created_at)
            VALUES (?, ?, ?)
        """, (question, sql_query, current_time))
        conn.commit()
    except Exception as e:
        print(f"Database error: {e}")
    finally:
        conn.close()