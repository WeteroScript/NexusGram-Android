#!/usr/bin/env python3
"""Inject WaysGram additions into the restored original Android project."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "TMessagesProj/src/main/java/org/telegram/ui/SettingsActivity.java"
PANEL_SOURCE = Path(__file__).with_name("DeveloperPanelActivity.java")
PANEL_TARGET = ROOT / "TMessagesProj/src/main/java/org/telegram/ui/DeveloperPanelActivity.java"
API_SOURCE = Path(__file__).with_name("WaysGramApiClient.java")
API_TARGET = ROOT / "TMessagesProj/src/main/java/org/telegram/messenger/WaysGramApiClient.java"

for required in (SETTINGS, PANEL_SOURCE, API_SOURCE):
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
print("WaysGram admin panel and REST transport injected into original Android project")
