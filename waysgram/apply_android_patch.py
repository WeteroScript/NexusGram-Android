#!/usr/bin/env python3
"""Inject the WaysGram admin panel into the restored original Android UI."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "TMessagesProj/src/main/java/org/telegram/ui/SettingsActivity.java"
PANEL_SOURCE = Path(__file__).with_name("DeveloperPanelActivity.java")
PANEL_TARGET = ROOT / "TMessagesProj/src/main/java/org/telegram/ui/DeveloperPanelActivity.java"

if not SETTINGS.is_file():
    raise SystemExit(f"Missing original settings source: {SETTINGS}")
if not PANEL_SOURCE.is_file():
    raise SystemExit(f"Missing WaysGram admin activity source: {PANEL_SOURCE}")

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
print("WaysGram admin panel injected into original SettingsActivity (item 27)")
