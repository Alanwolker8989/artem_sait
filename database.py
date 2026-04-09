import sqlite3
from datetime import datetime, timedelta

DB_NAME = "leads.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT NOT NULL,
            user_phone TEXT NOT NULL,
            contact_time TEXT NOT NULL,
            user_problem TEXT NOT NULL,
            created_at TEXT NOT NULL,
            ip_address TEXT,
            user_agent TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address TEXT NOT NULL,
            user_agent TEXT,
            visited_at TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_visits_date ON visits(visited_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_date ON leads(created_at)")
    conn.commit()
    conn.close()

def save_lead(user_name, user_phone, contact_time, user_problem, ip_address, user_agent):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO leads (user_name, user_phone, contact_time, user_problem, created_at, ip_address, user_agent) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_name, user_phone, contact_time, user_problem, datetime.now().isoformat(), ip_address, user_agent)
    )
    conn.commit()
    conn.close()

def get_all_leads():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows

def delete_lead(lead_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
    conn.commit()
    conn.close()

def add_visit(ip_address: str, user_agent: str):
    """Добавляет визит, только если с этого IP не было визита за последние 5 минут."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    five_min_ago = (datetime.now() - timedelta(minutes=5)).isoformat()
    cursor.execute(
        "SELECT 1 FROM visits WHERE ip_address = ? AND visited_at > ? LIMIT 1",
        (ip_address, five_min_ago)
    )
    if cursor.fetchone() is None:
        cursor.execute(
            "INSERT INTO visits (ip_address, user_agent, visited_at) VALUES (?, ?, ?)",
            (ip_address, user_agent, datetime.now().isoformat())
        )
        conn.commit()
    conn.close()

def get_visit_stats():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM visits")
    total = cursor.fetchone()[0]
    today = datetime.now().date().isoformat()
    cursor.execute("SELECT COUNT(*) FROM visits WHERE visited_at LIKE ?", (today + "%",))
    today_visits = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT ip_address) FROM visits")
    unique_ips = cursor.fetchone()[0]
    conn.close()
    return {"total": total, "today": today_visits, "unique_ips": unique_ips}

def delete_all_visits():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM visits")
    conn.commit()
    conn.close()