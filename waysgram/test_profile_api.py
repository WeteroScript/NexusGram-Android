#!/usr/bin/env python3
"""Add a regression test for the app-compatible POST /api/profile route."""
from pathlib import Path

path = Path("WaysGram-Backend/tests/smoke_test.py")
if not path.is_file():
    raise SystemExit(f"Missing WaysGram smoke test: {path}")

source = path.read_text(encoding="utf-8")
old = '''                profile = request(base, "/api/me", "PATCH", {"username": "q", "display_name": "First"}, token1)
                assert profile["username"] == "q"  # one-letter channel/usernames are supported.
'''
new = '''                request(base, "/api/profile", "POST", {"display_name": "No token"}, expected=401)
                profile = request(base, "/api/profile", "POST", {"username": "q", "display_name": "First"}, token1)
                assert profile["username"] == "q"  # one-letter channel/usernames are supported.
                assert profile["display_name"] == "First"
'''
if old in source:
    source = source.replace(old, new, 1)
elif 'request(base, "/api/profile", "POST", {"display_name": "No token"}, expected=401)' not in source:
    raise SystemExit("Could not locate the existing profile update smoke test")

if needle in source:
    source = source.replace(needle, addition, 1)
elif '"username": "Q"' not in source:
    raise SystemExit("Could not locate second-user registration for duplicate username tests")

path.write_text(source, encoding="utf-8")
print("Smoke test now covers authenticated POST /api/profile and profile fields")
