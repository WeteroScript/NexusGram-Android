#!/usr/bin/env python3
"""Connect the native Telegram login and text messaging controllers to WaysGram REST."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


def insert_after_once(path: Path, anchor: str, addition: str, label: str) -> bool:
    source = path.read_text(encoding="utf-8")
    if addition.strip() in source:
        return False
    count = source.count(anchor)
    if count != 1:
        raise RuntimeError(f"Expected exactly one {label} anchor in {path}; found {count}")
    path.write_text(source.replace(anchor, anchor + addition, 1), encoding="utf-8")
    return True


def replace_once(path: Path, old: str, new: str, label: str) -> bool:
    source = path.read_text(encoding="utf-8")
    if new.strip() in source:
        return False
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one {label} block in {path}; found {count}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    return True


def replace_regex_once(path: Path, pattern: str, replacement, label: str) -> bool:
    source = path.read_text(encoding="utf-8")
    matches = list(re.finditer(pattern, source, flags=re.MULTILINE))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one {label} regex match in {path}; found {len(matches)}")
    updated = re.sub(pattern, replacement, source, count=1, flags=re.MULTILINE)
    path.write_text(updated, encoding="utf-8")
    return True


def insert_before_once(path: Path, anchor: str, addition: str, label: str) -> bool:
    source = path.read_text(encoding="utf-8")
    if addition.strip() in source:
        return False
    count = source.count(anchor)
    if count != 1:
        raise RuntimeError(f"Expected exactly one {label} anchor in {path}; found {count}")
    path.write_text(source.replace(anchor, addition + anchor, 1), encoding="utf-8")
    return True


def insert_after_regex_once(path: Path, pattern: str, addition: str, label: str) -> bool:
    source = path.read_text(encoding="utf-8")
    matches = list(re.finditer(pattern, source, flags=re.MULTILINE))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one {label} declaration in {path}; found {len(matches)}")
    match = matches[0]
    path.write_text(source[:match.end()] + addition + source[match.end():], encoding="utf-8")
    return True


def add_imports(path: Path, imports: str) -> bool:
    source = path.read_text(encoding="utf-8")
    if "import app.waysgram.network.WaysGramApiRuntime;" in source:
        return False
    package_end = source.find("\n", source.find("package "))
    if package_end < 0:
        raise RuntimeError(f"Could not locate Java package declaration in {path}")
    source = source[:package_end + 1] + "\n" + imports + source[package_end + 1:]
    path.write_text(source, encoding="utf-8")
    return True


def patch_login(root: Path) -> int:
    source_root = root / "TMessagesProj/src/main/java"
    login = source_root / "org/telegram/ui/LoginActivity.java"
    if not login.is_file():
        raise RuntimeError(f"Missing {login}")

    changed = 0
    changed += add_imports(
        login,
        "import app.waysgram.network.WaysGramApiClient;\n"
        "import app.waysgram.network.WaysGramApiRuntime;\n"
        "import app.waysgram.network.WaysGramDataMapper;\n"
        "import org.json.JSONObject;\n",
    )

    phone_confirm_pattern = (
        r"^(?P<indent>[ \t]*)confirmedNumber = true;\n"
        r"(?P=indent)currentDoneType = DONE_TYPE_FLOATING;\n"
        r"(?P=indent)needShowProgress\(0, false\);"
    )
    phone_confirm_replacement = lambda match: (
        match.group("indent") + "confirmedNumber = true;\n"
        + match.group("indent") + "currentDoneType = DONE_TYPE_FLOATING;\n"
        + match.group("indent") + "needShowProgress(0, false);\n"
        + match.group("indent") + "if (activityMode == MODE_LOGIN) {\n"
        + match.group("indent") + "    if (!WaysGramApiRuntime.isConfigured()) {\n"
        + match.group("indent") + "        confirmedNumber = false;\n"
        + match.group("indent") + "        needHideProgress(false);\n"
        + match.group("indent") + "        needShowAlert(getString(R.string.AppName), WaysGramApiRuntime.getConfigurationError());\n"
        + match.group("indent") + "        return;\n"
        + match.group("indent") + "    }\n"
        + match.group("indent") + "    requestWaysGramCode();\n"
        + match.group("indent") + "    return;\n"
        + match.group("indent") + "}\n"
    )
    if "requestWaysGramCode();" not in login.read_text(encoding="utf-8"):
        changed += replace_regex_once(
            login,
            phone_confirm_pattern,
            phone_confirm_replacement,
            "PhoneView confirmation handler",
        )

    phone_method_pattern = r"^[ \t]*(?:public )?class PhoneView\b[^\n]*\n"
    phone_method_body = """        private void requestWaysGramCode() {
            String digits = PhoneFormat.stripExceptNumbers(
                    "" + codeField.getText() + phoneField.getText());
            if (!digits.matches("1[0-9]{10}")) {
                nextPressed = false;
                needHideProgress(false);
                needShowAlert(getString(R.string.AppName),
                        "Для входа WaysGram используйте виртуальный номер +1 и 10 цифр.");
                return;
            }
            WaysGramApiClient api = WaysGramApiRuntime.getClient();
            if (api == null) {
                nextPressed = false;
                needHideProgress(false);
                needShowAlert(getString(R.string.AppName),
                        WaysGramApiRuntime.getConfigurationError());
                return;
            }

            final String virtualPhone = "+" + digits;
            nextPressed = true;
            api.requestCode(virtualPhone, new WaysGramApiClient.Callback() {
                @Override
                public void onSuccess(JSONObject response) {
                    nextPressed = false;
                    needHideProgress(false);
                    Bundle params = new Bundle();
                    String displayPhone = "+1 " + digits.substring(1);
                    params.putString("phone", displayPhone);
                    params.putString("ephone", displayPhone);
                    params.putString("phoneFormated", virtualPhone);
                    params.putString("waysgram_phone", virtualPhone);
                    params.putString("waysgram_instruction", response.optString(
                            "message",
                            "Откройте AuthWaysGram_bot и нажмите «Получить код»."));
                    params.putBoolean("waysgram_mode", true);
                    params.putInt("type", AUTH_TYPE_SMS);
                    params.putInt("nextType", 0);
                    params.putInt("prevType", 0);
                    params.putInt("timeout", 0);
                    params.putInt("length", 6);
                    setPage(VIEW_CODE_SMS, true, params, false);
                }

                @Override
                public void onError(String message) {
                    nextPressed = false;
                    needHideProgress(false);
                    needShowAlert(getString(R.string.AppName), message);
                }
            });
        }

"""
    if "private void requestWaysGramCode()" not in login.read_text(encoding="utf-8"):
        changed += insert_after_regex_once(
            login,
            phone_method_pattern,
            phone_method_body,
            "PhoneView onNextPressed",
        )

    sms_class_start = "    public class LoginActivitySmsView extends SlideView implements NotificationCenter.NotificationCenterDelegate {"
    if sms_class_start not in login.read_text(encoding="utf-8"):
        raise RuntimeError("LoginActivitySmsView declaration not found")
    source = login.read_text(encoding="utf-8")
    class_index = source.index(sms_class_start)
    class_end_marker = "\n    public class LoadingTextView"
    class_end = source.find(class_end_marker, class_index)
    if class_end < 0:
        raise RuntimeError("Could not locate the end of LoginActivitySmsView")
    before = source[:class_index]
    sms = source[class_index:class_end]
    after = source[class_end:]

    field_anchor = "        private boolean nextPressed;\n        private String lastError = \"\";\n"
    field_replacement = field_anchor + (
        "        private boolean waysgramMode;\n"
        "        private String waysgramPhone;\n"
    )
    if "private boolean waysgramMode;" not in sms:
        if sms.count(field_anchor) != 1:
            raise RuntimeError("Could not locate LoginActivitySmsView state fields")
        sms = sms.replace(field_anchor, field_replacement, 1)
        changed += 1

    params_anchor = (
        "        public void setParams(Bundle params, boolean restore) {\n"
        "            if (params == null) {\n"
    )
    params_replacement = (
        "        public void setParams(Bundle params, boolean restore) {\n"
        "            if (params == null) {\n"
        "                waysgramMode = false;\n"
        "                waysgramPhone = null;\n"
    )
    if "waysgramMode = false;" not in sms:
        if sms.count(params_anchor) != 1:
            raise RuntimeError("Could not locate SMS view setParams")
        sms = sms.replace(params_anchor, params_replacement, 1)
        changed += 1

    set_params_wait = (
        "            waitingForEvent = true;\n"
        "            if (currentType == AUTH_TYPE_FRAGMENT_SMS) {\n"
    )
    set_params_wait_new = (
        "            waysgramMode = params.getBoolean(\"waysgram_mode\", false);\n"
        "            waysgramPhone = params.getString(\"waysgram_phone\", params.getString(\"phoneFormated\", \"\"));\n"
        "            waitingForEvent = true;\n"
        "            if (currentType == AUTH_TYPE_FRAGMENT_SMS) {\n"
    )
    if "waysgramPhone = params.getString" not in sms:
        if sms.count(set_params_wait) != 1:
            raise RuntimeError("Could not locate SMS view observer setup")
        sms = sms.replace(set_params_wait, set_params_wait_new, 1)
        changed += 1

    sms_observer = (
        "            } else if (currentType == AUTH_TYPE_SMS) {\n"
        "                AndroidUtilities.setWaitingForSms(true);\n"
        "                NotificationCenter.getGlobalInstance().addObserver(this, NotificationCenter.didReceiveSmsCode);\n"
    )
    sms_observer_new = (
        "            } else if (currentType == AUTH_TYPE_SMS && !waysgramMode) {\n"
        "                AndroidUtilities.setWaitingForSms(true);\n"
        "                NotificationCenter.getGlobalInstance().addObserver(this, NotificationCenter.didReceiveSmsCode);\n"
    )
    if sms.count(sms_observer):
        sms = sms.replace(sms_observer, sms_observer_new, 1)
        changed += 1

    sms_instruction_anchor = "            confirmTextView.setText(str);\n"
    sms_instruction_new = (
        "            if (waysgramMode) {\n"
        "                str = AndroidUtilities.replaceTags(waysgramInstruction());\n"
        "            }\n"
        "            confirmTextView.setText(str);\n"
    )
    if "confirmTextView.setText(AndroidUtilities.replaceTags(waysgramInstruction()))" not in sms:
        if sms.count(sms_instruction_anchor) != 1:
            raise RuntimeError("Could not locate SMS instruction text")
        sms = sms.replace(sms_instruction_anchor, sms_instruction_new, 1)
        changed += 1

    instruction_method_anchor = (
        "        @Override\n"
        "        public void setParams(Bundle params, boolean restore) {\n"
    )
    if instruction_method_anchor not in sms:
        instruction_method_anchor = "        public void setParams(Bundle params, boolean restore) {\n"
    instruction_method = (
        "        private String waysgramInstruction() {\n"
        "            if (currentParams != null) {\n"
        "                String value = currentParams.getString(\"waysgram_instruction\");\n"
        "                if (!TextUtils.isEmpty(value)) {\n"
        "                    return value;\n"
        "                }\n"
        "            }\n"
        "            return \"Откройте AuthWaysGram_bot и нажмите «Получить код».\";\n"
        "        }\n\n"
    )
    if "private String waysgramInstruction()" not in sms:
        if sms.count(instruction_method_anchor) != 1:
            raise RuntimeError("Could not locate SMS view setParams for instruction helper")
        sms = sms.replace(instruction_method_anchor, instruction_method + instruction_method_anchor, 1)
        changed += 1

    next_pressed_anchor = "            waitingForEvent = false;\n\n            switch (activityMode) {\n"
    next_pressed_code = """            waitingForEvent = false;

            if (waysgramMode) {
                if (!waysgramPhone.matches("^\\\\+1[0-9]{10}$")
                        || !code.matches("[0-9]{6}")) {
                    nextPressed = false;
                    shakeWrongCode();
                    return;
                }
                WaysGramApiClient api = WaysGramApiRuntime.getClient();
                if (api == null) {
                    nextPressed = false;
                    tryHideProgress(false, true);
                    needShowAlert(getString(R.string.AppName),
                            WaysGramApiRuntime.getConfigurationError());
                    return;
                }
                needShowProgress(0);
                api.verifyCode(waysgramPhone, code, new WaysGramApiClient.Callback() {
                    @Override
                    public void onSuccess(JSONObject response) {
                        nextPressed = false;
                        tryHideProgress(false, true);
                        destroyTimer();
                        destroyCodeTimer();
                        onWaysGramAuthSuccess(response);
                    }

                    @Override
                    public void onError(String message) {
                        nextPressed = false;
                        tryHideProgress(false, true);
                        showDoneButton(false, true);
                        needShowAlert(getString(R.string.AppName), message);
                    }
                });
                return;
            }

            switch (activityMode) {
"""
    if "api.verifyCode(waysgramPhone, code" not in sms:
        if sms.count(next_pressed_anchor) != 1:
            raise RuntimeError("Could not locate SMS view verification switch")
        sms = sms.replace(next_pressed_anchor, next_pressed_code, 1)
        changed += 1

    cancel_anchor = (
        "            TLRPC.TL_auth_cancelCode req = new TLRPC.TL_auth_cancelCode();\n"
        "            req.phone_number = requestPhone;\n"
        "            req.phone_code_hash = phoneHash;\n"
        "            ConnectionsManager.getInstance(currentAccount).sendRequest(req, (response, error) -> {\n\n            }, ConnectionsManager.RequestFlagFailOnServerErrors | ConnectionsManager.RequestFlagWithoutLogin);\n"
    )
    cancel_replacement = (
        "            if (!waysgramMode) {\n"
        "                TLRPC.TL_auth_cancelCode req = new TLRPC.TL_auth_cancelCode();\n"
        "                req.phone_number = requestPhone;\n"
        "                req.phone_code_hash = phoneHash;\n"
        "                ConnectionsManager.getInstance(currentAccount).sendRequest(req, (response, error) -> {\n\n                }, ConnectionsManager.RequestFlagFailOnServerErrors | ConnectionsManager.RequestFlagWithoutLogin);\n"
        "            }\n"
    )
    if "if (!waysgramMode) {\n                TLRPC.TL_auth_cancelCode" not in sms:
        if sms.count(cancel_anchor) != 1:
            raise RuntimeError("Could not locate SMS view Telegram cancel-code request")
        sms = sms.replace(cancel_anchor, cancel_replacement, 1)
        changed += 1

    sms = sms.replace(
        "} else if (currentType == AUTH_TYPE_SMS) {\n                AndroidUtilities.setWaitingForSms(false);",
        "} else if (currentType == AUTH_TYPE_SMS && !waysgramMode) {\n                AndroidUtilities.setWaitingForSms(false);",
    )

    before = source[:class_index]
    source = before + sms + after
    source = insert_outer_waysgram_success(source)
    login.write_text(source, encoding="utf-8")
    return changed


def insert_outer_waysgram_success(source: str) -> str:
    anchor = "    private void onAuthSuccess(TLRPC.TL_auth_authorization res) {\n"
    method = """    private void onWaysGramAuthSuccess(JSONObject response) {
        JSONObject userJson = response == null ? null : response.optJSONObject("user");
        TLRPC.User user = WaysGramDataMapper.user(userJson, true);
        if (user == null) {
            needShowAlert(getString(R.string.AppName), "Сервер WaysGram вернул неполный профиль.");
            return;
        }

        MessagesController.getInstance(currentAccount).cleanup();
        UserConfig.getInstance(currentAccount).clearConfig();
        MessagesController.getInstance(currentAccount).cleanup();
        UserConfig.getInstance(currentAccount).setCurrentUser(user);
        UserConfig.getInstance(currentAccount).saveConfig(true);
        MessagesStorage.getInstance(currentAccount).cleanup(true);
        ArrayList<TLRPC.User> users = new ArrayList<>();
        users.add(user);
        MessagesStorage.getInstance(currentAccount).putUsersAndChats(users, null, true, true);
        MessagesController.getInstance(currentAccount).putUser(user, false);

        if (getParentActivity() != null) {
            AndroidUtilities.setLightStatusBar(getParentActivity(), false);
        }
        clearCurrentState();
        if (getParentActivity() instanceof LaunchActivity) {
            if (newAccount) {
                newAccount = false;
                pendingSwitchingAccount = true;
                ((LaunchActivity) getParentActivity()).switchToAccount(currentAccount, true, obj -> {
                    Bundle args = new Bundle();
                    MainTabsActivity mainTabsActivity = new MainTabsActivity();
                    mainTabsActivity.prepareDialogsActivity(args);
                    return mainTabsActivity;
                });
                pendingSwitchingAccount = false;
                finishFragment();
            } else {
                Bundle args = new Bundle();
                MainTabsActivity mainTabsActivity = new MainTabsActivity();
                mainTabsActivity.prepareDialogsActivity(args);
                presentFragment(mainTabsActivity, true);
                NotificationCenter.getInstance(currentAccount).postNotificationName(
                        NotificationCenter.mainUserInfoChanged);
            }
        } else if (getParentActivity() instanceof ExternalActionActivity) {
            ((ExternalActionActivity) getParentActivity()).onFinishLogin();
        }
    }

"""
    if "private void onWaysGramAuthSuccess(JSONObject response)" in source:
        return source
    if source.count(anchor) != 1:
        raise RuntimeError("Could not locate LoginActivity onAuthSuccess")
    return source.replace(anchor, method + anchor, 1)


def patch_messages_controller(root: Path) -> int:
    path = root / "TMessagesProj/src/main/java/org/telegram/messenger/MessagesController.java"
    if not path.is_file():
        raise RuntimeError(f"Missing {path}")
    changed = 0
    changed += add_imports(
        path,
        "import app.waysgram.network.WaysGramApiClient;\n"
        "import app.waysgram.network.WaysGramApiRuntime;\n"
        "import app.waysgram.network.WaysGramDataMapper;\n",
    )

    load_dialogs_anchor = (
        "    public void loadDialogs(final int folderId, int offset, int count, boolean fromCache, Runnable onEmptyCallback) {\n"
    )
    load_dialogs_code = """        if (WaysGramApiRuntime.isWaysGramMode()) {
            if (loadingDialogs.get(folderId) || resetingDialogs) {
                return;
            }
            if (folderId != 0 || offset > 0) {
                loadingDialogs.put(folderId, false);
                dialogsEndReached.put(folderId, true);
                serverDialogsEndReached.put(folderId, true);
                getNotificationCenter().postNotificationName(NotificationCenter.dialogsNeedReload);
                return;
            }
            loadingDialogs.put(folderId, true);
            getNotificationCenter().postNotificationName(NotificationCenter.dialogsNeedReload);
            WaysGramApiClient api = WaysGramApiRuntime.getClient();
            if (api == null) {
                loadingDialogs.put(folderId, false);
                getNotificationCenter().postNotificationName(NotificationCenter.dialogsNeedReload);
                return;
            }
            api.getConversations(new WaysGramApiClient.Callback() {
                @Override
                public void onSuccess(org.json.JSONObject response) {
                    TLRPC.TL_messages_dialogsSlice dialogs = WaysGramDataMapper.dialogs(
                            response, getUserConfig().getClientUserId(), getUserConfig().getCurrentUser());
                    if (dialogs == null) {
                        loadingDialogs.put(folderId, false);
                        getNotificationCenter().postNotificationName(NotificationCenter.dialogsNeedReload);
                        return;
                    }
                    processLoadedDialogs(dialogs, null, null, folderId, 0, count,
                            0, false, false, false);
                    if (onEmptyCallback != null && dialogs.dialogs.isEmpty()) {
                        onEmptyCallback.run();
                    }
                }

                @Override
                public void onError(String message) {
                    loadingDialogs.put(folderId, false);
                    FileLog.e("WaysGram conversations: " + message);
                    getNotificationCenter().postNotificationName(NotificationCenter.dialogsNeedReload);
                    if (onEmptyCallback != null) {
                        onEmptyCallback.run();
                    }
                }
            });
            return;
        }
"""
    changed += insert_after_once(
        path,
        load_dialogs_anchor,
        load_dialogs_code,
        "MessagesController loadDialogs",
    )

    load_messages_anchor = (
        "            final TLRPC.Chat chat = dialogId < 0 ? getChat(-dialogId): null;\n"
    )
    load_messages_code = """            final Timer waysGramLoaderLogger = loaderLogger;
            if (WaysGramApiRuntime.isWaysGramMode()) {
                if (dialogId <= 0 || mergeDialogId != 0 || mode != ChatActivity.MODE_DEFAULT
                        || threadMessageId != 0 || isTopic
                        || (load_type != 0 && load_type != 1 && load_type != 2)) {
                    TLRPC.TL_error unsupported = new TLRPC.TL_error();
                    unsupported.code = 501;
                    unsupported.text = "WaysGram сейчас поддерживает только текстовые личные диалоги.";
                    getNotificationCenter().postNotificationName(
                            NotificationCenter.loadingMessagesFailed, classGuid, null, unsupported);
                    return;
                }
                WaysGramApiClient api = WaysGramApiRuntime.getClient();
                if (api == null) {
                    TLRPC.TL_error unavailable = new TLRPC.TL_error();
                    unavailable.code = 503;
                    unavailable.text = WaysGramApiRuntime.getConfigurationError();
                    getNotificationCenter().postNotificationName(
                            NotificationCenter.loadingMessagesFailed, classGuid, null, unavailable);
                    return;
                }
                long afterId = load_type == 2 ? Math.max(0, max_id) : 0;
                long beforeId = load_type == 1 ? Math.max(0, max_id) : 0;
                api.getMessages(dialogId, afterId, beforeId, new WaysGramApiClient.Callback() {
                    @Override
                    public void onSuccess(org.json.JSONObject response) {
                        TLRPC.User peerUser = getUser(dialogId);
                        if (peerUser != null) {
                            finishWaysGramMessages(response, peerUser, dialogId, mergeDialogId,
                                    count, max_id, offset_date, classGuid, load_type, first_unread,
                                    last_message_id, unread_count, last_date, queryFromServer,
                                    mentionsCount, mode, threadMessageId, loadIndex, isTopic,
                                    waysGramLoaderLogger);
                            return;
                        }
                        api.getUser(dialogId, new WaysGramApiClient.Callback() {
                            @Override
                            public void onSuccess(org.json.JSONObject profile) {
                                TLRPC.User loadedUser = WaysGramDataMapper.user(profile, false);
                                if (loadedUser == null) {
                                    failWaysGramMessages(classGuid, "Не удалось загрузить профиль собеседника.");
                                    return;
                                }
                                putUser(loadedUser, false);
                                finishWaysGramMessages(response, loadedUser, dialogId, mergeDialogId,
                                        count, max_id, offset_date, classGuid, load_type, first_unread,
                                        last_message_id, unread_count, last_date, queryFromServer,
                                        mentionsCount, mode, threadMessageId, loadIndex, isTopic,
                                        waysGramLoaderLogger);
                            }

                            @Override
                            public void onError(String message) {
                                failWaysGramMessages(classGuid, message);
                            }
                        });
                    }

                    @Override
                    public void onError(String message) {
                        failWaysGramMessages(classGuid, message);
                    }
                });
                return;
            }
"""
    changed += insert_after_once(
        path,
        load_messages_anchor,
        load_messages_code,
        "MessagesController loadMessagesInternal",
    )

    helper_anchor = (
        "    public void processLoadedMessages(TLRPC.messages_Messages messagesRes, int resCount, long dialogId, long mergeDialogId, int count, int max_id, int offset_date, boolean isCache, int classGuid,\n"
    )
    helper = """    private void failWaysGramMessages(int classGuid, String message) {
        TLRPC.TL_error error = new TLRPC.TL_error();
        error.code = 502;
        error.text = message == null ? "WaysGram API error" : message;
        AndroidUtilities.runOnUIThread(() -> getNotificationCenter().postNotificationName(
                NotificationCenter.loadingMessagesFailed, classGuid, null, error));
    }

    private void finishWaysGramMessages(org.json.JSONObject response, TLRPC.User peerUser,
                                        long dialogId, long mergeDialogId, int count, int maxId,
                                        int offsetDate, int classGuid, int loadType, int firstUnread,
                                        int lastMessageId, int unreadCount, int lastDate,
                                        boolean queryFromServer, int mentionsCount, int mode,
                                        long threadMessageId, int loadIndex, boolean isTopic,
                                        Timer loaderLogger) {
        TLRPC.TL_messages_messagesSlice messages = WaysGramDataMapper.messages(
                response, getUserConfig().getClientUserId(), dialogId,
                getUserConfig().getCurrentUser(), peerUser);
        processLoadedMessages(messages, messages.messages.size(), dialogId, mergeDialogId,
                count, maxId, offsetDate, false, classGuid, firstUnread, lastMessageId,
                unreadCount, lastDate, loadType, messages.messages.size() < count, mode,
                threadMessageId, loadIndex, queryFromServer, mentionsCount, true, isTopic,
                loaderLogger);
    }

"""
    changed += insert_before_once(
        path,
        helper_anchor,
        helper,
        "MessagesController processLoadedMessages",
    )
    return changed


def patch_send_helper(root: Path) -> int:
    path = root / "TMessagesProj/src/main/java/org/telegram/messenger/SendMessagesHelper.java"
    if not path.is_file():
        raise RuntimeError(f"Missing {path}")
    changed = 0
    changed += add_imports(
        path,
        "import app.waysgram.network.WaysGramApiClient;\n"
        "import app.waysgram.network.WaysGramApiRuntime;\n"
        "import app.waysgram.network.WaysGramDataMapper;\n",
    )

    anchor = "    public void sendMessage(SendMessageParams sendMessageParams) {\n"
    code = """        if (WaysGramApiRuntime.isWaysGramMode()) {
            final long waysGramPeer = sendMessageParams.peer;
            final String waysGramText = sendMessageParams.message;
            boolean textOnly = waysGramPeer > 0 && !TextUtils.isEmpty(waysGramText)
                    && (sendMessageParams.caption == null || sendMessageParams.caption.isEmpty())
                    && sendMessageParams.location == null
                    && sendMessageParams.photo == null
                    && sendMessageParams.videoEditedInfo == null
                    && sendMessageParams.user == null
                    && sendMessageParams.document == null
                    && sendMessageParams.game == null
                    && sendMessageParams.poll == null
                    && sendMessageParams.todo == null
                    && sendMessageParams.invoice == null
                    && sendMessageParams.path == null
                    && sendMessageParams.replyToMsg == null
                    && sendMessageParams.replyToTopMsg == null
                    && sendMessageParams.webPage == null
                    && sendMessageParams.mediaWebPage == null
                    && sendMessageParams.replyMarkup == null
                    && (sendMessageParams.entities == null || sendMessageParams.entities.isEmpty())
                    && (sendMessageParams.params == null || sendMessageParams.params.isEmpty())
                    && sendMessageParams.scheduleDate == 0
                    && sendMessageParams.scheduleRepeatPeriod == 0
                    && sendMessageParams.stars == 0
                    && sendMessageParams.payStars == 0
                    && sendMessageParams.pollSendParams == null
                    && sendMessageParams.richMessage == null
                    && sendMessageParams.replyQuote == null
                    && sendMessageParams.sendAnimationData == null
                    && sendMessageParams.effect_id == 0
                    && sendMessageParams.monoForumPeer == 0
                    && sendMessageParams.dice_stake == 0;
            if (!textOnly) {
                AndroidUtilities.runOnUIThread(() ->
                        android.widget.Toast.makeText(ApplicationLoader.applicationContext,
                                "В этой версии WaysGram поддерживаются только текстовые личные сообщения без вложений и ответов.",
                                android.widget.Toast.LENGTH_LONG).show());
                return;
            }
            WaysGramApiClient api = WaysGramApiRuntime.getClient();
            if (api == null) {
                AndroidUtilities.runOnUIThread(() ->
                        android.widget.Toast.makeText(ApplicationLoader.applicationContext,
                                WaysGramApiRuntime.getConfigurationError(),
                                android.widget.Toast.LENGTH_LONG).show());
                return;
            }
            final long selfId = UserConfig.getInstance(currentAccount).getClientUserId();
            api.sendMessage(waysGramPeer, waysGramText, new WaysGramApiClient.Callback() {
                @Override
                public void onSuccess(org.json.JSONObject response) {
                    TLRPC.TL_message message = WaysGramDataMapper.message(response, selfId, waysGramPeer);
                    if (message == null) {
                        android.widget.Toast.makeText(ApplicationLoader.applicationContext,
                                "Сервер вернул некорректное сообщение WaysGram.",
                                android.widget.Toast.LENGTH_LONG).show();
                        return;
                    }
                    message.out = true;
                    message.unread = false;
                    ArrayList<TLRPC.Message> stored = new ArrayList<>();
                    stored.add(message);
                    MessagesStorage.getInstance(currentAccount).putMessages(
                            stored, false, true, false, 0, 0, 0);
                    ArrayList<MessageObject> objects = new ArrayList<>();
                    MessageObject object = new MessageObject(currentAccount, message, true, true);
                    object.wasJustSent = true;
                    objects.add(object);
                    MessagesController.getInstance(currentAccount).updateInterfaceWithMessages(
                            waysGramPeer, objects, ChatActivity.MODE_DEFAULT);
                    NotificationCenter.getInstance(currentAccount).postNotificationName(
                            NotificationCenter.dialogsNeedReload);
                }

                @Override
                public void onError(String message) {
                    android.widget.Toast.makeText(ApplicationLoader.applicationContext,
                            message, android.widget.Toast.LENGTH_LONG).show();
                }
            });
            return;
        }
"""
    changed += insert_after_once(path, anchor, code, "SendMessagesHelper.sendMessage")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    root = args.root.resolve()
    source_root = root / "TMessagesProj/src/main/java"
    mapper_source = root / "waysgram/WaysGramDataMapper.java"
    mapper_target = source_root / "app/waysgram/network/WaysGramDataMapper.java"
    if not mapper_source.is_file():
        raise SystemExit(f"Missing bundled REST mapper: {mapper_source}")
    mapper_target.parent.mkdir(parents=True, exist_ok=True)
    bundled = mapper_source.read_text(encoding="utf-8")
    if not mapper_target.exists() or mapper_target.read_text(encoding="utf-8") != bundled:
        mapper_target.write_text(bundled, encoding="utf-8")

    changes = 0
    changes += patch_login(root)
    changes += patch_messages_controller(root)
    changes += patch_send_helper(root)
    print(f"Native WaysGram auth and text messaging bridge installed; {changes} patch operation(s) changed source.")
    print("Original Telegram PhoneView, SMS code view, DialogsActivity and ChatActivity remain in use.")
    print("MTProto calls for WaysGram login, dialog lists, direct text history and text sends are bypassed.")
    print("Media, replies, group/channel chats, calls and remaining Telegram services are not migrated.")


if __name__ == "__main__":
    main()
