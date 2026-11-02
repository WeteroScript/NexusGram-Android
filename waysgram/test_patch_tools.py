#!/usr/bin/env python3
"""Smoke-test the repeatable Android source-tree patch scripts without an SDK."""
from __future__ import annotations

import shutil
import subprocess
import re
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


def verify_login_view_variants() -> None:
    """Check both Telegram login snapshots: with and without the debug toggle."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "verify_original_ui", ROOT / "verify_original_ui.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load verify_original_ui.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)

    signature = (
        "public class PhoneView extends SlideView implements "
        "AdapterView.OnItemSelectedListener, NotificationCenter.NotificationCenterDelegate"
    )
    clean_snapshot = signature + """ {
        public PhoneView(Context context) {
            super(context);
        }
        public void updateColors() {
        }
    }
    """
    clean_problems = verifier.validate_login_view_methods(clean_snapshot, clean_snapshot)
    if clean_problems:
        raise RuntimeError(
            "UI verifier rejected a source snapshot without Test Backend controls: "
            + "; ".join(clean_problems)
        )

    original_snapshot = signature + """ {
        public PhoneView(Context context) {
            super(context);
            final boolean allowTestBackend = true;
            if (allowTestBackend && activityMode == MODE_LOGIN) {
                testBackendCheckBox = new CheckBoxCell(context, 2);
                addView(testBackendCheckBox, LayoutHelper.createLinear(1, 1));
                bottomMargin -= 24;
            }
            if (bottomMargin > 0) {
                addView(new Space(context), LayoutHelper.createLinear(1, 1));
            }
        }
        public void updateColors() {
            if (testBackendCheckBox != null) {
                testBackendCheckBox.setSquareCheckBoxColor(a, b, c);
                testBackendCheckBox.updateTextColor();
            }
        }
    }
    """
    patched_snapshot, row_count = re.subn(
        r"^[ \t]*final boolean allowTestBackend = [^\n]*\n.*?(?=^[ \t]*if \(bottomMargin > 0)",
        "\n",
        original_snapshot,
        count=1,
        flags=re.MULTILINE | re.DOTALL,
    )
    patched_snapshot, color_count = re.subn(
        r"^[ \t]*if \(testBackendCheckBox != null\) \{\s*"
        r"testBackendCheckBox\.setSquareCheckBoxColor\([^;]+;\s*"
        r"testBackendCheckBox\.updateTextColor\(\);\s*"
        r"^[ \t]*\}\s*",
        "\n",
        patched_snapshot,
        count=1,
        flags=re.MULTILINE | re.DOTALL,
    )
    if row_count != 1 or color_count != 1:
        raise RuntimeError(
            "Test fixture did not contain exactly one removable Test Backend row and color block"
        )
    patched_problems = verifier.validate_login_view_methods(
        original_snapshot, patched_snapshot
    )
    if patched_problems:
        raise RuntimeError(
            "UI verifier rejected the expected removal of Test Backend controls: "
            + "; ".join(patched_problems)
        )


def main() -> None:
    verify_login_view_variants()
    with tempfile.TemporaryDirectory(prefix="waysgram-patch-test-") as temp:
        root = Path(temp)
        source = root / "TMessagesProj/src/main/java"
        waysgram = root / "waysgram"

        write(
            source / "org/telegram/ui/IntroActivity.java",
            "new LoginActivity().setIntroView(frameContainerView, startMessagingButton);\n",
        )
        write(
            source / "org/telegram/ui/LoginActivity.java",
            """import app.waysgram.ui.WaysGramPortalActivity;
import app.nexusgram.ui.WaysGramPortalActivity;
        private CheckBoxCell testBackendCheckBox;
boolean testBackend = false;
void createLogin(Context context) {
    final boolean allowTestBackend = true;
    if (allowTestBackend && activityMode == MODE_LOGIN) {
        testBackendCheckBox = new CheckBoxCell(context, 2);
        testBackendCheckBox.setText(getString(R.string.DebugTestBackend), "", testBackend, false);
        addView(testBackendCheckBox, LayoutHelper.createLinear(1, 1));
        bottomMargin -= 24;
        testBackendCheckBox.setOnClickListener(v -> {
            testBackend = !testBackend;
            getConnectionsManager().switchBackend(false);
            loadCountries();
        });
    }
    if (bottomMargin > 0) {
    }
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
<activity android:name="app.waysgram.ui.WaysGramPortalActivity" />
<activity android:name="app.waysgram.ui.WaysGramHomeActivity" />
<activity android:name="app.nexusgram.ui.WaysGramPortalActivity" />
<activity android:name="app.nexusgram.ui.WaysGramHomeActivity" />
        <!-- usesCleartextTraffic for browser supporting opening http:// links -->
</application></manifest>
""",
        )
        write(
            root / "TMessagesProj/src/main/res/values/strings.xml",
            "<resources>\n"
            "    <string name=\"AppName\">Telegram</string>\n"
            "    <string name=\"DebugTestBackend\">Test Backend</string>\n"
            "</resources>\n",
        )
        write(
            root / "TMessagesProj/src/main/res/values-ru/strings.xml",
            "<resources>\n"
            "    <string name=\"AppName\">Telegram</string>\n"
            "</resources>\n",
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
        write(
            source / "org/telegram/ui/LoginActivity.java",
            """package org.telegram.ui;
import app.waysgram.ui.WaysGramPortalActivity;
import app.nexusgram.ui.WaysGramPortalActivity;
        private CheckBoxCell testBackendCheckBox;
boolean testBackend = false;
class LoginActivity {
    void createLogin(Context context) {
        final boolean allowTestBackend = true;
        if (allowTestBackend && activityMode == MODE_LOGIN) {
            testBackendCheckBox = new CheckBoxCell(context, 2);
            testBackendCheckBox.setText(getString(R.string.DebugTestBackend), "", testBackend, false);
            addView(testBackendCheckBox, LayoutHelper.createLinear(1, 1));
            bottomMargin -= 24;
            testBackendCheckBox.setOnClickListener(v -> {
                testBackend = !testBackend;
                getConnectionsManager().switchBackend(false);
                loadCountries();
            });
        }
        if (bottomMargin > 0) {
        }
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
    class PhoneView {
        boolean nextPressed;
        boolean isRequestingFirebaseSms;
        String phone;
        void onConfirm() {
            confirmedNumber = true;
            currentDoneType = DONE_TYPE_FLOATING;
            needShowProgress(0, false);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                requestPhonePermissions();
            }
        }
        @Override
        public void onNextPressed(String code) {
            if (getParentActivity() == null || nextPressed || isRequestingFirebaseSms) {
                return;
            }
        }
    }
    public class LoginActivitySmsView extends SlideView implements NotificationCenter.NotificationCenterDelegate {
        private boolean nextPressed;
        private String lastError = "";

        public void setParams(Bundle params, boolean restore) {
            if (params == null) {
                if (nextCodeParams != null && nextCodeAuth != null) {
                    return;
                }
                return;
            }
            waitingForEvent = true;
            if (currentType == AUTH_TYPE_FRAGMENT_SMS) {
                addSmsObserver();
            } else if (currentType == AUTH_TYPE_SMS) {
                AndroidUtilities.setWaitingForSms(true);
                NotificationCenter.getGlobalInstance().addObserver(this, NotificationCenter.didReceiveSmsCode);
            }
            confirmTextView.setText(str);
        }

        public void onNextPressed(String code) {
            nextPressed = true;
            if (currentType == AUTH_TYPE_FRAGMENT_SMS) {
                removeSmsObserver();
            } else if (currentType == AUTH_TYPE_SMS) {
                AndroidUtilities.setWaitingForSms(false);
                NotificationCenter.getGlobalInstance().removeObserver(this, NotificationCenter.didReceiveSmsCode);
            }
            waitingForEvent = false;

            switch (activityMode) {
                case MODE_LOGIN: break;
            }
        }

        public boolean onBackPressed(boolean force) {
            nextPressed = false;
            tryHideProgress(true);
            TLRPC.TL_auth_cancelCode req = new TLRPC.TL_auth_cancelCode();
            req.phone_number = requestPhone;
            req.phone_code_hash = phoneHash;
            ConnectionsManager.getInstance(currentAccount).sendRequest(req, (response, error) -> {

            }, ConnectionsManager.RequestFlagFailOnServerErrors | ConnectionsManager.RequestFlagWithoutLogin);

            destroyTimer();
            destroyCodeTimer();
            currentParams = null;
            if (currentType == AUTH_TYPE_FRAGMENT_SMS) {
                removeSmsObserver();
            } else if (currentType == AUTH_TYPE_SMS) {
                AndroidUtilities.setWaitingForSms(false);
                NotificationCenter.getGlobalInstance().removeObserver(this, NotificationCenter.didReceiveSmsCode);
            }
            waitingForEvent = false;
            return true;
        }

        @Override
        public void onDestroyActivity() {
            super.onDestroyActivity();
            if (currentType == AUTH_TYPE_FRAGMENT_SMS) {
                removeSmsObserver();
            } else if (currentType == AUTH_TYPE_SMS) {
                AndroidUtilities.setWaitingForSms(false);
                NotificationCenter.getGlobalInstance().removeObserver(this, NotificationCenter.didReceiveSmsCode);
            }
            waitingForEvent = false;
        }
    }
    public class LoadingTextView extends TextView {
    }
    private void onAuthSuccess(TLRPC.TL_auth_authorization res) {
    }
}
"""
        )
        write(
            source / "org/telegram/messenger/MessagesController.java",
            """package org.telegram.messenger;
class MessagesController {
    public void loadDialogs(final int folderId, int offset, int count, boolean fromCache, Runnable onEmptyCallback) {
        if (loadingDialogs.get(folderId) || resetingDialogs) {
            return;
        }
    }
    private void loadMessagesInternal() {
            final TLRPC.Chat chat = dialogId < 0 ? getChat(-dialogId): null;
    }
    public void processLoadedMessages(TLRPC.messages_Messages messagesRes, int resCount, long dialogId, long mergeDialogId, int count, int max_id, int offset_date, boolean isCache, int classGuid,
    }
}
"""
        )
        write(
            source / "org/telegram/messenger/SendMessagesHelper.java",
            """package org.telegram.messenger;
class SendMessagesHelper {
    public void sendMessage(SendMessageParams sendMessageParams) {
        final SendMessageChatArguments sendMessageChatArguments = SendMessageChatArguments.EMPTY;
    }
}
"""
        )
        (waysgram).mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "WaysGramApiClient.java", waysgram / "WaysGramApiClient.java")
        shutil.copy2(ROOT / "WaysGramApiRuntime.java", waysgram / "WaysGramApiRuntime.java")
        shutil.copy2(ROOT / "WaysGramDataMapper.java", waysgram / "WaysGramDataMapper.java")

        write(
            source / "app/waysgram/ui/WaysGramPortalActivity.java",
            "package app.waysgram.ui; class WaysGramPortalActivity {}\n",
        )
        write(
            source / "app/waysgram/ui/WaysGramHomeActivity.java",
            "package app.waysgram.ui; class WaysGramHomeActivity {}\n",
        )

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
            ROOT / "configure_native_messenger.py",
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
        assert '<string name="AppName">WaysGram</string>' in strings
        russian_strings = (root / "TMessagesProj/src/main/res/values-ru/strings.xml").read_text(encoding="utf-8")
        assert '<string name="AppName">WaysGram</string>' in russian_strings
        assert "app.waysgram.API_BASE_URL" in manifest
        assert "waysgramApiBaseUrl" in gradle
        assert "WaysGramApiRuntime.initialize(applicationContext);" in app_loader
        assert "import app.waysgram.network.WaysGramApiRuntime;" in app_loader
        assert (source / "app/waysgram/network/WaysGramApiClient.java").is_file()
        assert (source / "app/waysgram/network/WaysGramApiConfig.java").is_file()
        assert (source / "app/waysgram/network/WaysGramApiRuntime.java").is_file()
        assert (source / "app/waysgram/network/WaysGramDataMapper.java").is_file()
        assert "api.requestCode(virtualPhone" in login
        assert "api.verifyCode(waysgramPhone, code" in login
        assert "onWaysGramAuthSuccess(response)" in login
        assert "activityMode != MODE_LOGIN" in login
        assert "WaysGramApiRuntime.getConfigurationError()" in login
        assert "if (!WaysGramApiRuntime.isConfigured())" in login
        controller = (source / "org/telegram/messenger/MessagesController.java").read_text(encoding="utf-8")
        sender = (source / "org/telegram/messenger/SendMessagesHelper.java").read_text(encoding="utf-8")
        assert "api.getConversations(" in controller
        assert "finishWaysGramMessages(" in controller
        assert controller.count("WaysGramApiRuntime.isWaysGramMode()") == 2
        assert "isSignedIn()" not in controller
        assert "api.sendMessage(waysGramPeer" in sender
        assert "WaysGramDataMapper.message(response" in sender
        assert "WaysGramApiRuntime.isWaysGramMode()" in sender
        assert "isSignedIn()" not in sender
        assert "waysgramMode" in login
        assert not (source / "app/waysgram/ui/WaysGramPortalActivity.java").exists()
        assert not (source / "app/waysgram/ui/WaysGramHomeActivity.java").exists()
        assert not (source / "app/nexusgram/ui/WaysGramPortalActivity.java").exists()
        assert not (source / "app/nexusgram/ui/WaysGramHomeActivity.java").exists()

        reference = root / "Telegram-master"
        reference_ui = reference / "TMessagesProj/src/main/java/org/telegram/ui"
        write(reference_ui / "IntroActivity.java", "new LoginActivity().setIntroView(frameContainerView, startMessagingButton);\n")
        reference_res = reference / "TMessagesProj/src/main/res"
        for screen in ("DialogsActivity.java", "ChatActivity.java", "MainTabsActivity.java"):
            original_source = "public class " + screen.removesuffix(".java") + " {}\n"
            write(reference_ui / screen, original_source)
            write(source / "org/telegram/ui" / screen, original_source)
        write(reference_ui / "LoginActivity.java", "public class LoginActivity { /* original */ }\n")
        write(reference_res / "layout/main.xml", "<LinearLayout />\n")
        write(root / "TMessagesProj/src/main/res/layout/main.xml", "<LinearLayout />\n")
        write(reference_res / "drawable/original.xml", "<shape />\n")
        write(root / "TMessagesProj/src/main/res/drawable/original.xml", "<shape />\n")
        write(
            reference_res / "values/strings.xml",
            "<resources>\n"
            "    <string name=\"AppName\">Telegram</string>\n"
            "    <string name=\"DebugTestBackend\">Test Backend</string>\n"
            "</resources>\n",
        )
        write(
            reference_res / "values-ru/strings.xml",
            "<resources>\n"
            "    <string name=\"AppName\">Telegram</string>\n"
            "</resources>\n",
        )
        verify = subprocess.run(
            [
                sys.executable,
                str(ROOT / "verify_original_ui.py"),
                "--root", str(root),
                "--reference", str(reference),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if verify.returncode:
            raise RuntimeError(
                "verify_original_ui.py failed\n"
                + verify.stdout + "\n" + verify.stderr
            )

        print("PASS: native UI, API configuration, shared runtime and native messenger patches are idempotent.")
        print("PASS: original LoginActivity remains the login entry point.")
        print("PASS: no Portal/Home activities or Test Backend control remain.")


if __name__ == "__main__":
    main()
