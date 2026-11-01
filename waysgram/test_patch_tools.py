#!/usr/bin/env python3
"""Smoke-test the repeatable Android source-tree patch scripts without an SDK."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run(script: Path, root: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(script), "--root", str(root)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(
            f"{script.name} failed with exit {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="nexusgram-patch-test-") as temp:
        root = Path(temp)
        source = root / "TMessagesProj/src/main/java"
        waysgram = root / "waysgram"

        write(
            source / "org/telegram/ui/IntroActivity.java",
            "new LoginActivity().setIntroView(frameContainerView, startMessagingButton);\n",
        )
        write(
            source / "org/telegram/ui/LoginActivity.java",
            """import app.nexusgram.ui.WaysGramPortalActivity;
        private CheckBoxCell testBackendCheckBox;
boolean testBackend = false;
void createLogin(Context context) {
    if (activityMode == MODE_LOGIN) {
        TextView waysGramButton = new TextView(context);
        FrameLayout.LayoutParams waysGramParams = new FrameLayout.LayoutParams(1, 1);
        waysGramButton.setText("WaysGram");
        addView(waysGramButton, waysGramParams);
    }
    if (testBackendCheckBox != null) {
        testBackendCheckBox.setSquareCheckBoxColor(a, b, c);
        testBackendCheckBox.updateTextColor();
    }
}
""",
        )
        write(
            root / "TMessagesProj/src/main/AndroidManifest.xml",
            """<manifest><application>
<activity android:name="app.nexusgram.ui.WaysGramPortalActivity" />
<activity android:name="app.nexusgram.ui.WaysGramHomeActivity" />
<!-- usesCleartextTraffic for browser supporting opening http:// links -->
</application></manifest>
""",
        )
        write(
            root / "TMessagesProj/src/main/res/values/strings.xml",
            '<resources><string name="DebugTestBackend">Test Backend</string></resources>\n',
        )
        write(
            root / "TMessagesProj/build.gradle",
            "android {\n    defaultConfig {\n        minSdkVersion 23\n    }\n}\n",
        )
        write(
            source / "org/telegram/messenger/ApplicationLoader.java",
            """package org.telegram.messenger;
import org.telegram.ui.LauncherIconController;
public class ApplicationLoader {
    void onCreate() {
        super.onCreate();

        // AndroidUtilities must be initialized before FileLog
    }
}
""",
        )
        (waysgram).mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "NexusGramApiClient.java", waysgram / "NexusGramApiClient.java")
        shutil.copy2(ROOT / "WaysGramApiRuntime.java", waysgram / "WaysGramApiRuntime.java")

        write(
            source / "app/nexusgram/ui/WaysGramPortalActivity.java",
            "package app.nexusgram.ui; class WaysGramPortalActivity {}\n",
        )
        write(
            source / "app/nexusgram/ui/WaysGramHomeActivity.java",
            "package app.nexusgram.ui; class WaysGramHomeActivity {}\n",
        )

        scripts = (
            ROOT / "apply_native_ui_v11.py",
            ROOT / "configure_api_client.py",
            ROOT / "configure_api_runtime.py",
        )
        for script in scripts:
            run(script, root)
        for script in scripts:
            run(script, root)

        login = (source / "org/telegram/ui/LoginActivity.java").read_text(encoding="utf-8")
        manifest = (root / "TMessagesProj/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        strings = (root / "TMessagesProj/src/main/res/values/strings.xml").read_text(encoding="utf-8")
        app_loader = (source / "org/telegram/messenger/ApplicationLoader.java").read_text(encoding="utf-8")
        gradle = (root / "TMessagesProj/build.gradle").read_text(encoding="utf-8")

        assert "WaysGramPortalActivity" not in login
        assert "waysGramButton" not in login
        assert "testBackendCheckBox" not in login
        assert "WaysGramPortalActivity" not in manifest
        assert "WaysGramHomeActivity" not in manifest
        assert "DebugTestBackend" not in strings
        assert "app.nexusgram.API_BASE_URL" in manifest
        assert "waysgramApiBaseUrl" in gradle
        assert "WaysGramApiRuntime.initialize(applicationContext);" in app_loader
        assert "import app.nexusgram.network.WaysGramApiRuntime;" in app_loader
        assert (source / "app/nexusgram/network/NexusGramApiClient.java").is_file()
        assert (source / "app/nexusgram/network/WaysGramApiConfig.java").is_file()
        assert (source / "app/nexusgram/network/WaysGramApiRuntime.java").is_file()
        assert not (source / "app/nexusgram/ui/WaysGramPortalActivity.java").exists()
        assert not (source / "app/nexusgram/ui/WaysGramHomeActivity.java").exists()

        print("PASS: native UI, API configuration and shared runtime patches are idempotent.")
        print("PASS: original LoginActivity remains the login entry point.")
        print("PASS: no Portal/Home activities or Test Backend control remain.")


if __name__ == "__main__":
    main()
