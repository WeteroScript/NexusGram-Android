#!/usr/bin/env python3
"""Apply WaysGram branding and restore the native login entry point."""
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

    source = source.replace("import app.waysgram.ui.WaysGramPortalActivity;\n", "")
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

    # Some Telegram source snapshots still render the Test Backend row.
    # Remove the complete row, including its backend-switching click handler.
    if "final boolean allowTestBackend =" in source:
        source = replace_once(
            source,
            r"^[ \t]*final boolean allowTestBackend = [^\n]*\n.*?(?=^[ \t]*if \(bottomMargin > 0)",
            "\n",
            "Test Backend option and backend switch handler",
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
            r"\s*<activity\b(?=[^>]*android:name=\"app\.waysgram\.ui\."
            + re.escape(activity)
            + r"\")[^>]*/>"
        )
        source, count = re.subn(pattern, "", source, count=1, flags=re.DOTALL)
        if count not in (0, 1):
            raise RuntimeError(f"Unexpected number of manifest entries for {activity}: {count}")

    if (
        "app.waysgram.ui.WaysGramPortalActivity" in source
        or "app.waysgram.ui.WaysGramHomeActivity" in source
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
    app_name_pattern = r'(<string\s+name="AppName">)(.*?)(</string>)'
    source, app_name_count = re.subn(
        app_name_pattern, r'\1WaysGram\3', source, count=1, flags=re.DOTALL
    )
    if app_name_count != 1:
        raise RuntimeError(f"Expected exactly one AppName resource; found {app_name_count}")
    if source != original:
        path.write_text(source, encoding="utf-8")
        return True
    return False


def patch_obsolete_activities(root: Path) -> int:
    source_root = root / "TMessagesProj/src/main/java"
    obsolete = {
        "WaysGramPortalActivity": source_root / "app/waysgram/ui/WaysGramPortalActivity.java",
        "WaysGramHomeActivity": source_root / "app/waysgram/ui/WaysGramHomeActivity.java",
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
    strings_root = root / "TMessagesProj/src/main/res"
    string_files = sorted(strings_root.glob("values*/strings.xml"))
    for file in (intro, login, manifest):
        if not file.is_file():
            raise SystemExit(f"Missing required source file: {file}")
    if not string_files:
        raise SystemExit(f"No Android strings.xml files found under: {strings_root}")

    intro_source = intro.read_text(encoding="utf-8")
    if "new LoginActivity().setIntroView(frameContainerView, startMessagingButton)" not in intro_source:
        raise SystemExit("IntroActivity does not point to Telegram's native LoginActivity")

    changed = [
        patch_login(login),
        patch_manifest(manifest),
        *(patch_strings(path) for path in string_files),
    ]
    removed = patch_obsolete_activities(root)
    print(f"WaysGram branding applied to {len(string_files)} locale string file(s).")
    print(f"Native LoginActivity retained. Updated {sum(changed)} source/resource file(s); removed {removed} unreachable Portal/Home activity file(s).")
    print("No custom Portal/Home entry point or visible Test Backend control remains.")


if __name__ == "__main__":
    main()
