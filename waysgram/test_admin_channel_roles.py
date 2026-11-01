#!/usr/bin/env python3
"""Extend backend smoke coverage for assigning and removing channel administrators."""
from pathlib import Path

path = Path("WaysGram-Backend/tests/smoke_test.py")
if not path.is_file():
    raise SystemExit(f"Missing WaysGram smoke test: {path}")

source = path.read_text(encoding="utf-8")
old = '''                request(base, f"/api/channels/{channel_id}/messages", "POST",
                        {"body": "Not the owner"}, token2, expected=403)
'''
new = old + '''                request(base, f"/api/admin/channels/{channel_id}/admins", "POST",
                        {"user_id": user2_id}, admin_token)
                admin_channels = request(base, "/api/admin/channels", token=admin_token)
                channel_admin_ids = next(row["admin_user_ids"] for row in admin_channels["channels"] if row["id"] == channel_id)
                assert user2_id in channel_admin_ids
                request(base, f"/api/channels/{channel_id}/messages", "POST",
                        {"body": "Admin post"}, token2, expected=201)
                request(base, f"/api/admin/channels/{channel_id}/admins/{user2_id}", "DELETE", {}, admin_token)
                admin_channels = request(base, "/api/admin/channels", token=admin_token)
                channel_admin_ids = next(row["admin_user_ids"] for row in admin_channels["channels"] if row["id"] == channel_id)
                assert user2_id not in channel_admin_ids
                request(base, f"/api/channels/{channel_id}/messages", "POST",
                        {"body": "Admin role removed"}, token2, expected=403)
'''
if old in source:
    source = source.replace(old, new, 1)
elif 'assert user2_id not in channel_admin_ids' not in source:
    raise SystemExit("Could not add channel administrator assignment tests")

path.write_text(source, encoding="utf-8")
print("Smoke test now verifies channel admin assignment, posting rights, removal and permission revocation")
