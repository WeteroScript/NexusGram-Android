# NexusGram

NexusGram — Android-клиент на основе исходного проекта Telegram. Цель проекта — сохранить штатные экраны и навигацию Telegram, постепенно подключая их к единому WaysGram AuthBot backend.

## Сборка APK

Проект использует GitHub Actions: `.github/workflows/android.yml`.

1. Открой вкладку Actions.
2. Выбери **NexusGram Android APK**.
3. Нажми **Run workflow**.
4. После успешного завершения скачай артефакт **NexusGram-APK**.

Workflow собирает исходник из девяти частей `nexusgram.part01`–`nexusgram.part09`, восстанавливает Telegram source tree, удаляет отдельный Portal/Test Backend UI, устанавливает REST-клиент и bridge для native login/text messaging, а затем собирает APK.

Для подключения к развёрнутому AuthBot добавь в настройках GitHub-репозитория секрет **`WAYSGRAM_API_BASE_URL`** со значением HTTPS-адреса сервера без конечного пути API. Workflow передаёт его Gradle как manifest placeholder. Секрет не записывается в исходники. Без него APK может собраться, но вход WaysGram будет закрыт с сообщением о ненастроенном API. Резервного перехода на Telegram MTProto для входа нет.

## Оригинальный интерфейс и native integration

Все изменения применяются к штатным исходникам Telegram во время сборки. Внешний вид экранов не заменяется самодельными Portal/Home-страницами.

- `apply_native_ui_v11.py` сохраняет переход IntroActivity → LoginActivity, удаляет WaysGram Portal CTA, Portal/Home Activity registration и видимый переключатель `Test Backend`.
- `configure_api_client.py` устанавливает REST-клиент, читает HTTPS endpoint из build-time manifest metadata и добавляет `WaysGramApiConfig`.
- `configure_api_runtime.py` инициализирует единый экземпляр `NexusGramApiClient` в `ApplicationLoader`.
- `configure_native_messenger.py` подключает WaysGram REST к штатным `LoginActivity.PhoneView` / SMS code view, `MessagesController` и `SendMessagesHelper`.
- `WaysGramDataMapper.java` переводит серверные профили, диалоги и текстовые сообщения в native Telegram TL-модели, чтобы штатные `DialogsActivity` и `ChatActivity` могли их отображать.

Патчи идемпотентны. Отдельный workflow **WaysGram Android Patch Tests** проверяет их повторное применение на Python 3.11 и 3.12 без полной Android/NDK-сборки. Изменения в `waysgram/**` также запускают полную APK-сборку.

## Backend и текущий статус интеграции

Единый серверный репозиторий: [WaysGram-AuthBot](https://github.com/WeteroScript/WaysGram-AuthBot).

В AuthBot реализованы API авторизации через виртуальный номер и код из Telegram-бота, пользовательские сессии, профили, текстовые личные сообщения, текстовые каналы, внутренние Stars/Gram балансы и коллекционные подарки. Админ-панель находится только внутри Telegram-бота.

**В Android уже подключён ограниченный native REST bridge:**
- экран ввода виртуального номера отправляет запрос кода в AuthBot;
- штатный экран ввода SMS-кода проверяет WaysGram OTP и получает API-сессию;
- список диалогов загружается через `GET /api/conversations`;
- история личного текстового диалога загружается через `GET /api/messages` с курсорами;
- отправка обычного текстового личного сообщения идёт через `POST /api/messages`;
- при отсутствии `WAYSGRAM_API_BASE_URL` вход закрывается с сообщением о конфигурации, а не переключается на Telegram MTProto.

**Ограничения текущего bridge:**
- только текстовые личные диалоги; вложения, фото, видео, документы, ответы, реакции и форматирование ещё не подключены;
- групповые чаты, супергруппы и каналы пока не подключены к native UI;
- фоновая синхронизация, push-уведомления, звонки и медиа-транспорт ещё используют отсутствующие или прежние интеграции;
- настройки профиля, каталог и инвентарь подарков, кошелёк и управление каналами пока доступны в API, но ещё не все выведены в штатные Android-экраны;
- на устройстве и в процессе приложения используется локальная native Telegram-модель пользователя для отображения интерфейса; полноценная замена всех MTProto-зависимостей ещё не завершена.

Поэтому текущая стадия — частичная миграция авторизации и текстовых личных сообщений, а не полностью независимый от MTProto мессенджер.

## Исходники

В репозитории хранятся части исходного архива Telegram и repeatable patch scripts в `waysgram/`. Полная Android-сборка выполняется GitHub Actions с восстановлением исходников и сборкой native-библиотек.

Перед распространением APK необходимо проверить лицензии исходного проекта и используемых компонентов.
