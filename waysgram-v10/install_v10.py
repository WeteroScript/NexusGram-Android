#!/usr/bin/env python3
"""Install WaysGram v10 client and matching backend into a restored Telegram source tree."""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

if len(sys.argv) != 3:
    raise SystemExit("usage: install_v10.py <project-root> <bundle-root>")
root = Path(sys.argv[1]).resolve()
bundle = Path(sys.argv[2]).resolve()

# Copy the three self-contained Android components and their matching backend source.
client_root = bundle / "client/TMessagesProj/src/main/java/app/nexusgram"
copy_map = {
    client_root / "network/NexusGramApiClient.java": root / "TMessagesProj/src/main/java/app/nexusgram/network/NexusGramApiClient.java",
    client_root / "ui/WaysGramPortalActivity.java": root / "TMessagesProj/src/main/java/app/nexusgram/ui/WaysGramPortalActivity.java",
    client_root / "ui/WaysGramHomeActivity.java": root / "TMessagesProj/src/main/java/app/nexusgram/ui/WaysGramHomeActivity.java",
}
for source, target in copy_map.items():
    if not source.is_file():
        raise SystemExit(f"Missing v10 source file: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)

backend_source = bundle / "WaysGram-Backend"
backend_target = root / "WaysGram-Backend"
if not (backend_source / "server.py").is_file() or not (backend_source / "tests/smoke_test.py").is_file():
    raise SystemExit("v10 backend bundle is incomplete")
if backend_target.exists():
    shutil.rmtree(backend_target)
shutil.copytree(backend_source, backend_target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

# Register the private WaysGram screens; preserve the original launcher and visual resources.
manifest = root / "TMessagesProj/src/main/AndroidManifest.xml"
manifest_text = manifest.read_text(encoding="utf-8")
activity_anchor = '''        <activity
            android:name="org.telegram.ui.LaunchActivity"'''
activity_block = '''        <activity
            android:name="app.nexusgram.ui.WaysGramPortalActivity"
            android:exported="false"
            android:windowSoftInputMode="adjustResize" />
        <activity
            android:name="app.nexusgram.ui.WaysGramHomeActivity"
            android:exported="false"
            android:windowSoftInputMode="adjustResize" />

'''
if "app.nexusgram.ui.WaysGramPortalActivity" not in manifest_text:
    if activity_anchor not in manifest_text:
        raise SystemExit("Could not locate LaunchActivity manifest declaration")
    manifest_text = manifest_text.replace(activity_anchor, activity_block + activity_anchor, 1)
manifest.write_text(manifest_text, encoding="utf-8")

# Keep the original IntroActivity layout intact. Its existing "Start Messaging" action
# now opens the standalone WaysGram portal instead of Telegram MTProto phone login.
intro = root / "TMessagesProj/src/main/java/org/telegram/ui/IntroActivity.java"
intro_text = intro.read_text(encoding="utf-8")
old_pair = re.compile(
    r'(?m)^([ \t]*)presentFragment\(new LoginActivity\(\)\.setIntroView\(frameContainerView, startMessagingButton\), true\);\n\1destroyed = true;'
)
intro_text, replaced = old_pair.subn(r'\1openWaysGramPortal();', intro_text)
if replaced != 2:
    raise SystemExit(f"Expected exactly two IntroActivity login entry points, replaced {replaced}")
helper = '''\n    private void openWaysGramPortal() {\n        android.app.Activity activity = getParentActivity();\n        if (activity == null) {\n            return;\n        }\n        android.content.Intent intent = new android.content.Intent(\n                activity, app.nexusgram.ui.WaysGramPortalActivity.class);\n        activity.startActivity(intent);\n        activity.finish();\n        destroyed = true;\n    }\n'''
class_anchor = "public class IntroActivity extends BaseFragment implements NotificationCenter.NotificationCenterDelegate {"
if "private void openWaysGramPortal()" not in intro_text:
    if class_anchor not in intro_text:
        raise SystemExit("Could not locate IntroActivity class declaration")
    intro_text = intro_text.replace(class_anchor, class_anchor + helper, 1)
intro.write_text(intro_text, encoding="utf-8")

# Clear stale Telegram phone-login view state for users entering the WaysGram flow.
launch = root / "TMessagesProj/src/main/java/org/telegram/ui/LaunchActivity.java"
launch_text = launch.read_text(encoding="utf-8")
old_method = '''    private BaseFragment getClientNotActivatedFragment() {
        if (LoginActivity.loadCurrentState(false, currentAccount).getInt("currentViewNum", 0) != 0) {
            return new LoginActivity();
        }
        return new IntroActivity();
    }'''
new_method = '''    private BaseFragment getClientNotActivatedFragment() {
        // WaysGram has its own AuthBot session; do not resume a stale Telegram MTProto login form.
        return new IntroActivity();
    }'''
if old_method in launch_text:
    launch_text = launch_text.replace(old_method, new_method, 1)
elif new_method not in launch_text:
    raise SystemExit("Could not locate LaunchActivity unauthenticated fragment selector")
launch.write_text(launch_text, encoding="utf-8")

# Match the branded APK filename without changing application resources or layouts.
app_gradle = root / "TMessagesProj_App/build.gradle"
if app_gradle.is_file():
    gradle_text = app_gradle.read_text(encoding="utf-8")
    gradle_text = gradle_text.replace('outputFileName = "NexusGram.apk"', 'outputFileName = "WaysGram.apk"', 1)
    app_gradle.write_text(gradle_text, encoding="utf-8")

print("WaysGram v10 installed: portal launch, recovery-aware client, matching backend and manifest")