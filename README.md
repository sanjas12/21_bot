# 21_bot (https://t.me/sanjas12_bot)

# Contents

## Installation

### Prerequisites
1. Install Python 3.11+ and uv.
2. Run `uv sync --locked` from the project root on Windows for development.
3. On Ubuntu, run `uv sync --locked --no-dev`.
4. Copy `.env.example` to `.env` in the project root and set `BOT_TOKEN` there.

### Token storage

Keep the real token only in the local `.env` file. Git ignores `.env` and
`.env.*`, except for `.env.example`, which contains no secrets.
Create a separate `.env` on the Ubuntu server; do not transfer it through Git.
On Ubuntu, restrict access with `chmod 600 .env`.
If a real token has been committed or published, revoke it through BotFather
and put the replacement token in the local `.env`. Removing the file from
Git tracking does not remove it from old commits.

Bot sources are in `src/`; the entry point is `src/main.py`.

### Usage (Windows)
1. Run `uv run --locked --no-dev python src/main.py` from the project root.

### Usage (Ubuntu)
1. Run `bash start.sh`.

Развёртывание на сервере, настройка Mihomo с HTTPS-подпиской, прокси для бота,
автозапуск, перезапуск после сбоя и просмотр логов описаны в
[инструкции для Ubuntu](docs/ubuntu-deployment.md).
Шаблоны служб: [21-bot.service](deploy/systemd/21-bot.service) и
[mihomo.service](deploy/systemd/mihomo.service).

Автоматическое обновление сервера после публикации GitHub Release:
[настройка GitHub Actions](docs/automatic-deployment.md).

The bot loads the root `.env` file and runs from `src/main.py`.
Direct launch from the project root:

```sh
uv run --locked --no-dev --env-file .env python src/main.py
```


## Calendar

Open the bot in a private Telegram chat and send `/start`.

New events default to **Общее**: all users known to the bot can see them and
receive their reminders. The final creation step offers **Общее (по умолчанию)**
or **Личное** before saving. Personal events are visible only to their author.
Only the author can edit or delete an event, including a shared one. The
**Доступ** field in editing changes visibility. Existing records remain personal
when upgrading; they are never published automatically. Reminder delivery is
tracked separately for each recipient, so one failed delivery does not block
the others. New users see existing shared events on their next calendar view.

- **Добавить событие**: enter a title, select a day in the inline calendar,
  then an hour and minutes (5-minute steps). Navigate months or use Today/Tomorrow.
  Alternatively, type an exact future date (`25.12.2026 10:00`),
  a recurrence and a reminder interval. `/cancel` cancels unfinished input.
- Recurrence: once, daily, weekly, monthly or yearly. A monthly event on the
  31st uses the last day of a shorter month, then returns to the 31st.
  February 29 uses February 28 in non-leap years.
- View events from now through the next week, calendar month or calendar year.
  Lists have navigation buttons. Dates use your selected time zone.
- **Сегодня**: view all events for the current calendar day in your selected
  time zone, including events earlier today and recurring events.
- **Удалить**: use `/delete ID` from the list, then confirm. Deleting a
  recurring event deletes the entire series, not just one occurrence.
- **Редактировать**: press the edit button below an event list or use `/edit ID`.
  Change the text, date/time, recurrence or reminder, then choose
  **Сохранить изменения**. `/cancel` discards the draft. A recurring event is
  edited as an entire series; its original time zone is retained. Renaming
  preserves delivered reminders; changing the schedule recalculates future
  reminders. The event number stays the same.
- **Часовой пояс**: default `Europe/Moscow`; accepts IANA names such as
  `Asia/Yekaterinburg`. Existing events keep their original time zone.
  Ambiguous autumn times use the first occurrence; recurring times in a spring
  DST gap move forward by the gap. Nonexistent dates are rejected during input.

Reminders can be disabled or sent at the event time, 15 minutes, an hour,
a day or a week beforehand. They are checked every 30 seconds while the bot
is running. If the chosen reminder deadline has already passed when creating
an event, the reminder is sent on the next check.

Keep one bot process running continuously on Ubuntu. After downtime, reminders
are caught up within 24 hours of their deadline and no later than one hour
after the event. Successful deliveries are recorded in SQLite; failed deliveries
are retried. A crash between Telegram accepting a message and recording it can
cause a duplicate notification.

Events and time zones persist in `data/calendar.sqlite3` (excluded from Git).
For a simple backup, stop the bot and copy the whole `data/` directory.
Unfinished input and open list pages are reset on restart. Records are isolated
by Telegram user for personal events; shared events are visible to everyone.
Group chats are not used for calendar management.

Offline checks, without contacting Telegram:

```sh
uv run --locked python -m unittest discover -s tests -v
uv run --locked ruff check src tests
```

### help
https://www.freecodecamp.org/news/how-to-create-a-telegram-bot-using-python/
