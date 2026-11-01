#!/usr/bin/env python3
"""WaysGram standalone backend (SQLite + REST API; no Telegram dependencies)."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import ipaddress
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("NEXUSGRAM_DB", str(ROOT / "waysgram.db")))
HOST = os.environ.get("NEXUSGRAM_HOST", "127.0.0.1")
PORT = int(os.environ.get("NEXUSGRAM_PORT", "8080"))
ADMIN_USER = os.environ.get("NEXUSGRAM_ADMIN_USER", "")
ADMIN_PASSWORD = os.environ.get("NEXUSGRAM_ADMIN_PASSWORD", "")
DEV_OTP = os.environ.get("NEXUSGRAM_DEV_OTP", "0") == "1"
TEST_PHONES = {x.strip() for x in os.environ.get("NEXUSGRAM_TEST_PHONES", "").split(",") if x.strip()}
AUTHBOT_URL = os.environ.get("NEXUSGRAM_AUTHBOT_URL", "").strip().rstrip("/")
AUTHBOT_TOKEN = os.environ.get("NEXUSGRAM_AUTHBOT_TOKEN", "").strip()
TRUST_PROXY_HEADERS = os.environ.get("NEXUSGRAM_TRUST_PROXY_HEADERS", "0") == "1"
OTP_TTL = 300
SESSION_TTL = 60 * 60 * 24 * 30
ADMIN_SESSION_TTL = 60 * 60 * 8
MAX_BODY = 32768
DM_MESSAGES_PER_MINUTE = 30
CHANNEL_POSTS_PER_MINUTE = 20


@contextmanager
def db():
    """Open one SQLite connection per operation and always close it."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=20000")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL UNIQUE,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL DEFAULT '',
            stars INTEGER NOT NULL DEFAULT 0 CHECK(stars >= 0),
            grams INTEGER NOT NULL DEFAULT 0 CHECK(grams >= 0),
            is_banned INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS otp_codes (
            phone TEXT PRIMARY KEY,
            code_hash TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            requested_at INTEGER NOT NULL,
            source TEXT NOT NULL DEFAULT 'legacy_local'
        );
        CREATE TABLE IF NOT EXISTS otp_request_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            ip TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_otp_phone_time ON otp_request_log(phone,created_at);
        CREATE INDEX IF NOT EXISTS idx_otp_ip_time ON otp_request_log(ip,created_at);
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS admin_sessions (
            token_hash TEXT PRIMARY KEY,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS admin_login_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_admin_login_ip_time ON admin_login_log(ip,created_at);
        CREATE TABLE IF NOT EXISTS star_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            amount INTEGER NOT NULL CHECK(amount > 0),
            admin_name TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_star_transactions_user ON star_transactions(user_id,id DESC);
        CREATE TABLE IF NOT EXISTS gifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            price INTEGER NOT NULL CHECK(price >= 0),
            supply INTEGER NOT NULL CHECK(supply >= 0),
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_gifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            serial_number TEXT NOT NULL UNIQUE,
            gift_id INTEGER REFERENCES gifts(id) ON DELETE SET NULL,
            gift_name TEXT NOT NULL,
            owner_user_id INTEGER NOT NULL REFERENCES users(id),
            acquired_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_user_gifts_owner ON user_gifts(owner_user_id, id DESC);
        CREATE TABLE IF NOT EXISTS gram_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            amount INTEGER NOT NULL CHECK(amount <> 0),
            balance_after INTEGER NOT NULL CHECK(balance_after >= 0),
            reason TEXT NOT NULL,
            related_user_id INTEGER REFERENCES users(id),
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_gram_transactions_user ON gram_transactions(user_id,id DESC);
        CREATE TABLE IF NOT EXISTS gift_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL CHECK(event_type IN ('purchase','transfer')),
            gift_instance_id INTEGER NOT NULL REFERENCES user_gifts(id),
            from_user_id INTEGER REFERENCES users(id),
            to_user_id INTEGER NOT NULL REFERENCES users(id),
            amount_grams INTEGER NOT NULL DEFAULT 0 CHECK(amount_grams >= 0),
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_gift_transactions_instance ON gift_transactions(gift_instance_id,id DESC);
        CREATE INDEX IF NOT EXISTS idx_gift_transactions_user ON gift_transactions(to_user_id,id DESC);
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            owner_user_id INTEGER NOT NULL REFERENCES users(id),
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS channel_admins (
            channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at INTEGER NOT NULL,
            PRIMARY KEY(channel_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS channel_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
            author_id INTEGER NOT NULL REFERENCES users(id),
            body TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_channel_messages ON channel_messages(channel_id,id DESC);
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL REFERENCES users(id),
            recipient_id INTEGER NOT NULL REFERENCES users(id),
            body TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_pair ON messages(sender_id,recipient_id,id);
        CREATE INDEX IF NOT EXISTS idx_messages_sender_time ON messages(sender_id,created_at);
        CREATE INDEX IF NOT EXISTS idx_channel_messages_author_time ON channel_messages(author_id,created_at);
        CREATE TABLE IF NOT EXISTS idempotency_records (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            scope TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            response_status INTEGER NOT NULL,
            response_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            PRIMARY KEY(user_id, scope, idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS idx_idempotency_created ON idempotency_records(created_at);
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)
        # Upgrade older WaysGram databases without deleting user data.
        cols = _columns(c, "users")
        if "display_name" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
        if "grams" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN grams INTEGER NOT NULL DEFAULT 0 CHECK(grams >= 0)")
        otp_cols = _columns(c, "otp_codes")
        if "source" not in otp_cols:
            c.execute("ALTER TABLE otp_codes ADD COLUMN source TEXT NOT NULL DEFAULT 'legacy_local'")
        # Keep a persistent OTP pepper in the database if the operator did not provide one.
        if not os.environ.get("NEXUSGRAM_OTP_SECRET"):
            if not c.execute("SELECT 1 FROM app_settings WHERE key='otp_secret'").fetchone():
                c.execute("INSERT INTO app_settings(key,value) VALUES('otp_secret',?)", (secrets.token_hex(32),))


def app_secret():
    supplied = os.environ.get("NEXUSGRAM_OTP_SECRET")
    if supplied:
        return supplied.encode("utf-8")
    with db() as c:
        row = c.execute("SELECT value FROM app_settings WHERE key='otp_secret'").fetchone()
        if not row:
            secret = secrets.token_hex(32)
            c.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('otp_secret',?)", (secret,))
            row = c.execute("SELECT value FROM app_settings WHERE key='otp_secret'").fetchone()
        return row["value"].encode("utf-8")


def json_bytes(data):
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def otp_hash(phone: str, code: str) -> str:
    return hmac.new(app_secret(), f"{phone}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()


def valid_phone(phone: str) -> bool:
    # WaysGram virtual IDs are issued by AuthWaysGram_bot and always use +1 + ten digits.
    return bool(re.fullmatch(r"\+1[0-9]{10}", phone))


def clean_username(value: str) -> str:
    value = str(value).strip().lstrip("@").lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", value):
        raise ValueError("Username: 1–32 символа, латиница, цифры и _, первый символ — буква")
    return value


def authbot_request(endpoint: str, payload: dict):
    """Call the private AuthWaysGram bot API without exposing its shared secret."""
    if not AUTHBOT_URL or not AUTHBOT_TOKEN:
        raise ApiError(503, "AuthWaysGram_bot не настроен: задайте NEXUSGRAM_AUTHBOT_URL и NEXUSGRAM_AUTHBOT_TOKEN")

    parsed = urlparse(AUTHBOT_URL)
    local_http = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not local_http:
        raise ApiError(503, "Для AuthWaysGram_bot требуется HTTPS")

    url = AUTHBOT_URL + endpoint
    body = json_bytes(payload)
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "X-Internal-Token": AUTHBOT_TOKEN,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.status
            raw = response.read(8192)
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read(8192)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ApiError(503, "AuthWaysGram_bot временно недоступен") from None

    try:
        result = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ApiError(502, "AuthWaysGram_bot вернул некорректный ответ") from None

    if not 200 <= status < 300:
        if status == 401:
            raise ApiError(503, "Внутренний ключ AuthWaysGram_bot настроен неверно")
        if status == 403:
            raise ApiError(403, "Сначала откройте AuthWaysGram_bot и пройдите CAPTCHA")
        if status == 404:
            raise ApiError(404, "Номер не закреплён за пользователем в AuthWaysGram_bot")
        if status == 429:
            raise ApiError(429, "Повторный запрос кода пока недоступен")
        raise ApiError(503, "AuthWaysGram_bot не смог выполнить запрос")
    return result


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Handler(BaseHTTPRequestHandler):
    server_version = "WaysGram"
    sys_version = ""

    def log_message(self, fmt, *args):
        # Never log request bodies, passwords, bearer tokens, or OTP values.
        super().log_message(fmt, *args)

    def send_json(self, status, payload):
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(400, "Некорректный Content-Length")
        if length < 0 or length > MAX_BODY:
            raise ApiError(413, "Тело запроса слишком большое")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "Ожидается корректный JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "Ожидается JSON-объект")
        return data

    def bearer(self):
        value = self.headers.get("Authorization", "")
        return value[7:].strip() if value.startswith("Bearer ") else None

    def idempotency_descriptor(self, path, data):
        """Validate an optional client key and bind it to the exact route/body."""
        key = self.headers.get("Idempotency-Key", "").strip()
        if not key:
            return None
        if len(key) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", key):
            raise ApiError(400, "Некорректный Idempotency-Key")
        canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256((path + "\n" + canonical).encode("utf-8")).hexdigest()
        return key, digest

    @staticmethod
    def idempotency_lookup(conn, user_id, scope, descriptor):
        if descriptor is None:
            return None
        key, request_hash = descriptor
        row = conn.execute(
            "SELECT request_hash,response_status,response_json FROM idempotency_records "
            "WHERE user_id=? AND scope=? AND idempotency_key=? AND created_at>=?",
            (user_id, scope, key, int(time.time()) - 7 * 86400),
        ).fetchone()
        if not row:
            return None
        if not hmac.compare_digest(row["request_hash"], request_hash):
            raise ApiError(409, "Этот Idempotency-Key уже использован для другого запроса")
        try:
            payload = json.loads(row["response_json"])
        except json.JSONDecodeError:
            raise ApiError(500, "Не удалось восстановить результат предыдущего запроса") from None
        return row["response_status"], payload

    @staticmethod
    def idempotency_store(conn, user_id, scope, descriptor, status, payload, now):
        if descriptor is None:
            return
        key, request_hash = descriptor
        # Remove expired keys before INSERT so reusing an expired key can start a new operation.
        conn.execute("DELETE FROM idempotency_records WHERE created_at<?", (now - 7 * 86400,))
        conn.execute(
            "INSERT INTO idempotency_records "
            "(user_id,scope,idempotency_key,request_hash,response_status,response_json,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (user_id, scope, key, request_hash, status,
             json.dumps(payload, ensure_ascii=False, separators=(",", ":")), now),
        )

    def current_user(self):
        token = self.bearer()
        if not token:
            raise ApiError(401, "Требуется вход")
        with db() as c:
            row = c.execute("""SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.expires_at>?""", (token_hash(token), int(time.time()))).fetchone()
        if not row:
            raise ApiError(401, "Сессия истекла или недействительна")
        if row["is_banned"]:
            raise ApiError(403, "Аккаунт заблокирован")
        return row

    def admin_required(self):
        if not ADMIN_USER or not ADMIN_PASSWORD:
            raise ApiError(503, "Администратор не настроен: задайте NEXUSGRAM_ADMIN_USER и NEXUSGRAM_ADMIN_PASSWORD")
        token = self.bearer()
        if not token:
            raise ApiError(401, "Требуется вход администратора")
        with db() as c:
            row = c.execute("SELECT expires_at FROM admin_sessions WHERE token_hash=?", (token_hash(token),)).fetchone()
            if not row or row["expires_at"] <= int(time.time()):
                if row:
                    c.execute("DELETE FROM admin_sessions WHERE token_hash=?", (token_hash(token),))
                raise ApiError(401, "Сессия администратора истекла")

    def client_ip(self):
        """Return the socket peer IP, or a forwarded IP from an explicitly trusted local proxy."""
        if not self.client_address:
            return "unknown"
        peer = self.client_address[0]
        try:
            peer_ip = ipaddress.ip_address(peer)
        except ValueError:
            return "unknown"

        # Forwarded headers are attacker-controlled unless the connection came from
        # localhost (the configured reverse proxy) and proxy trust was explicitly enabled.
        if TRUST_PROXY_HEADERS and peer_ip.is_loopback:
            forwarded = self.headers.get("X-Forwarded-For", "") if self.headers else ""
            candidate = forwarded.split(",", 1)[0].strip()
            if candidate:
                try:
                    return str(ipaddress.ip_address(candidate))
                except ValueError:
                    pass
        return str(peer_ip)

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path in ("/", "/health"):
                self.send_json(200, {"name": "WaysGram", "status": "online", "version": "0.5.0", "api": True, "backend": "standalone", "database": "sqlite"})
                return
            if path == "/api/config":
                self.send_json(200, {"brand": "WaysGram", "api_version": 1, "auth": "authwaysgram_bot", "authbot_delivery_ready": bool(AUTHBOT_URL and AUTHBOT_TOKEN), "sms_delivery_ready": False, "test_otp_enabled": bool(DEV_OTP and TEST_PHONES), "currencies": ["stars", "grams"], "gift_model": "internal_collectible", "messaging_limits": {"direct_messages_per_minute": DM_MESSAGES_PER_MINUTE, "channel_posts_per_minute": CHANNEL_POSTS_PER_MINUTE, "message_characters": 4000}, "features": ["profiles", "direct_messages", "incremental_messages", "channels", "incremental_channel_posts", "idempotent_writes", "session_refresh", "gifts", "gift_inventory", "gift_transfer", "stars", "grams"]})
                return
            if path == "/admin":
                page = (ROOT / "static" / "admin.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(page)
                return
            if path == "/api/me":
                u = self.current_user()
                self.send_json(200, self.public_user(u, include_phone=True, include_stars=True, include_grams=True))
                return
            if path == "/api/me/wallet":
                u = self.current_user()
                self.send_json(200, {"user_id": u["id"], "stars": u["stars"], "grams": u["grams"], "currencies": {"stars": u["stars"], "grams": u["grams"]}})
                return
            if path == "/api/me/wallet/transactions":
                u = self.current_user()
                with db() as c:
                    rows = c.execute("SELECT id,amount,balance_after,reason,related_user_id,created_at FROM gram_transactions WHERE user_id=? ORDER BY id DESC LIMIT 100", (u["id"],)).fetchall()
                self.send_json(200, {"transactions": [dict(row) for row in rows]})
                return
            if path == "/api/me/gifts/transactions":
                u = self.current_user()
                with db() as c:
                    rows = c.execute("""SELECT gt.id,gt.event_type,gt.serial_number,gt.gift_name,gt.from_user_id,
                        sender.username AS from_username,gt.to_user_id,recipient.username AS to_username,
                        gt.amount_grams,gt.created_at
                        FROM (SELECT t.id,t.event_type,t.gift_instance_id,t.from_user_id,t.to_user_id,t.amount_grams,t.created_at,
                                     g.serial_number,g.gift_name FROM gift_transactions t JOIN user_gifts g ON g.id=t.gift_instance_id) gt
                        LEFT JOIN users sender ON sender.id=gt.from_user_id
                        JOIN users recipient ON recipient.id=gt.to_user_id
                        WHERE gt.from_user_id=? OR gt.to_user_id=? ORDER BY gt.id DESC LIMIT 100""", (u["id"], u["id"])).fetchall()
                self.send_json(200, {"transactions": [dict(row) for row in rows]})
                return
            if path == "/api/me/gifts":
                u = self.current_user()
                with db() as c:
                    rows = c.execute("""SELECT ug.id,ug.serial_number,ug.gift_name,ug.acquired_at,ug.gift_id
                        FROM user_gifts ug WHERE ug.owner_user_id=? ORDER BY ug.id DESC""", (u["id"],)).fetchall()
                self.send_json(200, {"gifts": [dict(row) for row in rows]})
                return
            if path == "/api/users":
                self.current_user()
                q = parse_qs(parsed.query).get("q", [""])[0].strip().lstrip("@")
                if not q:
                    self.send_json(200, {"users": []}); return
                with db() as c:
                    rows = c.execute("SELECT id,username,display_name FROM users WHERE username LIKE ? OR display_name LIKE ? ORDER BY id DESC LIMIT 30", (f"%{q}%", f"%{q}%")).fetchall()
                self.send_json(200, {"users": [dict(r) for r in rows]})
                return
            m = re.fullmatch(r"/api/users/(\d+)", path)
            if m:
                self.current_user()
                with db() as c:
                    row = c.execute("SELECT id,username,display_name,created_at FROM users WHERE id=?", (int(m.group(1)),)).fetchone()
                if not row: raise ApiError(404, "Пользователь не найден")
                self.send_json(200, dict(row)); return
            if path == "/api/gifts":
                self.current_user()
                with db() as c:
                    rows = c.execute("SELECT id,name,price,supply FROM gifts WHERE supply>0 ORDER BY id DESC").fetchall()
                self.send_json(200, {"currency": "grams", "gifts": [dict(r) for r in rows]}); return
            if path == "/api/channels":
                self.current_user()
                with db() as c:
                    rows = c.execute("""SELECT ch.id,ch.username,ch.title,ch.owner_user_id,u.username AS owner_username
                        FROM channels ch JOIN users u ON u.id=ch.owner_user_id ORDER BY ch.id DESC""").fetchall()
                self.send_json(200, {"channels": [dict(r) for r in rows]}); return
            m = re.fullmatch(r"/api/channels/(\d+)", path)
            if m:
                self.current_user()
                with db() as c:
                    row = c.execute("""SELECT ch.id,ch.username,ch.title,ch.owner_user_id,u.username AS owner_username
                        FROM channels ch JOIN users u ON u.id=ch.owner_user_id WHERE ch.id=?""", (int(m.group(1)),)).fetchone()
                if not row: raise ApiError(404, "Канал не найден")
                self.send_json(200, dict(row)); return
            m = re.fullmatch(r"/api/channels/(\d+)/messages", path)
            if m:
                self.current_user()
                query = parse_qs(parsed.query)
                try:
                    after_id = int(query.get("after_id", ["0"])[0])
                except (ValueError, TypeError):
                    raise ApiError(400, "Некорректный after_id")
                if after_id < 0 or after_id > 9_223_372_036_854_775_807:
                    raise ApiError(400, "Некорректный after_id")
                channel_id = int(m.group(1))
                with db() as c:
                    if after_id:
                        rows = c.execute("""SELECT id,channel_id,author_id,body,created_at
                            FROM channel_messages WHERE channel_id=? AND id>? ORDER BY id ASC LIMIT 100""",
                            (channel_id, after_id)).fetchall()
                    else:
                        rows = c.execute("""SELECT id,channel_id,author_id,body,created_at
                            FROM channel_messages WHERE channel_id=? ORDER BY id DESC LIMIT 100""",
                            (channel_id,)).fetchall()
                        rows = list(reversed(rows))
                self.send_json(200, {"messages": [dict(x) for x in rows]}); return
            if path == "/api/messages":
                u = self.current_user()
                query = parse_qs(parsed.query)
                try:
                    peer = int(query.get("with", ["0"])[0])
                    after_id = int(query.get("after_id", ["0"])[0])
                except (ValueError, TypeError):
                    raise ApiError(400, "Некорректный ID собеседника или after_id")
                if peer <= 0 or after_id < 0 or after_id > 9_223_372_036_854_775_807:
                    raise ApiError(400, "Некорректный ID собеседника или after_id")
                with db() as c:
                    if after_id:
                        rows = c.execute("""SELECT id,sender_id,recipient_id,body,created_at FROM messages
                            WHERE ((sender_id=? AND recipient_id=?) OR (sender_id=? AND recipient_id=?))
                              AND id>? ORDER BY id ASC LIMIT 100""",
                            (u["id"], peer, peer, u["id"], after_id)).fetchall()
                    else:
                        rows = c.execute("""SELECT id,sender_id,recipient_id,body,created_at FROM messages
                            WHERE (sender_id=? AND recipient_id=?) OR (sender_id=? AND recipient_id=?)
                            ORDER BY id DESC LIMIT 100""", (u["id"], peer, peer, u["id"])).fetchall()
                        rows = list(reversed(rows))
                self.send_json(200, {"messages": [dict(x) for x in rows]}); return
            if path == "/api/conversations":
                u = self.current_user()
                with db() as c:
                    rows = c.execute("""WITH recent AS (
                        SELECT CASE WHEN sender_id=? THEN recipient_id ELSE sender_id END AS peer_id,
                               MAX(id) AS last_message_id
                        FROM messages
                        WHERE sender_id=? OR recipient_id=?
                        GROUP BY peer_id
                    )
                    SELECT peer.id,peer.username,peer.display_name,
                           message.body AS last_message,message.created_at
                    FROM recent
                    JOIN users AS peer ON peer.id=recent.peer_id
                    JOIN messages AS message ON message.id=recent.last_message_id
                    WHERE peer.is_banned=0
                    ORDER BY message.id DESC
                    LIMIT 50""", (u["id"], u["id"], u["id"])).fetchall()
                self.send_json(200, {"conversations": [dict(row) for row in rows]}); return
            if path == "/api/admin/overview":
                self.admin_required()
                with db() as c:
                    counts = {
                        "users": c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],
                        "banned_users": c.execute("SELECT COUNT(*) n FROM users WHERE is_banned=1").fetchone()["n"],
                        "channels": c.execute("SELECT COUNT(*) n FROM channels").fetchone()["n"],
                        "messages": c.execute("SELECT COUNT(*) n FROM messages").fetchone()["n"],
                        "channel_messages": c.execute("SELECT COUNT(*) n FROM channel_messages").fetchone()["n"],
                        "gifts": c.execute("SELECT COUNT(*) n FROM gifts").fetchone()["n"],
                        "gift_instances": c.execute("SELECT COUNT(*) n FROM user_gifts").fetchone()["n"],
                        "gram_transactions": c.execute("SELECT COUNT(*) n FROM gram_transactions").fetchone()["n"],
                        "star_transactions": c.execute("SELECT COUNT(*) n FROM star_transactions").fetchone()["n"],
                    }
                self.send_json(200, counts); return
            if path == "/api/admin/channels":
                self.admin_required()
                with db() as c:
                    rows = c.execute("""SELECT ch.id,ch.username,ch.title,ch.owner_user_id,u.username AS owner_username,ch.created_at
                        FROM channels ch JOIN users u ON u.id=ch.owner_user_id ORDER BY ch.id DESC""").fetchall()
                    channels = []
                    for row in rows:
                        item = dict(row)
                        item["admin_user_ids"] = [x["user_id"] for x in c.execute(
                            "SELECT user_id FROM channel_admins WHERE channel_id=? ORDER BY user_id", (row["id"],)
                        ).fetchall()]
                        channels.append(item)
                self.send_json(200, {"channels": channels}); return
            if path == "/api/admin/users":
                self.admin_required()
                q = parse_qs(parsed.query).get("q", [""])[0].strip().lstrip("@")
                if not q:
                    self.send_json(200, {"users": []}); return
                with db() as c:
                    if q.isdigit():
                        rows = c.execute("SELECT id,username,display_name,stars,grams,is_banned,created_at FROM users WHERE id=? LIMIT 50", (int(q),)).fetchall()
                    else:
                        rows = c.execute("SELECT id,username,display_name,stars,grams,is_banned,created_at FROM users WHERE username LIKE ? OR display_name LIKE ? ORDER BY id DESC LIMIT 50", (f"%{q}%", f"%{q}%")).fetchall()
                self.send_json(200, {"users": [dict(x) for x in rows]}); return
            if path == "/api/admin/gifts":
                self.admin_required()
                with db() as c:
                    rows = c.execute("SELECT id,name,price,supply,created_at FROM gifts ORDER BY id DESC").fetchall()
                self.send_json(200, {"gifts": [dict(x) for x in rows]}); return
            if path == "/api/admin/stars/history":
                self.admin_required()
                uid = parse_qs(parsed.query).get("user_id", [""])[0]
                with db() as c:
                    if uid.isdigit():
                        rows = c.execute("SELECT id,user_id,amount,admin_name,created_at FROM star_transactions WHERE user_id=? ORDER BY id DESC LIMIT 100", (int(uid),)).fetchall()
                    else:
                        rows = c.execute("SELECT id,user_id,amount,admin_name,created_at FROM star_transactions ORDER BY id DESC LIMIT 100").fetchall()
                self.send_json(200, {"transactions": [dict(r) for r in rows]}); return
            if path == "/api/admin/grams/history":
                self.admin_required()
                uid = parse_qs(parsed.query).get("user_id", [""])[0]
                with db() as c:
                    if uid.isdigit():
                        rows = c.execute("SELECT gt.id,gt.user_id,u.username,gt.amount,gt.balance_after,gt.reason,gt.related_user_id,gt.created_at FROM gram_transactions gt JOIN users u ON u.id=gt.user_id WHERE gt.user_id=? ORDER BY gt.id DESC LIMIT 100", (int(uid),)).fetchall()
                    else:
                        rows = c.execute("SELECT gt.id,gt.user_id,u.username,gt.amount,gt.balance_after,gt.reason,gt.related_user_id,gt.created_at FROM gram_transactions gt JOIN users u ON u.id=gt.user_id ORDER BY gt.id DESC LIMIT 100").fetchall()
                self.send_json(200, {"transactions": [dict(r) for r in rows]}); return
            raise ApiError(404, "Маршрут не найден")
        except ApiError as e: self.send_json(e.status, {"error": str(e)})
        except (ValueError, TypeError): self.send_json(400, {"error": "Некорректный параметр"})
        except Exception: self.send_json(500, {"error": "Внутренняя ошибка сервера"})

    def do_POST(self):
        try:
            path = urlparse(self.path).path
            data = self.read_json()
            if path == "/api/auth/request-code":
                self.request_code(data.get("phone", "")); return
            if path == "/api/auth/verify-code":
                self.verify_code(data.get("phone", ""), data.get("code", "")); return
            if path == "/api/auth/refresh":
                user = self.current_user()
                token = self.bearer()
                now = int(time.time())
                expires_at = now + SESSION_TTL
                with db() as c:
                    cur = c.execute(
                        "UPDATE sessions SET expires_at=? WHERE token_hash=? AND expires_at>?",
                        (expires_at, token_hash(token), now),
                    )
                    if cur.rowcount != 1:
                        raise ApiError(401, "Сессия истекла или недействительна")
                self.send_json(200, {
                    "status": "refreshed",
                    "expires_at": expires_at,
                    "user": self.public_user(user, include_phone=True, include_stars=True, include_grams=True),
                }); return
            if path == "/api/auth/logout":
                token = self.bearer()
                if token:
                    with db() as c: c.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
                self.send_json(200, {"status": "logged_out"}); return
            purchase_match = re.fullmatch(r"/api/gifts/(\d+)/purchase", path)
            if purchase_match:
                u = self.current_user()
                gift_id = int(purchase_match.group(1))
                now = int(time.time())
                descriptor = self.idempotency_descriptor(path, data)
                response = None
                with db() as c:
                    c.execute("BEGIN IMMEDIATE")
                    response = self.idempotency_lookup(c, u["id"], path, descriptor)
                    if response is None:
                        gift = c.execute("SELECT id,name,price,supply FROM gifts WHERE id=?", (gift_id,)).fetchone()
                        if not gift:
                            raise ApiError(404, "Подарок не найден")
                        if gift["supply"] <= 0:
                            raise ApiError(409, "Подарок закончился")
                        account = c.execute("SELECT grams FROM users WHERE id=? AND is_banned=0", (u["id"],)).fetchone()
                        if not account:
                            raise ApiError(403, "Аккаунт недоступен")
                        price = int(gift["price"])
                        if account["grams"] < price:
                            raise ApiError(409, "Недостаточно Gram")
                        updated = c.execute("UPDATE users SET grams=grams-? WHERE id=? AND grams>=?", (price, u["id"], price))
                        if updated.rowcount != 1:
                            raise ApiError(409, "Недостаточно Gram")
                        stocked = c.execute("UPDATE gifts SET supply=supply-1 WHERE id=? AND supply>0", (gift_id,))
                        if stocked.rowcount != 1:
                            raise ApiError(409, "Подарок закончился")
                        serial = None
                        for _ in range(10):
                            candidate = "WG-" + secrets.token_hex(6).upper()
                            if not c.execute("SELECT 1 FROM user_gifts WHERE serial_number=?", (candidate,)).fetchone():
                                serial = candidate
                                break
                        if serial is None:
                            raise ApiError(503, "Не удалось выдать серийный номер. Повторите покупку.")
                        cur = c.execute("INSERT INTO user_gifts(serial_number,gift_id,gift_name,owner_user_id,acquired_at) VALUES(?,?,?,?,?)", (serial, gift_id, gift["name"], u["id"], now))
                        balance = c.execute("SELECT grams FROM users WHERE id=?", (u["id"],)).fetchone()["grams"]
                        if price > 0:
                            c.execute("INSERT INTO gram_transactions(user_id,amount,balance_after,reason,created_at) VALUES(?,?,?,?,?)", (u["id"], -price, balance, "gift_purchase:" + str(gift_id), now))
                        c.execute("INSERT INTO gift_transactions(event_type,gift_instance_id,from_user_id,to_user_id,amount_grams,created_at) VALUES('purchase',?,NULL,?,?,?)", (cur.lastrowid, u["id"], price, now))
                        payload = {"status": "purchased", "gift": {"id": cur.lastrowid, "serial_number": serial, "gift_id": gift_id, "name": gift["name"], "acquired_at": now}, "grams_spent": price, "grams_balance": balance}
                        self.idempotency_store(c, u["id"], path, descriptor, 201, payload, now)
                        response = (201, payload)
                self.send_json(response[0], response[1]); return
            if path == "/api/gifts/transfer":
                u = self.current_user()
                serial = str(data.get("serial_number", "")).strip().upper()
                recipient_key = str(data.get("recipient", data.get("recipient_id", ""))).strip().lstrip("@")
                if not re.fullmatch(r"WG-[A-F0-9]{12}", serial):
                    raise ApiError(400, "Некорректный серийный номер подарка")
                if not recipient_key:
                    raise ApiError(400, "Укажите получателя по username или ID")
                now = int(time.time())
                descriptor = self.idempotency_descriptor(path, data)
                response = None
                with db() as c:
                    c.execute("BEGIN IMMEDIATE")
                    response = self.idempotency_lookup(c, u["id"], path, descriptor)
                    if response is None:
                        if recipient_key.isdigit():
                            recipient = c.execute("SELECT id,username,is_banned FROM users WHERE id=?", (int(recipient_key),)).fetchone()
                        else:
                            recipient = c.execute("SELECT id,username,is_banned FROM users WHERE username=? COLLATE NOCASE", (recipient_key,)).fetchone()
                        if not recipient:
                            raise ApiError(404, "Получатель не найден")
                        if recipient["is_banned"]:
                            raise ApiError(403, "Получатель заблокирован")
                        if recipient["id"] == u["id"]:
                            raise ApiError(400, "Нельзя передать подарок самому себе")
                        instance = c.execute("SELECT id,serial_number,gift_name,owner_user_id FROM user_gifts WHERE serial_number=?", (serial,)).fetchone()
                        if not instance:
                            raise ApiError(404, "Подарок с таким серийным номером не найден")
                        if instance["owner_user_id"] != u["id"]:
                            raise ApiError(403, "Этот подарок вам не принадлежит")
                        moved = c.execute("UPDATE user_gifts SET owner_user_id=? WHERE id=? AND owner_user_id=?", (recipient["id"], instance["id"], u["id"]))
                        if moved.rowcount != 1:
                            raise ApiError(409, "Владелец подарка уже изменился")
                        c.execute("INSERT INTO gift_transactions(event_type,gift_instance_id,from_user_id,to_user_id,amount_grams,created_at) VALUES('transfer',?,?,?,0,?)", (instance["id"], u["id"], recipient["id"], now))
                        payload = {"status": "transferred", "serial_number": serial, "gift_name": instance["gift_name"], "from_user_id": u["id"], "to_user_id": recipient["id"], "to_username": recipient["username"]}
                        self.idempotency_store(c, u["id"], path, descriptor, 200, payload, now)
                        response = (200, payload)
                self.send_json(response[0], response[1]); return
            if path == "/api/messages":
                u = self.current_user()
                try: recipient = int(data.get("recipient_id", 0))
                except (ValueError, TypeError): raise ApiError(400, "Некорректный ID получателя")
                body = str(data.get("body", "")).strip()
                if not body or len(body) > 4000: raise ApiError(400, "Сообщение должно содержать от 1 до 4000 символов")
                now = int(time.time())
                descriptor = self.idempotency_descriptor(path, data)
                response = None
                with db() as c:
                    c.execute("BEGIN IMMEDIATE")
                    response = self.idempotency_lookup(c, u["id"], path, descriptor)
                    if response is None:
                        sender = c.execute("SELECT is_banned FROM users WHERE id=?", (u["id"],)).fetchone()
                        if not sender or sender["is_banned"]:
                            raise ApiError(403, "Аккаунт недоступен")
                        recent_count = c.execute(
                            "SELECT COUNT(*) n FROM messages WHERE sender_id=? AND created_at>?",
                            (u["id"], now - 60),
                        ).fetchone()["n"]
                        if recent_count >= DM_MESSAGES_PER_MINUTE:
                            raise ApiError(429, "Слишком часто. Лимит — 30 сообщений в минуту.")
                        peer = c.execute("SELECT id,is_banned FROM users WHERE id=?", (recipient,)).fetchone()
                        if not peer: raise ApiError(404, "Получатель не найден")
                        if peer["is_banned"]: raise ApiError(403, "Получатель заблокирован")
                        cur = c.execute("INSERT INTO messages(sender_id,recipient_id,body,created_at) VALUES(?,?,?,?)", (u["id"], recipient, body, now))
                        payload = {"id": cur.lastrowid, "status": "sent"}
                        self.idempotency_store(c, u["id"], path, descriptor, 201, payload, now)
                        response = (201, payload)
                self.send_json(response[0], response[1]); return
            cm = re.fullmatch(r"/api/channels/(\d+)/messages", path)
            if cm:
                u = self.current_user(); channel_id = int(cm.group(1)); body = str(data.get("body", "")).strip()
                if not body or len(body) > 4000: raise ApiError(400, "Пост должен содержать от 1 до 4000 символов")
                now = int(time.time())
                descriptor = self.idempotency_descriptor(path, data)
                response = None
                with db() as c:
                    c.execute("BEGIN IMMEDIATE")
                    response = self.idempotency_lookup(c, u["id"], path, descriptor)
                    if response is None:
                        author = c.execute("SELECT is_banned FROM users WHERE id=?", (u["id"],)).fetchone()
                        if not author or author["is_banned"]:
                            raise ApiError(403, "Аккаунт недоступен")
                        channel = c.execute("SELECT owner_user_id FROM channels WHERE id=?", (channel_id,)).fetchone()
                        if not channel: raise ApiError(404, "Канал не найден")
                        is_admin = c.execute("SELECT 1 FROM channel_admins WHERE channel_id=? AND user_id=?", (channel_id, u["id"])).fetchone()
                        if channel["owner_user_id"] != u["id"] and not is_admin:
                            raise ApiError(403, "Публиковать может только владелец или администратор канала")
                        recent_count = c.execute(
                            "SELECT COUNT(*) n FROM channel_messages WHERE author_id=? AND created_at>?",
                            (u["id"], now - 60),
                        ).fetchone()["n"]
                        if recent_count >= CHANNEL_POSTS_PER_MINUTE:
                            raise ApiError(429, "Слишком часто. Лимит — 20 публикаций в минуту.")
                        cur = c.execute("INSERT INTO channel_messages(channel_id,author_id,body,created_at) VALUES(?,?,?,?)", (channel_id, u["id"], body, now))
                        payload = {"id": cur.lastrowid, "status": "published"}
                        self.idempotency_store(c, u["id"], path, descriptor, 201, payload, now)
                        response = (201, payload)
                self.send_json(response[0], response[1]); return
            if path == "/api/admin/login":
                if not ADMIN_USER or not ADMIN_PASSWORD: raise ApiError(503, "Администратор не настроен в переменных окружения")
                username, password = str(data.get("username", "")), str(data.get("password", ""))
                ip = self.client_ip(); now = int(time.time())
                with db() as c:
                    failures = c.execute("SELECT COUNT(*) n FROM admin_login_log WHERE ip=? AND created_at>?", (ip, now - 900)).fetchone()["n"]
                    if failures >= 10:
                        raise ApiError(429, "Слишком много неудачных попыток. Повторите вход позже.")
                    if not (hmac.compare_digest(username, ADMIN_USER) and hmac.compare_digest(password, ADMIN_PASSWORD)):
                        c.execute("INSERT INTO admin_login_log(ip,created_at) VALUES(?,?)", (ip, now))
                        login_error = True
                    else:
                        login_error = False
                        c.execute("DELETE FROM admin_login_log WHERE ip=?", (ip,))
                if login_error:
                    raise ApiError(401, "Неверные учётные данные")
                token = secrets.token_urlsafe(32); expires = now + ADMIN_SESSION_TTL
                with db() as c: c.execute("INSERT INTO admin_sessions(token_hash,expires_at) VALUES(?,?)", (token_hash(token), expires))
                self.send_json(200, {"token": token, "expires_in": ADMIN_SESSION_TTL}); return
            if path == "/api/admin/logout":
                self.admin_required(); token = self.bearer()
                with db() as c: c.execute("DELETE FROM admin_sessions WHERE token_hash=?", (token_hash(token),))
                self.send_json(200, {"status": "logged_out"}); return
            self.admin_required()
            if path == "/api/admin/stars":
                user_key = str(data.get("user", data.get("user_id", ""))).strip().lstrip("@")
                try: amount = int(data.get("amount", 0))
                except (ValueError, TypeError): raise ApiError(400, "Некорректное количество звёзд")
                if not user_key or amount <= 0 or amount > 1_000_000: raise ApiError(400, "Количество звёзд должно быть от 1 до 1000000")
                with db() as c:
                    if user_key.isdigit(): user = c.execute("SELECT id,username,stars FROM users WHERE id=?", (int(user_key),)).fetchone()
                    else: user = c.execute("SELECT id,username,stars FROM users WHERE username=? COLLATE NOCASE", (user_key,)).fetchone()
                    if not user: raise ApiError(404, "Пользователь не найден")
                    c.execute("UPDATE users SET stars=stars+? WHERE id=?", (amount, user["id"]))
                    c.execute("INSERT INTO star_transactions(user_id,amount,admin_name,created_at) VALUES(?,?,?,?)", (user["id"], amount, ADMIN_USER, int(time.time())))
                    row = c.execute("SELECT id,username,stars FROM users WHERE id=?", (user["id"],)).fetchone()
                self.send_json(200, {"user_id": row["id"], "username": row["username"], "stars": row["stars"], "credited": amount}); return
            if path == "/api/admin/grams":
                user_key = str(data.get("user", data.get("user_id", ""))).strip().lstrip("@")
                try: amount = int(data.get("amount", 0))
                except (ValueError, TypeError): raise ApiError(400, "Некорректное количество Gram")
                if not user_key or amount <= 0 or amount > 1_000_000:
                    raise ApiError(400, "Количество Gram должно быть от 1 до 1000000")
                now = int(time.time())
                with db() as c:
                    c.execute("BEGIN IMMEDIATE")
                    if user_key.isdigit():
                        user = c.execute("SELECT id,username,grams FROM users WHERE id=?", (int(user_key),)).fetchone()
                    else:
                        user = c.execute("SELECT id,username,grams FROM users WHERE username=? COLLATE NOCASE", (user_key,)).fetchone()
                    if not user: raise ApiError(404, "Пользователь не найден")
                    c.execute("UPDATE users SET grams=grams+? WHERE id=?", (amount, user["id"]))
                    balance = user["grams"] + amount
                    c.execute("INSERT INTO gram_transactions(user_id,amount,balance_after,reason,created_at) VALUES(?,?,?,?,?)", (user["id"], amount, balance, "admin_credit:" + ADMIN_USER, now))
                self.send_json(200, {"user_id": user["id"], "username": user["username"], "grams": balance, "credited": amount}); return
            if path == "/api/admin/gifts":
                name = str(data.get("name", "")).strip()
                try: price, supply = int(data.get("price", -1)), int(data.get("supply", -1))
                except (ValueError, TypeError): raise ApiError(400, "Стоимость и supply должны быть целыми числами")
                if not name or len(name) > 80 or price < 0 or supply < 0: raise ApiError(400, "Проверьте название, стоимость и supply")
                try:
                    with db() as c: cur = c.execute("INSERT INTO gifts(name,price,supply,created_at) VALUES(?,?,?,?)", (name, price, supply, int(time.time())))
                except sqlite3.IntegrityError: raise ApiError(409, "Подарок с таким названием уже существует")
                self.send_json(201, {"id": cur.lastrowid, "name": name, "price": price, "supply": supply}); return
            if path == "/api/admin/channels":
                try: owner_id = int(data.get("owner_user_id", 0))
                except (ValueError, TypeError): raise ApiError(400, "Некорректный ID владельца")
                username = clean_username(data.get("username", "")); title = str(data.get("title", "")).strip() or username
                if len(title) > 100: raise ApiError(400, "Название слишком длинное")
                admin_ids = data.get("admin_user_ids", [])
                if not isinstance(admin_ids, list) or len(admin_ids) > 100:
                    raise ApiError(400, "admin_user_ids должен быть списком не более чем из 100 ID")
                try: admin_ids = list(dict.fromkeys(int(value) for value in admin_ids))
                except (ValueError, TypeError): raise ApiError(400, "Некорректный ID администратора")
                with db() as c:
                    if c.execute("SELECT 1 FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone(): raise ApiError(409, "Этот username уже занят пользователем")
                    if c.execute("SELECT 1 FROM channels WHERE username=? COLLATE NOCASE", (username,)).fetchone(): raise ApiError(409, "Этот username уже занят каналом")
                    if not c.execute("SELECT 1 FROM users WHERE id=?", (owner_id,)).fetchone(): raise ApiError(404, "Аккаунт владельца не найден")
                    for admin_id in admin_ids:
                        if admin_id == owner_id: continue
                        if not c.execute("SELECT 1 FROM users WHERE id=?", (admin_id,)).fetchone(): raise ApiError(404, f"Администратор с ID {admin_id} не найден")
                    cur = c.execute("INSERT INTO channels(username,title,owner_user_id,created_at) VALUES(?,?,?,?)", (username, title, owner_id, int(time.time())))
                    for admin_id in admin_ids:
                        if admin_id != owner_id:
                            c.execute("INSERT INTO channel_admins(channel_id,user_id,created_at) VALUES(?,?,?)", (cur.lastrowid, admin_id, int(time.time())))
                self.send_json(201, {"id": cur.lastrowid, "username": "@" + username, "title": title, "owner_user_id": owner_id, "admin_user_ids": admin_ids}); return
            if path == "/api/admin/ban":
                try: user_id = int(data.get("user_id", 0))
                except (ValueError, TypeError): raise ApiError(400, "Некорректный ID пользователя")
                banned = bool(data.get("banned", True))
                with db() as c:
                    cur = c.execute("UPDATE users SET is_banned=? WHERE id=?", (1 if banned else 0, user_id))
                    if cur.rowcount == 0: raise ApiError(404, "Пользователь не найден")
                    if banned: c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
                self.send_json(200, {"user_id": user_id, "is_banned": banned}); return
            if path == "/api/admin/dev-code":
                if not (DEV_OTP and TEST_PHONES): raise ApiError(403, "Тестовый режим отключён")
                self.request_code(data.get("phone", ""), admin_request=True); return
            admin_match = re.fullmatch(r"/api/admin/channels/(\d+)/admins", path)
            if admin_match:
                channel_id = int(admin_match.group(1))
                try: user_id = int(data.get("user_id", 0))
                except (ValueError, TypeError): raise ApiError(400, "Некорректный ID пользователя")
                with db() as c:
                    if not c.execute("SELECT 1 FROM channels WHERE id=?", (channel_id,)).fetchone(): raise ApiError(404, "Канал не найден")
                    if not c.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone(): raise ApiError(404, "Пользователь не найден")
                    c.execute("INSERT OR IGNORE INTO channel_admins(channel_id,user_id,created_at) VALUES(?,?,?)", (channel_id, user_id, int(time.time())))
                self.send_json(200, {"channel_id": channel_id, "user_id": user_id, "is_admin": True}); return
            raise ApiError(404, "Маршрут не найден")
        except ApiError as e: self.send_json(e.status, {"error": str(e)})
        except (ValueError, TypeError): self.send_json(400, {"error": "Некорректные поля запроса"})
        except Exception: self.send_json(500, {"error": "Внутренняя ошибка сервера"})

    def do_PATCH(self):
        try:
            path = urlparse(self.path).path
            data = self.read_json()
            if path == "/api/me":
                u = self.current_user(); fields = []; values = []
                if "username" in data:
                    username = clean_username(data["username"])
                    with db() as c:
                        if c.execute("SELECT 1 FROM users WHERE username=? COLLATE NOCASE AND id<>?", (username, u["id"])).fetchone(): raise ApiError(409, "Username уже занят")
                    fields.append("username=?"); values.append(username)
                if "display_name" in data:
                    name = str(data["display_name"]).strip()
                    if len(name) > 60: raise ApiError(400, "Имя профиля слишком длинное")
                    fields.append("display_name=?"); values.append(name)
                if not fields: raise ApiError(400, "Нет полей для изменения")
                values.append(u["id"])
                with db() as c:
                    c.execute("UPDATE users SET " + ",".join(fields) + " WHERE id=?", values)
                    row = c.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()
                self.send_json(200, self.public_user(row, include_phone=True, include_stars=True, include_grams=True)); return
            self.admin_required()
            cm = re.fullmatch(r"/api/admin/channels/(\d+)", path)
            if cm:
                channel_id = int(cm.group(1)); fields, values = [], []
                if "title" in data:
                    title = str(data["title"]).strip()
                    if not title or len(title) > 100: raise ApiError(400, "Название канала должно содержать 1–100 символов")
                    fields.append("title=?"); values.append(title)
                if "username" in data:
                    username = clean_username(data["username"])
                    with db() as c:
                        if c.execute("SELECT 1 FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone(): raise ApiError(409, "Username занят пользователем")
                        if c.execute("SELECT 1 FROM channels WHERE username=? AND id<>?", (username, channel_id)).fetchone(): raise ApiError(409, "Username занят другим каналом")
                    fields.append("username=?"); values.append(username)
                if "owner_user_id" in data:
                    try: owner_id = int(data["owner_user_id"])
                    except (ValueError, TypeError): raise ApiError(400, "Некорректный ID владельца")
                    with db() as c:
                        if not c.execute("SELECT 1 FROM users WHERE id=?", (owner_id,)).fetchone(): raise ApiError(404, "Аккаунт владельца не найден")
                    fields.append("owner_user_id=?"); values.append(owner_id)
                if not fields: raise ApiError(400, "Укажите title, username или owner_user_id")
                values.append(channel_id)
                with db() as c:
                    cur = c.execute("UPDATE channels SET " + ",".join(fields) + " WHERE id=?", values)
                    if cur.rowcount == 0: raise ApiError(404, "Канал не найден")
                    row = c.execute("SELECT id,username,title,owner_user_id FROM channels WHERE id=?", (channel_id,)).fetchone()
                self.send_json(200, dict(row)); return
            m = re.fullmatch(r"/api/admin/gifts/(\d+)", path)
            if not m: raise ApiError(404, "Маршрут не найден")
            gift_id = int(m.group(1)); fields, values = [], []
            for key in ("name", "price", "supply"):
                if key in data:
                    val = data[key]
                    if key == "name":
                        val = str(val).strip()
                        if not val or len(val) > 80: raise ApiError(400, "Некорректное название")
                    else:                        val = int(val)
                        if val < 0: raise ApiError(400, "Стоимость и supply не могут быть отрицательными")
                    fields.append(key + "=?"); values.append(val)
            if not fields: raise ApiError(400, "Нет полей для изменения")
            values.append(gift_id)
            try:
                with db() as c:
                    cur = c.execute("UPDATE gifts SET " + ",".join(fields) + " WHERE id=?", values)
                    if cur.rowcount == 0: raise ApiError(404, "Подарок не найден")
                    row = c.execute("SELECT id,name,price,supply FROM gifts WHERE id=?", (gift_id,)).fetchone()
            except sqlite3.IntegrityError: raise ApiError(409, "Подарок с таким названием уже существует")
            self.send_json(200, dict(row))
        except ApiError as e: self.send_json(e.status, {"error": str(e)})
        except (ValueError, TypeError): self.send_json(400, {"error": "Некорректные поля"})
        except Exception: self.send_json(500, {"error": "Внутренняя ошибка сервера"})

    def do_DELETE(self):
        try:
            path = urlparse(self.path).path
            self.admin_required()
            admin_match = re.fullmatch(r"/api/admin/channels/(\d+)/admins/(\d+)", path)
            if admin_match:
                channel_id, user_id = int(admin_match.group(1)), int(admin_match.group(2))
                with db() as c:
                    cur = c.execute("DELETE FROM channel_admins WHERE channel_id=? AND user_id=?", (channel_id, user_id))
                    if cur.rowcount == 0: raise ApiError(404, "Администратор канала не найден")
                self.send_json(200, {"deleted": True, "channel_id": channel_id, "user_id": user_id}); return
            cm = re.fullmatch(r"/api/admin/channels/(\d+)", path)
            if cm:
                with db() as c:
                    cur = c.execute("DELETE FROM channels WHERE id=?", (int(cm.group(1)),))
                    if cur.rowcount == 0: raise ApiError(404, "Канал не найден")
                self.send_json(200, {"deleted": True}); return
            m = re.fullmatch(r"/api/admin/gifts/(\d+)", path)
            if not m: raise ApiError(404, "Маршрут не найден")
            with db() as c:
                cur = c.execute("DELETE FROM gifts WHERE id=?", (int(m.group(1)),))
                if cur.rowcount == 0: raise ApiError(404, "Подарок не найден")
            self.send_json(200, {"deleted": True})
        except ApiError as e: self.send_json(e.status, {"error": str(e)})
        except Exception: self.send_json(500, {"error": "Внутренняя ошибка сервера"})

    def request_code(self, phone, admin_request=False):
        phone = str(phone).strip()
        if not valid_phone(phone):
            raise ApiError(400, "Номер должен иметь формат +1 и 10 цифр. Получите его в AuthWaysGram_bot.")
        is_test = DEV_OTP and phone in TEST_PHONES
        if admin_request and not is_test:
            raise ApiError(403, "Тестовый код доступен только для номера из NEXUSGRAM_TEST_PHONES")
        if not is_test and (not AUTHBOT_URL or not AUTHBOT_TOKEN):
            raise ApiError(503, "AuthWaysGram_bot не настроен на сервере WaysGram")

        now = int(time.time())
        ip = self.client_ip()
        # The bot generates production OTPs. The backend stores only a random marker hash
        # plus expiry/rate-limit metadata; it never stores or receives the production code.
        generated_value = f"{secrets.randbelow(1_000_000):06d}" if is_test else secrets.token_urlsafe(32)
        source = "local_test" if is_test else "authbot"
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            prev = c.execute("SELECT requested_at FROM otp_codes WHERE phone=?", (phone,)).fetchone()
            if prev and now - prev["requested_at"] < 30:
                raise ApiError(429, "Повторный запрос кода доступен через 30 секунд")
            phone_count = c.execute("SELECT COUNT(*) n FROM otp_request_log WHERE phone=? AND created_at> ?", (phone, now - 3600)).fetchone()["n"]
            ip_count = c.execute("SELECT COUNT(*) n FROM otp_request_log WHERE ip=? AND created_at> ?", (ip, now - 3600)).fetchone()["n"]
            if phone_count >= 5:
                raise ApiError(429, "Для номера достигнут лимит запросов кода на час")
            if ip_count >= 15:
                raise ApiError(429, "Слишком много запросов с этого подключения")
            c.execute(
                "INSERT INTO otp_codes(phone,code_hash,expires_at,attempts,requested_at,source) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(phone) DO UPDATE SET code_hash=excluded.code_hash,expires_at=excluded.expires_at,attempts=0,requested_at=excluded.requested_at,source=excluded.source",
                (phone, otp_hash(phone, generated_value), now + OTP_TTL, 0, now, source),
            )
            c.execute("INSERT INTO otp_request_log(phone,ip,created_at) VALUES(?,?,?)", (phone, ip, now))

        if is_test:
            print(f"\n[WaysGram TEST OTP] phone={phone} code={generated_value} expires_in={OTP_TTL}s\n", flush=True)
            if admin_request:
                self.send_json(200, {"status": "test_code_created", "test_code": generated_value, "expires_in": OTP_TTL,
                                     "message": "Код выдан только для номера из тестового allowlist."})
            else:
                self.send_json(200, {"status": "test_code_created", "message": "Тестовый код выведен в консоль сервера. Он действует 5 минут."})
            return

        try:
            authbot_request("/internal/v1/auth-code/request", {"number": phone})
        except ApiError as exc:
            # Keep the local request marker for ambiguous timeouts/5xx responses: the bot
            # may already have created and stored the code before the connection failed.
            if exc.status in (400, 401, 403, 404, 422):
                with db() as c:
                    c.execute("DELETE FROM otp_codes WHERE phone=? AND requested_at=?", (phone, now))
            raise
        self.send_json(200, {
            "status": "sent",
            "brand": "WaysGram",
            "delivery": "AuthWaysGram_bot",
            "message": "Код подготовлен. Откройте AuthWaysGram_bot и нажмите «Получить код».",
        })

    def verify_code(self, phone, code):
        phone, code = str(phone).strip(), str(code).strip()
        if not valid_phone(phone) or not re.fullmatch(r"\d{6}", code):
            raise ApiError(400, "Проверьте виртуальный номер +1 и шестизначный код")

        now = int(time.time())
        precheck_error = None
        source = None
        requested_at = None
        with db() as c:
            row = c.execute("SELECT * FROM otp_codes WHERE phone=?", (phone,)).fetchone()
            if not row or row["expires_at"] < now or row["attempts"] >= 5:
                if row:
                    c.execute("DELETE FROM otp_codes WHERE phone=?", (phone,))
                precheck_error = ApiError(401, "Код истёк или больше недоступен")
            else:
                source = row["source"] if "source" in row.keys() else "legacy_local"
                requested_at = row["requested_at"]
                if source != "authbot" and not hmac.compare_digest(row["code_hash"], otp_hash(phone, code)):
                    c.execute("UPDATE otp_codes SET attempts=attempts+1 WHERE phone=?", (phone,))
                    precheck_error = ApiError(401, "Неверный код")
        if precheck_error:
            raise precheck_error

        if source == "authbot":
            result = authbot_request(
                "/internal/v1/auth-code/verify",
                {"number": phone, "code": code},
            )
            if not result.get("valid"):
                with db() as c:
                    c.execute(
                        "UPDATE otp_codes SET attempts=attempts+1 WHERE phone=? AND requested_at=?",
                        (phone, requested_at),
                    )
                raise ApiError(401, "Неверный или уже использованный код")

        error = None
        token = None
        user_payload = None
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            current = c.execute("SELECT requested_at,expires_at FROM otp_codes WHERE phone=?", (phone,)).fetchone()
            if not current or current["requested_at"] != requested_at or current["expires_at"] < int(time.time()):
                raise ApiError(401, "Код уже недоступен")
            c.execute("DELETE FROM otp_codes WHERE phone=?", (phone,))
            user = c.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
            if not user:
                while True:
                    username = "user_" + secrets.token_hex(4)
                    if not c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                        break
                c.execute("INSERT INTO users(phone,username,created_at) VALUES(?,?,?)", (phone, username, int(time.time())))
                user = c.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
            if user["is_banned"]:
                error = ApiError(403, "Аккаунт заблокирован")
            else:
                token = secrets.token_urlsafe(36)
                c.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)", (token_hash(token), user["id"], int(time.time()) + SESSION_TTL))
                user_payload = self.public_user(user, include_phone=True, include_stars=True, include_grams=True)
        if error:
            raise error
        self.send_json(200, {"token": token, "user": user_payload})

    @staticmethod
    def public_user(user, include_phone=False, include_stars=False, include_grams=False):
        result = {"id": user["id"], "username": user["username"], "display_name": user["display_name"]}
        if include_phone: result["phone"] = user["phone"]
        if include_stars: result["stars"] = user["stars"]
        if include_grams: result["grams"] = user["grams"]
        return result


def main():
    init_db()
    print(f"WaysGram standalone backend listening at http://{HOST}:{PORT}")
    print(f"Database: {DB_PATH}")
    print(f"Admin login configured: {'yes' if ADMIN_USER and ADMIN_PASSWORD else 'NO — set environment variables'}")
    print(f"Test OTP mode: {'ON (allowlist only)' if DEV_OTP and TEST_PHONES else 'OFF'}")
    print(f"AuthWaysGram bot: {'configured' if AUTHBOT_URL and AUTHBOT_TOKEN else 'NOT CONFIGURED'}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()