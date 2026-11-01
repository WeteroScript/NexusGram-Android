#!/usr/bin/env python3
"""Add regression tests for the app-compatible POST /api/profile route."""
from pathlib import Path

path = Path("WaysGram-Backend/tests/smoke_test.py")
if not path.is_file():
    raise SystemExit(f"Missing WaysGram smoke test: {path}")

source = path.read_text(encoding="utf-8")
old_profile = '''                profile = request(base, "/api/me", "PATCH", {"username": "q", "display_name": "First"}, token1)
                assert profile["username"] == "q"  # one-letter channel/usernames are supported.
'''
new_profile = '''                request(base, "/api/profile", "POST", {"display_name": "No token"}, expected=401)
                profile = request(base, "/api/profile", "POST", {"username": "q", "display_name": "First"}, token1)
                assert profile["username"] == "q"  # one-letter channel/usernames are supported.
                assert profile["display_name"] == "First"
'''
if old_profile in source:
    source = source.replace(old_profile, new_profile, 1)
elif 'request(base, "/api/profile", "POST", {"display_name": "No token"}, expected=401)' not in source:
    raise SystemExit("Could not locate the existing profile update smoke test")

needle = '''                user2_id = user2_auth["user"]["id"]
'''
addition = needle + '''                request(base, "/api/profile", "POST", {"username": "Q"}, token2, expected=409)
                request(base, "/api/profile", "POST", {"username": "not valid"}, token2, expected=400)
'''
if needle in source:
    source = source.replace(needle, addition, 1)
elif 'request(base, "/api/profile", "POST", {"username": "Q"}, token2, expected=409)' not in source:
    raise SystemExit("Could not locate second-user registration for duplicate username tests")

path.write_text(source, encoding="utf-8")
print("Smoke test now covers authenticated profile updates, missing auth, duplicate usernames and invalid usernames")
