#!/usr/bin/env python3
"""Configure the NexusGram source tree to receive its WaysGram API URL at build time."""
from __future__ import annotations

from pathlib import Path

CONFIG_JAVA = '''package app.nexusgram.network;

import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Bundle;

/** Reads the single production WaysGram API endpoint injected by the Android build. */
public final class WaysGramApiConfig {
    private static final String META_DATA_KEY = "app.nexusgram.API_BASE_URL";

    private WaysGramApiConfig() {
    }

    public static String getBaseUrl(Context context) {
        if (context == null) return "";
        try {
            PackageManager manager = context.getPackageManager();
            ApplicationInfo info = manager.getApplicationInfo(
                    context.getPackageName(), PackageManager.GET_META_DATA);
            Bundle metadata = info.metaData;
            if (metadata == null) return "";
            String value = metadata.getString(META_DATA_KEY, "");
            return value == null ? "" : value.trim().replaceAll("/+$", "");
        } catch (PackageManager.NameNotFoundException error) {
            return "";
        }
    }

    public static NexusGramApiClient createClient(Context context) {
        String baseUrl = getBaseUrl(context);
        if (baseUrl.isEmpty()) {
            throw new IllegalStateException(
                    "WaysGram API URL is not configured in this build. "
                    + "Set the WAYSGRAM_API_BASE_URL repository secret.");
        }
        return new NexusGramApiClient(context.getApplicationContext(), baseUrl);
    }
}
'''


def update_once(path: Path, old: str, new: str, label: str) -> bool:
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

    gradle = root / "TMessagesProj/build.gradle"
    manifest = root / "TMessagesProj/src/main/AndroidManifest.xml"
    client_source = root / "waysgram/NexusGramApiClient.java"
    client = root / "TMessagesProj/src/main/java/app/nexusgram/network/NexusGramApiClient.java"
    config = root / "TMessagesProj/src/main/java/app/nexusgram/network/WaysGramApiConfig.java"
    for path in (gradle, manifest, client_source):
        if not path.is_file():
            raise SystemExit(f"Missing required source file: {path}")

    changed = 0
    client.parent.mkdir(parents=True, exist_ok=True)
    bundled_client = client_source.read_text(encoding="utf-8")
    if not client.exists() or client.read_text(encoding="utf-8") != bundled_client:
        client.write_text(bundled_client, encoding="utf-8")
        changed += 1

    changed += update_once(
        gradle,
        "    defaultConfig {\n        minSdkVersion 23",
        "    defaultConfig {\n"
        "        manifestPlaceholders += [waysgramApiBaseUrl: (project.findProperty('waysgramApiBaseUrl') ?: System.getenv('WAYSGRAM_API_BASE_URL') ?: '').toString()]\n"
        "        minSdkVersion 23",
        "TMessagesProj defaultConfig",
    )
    manifest_placeholder = "$" + "{waysgramApiBaseUrl}"
    manifest_anchor = "        <!-- usesCleartextTraffic for browser supporting opening http:// links -->"
    manifest_replacement = (
        '        <meta-data android:name="app.nexusgram.API_BASE_URL" android:value="'
        + manifest_placeholder + '" />\n\n' + manifest_anchor
    )
    changed += update_once(
        manifest,
        manifest_anchor,
        manifest_replacement,
        "application metadata insertion",
    )

    if not config.exists() or config.read_text(encoding="utf-8") != CONFIG_JAVA:
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(CONFIG_JAVA, encoding="utf-8")
        changed += 1

    source = client.read_text(encoding="utf-8")
    old_error = 'String message = json.optString("error", "Ошибка WaysGram API: HTTP " + status);'
    new_error = 'String message = json.optString("detail", json.optString("error", "Ошибка WaysGram API: HTTP " + status));'
    if 'json.optString("detail", json.optString("error"' not in source:
        if source.count(old_error) != 1:
            raise RuntimeError("Android REST client must parse FastAPI detail errors")
        client.write_text(source.replace(old_error, new_error, 1), encoding="utf-8")
        changed += 1

    gradle_source = gradle.read_text(encoding="utf-8")
    manifest_source = manifest.read_text(encoding="utf-8")
    client_source = client.read_text(encoding="utf-8")
    if "waysgramApiBaseUrl" not in gradle_source:
        raise RuntimeError("Gradle does not define the waysgramApiBaseUrl manifest placeholder")
    if 'android:name="app.nexusgram.API_BASE_URL"' not in manifest_source:
        raise RuntimeError("Android manifest does not expose the WaysGram API endpoint")
    if 'optString("detail", json.optString("error"' not in client_source:
        raise RuntimeError("Android REST client does not handle FastAPI detail errors")

    print(f"WaysGram API build configuration verified. Updated {changed} file(s).")
    print("The server URL is injected at build time; no manual URL field or test-backend switch is added.")


if __name__ == "__main__":
    main()
