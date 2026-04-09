import sqlite3
from datetime import datetime

DB_NAME = "leads.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Ваша существующая таблица leads (оставляем как есть)
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
    
    # НОВАЯ таблица для посещений
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address TEXT NOT NULL,
            user_agent TEXT,
            visited_at TEXT NOT NULL
        )
    """)
    
    # Индексы для ускорения запросов
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_visits_date ON visits(visited_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_date ON leads(created_at)")
    
    conn.commit()
    conn.close()

def save_lead(user_name: str, user_phone: str, contact_time: str, user_problem: str, ip_address: str, user_agent: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    query = "INSERT INTO leads (user_name, user_phone, contact_time, user_problem, created_at, ip_address, user_agent) VALUES (?, ?, ?, ?, ?, ?, ?)"
    values = (user_name, user_phone, contact_time, user_problem, datetime.now().isoformat(), ip_address, user_agent)
    cursor.execute(query, values)
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

# ========== НОВЫЕ ФУНКЦИИ ДЛЯ ПОСЕЩЕНИЙ ==========

def add_visit(ip_address: str, user_agent: str):
    """Добавляет запись о посещении сайта"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO visits (ip_address, user_agent, visited_at) VALUES (?, ?, ?)",
        (ip_address, user_agent, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_visit_stats():
    """Возвращает статистику посещений"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Общее число посещений
    cursor.execute("SELECT COUNT(*) FROM visits")
    total = cursor.fetchone()[0]
    
    # Посещения за сегодня (по UTC)
    today = datetime.now().date().isoformat()
    cursor.execute(
        "SELECT COUNT(*) FROM visits WHERE visited_at LIKE ?",
        (today + "%",)
    )
    today_visits = cursor.fetchone()[0]
    
    # Уникальные IP
    cursor.execute("SELECT COUNT(DISTINCT ip_address) FROM visits")
    unique_ips = cursor.fetchone()[0]
    
    # Последние 10 посещений
    cursor.execute(
        "SELECT ip_address, user_agent, visited_at FROM visits ORDER BY visited_at DESC LIMIT 10"
    )
    recent = cursor.fetchall()
    
    conn.close()
    
    return {
        "total": total,
        "today": today_visits,
        "unique_ips": unique_ips,
        "recent": recent  # список кортежей (ip, user_agent, visited_at)
    }