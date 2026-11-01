# WaysGram — состояние интеграции

Дата обновления: 1 ноября 2026.

Ревизия исходников: **v10**. Backend API contract: **v1**.

## Текущий этап

- Исправлена независимость одинаковых действий: каждый новый запрос получает собственный UUID/Idempotency-Key и отдельную запись очереди.
- Добавлена монотонная последовательность операций; очередь восстанавливается строго в порядке создания.
- Повторная отправка уже сохранённой операции использует прежний ключ и не должна повторно применять действие на сервере в пределах семидневного срока идемпотентности.
- Очередь запускается повторно при возврате на передний план и восстановлении сети.
- Старые v9-записи без sequence читаются с сортировкой по created_at.
- Видимая разметка не менялась; `buildUi()` остался без изменений.

## Сохранённые функции

- WaysGram OTP-вход через AuthWaysGram_bot; Telegram MTProto-вход не менялся.
- Android bearer-токен и записи очереди защищены AES-GCM с ключом Android Keystore.
- `POST /api/auth/refresh` продлевает только активную сессию на 30 дней; истёкшая/отозванная сессия требует нового OTP-входа.
- Профиль, Stars/Gram, подарки, инвентарь, передачи, история операций, личные сообщения и каналы.
- Incremental polling, восстановление сетевого соединения и backoff на переднем плане.
- Лимиты и транзакционная идемпотентность backend.

## Проверки

- Backend `compileall` — PASS.
- `bash -n WaysGram-Backend/start-termux.sh` — PASS.
- `WaysGram-Backend/tests/smoke_test.py` — PASS.
- Android `NexusGramApiClient.java`, `WaysGramHomeActivity.java` и `WaysGramPortalActivity.java` прошли `javac` syntax/type check с Android/JSON API-заглушками — PASS.
- REST-клиент и backend integration sample совпадают побайтно.
- `WaysGramPortalActivity.java` и AndroidManifest не менялись; `WaysGramHomeActivity.buildUi()` не менялся.

## До APK

Остался полный Android Gradle build и разбор возможных ошибок интеграции/нативных зависимостей. В текущей среде `ANDROID_HOME`/`ANDROID_SDK_ROOT` не заданы, а Gradle 8.13 не загружается из-за недоступности `services.gradle.org` (`UnknownHostException`). Поэтому APK на этом этапе не собран.