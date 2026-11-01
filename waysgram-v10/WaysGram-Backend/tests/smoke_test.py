#!/usr/bin/env python3
"""End-to-end smoke test for the local WaysGram backend. Uses only Python stdlib."""
import json
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import re
import socket
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server as backend_module  # noqa: E402

PHONES = ["+12025550123", "+12025550124", "+12025550125", "+12025550126"]


class FakeAuthBotHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_json(self, status, payload):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        if self.headers.get("X-Internal-Token") != self.server.auth_token:
            self.send_json(401, {"detail": "Unauthorized"})
            return
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        except Exception:
            self.send_json(400, {"detail": "Invalid JSON"})
            return
        number = str(payload.get("number", ""))
        if self.path == "/internal/v1/auth-code/request":
            if number not in self.server.assigned_numbers:
                self.send_json(404, {"detail": "Number is not assigned"})
                return
            if number in self.server.codes:
                self.send_json(429, {"detail": "Rate limited"})
                return
            self.server.codes[number] = "123456"
            self.send_json(200, {"status": "delivered"})
            return
        if self.path == "/internal/v1/auth-code/verify":
            code = str(payload.get("code", ""))
            valid = self.server.codes.get(number) == code
            if valid:
                self.server.codes.pop(number, None)
            self.send_json(200, {"valid": valid})
            return
        self.send_json(404, {"detail": "Not found"})


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(base, path, method="GET", body=None, token=None, expected=200, extra_headers=None):
    headers = {"Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    result = json.loads(raw.decode() or "{}")
    assert status == expected, f"{method} {path}: expected {expected}, got {status}: {result}"
    return result


def wait_ready(base, proc):
    for _ in range(60):
        if proc.poll() is not None:
            raise RuntimeError("WaysGram server stopped unexpectedly")
        try:
            request(base, "/health")
            return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("WaysGram server did not start")


def get_code(log_path, phone):
    content = log_path.read_text(errors="replace")
    match = re.search(r"\[WaysGram TEST OTP\] phone=" + re.escape(phone) + r" code=(\d{6})", content)
    assert match, f"Test OTP for {phone} not found in server log"
    return match.group(1)


def verify_proxy_ip_handling():
    original = backend_module.TRUST_PROXY_HEADERS
    try:
        handler = object.__new__(backend_module.Handler)
        handler.client_address = ("127.0.0.1", 12345)
        handler.headers = Message()

        backend_module.TRUST_PROXY_HEADERS = False
        handler.headers["X-Forwarded-For"] = "203.0.113.10"
        assert handler.client_ip() == "127.0.0.1", "Untrusted forwarded header must be ignored"

        backend_module.TRUST_PROXY_HEADERS = True
        assert handler.client_ip() == "203.0.113.10", "Trusted local proxy IP should be used"

        handler.client_address = ("192.0.2.44", 12345)
        assert handler.client_ip() == "192.0.2.44", "Non-local peers must not spoof forwarded IPs"
    finally:
        backend_module.TRUST_PROXY_HEADERS = original



def verify_legacy_otp_schema_migration():
    with tempfile.TemporaryDirectory(prefix="waysgram-legacy-db-") as tmp:
        path = Path(tmp) / "legacy.db"
        with sqlite3.connect(path) as conn:
            # Simulate a pre-Gram installation: user data exists, but the new wallet column does not.
            conn.execute("""CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL UNIQUE,
                username TEXT NOT NULL UNIQUE,
                stars INTEGER NOT NULL DEFAULT 0,
                is_banned INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            )""")
            conn.execute("INSERT INTO users(phone,username,stars,created_at) VALUES(?,?,?,?)",
                         ("+12025550198", "legacy_user", 12, int(time.time())))
            conn.execute("""CREATE TABLE otp_codes (
                phone TEXT PRIMARY KEY,
                code_hash TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                requested_at INTEGER NOT NULL
            )""")
            conn.execute(
                "INSERT INTO otp_codes(phone,code_hash,expires_at,attempts,requested_at) VALUES(?,?,?,?,?)",
                ("+12025550199", "legacy-hash", int(time.time()) + 300, 0, int(time.time())),
            )

        env = os.environ.copy()
        env["NEXUSGRAM_DB"] = str(path)
        subprocess.run(
            [sys.executable, "-c", "import server; server.init_db()"],
            cwd=ROOT, env=env, check=True, capture_output=True, text=True, timeout=10,
        )
        with sqlite3.connect(path) as conn:
            otp_columns = {row[1] for row in conn.execute("PRAGMA table_info(otp_codes)")}
            user_columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
            otp_row = conn.execute("SELECT phone, code_hash, source FROM otp_codes").fetchone()
            user_row = conn.execute("SELECT phone,username,stars,grams,display_name FROM users").fetchone()
            econ_tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "source" in otp_columns, "Legacy OTP table was not upgraded"
        assert otp_row == ("+12025550199", "legacy-hash", "legacy_local"), "Legacy OTP row was not preserved"
        assert {"grams", "display_name"}.issubset(user_columns), "Legacy user table was not upgraded"
        assert user_row == ("+12025550198", "legacy_user", 12, 0, ""), "Legacy user/wallet data was not preserved"
        assert {"user_gifts", "gram_transactions", "gift_transactions", "idempotency_records"}.issubset(econ_tables), "Economy/idempotency tables were not migrated"

def main():
    verify_proxy_ip_handling()
    verify_legacy_otp_schema_migration()
    with tempfile.TemporaryDirectory(prefix="nexusgram-test-") as tmp:
        port = free_port()
        authbot_port = free_port()
        authbot = ThreadingHTTPServer(("127.0.0.1", authbot_port), FakeAuthBotHandler)
        authbot.auth_token = "fake-authbot-test-secret"
        authbot.assigned_numbers = {PHONES[0], PHONES[1], PHONES[3]}
        authbot.codes = {}
        authbot_thread = threading.Thread(target=authbot.serve_forever, daemon=True)
        authbot_thread.start()
        base = f"http://127.0.0.1:{port}"
        log_path = Path(tmp) / "server.log"
        env = os.environ.copy()
        env.update({
            "NEXUSGRAM_HOST": "127.0.0.1",
            "NEXUSGRAM_PORT": str(port),
            "NEXUSGRAM_DB": str(Path(tmp) / "waysgram.db"),
            "NEXUSGRAM_ADMIN_USER": "test-owner",
            "NEXUSGRAM_ADMIN_PASSWORD": "smoke-test-password-strong-2026",
            "NEXUSGRAM_DEV_OTP": "1",
            "NEXUSGRAM_TEST_PHONES": PHONES[2],
            "NEXUSGRAM_AUTHBOT_URL": f"http://127.0.0.1:{authbot_port}",
            "NEXUSGRAM_AUTHBOT_TOKEN": "fake-authbot-test-secret",
            "NEXUSGRAM_TRUST_PROXY_HEADERS": "0",
        })
        with log_path.open("w+") as log:
            proc = subprocess.Popen([sys.executable, str(ROOT / "server.py")], cwd=ROOT, env=env,
                                    stdout=log, stderr=subprocess.STDOUT, text=True)
            try:
                wait_ready(base, proc)
                config = request(base, "/api/config")
                assert config["brand"] == "WaysGram"
                assert config["test_otp_enabled"] is True
                assert config["authbot_delivery_ready"] is True
                assert config["sms_delivery_ready"] is False
                assert config["messaging_limits"]["direct_messages_per_minute"] == 30
                assert config["messaging_limits"]["channel_posts_per_minute"] == 20

                # Register and update user 1.
                request(base, "/api/auth/request-code", "POST", {"phone": PHONES[0]})
                time.sleep(0.1)
                user1_auth = request(base, "/api/auth/verify-code", "POST",
                                     {"phone": PHONES[0], "code": "123456"})
                token1 = user1_auth["token"]
                user1 = user1_auth["user"]
                request(base, "/api/auth/request-code", "POST",
                        {"phone": "+12025550128"}, expected=404)
                profile = request(base, "/api/me", token=token1)
                assert profile["id"] == user1["id"]
                profile = request(base, "/api/me", "PATCH", {"username": "q", "display_name": "First"}, token1)
                assert profile["username"] == "q"  # one-letter channel/usernames are supported.

                # Register user 2.
                request(base, "/api/auth/request-code", "POST", {"phone": PHONES[1]})
                time.sleep(0.1)
                user2_auth = request(base, "/api/auth/verify-code", "POST",
                                     {"phone": PHONES[1], "code": "123456"})
                token2 = user2_auth["token"]
                user2_id = user2_auth["user"]["id"]

                # AuthBot OTP attempts are also limited by the WaysGram backend.
                request(base, "/api/auth/request-code", "POST", {"phone": PHONES[3]})
                for _ in range(5):
                    request(base, "/api/auth/verify-code", "POST",
                            {"phone": PHONES[3], "code": "999999"}, expected=401)
                request(base, "/api/auth/verify-code", "POST",
                        {"phone": PHONES[3], "code": "123456"}, expected=401)
                request(base, "/api/auth/request-code", "POST",
                        {"phone": "+353860000001"}, expected=400)

                # Independent admin session and existing administrative functions.
                admin = request(base, "/api/admin/login", "POST",
                                 {"username": "test-owner", "password": "smoke-test-password-strong-2026"})
                admin_token = admin["token"]
                # Test OTP retrieval is admin-only, allowlist-limited, and never returned in JSON.
                request(base, "/api/admin/dev-code", "POST", {"phone": PHONES[2]}, expected=401)
                request(base, "/api/admin/dev-code", "POST",
                        {"phone": "+12025550127"}, admin_token, expected=403)
                test_code_result = request(base, "/api/admin/dev-code", "POST",
                                           {"phone": PHONES[2]}, admin_token)
                assert test_code_result["status"] == "test_code_created"
                assert re.fullmatch(r"\d{6}", test_code_result.get("test_code", "")), "Admin test-code endpoint must return a code only after authenticated allowlist validation"
                test_code_auth = request(base, "/api/auth/verify-code", "POST",
                                         {"phone": PHONES[2], "code": get_code(log_path, PHONES[2])})
                assert test_code_auth["user"]["phone"] == PHONES[2]
                # An active user session can be extended, while an expired token cannot be revived.
                test_session_token = test_code_auth["token"]
                refreshed = request(base, "/api/auth/refresh", "POST", {}, test_session_token)
                assert refreshed["status"] == "refreshed"
                assert refreshed["user"]["id"] == test_code_auth["user"]["id"]
                assert refreshed["expires_at"] >= int(time.time()) + backend_module.SESSION_TTL - 2
                with sqlite3.connect(Path(tmp) / "waysgram.db") as conn:
                    conn.execute("UPDATE sessions SET expires_at=? WHERE token_hash=?",
                                 (int(time.time()) - 1, backend_module.token_hash(test_session_token)))
                    conn.execute("DELETE FROM otp_request_log WHERE phone=?", (PHONES[2],))
                request(base, "/api/auth/refresh", "POST", {}, test_session_token, expected=401)
                request(base, "/api/me", token=test_session_token, expected=401)
                # A fresh OTP login restores the same server-side account, not a duplicate user.
                reauth_code = request(base, "/api/admin/dev-code", "POST",
                                      {"phone": PHONES[2]}, admin_token)["test_code"]
                reauth = request(base, "/api/auth/verify-code", "POST",
                                 {"phone": PHONES[2], "code": reauth_code})
                assert reauth["user"]["id"] == test_code_auth["user"]["id"]
                assert reauth["token"] != test_session_token
                assert request(base, "/api/me", token=reauth["token"])["id"] == test_code_auth["user"]["id"]
                gift = request(base, "/api/admin/gifts", "POST",
                               {"name": "Test Gift", "price": 25, "supply": 10}, admin_token, expected=201)
                assert gift["supply"] == 10
                request(base, "/api/admin/gifts/" + str(gift["id"]), "PATCH",
                        {"price": 30, "supply": 8}, admin_token)
                catalog = request(base, "/api/gifts", token=token1)
                assert catalog["currency"] == "grams"
                assert catalog["gifts"][0]["price"] == 30
                # Gram wallet: admin credit is journaled and the balance is visible to the owner.
                gram_credit = request(base, "/api/admin/grams", "POST", {"user": "@q", "amount": 100}, admin_token)
                assert gram_credit["grams"] == 100
                wallet = request(base, "/api/me/wallet", token=token1)
                assert wallet["grams"] == 100 and wallet["stars"] == 0
                # Gift purchase atomically spends Gram, decrements supply and issues a unique serial.
                purchase_headers = {"Idempotency-Key": "purchase-test-key-00000001"}
                purchased = request(base, f"/api/gifts/{gift['id']}/purchase", "POST", {}, token1,
                                    expected=201, extra_headers=purchase_headers)
                purchased_replay = request(base, f"/api/gifts/{gift['id']}/purchase", "POST", {}, token1,
                                           expected=201, extra_headers=purchase_headers)
                assert purchased_replay == purchased, "A retried purchase must return the original result"
                serial = purchased["gift"]["serial_number"]
                assert re.fullmatch(r"WG-[A-F0-9]{12}", serial)
                assert purchased["grams_spent"] == 30 and purchased["grams_balance"] == 70
                assert request(base, "/api/me/gifts", token=token1)["gifts"] and len(request(base, "/api/me/gifts", token=token1)["gifts"]) == 1
                inventory1 = request(base, "/api/me/gifts", token=token1)
                assert len(inventory1["gifts"]) == 1 and inventory1["gifts"][0]["serial_number"] == serial
                assert request(base, "/api/me/wallet", token=token1)["grams"] == 70
                assert request(base, "/api/me/wallet", token=token2)["grams"] == 0
                request(base, f"/api/gifts/{gift['id']}/purchase", "POST", {}, token2, expected=409)
                # Transfer changes the owner once; the former owner cannot transfer it again.
                transfer_body = {"serial_number": serial, "recipient": user2_auth["user"]["username"]}
                transfer_headers = {"Idempotency-Key": "gift-transfer-key-000001"}
                transferred = request(base, "/api/gifts/transfer", "POST",
                                      transfer_body, token1, extra_headers=transfer_headers)
                transferred_replay = request(base, "/api/gifts/transfer", "POST",
                                              transfer_body, token1, extra_headers=transfer_headers)
                assert transferred_replay == transferred, "A retried transfer must return the original result"
                assert transferred["to_user_id"] == user2_id
                assert request(base, "/api/me/gifts/transactions", token=token2)["transactions"]
                assert sum(1 for row in request(base, "/api/me/gifts/transactions", token=token2)["transactions"]
                           if row["event_type"] == "transfer") == 1
                assert request(base, "/api/me/gifts", token=token1)["gifts"] == []
                inventory2 = request(base, "/api/me/gifts", token=token2)
                assert len(inventory2["gifts"]) == 1 and inventory2["gifts"][0]["serial_number"] == serial
                request(base, "/api/gifts/transfer", "POST",
                        {"serial_number": serial, "recipient": user2_id}, token1, expected=403)
                gram_history = request(base, "/api/me/wallet/transactions", token=token1)
                assert gram_history["transactions"][0]["amount"] == -30
                gift_history = request(base, "/api/me/gifts/transactions", token=token2)
                assert any(row["event_type"] == "transfer" for row in gift_history["transactions"])
                admin_gram_history = request(base, f"/api/admin/grams/history?user_id={user1['id']}", token=admin_token)
                assert [row["amount"] for row in admin_gram_history["transactions"]] == [-30, 100]
                # Concurrent purchases cannot oversell the final stock unit or double-spend.
                limited = request(base, "/api/admin/gifts", "POST",
                                  {"name": "Limited Gift", "price": 10, "supply": 1}, admin_token, expected=201)
                request(base, "/api/admin/grams", "POST", {"user": "@q", "amount": 20}, admin_token)
                def concurrent_purchase():
                    try:
                        return request(base, f"/api/gifts/{limited['id']}/purchase", "POST", {}, token1, expected=201)["status"]
                    except AssertionError as exc:
                        assert "got 409" in str(exc), str(exc)
                        return "rejected"
                with ThreadPoolExecutor(max_workers=4) as pool:
                    outcomes = list(pool.map(lambda _n: concurrent_purchase(), range(4)))
                assert outcomes.count("purchased") == 1 and outcomes.count("rejected") == 3, outcomes
                limited_catalog = request(base, "/api/admin/gifts", token=admin_token)
                assert next(row for row in limited_catalog["gifts"] if row["id"] == limited["id"])["supply"] == 0
                assert request(base, "/api/me/wallet", token=token1)["grams"] == 80
                # Concurrent retries of one purchase key issue exactly one serial and spend once.
                retry_gift = request(base, "/api/admin/gifts", "POST",
                                     {"name": "Retry Purchase Gift", "price": 15, "supply": 1}, admin_token, expected=201)
                purchase_body = {}
                purchase_headers = {"Idempotency-Key": "concurrent-purchase-key-0001"}
                def retry_same_purchase():
                    return request(base, f"/api/gifts/{retry_gift['id']}/purchase", "POST",
                                   purchase_body, token1, expected=201, extra_headers=purchase_headers)
                with ThreadPoolExecutor(max_workers=5) as pool:
                    purchase_retries = list(pool.map(lambda _n: retry_same_purchase(), range(5)))
                assert len({row["gift"]["serial_number"] for row in purchase_retries}) == 1
                assert request(base, "/api/me/wallet", token=token1)["grams"] == 65
                assert next(row for row in request(base, "/api/admin/gifts", token=admin_token)["gifts"]
                            if row["id"] == retry_gift["id"])["supply"] == 0
                # Zero-price gifts are allowed and do not create invalid zero-value ledger rows.
                free_gift = request(base, "/api/admin/gifts", "POST",
                                    {"name": "Free Gift", "price": 0, "supply": 1}, admin_token, expected=201)
                request(base, f"/api/gifts/{free_gift['id']}/purchase", "POST", {}, token1, expected=201)
                assert request(base, "/api/me/wallet", token=token1)["grams"] == 65
                channel = request(base, "/api/admin/channels", "POST",
                                  {"owner_user_id": user1["id"], "username": "c", "title": "Channel"}, admin_token, expected=201)
                channel_id = channel["id"]
                post_body = {"body": "First post"}
                post_headers = {"Idempotency-Key": "channel-post-test-key-00001"}
                first_post = request(base, f"/api/channels/{channel_id}/messages", "POST",
                                     post_body, token1, expected=201, extra_headers=post_headers)
                post_replay = request(base, f"/api/channels/{channel_id}/messages", "POST",
                                      post_body, token1, expected=201, extra_headers=post_headers)
                assert post_replay == first_post, "A retried channel post must return the original result"
                posts = request(base, f"/api/channels/{channel_id}/messages", token=token2)
                assert len(posts["messages"]) == 1
                assert posts["messages"][0]["body"] == "First post"
                assert request(base, f"/api/channels/{channel_id}/messages?after_id={first_post['id']}", token=token2)["messages"] == []
                request(base, f"/api/channels/{channel_id}/messages?after_id=-1", token=token2, expected=400)
                request(base, f"/api/channels/{channel_id}/messages", "POST",
                        {"body": "Not the owner"}, token2, expected=403)
                request(base, f"/api/admin/channels/{channel_id}/admins", "POST",
                        {"user_id": user2_id}, admin_token)
                admin_channels = request(base, "/api/admin/channels", token=admin_token)
                channel_admin_ids = next(row["admin_user_ids"] for row in admin_channels["channels"] if row["id"] == channel_id)
                assert user2_id in channel_admin_ids
                admin_post = request(base, f"/api/channels/{channel_id}/messages", "POST",
                                     {"body": "Admin post"}, token2, expected=201)
                newer_posts = request(base, f"/api/channels/{channel_id}/messages?after_id={first_post['id']}", token=token1)
                assert [item["id"] for item in newer_posts["messages"]] == [admin_post["id"]]
                request(base, f"/api/admin/channels/{channel_id}/admins/{user2_id}", "DELETE", {}, admin_token)
                admin_channels = request(base, "/api/admin/channels", token=admin_token)
                channel_admin_ids = next(row["admin_user_ids"] for row in admin_channels["channels"] if row["id"] == channel_id)
                assert user2_id not in channel_admin_ids
                request(base, f"/api/channels/{channel_id}/messages", "POST",
                        {"body": "Admin role removed"}, token2, expected=403)
                dm_body = {"recipient_id": user2_id, "body": "Hello"}
                dm_headers = {"Idempotency-Key": "direct-message-test-key-0001"}
                first_dm = request(base, "/api/messages", "POST", dm_body, token1,
                                   expected=201, extra_headers=dm_headers)
                dm_replay = request(base, "/api/messages", "POST", dm_body, token1,
                                    expected=201, extra_headers=dm_headers)
                assert dm_replay == first_dm, "A retried DM must return the original result"
                request(base, "/api/messages", "POST",
                        {"recipient_id": user2_id, "body": "Different body"}, token1,
                        expected=409, extra_headers=dm_headers)
                inbox = request(base, f"/api/messages?with={user1['id']}", token=token2)
                assert len(inbox["messages"]) == 1
                assert inbox["messages"][0]["body"] == "Hello"
                assert request(base, f"/api/messages?with={user1['id']}&after_id={first_dm['id']}", token=token2)["messages"] == []
                second_dm = request(base, "/api/messages", "POST", {"recipient_id": user1['id'], "body": "Reply"}, token2, expected=201)
                incremental_inbox = request(base, f"/api/messages?with={user2_id}&after_id={first_dm['id']}", token=token1)
                assert [item["id"] for item in incremental_inbox["messages"]] == [second_dm["id"]]
                request(base, f"/api/messages?with={user1['id']}&after_id=-1", token=token2, expected=400)
                conversations = request(base, "/api/conversations", token=token2)
                assert conversations["conversations"][0]["id"] == user1["id"]
                assert conversations["conversations"][0]["last_message"] == "Reply"
                own_conversations = request(base, "/api/conversations", token=token1)
                assert own_conversations["conversations"][0]["id"] == user2_id
                request(base, "/api/conversations", expected=401)
                # Concurrent retries with one key must all resolve to the same single message.
                concurrent_body = {"recipient_id": user2_id, "body": "Concurrent retry"}
                concurrent_headers = {"Idempotency-Key": "concurrent-message-key-00001"}
                def retry_same_message():
                    return request(base, "/api/messages", "POST", concurrent_body, token1,
                                   expected=201, extra_headers=concurrent_headers)
                with ThreadPoolExecutor(max_workers=5) as pool:
                    duplicate_results = list(pool.map(lambda _n: retry_same_message(), range(5)))
                assert len({row["id"] for row in duplicate_results}) == 1, duplicate_results
                assert len(request(base, f"/api/messages?with={user2_id}", token=token1)["messages"]) == 3
                # Message and channel publishing rate limits are enforced atomically.
                for index in range(28):
                    request(base, "/api/messages", "POST",
                            {"recipient_id": user2_id, "body": f"Rate test {index}"}, token1, expected=201)
                request(base, "/api/messages", "POST",
                        {"recipient_id": user2_id, "body": "Rate limit boundary"}, token1, expected=429)
                for index in range(19):
                    request(base, f"/api/channels/{channel_id}/messages", "POST",
                            {"body": f"Channel rate test {index}"}, token1, expected=201)
                request(base, f"/api/channels/{channel_id}/messages", "POST",
                        {"body": "Channel rate limit boundary"}, token1, expected=429)
                stars = request(base, "/api/admin/stars", "POST", {"user": "@q", "amount": 7}, admin_token)
                assert stars["stars"] == 7
                history = request(base, f"/api/admin/stars/history?user_id={user1['id']}", token=admin_token)
                assert history["transactions"][0]["amount"] == 7
                request(base, "/api/admin/ban", "POST", {"user_id": user2_id, "banned": True}, admin_token)
                request(base, "/api/me", token=token2, expected=401)
                assert request(base, "/api/conversations", token=token1)["conversations"] == []
                request(base, "/api/admin/logout", "POST", {}, admin_token)
                request(base, "/api/admin/users", token=admin_token, expected=401)
                print("PASS: proxy IP trust, OTP security, session refresh/expiry/reauth, profiles, Gram wallet, collectible gift inventory, purchases, transfers, admin, channels, ownership, incremental chat polling, transactional idempotency, DM/channel rate limits, conversations, DMs, stars, ban/logout")
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                authbot.shutdown()
                authbot.server_close()
                authbot_thread.join(timeout=3)


if __name__ == "__main__":
    main()