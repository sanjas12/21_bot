# Запуск бота на Ubuntu, прокси и автозапуск

Инструкция рассчитана на Ubuntu 24.04 с systemd, проект в `/root/21_bot`
и установленный Mihomo. Команды выполняются на сервере от `root`.
Шаблон бота использует `User=root`, поскольку проект расположен в `/root`.
Если проект перенесён, измените `User`, `WorkingDirectory`, `ExecStart` и `PATH`.

Схема подключения: бот → `127.0.0.1:7890` → Mihomo → узел из подписки → Telegram.
Проксируются запросы бота; системные маршруты и SSH-подключение не меняются.

## 1. Подготовить проект

Проверьте установленные программы:

```bash
python3 --version
command -v uv
command -v mihomo
mihomo -v
```

Текущий код проекта требует Python 3.11+, как указано в `pyproject.toml`.
Скрипт `recreate_env.sh` самостоятельно не ограничивает младшую версию Python 3;
совместимость зависимостей проверяется при установке.

Для обычной установки на сервере:

```bash
cd /root/21_bot
uv sync --locked --no-dev
```

Для полного пересоздания окружения разработки можно выполнить
`bash scripts/recreate_env.sh`. Этот скрипт удаляет `.venv`, устанавливает
зависимости разработки и сборки. Остановите службу бота перед пересозданием.

Создайте серверный `.env`, если его ещё нет:

```bash
cd /root/21_bot
test -f .env || cp .env.example .env
chmod 600 .env
nano .env
```

Содержимое:

```dotenv
BOT_TOKEN=YOUR_NEW_TELEGRAM_BOT_TOKEN
HTTPS_PROXY=http://127.0.0.1:7890
```

Настоящий токен хранится только в серверном `.env`. Если он был опубликован
в коммите или логе, отзовите его через `/revoke` в BotFather и задайте новый.
В репозиторий добавляется только `.env.example` без секретов.

## 2. Настроить Mihomo с HTTPS-подпиской

FlClashX — графический клиент; для сервера используется ядро Mihomo.
HTTPS-ссылка подписки загружается Mihomo и не является адресом прокси для бота.
Подписка должна выдавать узлы в поддерживаемом Mihomo формате. Если провайдер
предлагает разные ссылки, выберите Clash/Mihomo. Не публикуйте ссылку подписки.

При первой настройке скопируйте шаблон. Если конфигурация уже работает,
сохраните её и пропустите копирование:

```bash
install -d -m 700 /etc/mihomo
test -f /etc/mihomo/config.yaml || install -m 600 \
  /root/21_bot/deploy/mihomo.example.yaml /etc/mihomo/config.yaml
nano /etc/mihomo/config.yaml
```

Замените `REPLACE_WITH_PRIVATE_HTTPS_SUBSCRIPTION_URL` реальной ссылкой.
Шаблон открывает смешанный HTTP/SOCKS-порт только на `127.0.0.1:7890`,
обновляет подписку каждый час и автоматически выбирает узел из группы `AUTO`.
Не включайте TUN для этой схемы.

```bash
chmod 600 /etc/mihomo/config.yaml
mihomo -t -d /etc/mihomo
```

Успешная проверка конфигурации ещё не подтверждает доступность узлов и Telegram.

## 3. Запустить Mihomo как службу

Сначала проверьте, нет ли уже ручного экземпляра:

```bash
systemctl status mihomo --no-pager
pgrep -a mihomo
ss -ltnp 'sport = :7890'
```

Если служба отсутствует, но `pgrep` показывает `mihomo -d /etc/mihomo`,
остановите именно этот ручной процесс: `kill -TERM PID`, заменив `PID`
актуальным номером. Не запускайте второй экземпляр с тем же портом и каталогом.

Установите шаблон службы, подставив фактический путь к программе:

```bash
MIHOMO_BIN="$(command -v mihomo)"
test -n "$MIHOMO_BIN" || { echo 'mihomo не найден'; exit 1; }
sed "s|/usr/local/bin/mihomo|$MIHOMO_BIN|" \
  /root/21_bot/deploy/systemd/mihomo.service \
  > /etc/systemd/system/mihomo.service

systemctl daemon-reload
systemctl enable mihomo
systemctl restart mihomo
systemctl status mihomo --no-pager
```

Проверьте подключение через прокси без токена бота:

```bash
curl -I --connect-timeout 15 --max-time 30 \
  --proxy http://127.0.0.1:7890 https://api.telegram.org
```

`HTTP/1.1 200 Connection established` означает создание туннеля через прокси.
Следующий HTTP-ответ от Telegram, например `HTTP/2 302`, подтверждает
HTTPS-соединение с Telegram. Один только ответ `200 Connection established`
ещё не подтверждает успешность конечного HTTPS-запроса.

## 4. Проверить ручной запуск бота

```bash
cd /root/21_bot
bash start.sh
```

Отправьте боту `/start` в Telegram. После проверки остановите ручной запуск
через `Ctrl+C` перед включением службы: один токен должен обслуживать один
процесс polling. `start.sh` запускает бот через uv и читает корневой `.env`.

## 5. Включить автозапуск и перезапуск бота

Готовый шаблон находится в `deploy/systemd/21-bot.service`. Проверьте, что
`command -v uv` показывает программу в одном из каталогов `PATH` шаблона;
если uv установлен иначе, добавьте его каталог в `Environment="PATH=..."`.

```bash
install -m 644 /root/21_bot/deploy/systemd/21-bot.service \
  /etc/systemd/system/21-bot.service

systemd-analyze verify /etc/systemd/system/21-bot.service \
  /etc/systemd/system/mihomo.service
systemctl daemon-reload
systemctl enable --now 21-bot
systemctl status 21-bot --no-pager
```

`enable` включает запуск при загрузке Ubuntu, `--now` сразу запускает службу.
Бот стартует после запуска службы Mihomo. Это порядок запуска, а не проверка
доступности прокси или подписки; временные сетевые ошибки бот повторяет сам.

В обоих шаблонах `Restart=always` и `RestartSec=10`: завершившийся процесс
запускается заново через 10 секунд. `StartLimitIntervalSec=0` отключает лимит
повторных попыток. Ручная команда `systemctl stop` не вызывает перезапуск.
Автоперезапуск реагирует на завершение процесса; зависший, но работающий процесс
этой настройкой не обнаруживается.

## 6. Управление и логи

```bash
# Запуск, остановка, перезапуск бота
systemctl start 21-bot
systemctl stop 21-bot
systemctl restart 21-bot

# Статус и последние сообщения
systemctl status 21-bot mihomo --no-pager
journalctl -u 21-bot -n 100 --no-pager
journalctl -u mihomo -n 50 --no-pager

# Следить за логом бота; Ctrl+C завершает только просмотр
journalctl -u 21-bot -f

# Отключить автозапуск и остановить бота
systemctl disable --now 21-bot
```

После изменения `.env` или кода выполните `systemctl restart 21-bot`.
После изменения конфигурации Mihomo — `systemctl restart mihomo`.
После изменения файлов `.service` — сначала `systemctl daemon-reload`,
затем перезапуск соответствующей службы.

### Диагностика недоступного VPN через журнал Mihomo

При запуске через `mihomo.service` стандартный вывод и ошибки Mihomo попадают
в журнал systemd (journald). В конфигурации задан `log-level: info`: журнал
помогает найти ошибки подключения, таймауты, проблемы подписки и запуска.
Уровень подробности отдельных проверок узлов зависит от сообщений самого Mihomo.

```bash
# Последние 100 сообщений Mihomo
journalctl -u mihomo -n 100 --no-pager

# Наблюдать за новыми сообщениями; Ctrl+C завершает только просмотр
journalctl -u mihomo -f

# Сообщения за последний час
journalctl -u mihomo --since "1 hour ago" --no-pager

# Состояние процесса и число автоматических перезапусков
systemctl status mihomo --no-pager
systemctl show mihomo -p NRestarts
```

Если процесс Mihomo завершился, systemd перезапускает его согласно настройке
`Restart=always`. Если процесс работает, но узлы подписки недоступны, служба
может оставаться в состоянии `active (running)` и не перезапускаться.
В этом случае проверьте журнал и повторите запрос через прокси из раздела 3.
Сам по себе статус `active` не подтверждает доступность Telegram через VPN.

Эта конфигурация использует только локальный прокси и не меняет системные
маршруты SSH. При недоступности VPN можно подключиться к серверу по SSH и
прочитать журнал, если обычная сеть сервера остаётся доступной.
Глубина истории журнала и сохранение после перезагрузки зависят от настройки
journald на сервере; приведённые команды сами по себе постоянное хранение
не включают. Перед публикацией логов скройте ссылки подписки и другие секреты.

## 7. Обновление и резервная копия

События находятся в `data/calendar.sqlite3`. При обновлении сохраняйте каталог
`data/` и серверный `.env`. Для согласованной резервной копии остановите бота
и скопируйте весь каталог `data/` в закрытое хранилище вне репозитория.

```bash
systemctl stop 21-bot
cd /root/21_bot
# Здесь обновите исходники согласованным для проекта способом.
uv sync --locked --no-dev
systemctl start 21-bot
```

Проверьте `systemctl status 21-bot` и отправьте `/start` после обновления.

## 8. Частые ошибки

- **`Network is unreachable`**: проверьте выход сервера в интернет и доступность
  Telegram. Это не обязательно блокировка: возможны проблемы маршрута или IPv6.
  Сравните `curl -4 -I https://api.telegram.org` и `curl -6 -I https://api.telegram.org`,
  добавив `--connect-timeout 10 --max-time 20` к каждой команде.
- **`bind: address already in use`** на 7890: порт занят, часто другим экземпляром
  Mihomo. Используйте `ss -ltnp 'sport = :7890'` и `pgrep -a mihomo`.
- **`can't open cache file: timeout`**: проверьте, не используют ли два экземпляра
  Mihomo один каталог `/etc/mihomo`; это одна из возможных причин.
- **`uv: command not found`** в службе: исправьте `PATH` в её конфигурации,
  затем выполните `daemon-reload` и перезапуск.
- **Конфликт `getUpdates`**: остановите второй экземпляр бота, в том числе
  запущенный на компьютере разработчика с тем же токеном.
- **Ошибка подписки**: проверьте формат и доступность ссылки в журнале Mihomo.
  Перед отправкой логов скройте ссылки подписки, токены и пароли. Telegram-библиотека
  может включать токен в адрес запроса внутри traceback.

## Источники

- [Подписки Mihomo](https://wiki.metacubex.one/en/config/proxy-providers/)
- [Локальные порты прокси](https://wiki.metacubex.one/en/config/inbound/port/)
- [Служба Mihomo](https://wiki.metacubex.one/en/startup/service/)
- [Перезапуск служб systemd](https://www.freedesktop.org/software/systemd/man/systemd.service.html)
- [Прокси в Requests](https://requests.readthedocs.io/en/stable/user/advanced/#proxies)
