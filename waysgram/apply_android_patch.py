#!/usr/bin/env python3
"""Inject WaysGram additions into the restored original Android project."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "TMessagesProj/src/main/java/org/telegram/ui/SettingsActivity.java"
PANEL_SOURCE = Path(__file__).with_name("DeveloperPanelActivity.java")
PANEL_TARGET = ROOT / "TMessagesProj/src/main/java/org/telegram/ui/DeveloperPanelActivity.java"
API_SOURCE = Path(__file__).with_name("WaysGramApiClient.java")
API_TARGET = ROOT / "TMessagesProj/src/main/java/org/telegram/messenger/WaysGramApiClient.java"
SESSION_SOURCE = Path(__file__).with_name("WaysGramSessionStore.java")
SESSION_TARGET = ROOT / "TMessagesProj/src/main/java/org/telegram/messenger/WaysGramSessionStore.java"
AUTH_SOURCE = Path(__file__).with_name("WaysGramAuthRepository.java")
AUTH_TARGET = ROOT / "TMessagesProj/src/main/java/org/telegram/messenger/WaysGramAuthRepository.java"

for required in (SETTINGS, PANEL_SOURCE, API_SOURCE, SESSION_SOURCE, AUTH_SOURCE):
    if not required.is_file():
        raise SystemExit(f"Missing required WaysGram integration file: {required}")

api_source = API_SOURCE.read_text(encoding="utf-8")
api_contract = (
    "normalizeBaseUrl", "getConfig", "requestCode", "verifyCode",
    "getConversations", "getMessages", "sendMessage",
    "getChannels", "getChannelMessages", "getGifts",
    "Authorization", "Bearer ", "CONNECT_TIMEOUT_MS", "READ_TIMEOUT_MS",
)
missing = [marker for marker in api_contract if marker not in api_source]
if missing:
    raise SystemExit("WaysGram REST client contract is incomplete: " + ", ".join(missing))

session_source = SESSION_SOURCE.read_text(encoding="utf-8")
session_contract = (
    "AndroidKeyStore", "AES/GCM/NoPadding", "saveAccessToken",
    "getAccessToken", "clear", "GCMParameterSpec",
)
missing = [marker for marker in session_contract if marker not in session_source]
if missing:
    raise SystemExit("WaysGram session storage contract is incomplete: " + ", ".join(missing))

auth_source = AUTH_SOURCE.read_text(encoding="utf-8")
auth_contract = (
    "requestCode", "verifyCode", "restoreSession", "logout",
    "normalizePhone", "saveAccessToken", "getAccessToken", "api.getMe",
)
missing = [marker for marker in auth_contract if marker not in auth_source]
if missing:
    raise SystemExit("WaysGram auth repository contract is incomplete: " + ", ".join(missing))
if "new TLRPC.TL_auth_sendCode" in auth_source or "new TLRPC.TL_auth_signIn" in auth_source:
    raise SystemExit("WaysGram auth repository must not use Telegram MTProto login")

source = SETTINGS.read_text(encoding="utf-8")
old_entry = '''        items.add(UItem.asShadow(null));
        items.add(UItem.asHeader("Разработчик"));
        items.add(SettingCell.Factory.of(27, 0xFF3390EC, 0xFF2479D4, R.drawable.settings_account, "Панель разработчика", "Управление личным сервером"));
'''
if old_entry in source:
    source = source.replace(old_entry, "", 1)

new_entry = '''        items.add(UItem.asShadow(null));
        items.add(UItem.asHeader("WaysGram"));
        items.add(SettingCell.Factory.of(27, IconBackgroundColors.BLUE.top, IconBackgroundColors.BLUE.bottom, R.drawable.settings_account, "Админ-панель WaysGram", "Пользователи, Stars, подарки и каналы"));
'''
if '"Админ-панель WaysGram"' not in source:
    anchor = '        items.add(SettingCell.Factory.of(10, IconBackgroundColors.PURPLE.top, IconBackgroundColors.PURPLE.bottom, R.drawable.settings_language, getString(R.string.SettingsLanguage), LocaleController.getCurrentLanguageName()));\n'
    if anchor not in source:
        raise SystemExit("Could not find the original Settings language row to anchor the WaysGram panel entry")
    source = source.replace(anchor, anchor + new_entry, 1)

if "case 27:" not in source or "new DeveloperPanelActivity()" not in source:
    raise SystemExit("The original SettingsActivity click handler does not route item 27 to DeveloperPanelActivity")

SETTINGS.write_text(source, encoding="utf-8")
PANEL_TARGET.parent.mkdir(parents=True, exist_ok=True)
PANEL_TARGET.write_text(PANEL_SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
API_TARGET.parent.mkdir(parents=True, exist_ok=True)
API_TARGET.write_text(api_source, encoding="utf-8")
SESSION_TARGET.parent.mkdir(parents=True, exist_ok=True)
SESSION_TARGET.write_text(session_source, encoding="utf-8")
AUTH_TARGET.parent.mkdir(parents=True, exist_ok=True)
AUTH_TARGET.write_text(auth_source, encoding="utf-8")
print("WaysGram admin panel, REST transport, Keystore storage and auth repository injected")
