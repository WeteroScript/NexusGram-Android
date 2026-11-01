#!/usr/bin/env python3
"""Restore Telegram's native login entry point in an unpacked NexusGram source tree."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


def replace_once(source: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, source, count=1, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise RuntimeError(f"Expected exactly one {label} block; found {count}")
    return updated


def patch_login(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    original = source

    source = source.replace("import app.nexusgram.ui.WaysGramPortalActivity;\n", "")
    source = source.replace("        private CheckBoxCell testBackendCheckBox;\n", "")

    if "waysGramButton" in source:
        source = replace_once(
            source,
            r"^[ \t]*if \(activityMode == MODE_LOGIN\) \{\s*"
            r"TextView waysGramButton = new TextView\(context\);.*?"
            r"^[ \t]*addView\(waysGramButton, waysGramParams\);\s*"
            r"^[ \t]*\}\s*",
            "\n",
            "custom WaysGram login button",
        )

    if "testBackendCheckBox != null" in source:
        source = replace_once(
            source,
            r"^[ \t]*if \(testBackendCheckBox != null\) \{\s*"
            r"testBackendCheckBox\.setSquareCheckBoxColor\([^;]+;\s*"
            r"testBackendCheckBox\.updateTextColor\(\);\s*"
            r"^[ \t]*\}\s*",
            "\n",
            "Test Backend checkbox color block",
        )

    leftovers = [
        name for name in ("WaysGramPortalActivity", "waysGramButton", "testBackendCheckBox")
        if name in source
    ]
    if leftovers:
        raise RuntimeError(f"Unremoved LoginActivity references: {', '.join(leftovers)}")
    if "testBackend = false;" not in source:
        raise RuntimeError("Telegram test-backend default must remain explicitly disabled")

    if source != original:
        path.write_text(source, encoding="utf-8")
        return True
    return False


def patch_manifest(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    original = source
    for activity in ("WaysGramPortalActivity", "WaysGramHomeActivity"):
        pattern = (
            r"\s*<activity\b(?=[^>]*android:name=\"app\.nexusgram\.ui\."
            + re.escape(activity)
            + r"\")[^>]*/>"
        )
        source, count = re.subn(pattern, "", source, count=1, flags=re.DOTALL)
        if count not in (0, 1):
            raise RuntimeError(f"Unexpected number of manifest entries for {activity}: {count}")

    if (
        "app.nexusgram.ui.WaysGramPortalActivity" in source
        or "app.nexusgram.ui.WaysGramHomeActivity" in source
    ):
        raise RuntimeError("A custom Portal/Home Activity registration remains in AndroidManifest.xml")
    if source != original:
        path.write_text(source, encoding="utf-8")
        return True
    return False


def patch_strings(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    original = source
    source, count = re.subn(
        r"^[ \t]*<string name=\"DebugTestBackend\">.*?</string>\s*\n?",
        "",
        source,
        count=1,
        flags=re.MULTILINE | re.DOTALL,
    )
    if count not in (0, 1):
        raise RuntimeError(f"Unexpected DebugTestBackend resource count: {count}")
    if 'name="DebugTestBackend"' in source:
        raise RuntimeError("DebugTestBackend string resource remains")
    if source != original:
        path.write_text(source, encoding="utf-8")
        return True
    return False


def patch_obsolete_activities(root: Path) -> int:
    source_root = root / "TMessagesProj/src/main/java"
    obsolete = {
        "WaysGramPortalActivity": source_root / "app/nexusgram/ui/WaysGramPortalActivity.java",
        "WaysGramHomeActivity": source_root / "app/nexusgram/ui/WaysGramHomeActivity.java",
    }
    existing = {name: path for name, path in obsolete.items() if path.is_file()}
    if not existing:
        return 0

    excluded = set(existing.values())
    references: dict[str, list[str]] = {name: [] for name in existing}
    for java_file in source_root.rglob("*.java"):
        if java_file in excluded:
            continue
        source = java_file.read_text(encoding="utf-8", errors="replace")
        for name in existing:
            if name in source:
                references[name].append(str(java_file.relative_to(root)))

    used = {name: paths for name, paths in references.items() if paths}
    if used:
        details = "; ".join(f"{name}: {', '.join(paths)}" for name, paths in used.items())
        raise RuntimeError(f"Obsolete Portal/Home activities still have external references: {details}")

    for path in existing.values():
        path.unlink()
        print(f"Removed unreachable custom activity: {path.relative_to(root)}")
    return len(existing)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."), help="Unpacked Android project root")
    args = parser.parse_args()
    root = args.root.resolve()

    intro = root / "TMessagesProj/src/main/java/org/telegram/ui/IntroActivity.java"
    login = root / "TMessagesProj/src/main/java/org/telegram/ui/LoginActivity.java"
    manifest = root / "TMessagesProj/src/main/AndroidManifest.xml"
    strings = root / "TMessagesProj/src/main/res/values/strings.xml"
    for file in (intro, login, manifest, strings):
        if not file.is_file():
            raise SystemExit(f"Missing required source file: {file}")

    intro_source = intro.read_text(encoding="utf-8")
    if "new LoginActivity().setIntroView(frameContainerView, startMessagingButton)" not in intro_source:
        raise SystemExit("IntroActivity does not point to Telegram's native LoginActivity")

    changed = [
        patch_login(login),
        patch_manifest(manifest),
        patch_strings(strings),
    ]
    removed = patch_obsolete_activities(root)
    print(f"Native Telegram login UI verified. Updated {sum(changed)} source file(s); removed {removed} unreachable Portal/Home activity file(s).")
    print("No WaysGram Portal/Home entry point or visible Test Backend control remains.")
    print("This restores native navigation only; it does not yet replace MTProto auth or message transport.")


if __name__ == "__main__":
    main()
