#!/usr/bin/env python3
"""Static contract checks for the WaysGram Android REST/auth/data layer."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = (ROOT / "waysgram/WaysGramApiClient.java").read_text(encoding="utf-8")
AUTH = (ROOT / "waysgram/WaysGramAuthRepository.java").read_text(encoding="utf-8")
SESSION = (ROOT / "waysgram/WaysGramSessionStore.java").read_text(encoding="utf-8")
MODELS = (ROOT / "waysgram/WaysGramModels.java").read_text(encoding="utf-8")
DATA = (ROOT / "waysgram/WaysGramMessagingRepository.java").read_text(encoding="utf-8")
PATCH = (ROOT / "waysgram/apply_android_patch.py").read_text(encoding="utf-8")
SERVER = (ROOT / "WaysGram-Backend/server.py").read_text(encoding="utf-8")

# Transport methods must point to routes implemented by the private backend.
api_routes = (
    "/api/config",
    "/api/auth/request-code",
    "/api/auth/verify-code",
    "/api/auth/logout",
    "/api/me",
    "/api/users",
    "/api/messages",
    "/api/conversations",
    "/api/channels",
    "/api/gifts",
)
for route in api_routes:
    assert route in API, f"Android REST client is missing route {route}"
    assert route in SERVER, f"Backend does not declare route {route}"

# Backend auth must issue its own token, and Android must persist it encrypted.
for marker in ("requestCode", "verifyCode", "restoreSession", "logout", "saveAccessToken", "getAccessToken"):
    assert marker in AUTH, f"Auth repository is missing {marker}"
assert "new TLRPC.TL_auth_sendCode" not in AUTH
assert "new TLRPC.TL_auth_signIn" not in AUTH
assert "AndroidKeyStore" in SESSION
assert "AES/GCM/NoPadding" in SESSION
assert "GCMParameterSpec" in SESSION
assert "setInstanceFollowRedirects(false)" in API, "Authenticated API requests must not follow redirects"

# Data types are explicitly WaysGram-owned and repository code has no MTProto dependency.
for marker in ("class User", "class Conversation", "class Message", "class Channel", "class ChannelMessage", "class Gift"):
    assert marker in MODELS, f"Missing typed model: {marker}"
for marker in ("getConversations", "searchUsers", "getMessages", "sendMessage",
               "getChannels", "getChannelMessages", "publishChannelMessage", "getGifts"):
    assert marker in DATA, f"Messaging repository is missing {marker}"
assert "ConnectionsManager" not in DATA
assert "TLRPC." not in DATA

# The restoration patch must copy every new class into the original client source tree.
for marker in ("API_TARGET", "SESSION_TARGET", "AUTH_TARGET", "MODELS_TARGET", "MESSAGING_TARGET"):
    assert marker in PATCH, f"Android patch does not install {marker}"

print("PASS: WaysGram Android routes, OTP repository, Keystore session storage, typed models and data repository")
