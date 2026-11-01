#!/usr/bin/env python3
"""Fail the build if WaysGram changes Telegram's original UI source or resources."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


UI_JAVA = Path("TMessagesProj/src/main/java/org/telegram/ui")
UI_RES = Path("TMessagesProj/src/main/res")


def relative_files(root: Path, base: Path, suffix: str | None = None) -> set[Path]:
    if not base.is_dir():
        raise RuntimeError(f"Required directory is missing: {base}")
    files = {p.relative_to(base) for p in base.rglob("*") if p.is_file()}
    if suffix is not None:
        files = {p for p in files if p.suffix == suffix}
    return files


def compare_bytes(reference: Path, current: Path, label: str) -> list[str]:
    reference_files = relative_files(reference, reference)
    current_files = relative_files(current, current)
    problems: list[str] = []
    for path in sorted(reference_files | current_files):
        old = reference / path
        new = current / path
        if not old.is_file():
            problems.append(f"unexpected file: {label}/{path.as_posix()}")
        elif not new.is_file():
            problems.append(f"missing original file: {label}/{path.as_posix()}")
        elif old.read_bytes() != new.read_bytes():
            problems.append(f"modified original file: {label}/{path.as_posix()}")
    return problems


def validate_app_names(resource_root: Path) -> list[str]:
    problems: list[str] = []
    files = sorted(resource_root.glob("values*/strings.xml"))
    if not files:
        return [f"No locale strings.xml files found under {resource_root}"]
    for path in files:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as error:
            problems.append(f"Invalid XML in {path}: {error}")
            continue
        labels = [node.text or "" for node in root.findall("string") if node.attrib.get("name") == "AppName"]
        if labels != ["WaysGram"]:
            problems.append(f"{path}: expected one AppName=WaysGram, found {labels!r}")
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
    ref_java = relative_files(reference, reference_ui, ".java")
    cur_java = relative_files(root, current_ui, ".java")
    allowed = {Path("LoginActivity.java")}
    for path in sorted((ref_java | cur_java) - allowed):
        old, new = reference_ui / path, current_ui / path
        if not old.is_file():
            problems.append(f"unexpected UI Java file: {path.as_posix()}")
        elif not new.is_file():
            problems.append(f"missing original UI Java file: {path.as_posix()}")
        elif old.read_bytes() != new.read_bytes():
            problems.append(f"modified original UI Java file: {path.as_posix()}")

    # Layouts, drawables, menus, themes, dimensions and other resources must be
    # identical. Only strings.xml files may differ for the WaysGram app name.
    ref_res = reference / UI_RES
    cur_res = root / UI_RES
    ref_files = relative_files(reference, ref_res)
    cur_files = relative_files(root, cur_res)
    excluded = {p for p in (ref_files | cur_files) if p.name == "strings.xml"}
    for path in sorted((ref_files | cur_files) - excluded):
        old, new = ref_res / path, cur_res / path
        if not old.is_file():
            problems.append(f"unexpected UI resource: {path.as_posix()}")
        elif not new.is_file():
            problems.append(f"missing original UI resource: {path.as_posix()}")
        elif old.read_bytes() != new.read_bytes():
            problems.append(f"modified original UI resource: {path.as_posix()}")

    problems.extend(validate_app_names(cur_res))
    manifest = root / "TMessagesProj/src/main/AndroidManifest.xml"
    manifest_text = manifest.read_text(encoding="utf-8")
    for custom_name in ("WaysGramPortalActivity", "WaysGramHomeActivity"):
        if custom_name in manifest_text:
            problems.append(f"custom activity remains registered: {custom_name}")

    custom_ui = root / "TMessagesProj/src/main/java/app/nexusgram/ui"
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
