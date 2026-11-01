# NexusGram

NexusGram — Android-клиент на основе исходного проекта Telegram. Цель проекта — сохранить штатные экраны и навигацию Telegram, подключив их к единому WaysGram AuthBot backend.

## Сборка APK

Проект использует GitHub Actions: `.github/workflows/android.yml`.

1. Открой вкладку Actions.
2. Выбери **NexusGram Android APK**.
3. Нажми **Run workflow**.
4. После успешного завершения скачай артефакт **NexusGram-APK**.

Workflow собирает исходник из девяти частей `nexusgram.part01`–`nexusgram.part09`, восстанавливает Telegram source tree, применяет native UI patch v11, подготавливает API-конфигурацию и собирает APK.

Для подключения к развёрнутому AuthBot добавь в настройках GitHub-репозитория секрет **`WAYSGRAM_API_BASE_URL`** со значением HTTPS-адреса сервера без конечного пути API. Workflow передаёт его Gradle как manifest placeholder. Секрет не записывается в исходники. Без него APK может собраться, но REST-клиент не сможет подключиться к backend.

## Сохранение оригинального интерфейса

Скрипты `waysgram/apply_native_ui_v11.py` и `waysgram/configure_api_client.py` автоматически запускаются в Android workflow после восстановления исходников. Второй скрипт внедряет адрес сервера из build secret в Android Manifest и добавляет `WaysGramApiConfig` для получения настройки приложением. Он:
- сохраняет штатный переход IntroActivity → LoginActivity;
- удаляет отдельный WaysGram Portal CTA из LoginActivity;
- снимает Portal/Home Activities с регистрации в Android Manifest и удаляет их Java-файлы после проверки, что на них нет внешних ссылок;
- удаляет видимый переключатель `Test Backend` и его строковый ресурс;
- проверяет, что исходный LoginActivity остаётся точкой входа.

Скрипт `waysgram/configure_api_client.py` устанавливает REST-клиент из `waysgram/NexusGramApiClient.java` и helper конфигурации в штатное дерево проекта.

Скрипт идемпотентен: повторное применение не меняет уже исправленные файлы. Он не перерисовывает штатные Telegram-экраны.

## Backend и текущий статус интеграции

Единый серверный репозиторий: [WaysGram-AuthBot](https://github.com/WeteroScript/WaysGram-AuthBot).

В AuthBot реализованы API авторизации через виртуальный номер и код из Telegram-бота, пользовательские сессии, профили, текстовые личные сообщения, каналы, внутренние Stars/Gram балансы и коллекционные подарки. Админ-панель находится только внутри Telegram-бота.

**Android-клиент пока не переведён полностью на этот API.** Native UI patch v11 исправляет навигацию и убирает отдельные Portal/Home-экраны, но сам по себе не меняет транспорт:
- штатная авторизация LoginActivity пока использует Telegram MTProto;
- список диалогов и история чата пока используют MessagesController;
- отправка сообщений пока использует SendMessagesHelper;
- медиа, синхронизация в реальном времени, push, групповые чаты и звонки ещё не перенесены в AuthBot REST API.

Следующий этап — подключить API AuthBot к существующим native views и заменить источники данных MessagesController/SendMessagesHelper, не меняя внешний интерфейс. До завершения этой миграции нельзя считать Android-приложение полностью независимым от Telegram MTProto.

## Исходники

В репозитории хранятся части исходного архива и workflow восстановления. Скрипт восстановления UI находится в `waysgram/apply_native_ui_v11.py`.

Перед распространением APK необходимо проверить лицензии исходного проекта и используемых компонентов.
