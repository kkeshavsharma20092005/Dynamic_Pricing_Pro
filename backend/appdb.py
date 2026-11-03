"""SQLite storage for the ride app. Standard library only, so a fresh clone just runs."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager

from config import DATA_DIR

DB_PATH = os.environ.get("APP_DB_PATH", str(DATA_DIR / "app.db"))
PBKDF2_ROUNDS = 240_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    phone TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('rider', 'driver', 'admin')),
    vehicle TEXT,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE (phone, role)
);
CREATE TABLE IF NOT EXISTS rides (
    id INTEGER PRIMARY KEY,
    rider_id INTEGER NOT NULL REFERENCES users(id),
    driver_id INTEGER REFERENCES users(id),
    sim_driver TEXT,
    status TEXT NOT NULL,
    pickup TEXT NOT NULL,
    dropoff TEXT NOT NULL,
    vehicle TEXT NOT NULL,
    region TEXT NOT NULL,
    km REAL NOT NULL,
    minutes INTEGER NOT NULL,
    fare INTEGER NOT NULL,
    quote TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS rides_rider ON rides(rider_id);
CREATE INDEX IF NOT EXISTS rides_driver ON rides(driver_id);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    ride_id INTEGER NOT NULL REFERENCES rides(id),
    sender TEXT NOT NULL CHECK (sender IN ('rider', 'driver')),
    body TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_ride ON messages(ride_id);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def migrate_users_to_per_role_accounts():
    """Older databases allowed one account per number across all roles."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        row = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'users'").fetchone()
        if row and "UNIQUE (phone, role)" not in row[0]:
            conn.executescript("""
                PRAGMA foreign_keys = OFF;
                BEGIN;
                CREATE TABLE users_new (
                    id INTEGER PRIMARY KEY, phone TEXT NOT NULL, name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('rider', 'driver', 'admin')),
                    vehicle TEXT, password_hash TEXT NOT NULL, salt TEXT NOT NULL,
                    created_at REAL NOT NULL, UNIQUE (phone, role));
                INSERT INTO users_new SELECT id, phone, name, role, vehicle, password_hash, salt, created_at FROM users;
                DROP TABLE users;
                ALTER TABLE users_new RENAME TO users;
                COMMIT;
            """)
    finally:
        conn.close()


def init_db():
    migrate_users_to_per_role_accounts()
    with connect() as conn:
        conn.executescript(SCHEMA)


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()


def create_user(phone, name, role, password, vehicle=None) -> int:
    salt = secrets.token_hex(16)
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO users (phone, name, role, vehicle, password_hash, salt, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (phone, name, role, vehicle, hash_password(password, salt), salt, time.time()))
        return cursor.lastrowid


def verify_user(phone, password, role):
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE phone = ? AND role = ?", (phone, role)).fetchone()
    if row is None:
        return None
    if not hmac.compare_digest(row["password_hash"], hash_password(password, row["salt"])):
        return None
    return dict(row)


def get_user(user_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_setting(key, default=None):
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(key, value):
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)))


def ensure_admin() -> str | None:
    """
    Create the admin account if missing. There is no default password in the code: it
    comes from ADMIN_PASSWORD, or is generated and returned for one-time display.
    """
    phone = os.environ.get("ADMIN_PHONE", "9000000000")
    with connect() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE phone = ? AND role = 'admin'", (phone,)).fetchone()
    if exists:
        return None
    password = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(9)
    create_user(phone, "Admin", "admin", password)
    return None if os.environ.get("ADMIN_PASSWORD") else f"{phone} / {password}"
