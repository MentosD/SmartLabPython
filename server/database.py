import sqlite3
import os

from passlib.context import CryptContext

DB_PATH = os.path.join(os.path.dirname(__file__), "smart_lab.db")
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 资产表 (增强版)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_no TEXT UNIQUE,
            name TEXT NOT NULL,
            category TEXT,
            model TEXT,
            sn TEXT,
            location TEXT,
            status TEXT DEFAULT '在库',
            current_user TEXT,
            buy_date TEXT
        )
    ''')
    
    # 动态检查并补全可能缺失的列 (防止旧数据库升级报错)
    cursor.execute("PRAGMA table_info(assets)")
    columns = [col[1] for col in cursor.fetchall()]
    needed = [
        ("asset_no", "TEXT"), ("model", "TEXT"), 
        ("sn", "TEXT"), ("location", "TEXT"), 
        ("current_user", "TEXT"), ("buy_date", "TEXT")
    ]
    for col_name, col_type in needed:
        if col_name not in columns:
            try:
                cursor.execute(f"ALTER TABLE assets ADD COLUMN {col_name} {col_type}")
                print(f"Migration: Added column {col_name} to assets table.")
            except: pass
    
    # 资产借用/归还日志
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS borrow_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER,
            username TEXT,
            action TEXT,                 -- 借用 / 归还
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(asset_id) REFERENCES assets(id)
        )
    ''')
    
    # 用户表 (增加所属组字段)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            group_name TEXT DEFAULT '未分配'
        )
    ''')
    
    # 动态检查 users 表是否需要迁移 (针对旧数据)
    cursor.execute("PRAGMA table_info(users)")
    user_cols = [col[1] for col in cursor.fetchall()]
    if "group_name" not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN group_name TEXT DEFAULT '未分配'")

    # 课题组/用户组表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    ''')

    # NAS 文件存储表 (核心权限表)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS nas_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,         -- 原始文件名
            storage_name TEXT NOT NULL,     -- 硬盘存储名 (UUID)
            size INTEGER,                   -- 文件大小 (Bytes)
            uploader TEXT,                  -- 上传者 username
            upload_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            permission_type TEXT,           -- 'private', 'public', 'custom'
            allowed_groups TEXT,            -- JSON 数组 ["组A", "组B"]
            allowed_users TEXT,             -- JSON 数组 ["user1", "user2"]
            allow_write INTEGER DEFAULT 0   -- 是否允许被授权者删除/覆盖 (0: 否, 1: 是)
        )
    ''')
    
    # 初始化一些默认组
    cursor.execute("SELECT COUNT(*) FROM groups")
    if cursor.fetchone()[0] == 0:
        default_groups = ["结构工程组", "岩土工程组", "桥梁工程组", "防灾减灾组", "风工程组"]
        for g in default_groups:
            cursor.execute("INSERT INTO groups (name) VALUES (?)", (g,))

    # 传感器通道配置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channel_configs (
            channel_id TEXT PRIMARY KEY, 
            display_name TEXT, 
            unit TEXT, 
            scale REAL DEFAULT 1.0, 
            offset REAL DEFAULT 0.0
        )
    ''')

    # 摄像头配置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cameras (
            id INTEGER PRIMARY KEY,
            name TEXT,
            rtsp_url TEXT
        )
    ''')

    # 初始化管理员账号 admin / admin123
    cursor.execute("SELECT COUNT(*) FROM users WHERE username='admin'")
    if cursor.fetchone()[0] == 0:
        h = pwd_context.hash("admin123")
        cursor.execute("INSERT INTO users (username, password_hash, role, group_name) VALUES (?, ?, ?, ?)", 
                     ("admin", h, "admin", "系统管理组"))

    # 初始化4个空位
    cursor.execute("SELECT COUNT(*) FROM cameras")
    if cursor.fetchone()[0] == 0:
        for i in range(4):
            cursor.execute("INSERT INTO cameras (id, name, rtsp_url) VALUES (?, ?, ?)", 
                         (i, f"通道 {i+1}", ""))
            
    conn.commit()
    conn.close()

def get_all_channel_configs():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM channel_configs")
    rows = c.fetchall()
    conn.close()
    return {r[0]: {"name": r[1], "unit": r[2], "scale": r[3], "offset": r[4]} for r in rows}

def update_channel_config(channel_id, name, unit, scale, offset):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO channel_configs (channel_id, display_name, unit, scale, offset) VALUES (?, ?, ?, ?, ?)",
              (channel_id, name, unit, scale, offset))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
