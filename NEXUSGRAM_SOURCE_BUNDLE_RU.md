# NexusGram: самостоятельный клиент и backend

Ветка `nexusgram-standalone-upload` добавляет отдельную реализацию NexusGram, не зависящую от Telegram/MTProto.

## Состав

После восстановления архива появятся:

- `android-standalone/` — самостоятельный Android-клиент с REST API-клиентом.
- `NexusGram-Termux-Backend/` — backend на Python, SQLite, веб-панель администратора, smoke-тесты и примеры развёртывания.
- `ANDROID_STANDALONE_BUILD_RU.md` — инструкция по сборке Android-клиента.

Архив разбит на текстовые base64-сегменты в `release/`, чтобы передать его через GitHub Contents API без потери бинарных данных.

## Восстановление исходников

Linux, macOS или Termux:

```bash
cat release/NexusGram-Standalone-Repository-Bundle-v3.tar.xz.b64.part* \
  | base64 --decode > NexusGram-Standalone-Repository-Bundle-v3.tar.xz

xz --test NexusGram-Standalone-Repository-Bundle-v3.tar.xz
tar -xJf NexusGram-Standalone-Repository-Bundle-v3.tar.xz
```

## Интеграция в основной Android APK

Workflow `NexusGram Android APK` восстанавливает этот архив в CI и копирует два Java-класса в пакет `app.nexusgram.standalone` внутри модуля `TMessagesProj_App`. В AndroidManifest добавляется Activity с отдельным значком запуска **NexusGram Independent**.

Существующий Telegram-derived экран запуска сохраняется. Новый экран работает с NexusGram REST API и отдельной серверной базой. Аккаунты, контакты и история сообщений Telegram автоматически не переносятся; полная замена MTProto/Telegram backend этим этапом не выполняется.

## Автоматическая проверка и APK

Workflow `NexusGram Standalone Android APK` автоматически:

1. Проверяет количество сегментов и целостность архива.
2. Восстанавливает исходники.
3. Запускает backend smoke-тесты с временной SQLite-базой и тестовыми номерами из allowlist.
4. Собирает самостоятельный debug APK.
5. Проверяет пакет `app.nexusgram` и загружает artifact `NexusGram-Standalone-APK`.

Запустить сборку вручную можно во вкладке **Actions** через **Run workflow**. APK предназначен для тестирования, а не для публикации в Google Play.

## Подключение к серверу

Android-клиент использует NexusGram REST API. В VDS-развёртывании укажи публичный HTTPS-адрес backend в настройках приложения. База данных должна оставаться на сервере; не открывай SQLite напрямую в интернет.

Для production необходимо настроить HTTPS, секреты окружения, реального SMS-провайдера и отключить тестовый OTP-режим. Smoke-тест включает только локальные тестовые номера и не отправляет реальные SMS.
