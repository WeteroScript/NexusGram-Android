#!/usr/bin/env python3
"""Fail the build if WaysGram changes Telegram's original UI source or resources."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import xml.etree.ElementTree as ET


UI_JAVA = Path("TMessagesProj/src/main/java/org/telegram/ui")
UI_RES = Path("TMessagesProj/src/main/res")


def relative_files(base: Path, suffix: str | None = None) -> set[Path]:
    if not base.is_dir():
        raise RuntimeError(f"Required directory is missing: {base}")
    files = {p.relative_to(base) for p in base.rglob("*") if p.is_file()}
    if suffix is not None:
        files = {p for p in files if p.suffix == suffix}
    return files


def extract_java_block(source: str, signature: str) -> str:
    if source.count(signature) != 1:
        raise RuntimeError(
            f"Expected exactly one Java UI method signature {signature!r}; "
            f"found {source.count(signature)}"
        )
    start = source.index(signature)
    opening = source.find("{", start)
    if opening < 0:
        raise RuntimeError(f"Missing opening brace for {signature!r}")

    depth = 0
    index = opening
    state = "code"
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if state == "line_comment":
            if char == "\\n":
                state = "code"
        elif state == "block_comment":
            if char == "*" and next_char == "/":
                state = "code"
                index += 1
        elif state in ("string", "char"):
            if char == "\\\\":
                index += 1
            elif (state == "string" and char == '"') or (state == "char" and char == "'"):
                state = "code"
        else:
            if char == "/" and next_char == "/":
                state = "line_comment"
                index += 1
            elif char == "/" and next_char == "*":
                state = "block_comment"
                index += 1
            elif char == '"':
                state = "string"
            elif char == "'":
                state = "char"
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return source[start:index + 1]
        index += 1
    raise RuntimeError(f"Unbalanced Java braces in {signature!r}")


def validate_login_view_methods(original: str, current: str) -> list[str]:
    problems: list[str] = []
    signatures = (
        "public View createView(Context context)",
        "public PhoneView(Context context)",
        "public LoginActivitySmsView(Context context, @AuthType int type)",
    )
    blocks: dict[str, tuple[str, str]] = {}
    for signature in signatures:
        if signature not in original and signature not in current:
            continue
        try:
            blocks[signature] = (
                extract_java_block(original, signature),
                extract_java_block(current, signature),
            )
        except RuntimeError as error:
            problems.append(str(error))

    for signature in (
        "public View createView(Context context)",
        "public LoginActivitySmsView(Context context, @AuthType int type)",
    ):
        if signature in blocks and blocks[signature][0] != blocks[signature][1]:
            problems.append(f"Original LoginActivity layout method was modified: {signature}")

    phone_signature = "public PhoneView(Context context)"
    if phone_signature in blocks:
        original_phone, current_phone = blocks[phone_signature]
        expected_phone, count = re.subn(
            r"^[ \t]*final boolean allowTestBackend = [^\n]*\n.*?(?=^[ \t]*if \(bottomMargin > 0)",
            "\n",
            original_phone,
            count=1,
            flags=re.MULTILINE | re.DOTALL,
        )
        if count not in (0, 1):
            problems.append(f"Unexpected Test Backend block count in {phone_signature}: {count}")
        expected_phone, custom_count = re.subn(
            r"^[ \t]*if \(activityMode == MODE_LOGIN\) \{\s*"
            r"TextView waysGramButton = new TextView\(context\);.*?"
            r"^[ \t]*addView\(waysGramButton, waysGramParams\);\s*"
            r"^[ \t]*\}\s*",
            "\n",
            expected_phone,
            count=1,
            flags=re.MULTILINE | re.DOTALL,
        )
        if custom_count not in (0, 1):
            problems.append(f"Unexpected custom WaysGram button count in {phone_signature}: {custom_count}")
        expected_phone, color_count = re.subn(
            r"^[ \t]*if \(testBackendCheckBox != null\) \{\s*"
            r"testBackendCheckBox\.setSquareCheckBoxColor\([^;]+;\s*"
            r"testBackendCheckBox\.updateTextColor\(\);\s*"
            r"^[ \t]*\}\s*",
            "\n",
            expected_phone,
            count=1,
            flags=re.MULTILINE | re.DOTALL,
        )
        if color_count not in (0, 1):
            problems.append(f"Unexpected Test Backend color block count in {phone_signature}: {color_count}")
        for marker in ("allowTestBackend", "testBackendCheckBox", "waysGramButton"):
            if marker in current_phone:
                problems.append(f"Custom or debug UI remains inside {phone_signature}: {marker}")
        if expected_phone != current_phone:
            problems.append(
                "PhoneView constructor differs from the original apart from removal of the Test Backend row"
            )
    return problems


def validate_string_resources(reference_root: Path, current_root: Path) -> list[str]:
    problems: list[str] = []
    reference_files = {
        p.relative_to(reference_root)
        for p in reference_root.glob("values*/strings.xml")
    }
    current_files = {
        p.relative_to(current_root)
        for p in current_root.glob("values*/strings.xml")
    }
    if reference_files != current_files:
        missing = sorted(p.as_posix() for p in reference_files - current_files)
        unexpected = sorted(p.as_posix() for p in current_files - reference_files)
        if missing:
            problems.append("missing locale strings resources: " + ", ".join(missing))
        if unexpected:
            problems.append("unexpected locale strings resources: " + ", ".join(unexpected))

    debug_pattern = r'^[ \t]*<string name="DebugTestBackend">.*?</string>\s*\n?'
    app_name_pattern = r'(<string\s+name="AppName">)(.*?)(</string>)'
    for relative in sorted(reference_files & current_files):
        original = (reference_root / relative).read_text(encoding="utf-8")
        expected, debug_count = re.subn(
            debug_pattern, "", original, count=1, flags=re.MULTILINE | re.DOTALL
        )
        if debug_count not in (0, 1):
            problems.append(f"{relative}: unexpected DebugTestBackend count {debug_count}")
        expected, app_name_count = re.subn(
            app_name_pattern, r'\1WaysGram\3', expected, count=1, flags=re.DOTALL
        )
        if app_name_count != 1:
            problems.append(f"{relative}: expected exactly one original AppName resource")
            continue

        actual_path = current_root / relative
        actual = actual_path.read_text(encoding="utf-8")
        if actual != expected:
            problems.append(f"{relative}: strings changed beyond the allowed WaysGram name and removed test toggle")
        try:
            xml_root = ET.fromstring(actual)
        except ET.ParseError as error:
            problems.append(f"{relative}: invalid XML: {error}")
            continue
        labels = [
            node.text or ""
            for node in xml_root.findall("string")
            if node.attrib.get("name") == "AppName"
        ]
        if labels != ["WaysGram"]:
            problems.append(f"{relative}: expected one AppName=WaysGram, found {labels!r}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--reference", type=Path, default=Path("Telegram-master"))
    args = parser.parse_args()
    root = args.root.resolve()
    reference = args.reference.resolve()

    reference_ui = reference / UI_JAVA
    current_ui = root / UI_JAVA
    problems: list[str] = []

    # LoginActivity is the only screen whose behavior is patched for WaysGram
    # authentication. All other Telegram UI Java classes must remain byte-identical.
    ref_java = relative_files(reference_ui, ".java")
    cur_java = relative_files(current_ui, ".java")
    allowed = {Path("LoginActivity.java")}
    for path in sorted((ref_java | cur_java) - allowed):
        old, new = reference_ui / path, current_ui / path
        if not old.is_file():
            problems.append(f"unexpected UI Java file: {path.as_posix()}")
        elif not new.is_file():
            problems.append(f"missing original UI Java file: {path.as_posix()}")
        else:
            expected = old.read_bytes()
            if path == Path("DeveloperPanelActivity.java"):
                original_text = expected.decode("utf-8")
                pattern = re.compile(r'(\.append\(")(.*?)(?="\))', re.DOTALL)
                repaired, count = pattern.subn(
                    lambda match: match.group(1) + match.group(2).replace("\n", r"\n"),
                    original_text,
                )
                if count == 0:
                    problems.append("expected DeveloperPanelActivity string-literal repair anchor was not found in reference")
                expected = repaired.encode("utf-8")
            if expected != new.read_bytes():
                problems.append(f"modified original UI Java file: {path.as_posix()}")

    # Layouts, drawables, menus, themes, dimensions and other resources must be
    # identical. Only strings.xml files may differ for the WaysGram app name.
    ref_res = reference / UI_RES
    cur_res = root / UI_RES
    ref_files = relative_files(ref_res)
    cur_files = relative_files(cur_res)
    excluded = {
        p for p in (ref_files | cur_files)
        if p.name == "strings.xml" and p.parent.name.startswith("values")
    }
    for path in sorted((ref_files | cur_files) - excluded):
        old, new = ref_res / path, cur_res / path
        if not old.is_file():
            problems.append(f"unexpected UI resource: {path.as_posix()}")
        elif not new.is_file():
            problems.append(f"missing original UI resource: {path.as_posix()}")
        elif old.read_bytes() != new.read_bytes():
            problems.append(f"modified original UI resource: {path.as_posix()}")

    # LoginActivity receives behavior hooks, but it must not gain custom views.
    reference_login = reference_ui / "LoginActivity.java"
    current_login = current_ui / "LoginActivity.java"
    if not reference_login.is_file() or not current_login.is_file():
        problems.append("original or patched LoginActivity.java is missing")
    else:
        original_login = reference_login.read_text(encoding="utf-8")
        patched_login = current_login.read_text(encoding="utf-8")
        original_add_views = len(re.findall(r"\baddView\s*\(", original_login))
        patched_add_views = len(re.findall(r"\baddView\s*\(", patched_login))
        removed_original_views = 0
        if "final boolean allowTestBackend =" in original_login:
            start = original_login.index("final boolean allowTestBackend =")
            end = original_login.find("if (bottomMargin > 0)", start)
            if end < 0:
                problems.append("could not identify the removed original Test Backend row")
            else:
                removed_original_views += len(
                    re.findall(r"\baddView\s*\(", original_login[start:end])
                )
        if "waysGramButton" in original_login:
            removed_original_views += len(
                re.findall(r"addView\s*\(\s*waysGramButton", original_login)
            )
        expected_add_views = original_add_views - removed_original_views
        if patched_add_views != expected_add_views:
            problems.append(
                f"LoginActivity view hierarchy changed: expected {expected_add_views} addView calls "
                f"after removing only test controls, found {patched_add_views}"
            )
        for marker in ("WaysGramPortalActivity", "WaysGramHomeActivity", "waysGramButton", "testBackendCheckBox"):
            if marker in patched_login:
                problems.append(f"custom or debug UI remains in LoginActivity: {marker}")
        problems.extend(validate_login_view_methods(original_login, patched_login))

    problems.extend(validate_string_resources(ref_res, cur_res))
    manifest = root / "TMessagesProj/src/main/AndroidManifest.xml"
    manifest_text = manifest.read_text(encoding="utf-8")
    for custom_name in ("WaysGramPortalActivity", "WaysGramHomeActivity"):
        if custom_name in manifest_text:
            problems.append(f"custom activity remains registered: {custom_name}")

    custom_ui = root / "TMessagesProj/src/main/java/app/waysgram/ui"
    if custom_ui.exists():
        remaining = sorted(p.relative_to(root) for p in custom_ui.rglob("*.java"))
        if remaining:
            problems.append("custom UI Java classes remain: " + ", ".join(p.as_posix() for p in remaining))

    if problems:
        print("ORIGINAL UI VERIFICATION FAILED:")
        for problem in problems:
            print(f" - {problem}")
        return 1

    checked_ui = len(ref_java - allowed)
    checked_resources = len((ref_files | cur_files) - excluded)
    print(f"PASS: {checked_ui} original Telegram UI Java files are byte-identical.")
    print(f"PASS: {checked_resources} original Android UI resources are byte-identical.")
    print("PASS: WaysGram is the launcher name in every locale.")
    print("PASS: no custom Portal/Home UI activity remains.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
