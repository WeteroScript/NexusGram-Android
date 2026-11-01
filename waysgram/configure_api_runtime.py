#!/usr/bin/env python3
"""Install the process-wide WaysGram REST client runtime into Telegram source."""
from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> bool:
    source = path.read_text(encoding="utf-8")
    if new in source:
        return False
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one {label} anchor in {path}; found {count}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    return True


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    root = args.root.resolve()

    source_root = root / "TMessagesProj/src/main/java"
    app_loader = source_root / "org/telegram/messenger/ApplicationLoader.java"
    package_root = source_root / "app/nexusgram/network"
    client = package_root / "NexusGramApiClient.java"
    config = package_root / "WaysGramApiConfig.java"
    runtime = package_root / "WaysGramApiRuntime.java"
    bundled_runtime = root / "waysgram/WaysGramApiRuntime.java"

    for path in (app_loader, client, config, bundled_runtime):
        if not path.is_file():
            raise SystemExit(f"Missing required source file: {path}")

    package_root.mkdir(parents=True, exist_ok=True)
    bundled = bundled_runtime.read_text(encoding="utf-8")
    if not runtime.exists() or runtime.read_text(encoding="utf-8") != bundled:
        runtime.write_text(bundled, encoding="utf-8")

    changed = replace_once(
        app_loader,
        "import org.telegram.ui.LauncherIconController;\n",
        "import org.telegram.ui.LauncherIconController;\n"
        "import app.nexusgram.network.WaysGramApiRuntime;\n",
        "ApplicationLoader WaysGram runtime import",
    )
    changed |= replace_once(
        app_loader,
        "        super.onCreate();\n\n        // AndroidUtilities must be initialized before FileLog\n",
        "        super.onCreate();\n"
        "        WaysGramApiRuntime.initialize(applicationContext);\n\n"
        "        // AndroidUtilities must be initialized before FileLog\n",
        "ApplicationLoader REST runtime initialization",
    )

    source = app_loader.read_text(encoding="utf-8")
    if "import app.nexusgram.network.WaysGramApiRuntime;" not in source:
        raise RuntimeError("WaysGramApiRuntime import was not installed")
    if "WaysGramApiRuntime.initialize(applicationContext);" not in source:
        raise RuntimeError("WaysGramApiRuntime initialization was not installed")

    runtime_source = runtime.read_text(encoding="utf-8")
    required = (
        "public static NexusGramApiClient getClient()",
        "public static boolean isConfigured()",
        "public static String getConfigurationError()",
        "WaysGramApiConfig.getBaseUrl(context)",
    )
    missing = [value for value in required if value not in runtime_source]
    if missing:
        raise RuntimeError("WaysGramApiRuntime is incomplete: " + ", ".join(missing))

    print(f"WaysGram API runtime installed. ApplicationLoader updated: {changed}.")
    print("Native UI code can now retrieve the shared client using WaysGramApiRuntime.getClient().")


if __name__ == "__main__":
    main()
