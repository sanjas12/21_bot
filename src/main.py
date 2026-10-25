"""Personal Telegram calendar. Run python src/main.py."""

import logging
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import telebot
from dotenv import load_dotenv
from telebot import types

from date_picker import picker
from notebook import REPEATS, Store, add_months, due_reminders, occurrences

ROOT = Path(__file__).resolve().parent.parent
LOG = logging.getLogger(__name__)
MENU = [
    "➕ Добавить событие",
    "📅 Неделя",
    "🗓 Месяц",
    "📆 Год",
    "🗑 Удалить",
    "🌍 Часовой пояс",
    "✏️ Редактировать",
    "📋 Сегодня",
]
REMINDERS = {
    "Без уведомления": -1,
    "В момент события": 0,
    "За 15 минут": 15,
    "За час": 60,
    "За день": 1440,
    "За неделю": 10080,
}
PAGE_SIZE = 3
VISIBILITY = {"Общее (по умолчанию)": "public", "Личное": "private"}
EDIT_FIELDS = [
    "Текст",
    "Дата и время",
    "Повтор",
    "Напоминание",
    "Доступ",
    "Сохранить изменения",
    "Отмена",
]


def keyboard(labels):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(*[types.KeyboardButton(label) for label in labels])
    return markup


class MyBot:
    def __init__(self, token, store):
        self.bot = telebot.TeleBot(token, threaded=False)
        self.store = store
        self.drafts = {}
        self.pages = {}
        self.page_events = {}
        self.stop = threading.Event()
        self.event_lock = threading.RLock()
        self.bot.message_handler(content_types=["text"])(self.handle)
        self.bot.callback_query_handler(func=lambda call: True)(self.callback)

    def say(self, uid, text, labels=MENU):
        self.bot.send_message(uid, text, reply_markup=keyboard(labels))

    def handle(self, message):
        if message.chat.type != "private":
            self.bot.reply_to(
                message, "Для личных заметок откройте приватный чат со мной."
            )
            return
        uid, text = message.from_user.id, message.text.strip()
        self.store.ensure_user(uid)
        if text in ("/start", "/help", "/menu", "/cancel", "Отмена"):
            self.drafts.pop(uid, None)
            self.say(
                uid,
                "Личный календарь: добавляйте события и смотрите планы.\n"
                f"Часовой пояс: {self.store.timezone(uid)}.\n/cancel — отменить ввод.",
            )
        elif text.startswith("/delete"):
            self.confirm_delete(uid, text)
        elif text.startswith("/edit"):
            parts = text.split()
            if (
                len(parts) == 2
                and parts[1].isascii()
                and parts[1].isdigit()
                and len(parts[1]) <= 18
            ):
                self.begin_edit(uid, int(parts[1]))
            else:
                self.say(
                    uid,
                    "Введите /edit ID, например /edit 12. Номер # есть в списке событий.",
                )
        elif text in MENU:
            self.drafts.pop(uid, None)
            if text == MENU[0]:
                self.drafts[uid] = {"step": "title", "visibility": "public"}
                self.say(
                    uid, "Название или текст заметки (до 500 символов):", ["Отмена"]
                )
            elif text == MENU[4]:
                self.say(
                    uid,
                    "Введите /delete ID, например /delete 12. Номер # есть в списке событий.\n"
                    "Для повтора удаляется вся серия.",
                )
            elif text == MENU[5]:
                self.drafts[uid] = {"step": "timezone"}
                self.say(
                    uid,
                    "Введите пояс, например Europe/Moscow или Asia/Yekaterinburg.\n"
                    "Уже созданные события сохранят свой пояс.",
                    ["Отмена"],
                )
            elif text == MENU[6]:
                self.say(
                    uid,
                    "Введите /edit ID, например /edit 12. Номер # есть в списке событий.\n"
                    "У повторяющегося события изменяется вся серия.",
                )
            else:
                self.show_events(uid, MENU.index(text))
        elif uid in self.drafts:
            self.advance(uid, text)
        else:
            self.say(uid, "Выберите действие в меню или нажмите /start.")

    def advance(self, uid, text):
        draft = self.drafts[uid]
        step = draft["step"]
        if step == "edit_fields":
            if text == "Текст":
                draft["step"] = "title"
                self.say(uid, "Введите новый текст (до 500 символов).", ["Отмена"])
            elif text == "Дата и время":
                draft["step"] = "date"
                self.ask_date(uid, draft)
            elif text == "Повтор":
                draft["step"] = "repeat"
                self.say(uid, "Как часто повторять?", [*REPEATS.values(), "Отмена"])
            elif text == "Напоминание":
                draft["step"] = "reminder"
                self.say(uid, "Когда напомнить?", [*REMINDERS, "Отмена"])
            elif text == "Доступ":
                draft["step"] = "visibility"
                self.say(uid, "Кому доступно событие?", [*VISIBILITY, "Отмена"])
            elif text == "Сохранить изменения":
                self.save_edit(uid)
            else:
                self.edit_summary(uid)
        elif step == "timezone":
            try:
                ZoneInfo(text)
            except (ZoneInfoNotFoundError, ValueError):
                self.say(uid, "Неизвестный пояс. Пример: Europe/Moscow.", ["Отмена"])
                return
            self.store.set_timezone(uid, text)
            self.drafts.pop(uid)
            self.say(uid, f"Часовой пояс: {text}.")
        elif step == "title":
            if not 1 <= len(text) <= 500:
                self.say(uid, "Нужно от 1 до 500 символов.", ["Отмена"])
                return
            if "event_id" in draft:
                draft["title"] = text
                self.edit_summary(uid)
                return
            draft.update(title=text, step="date", timezone=self.store.timezone(uid))
            self.ask_date(uid, draft)
        elif step == "date":
            try:
                local = datetime.strptime(text, "%d.%m.%Y %H:%M")
                start = local.replace(tzinfo=ZoneInfo(draft["timezone"]))
                if not 2020 <= start.year <= 2099 or start <= datetime.now(UTC):
                    raise ValueError
                if (
                    start.astimezone(UTC).astimezone(start.tzinfo).replace(tzinfo=None)
                    != local
                ):
                    raise ValueError
            except ValueError:
                self.say(
                    uid,
                    "Нужна будущая дата до 2100 года: ДД.ММ.ГГГГ ЧЧ:ММ.",
                    ["Отмена"],
                )
                return
            draft.update(starts=local.isoformat(), step="repeat")
            if "event_id" in draft:
                self.edit_summary(uid)
                return
            self.say(uid, "Как часто повторять?", [*REPEATS.values(), "Отмена"])
        elif step == "repeat":
            choices = {label: key for key, label in REPEATS.items()}
            if text not in choices:
                self.say(uid, "Выберите период кнопкой.", [*REPEATS.values(), "Отмена"])
                return
            draft.update(repeat=choices[text], step="reminder")
            if "event_id" in draft:
                self.edit_summary(uid)
                return
            self.say(uid, "Когда напомнить?", [*REMINDERS, "Отмена"])
        elif step == "reminder":
            if text not in REMINDERS:
                self.say(uid, "Выберите интервал кнопкой.", [*REMINDERS, "Отмена"])
                return
            if "event_id" in draft:
                draft["reminder"] = REMINDERS[text]
                self.edit_summary(uid)
                return
            draft.update(reminder=REMINDERS[text], step="visibility")
            self.say(
                uid,
                "Кому доступно событие? По умолчанию — общее.\n"
                "Общее увидят все пользователи бота; напоминания тоже придут всем.\n"
                "Личное видно только вам. Выберите вариант для сохранения.",
                [*VISIBILITY, "Отмена"],
            )
        elif step == "visibility":
            if text not in VISIBILITY:
                self.say(uid, "Выберите доступ кнопкой.", [*VISIBILITY, "Отмена"])
                return
            draft["visibility"] = VISIBILITY[text]
            if "event_id" in draft:
                self.edit_summary(uid)
                return
            start = datetime.fromisoformat(draft["starts"]).replace(
                tzinfo=ZoneInfo(draft["timezone"])
            )

            if start <= datetime.now(UTC):
                draft["step"] = "date"
                self.ask_date(uid, draft)
                return
            event_id = self.store.add(uid, draft, draft["reminder"])
            self.drafts.pop(uid)
            self.say(
                uid,
                f"Сохранено #{event_id}: {draft['title']}\n"
                f"{start:%d.%m.%Y %H:%M} ({draft['timezone']})\n"
                f"{REPEATS[draft['repeat']]}. {'Общее' if draft['visibility'] == 'public' else 'Личное'}.",
            )

    def begin_edit(self, uid, event_id):
        event = self.store.get(uid, event_id)
        if event is None:
            self.say(uid, "Событие не найдено или недоступно.")
            return
        self.drafts[uid] = {
            **dict(event),
            "event_id": event_id,
            "original": dict(event),
        }
        self.edit_summary(uid)

    def edit_summary(self, uid):
        draft = self.drafts[uid]
        draft["step"] = "edit_fields"
        date = datetime.fromisoformat(draft["starts"])
        reminder = next(
            label for label, value in REMINDERS.items() if value == draft["reminder"]
        )
        self.say(
            uid,
            f"Редактирование #{draft['event_id']}\n{draft['title']}\n"
            f"Дата начала: {date:%d.%m.%Y %H:%M} ({draft['timezone']})\n"
            f"{REPEATS[draft['repeat']]}. {reminder}.\n"
            f"Доступ: {'общее для всех' if draft['visibility'] == 'public' else 'личное'}.\n"
            "Выберите поле. Изменения вступят в силу после сохранения.\n"
            "Для повтора изменяется вся серия.",
            EDIT_FIELDS,
        )

    def save_edit(self, uid):
        draft = self.drafts[uid]
        start = datetime.fromisoformat(draft["starts"]).replace(
            tzinfo=ZoneInfo(draft["timezone"])
        )
        if draft["repeat"] == "once" and start <= datetime.now(UTC):
            draft["step"] = "date"
            self.say(uid, "Для разового события выберите будущую дату.", ["Отмена"])
            self.ask_date(uid, draft)
            return
        with self.event_lock:
            saved = self.store.update(uid, draft["event_id"], draft)
        self.drafts.pop(uid)
        self.pages.clear()
        self.page_events.clear()
        self.say(
            uid,
            "Изменения сохранены."
            if saved
            else "Запись удалена или уже изменена. Откройте её заново через /edit ID.",
        )

    def ask_date(self, uid, draft):
        self.say(
            uid,
            "Выберите дату и время кнопками ниже или введите вручную:\n"
            f"25.12.2026 10:00. Пояс: {draft['timezone']}.",
            ["Отмена"],
        )
        self.show_picker(uid)

    def show_picker(self, uid, stage="day", month=None, message_id=None):
        draft = self.drafts[uid]
        token = uuid4().hex[:10]
        draft.update(picker_token=token, picker_stage=stage)
        today = datetime.now(ZoneInfo(draft["timezone"])).date()
        text, markup = picker(
            stage,
            token,
            today,
            month=month,
            day=draft.get("day"),
            hour=draft.get("hour"),
        )
        text += (
            f"\nЧасовой пояс: {draft['timezone']}. Можно ввести дату и время текстом."
        )
        if message_id is None:
            self.bot.send_message(uid, text, reply_markup=markup)
        else:
            self.bot.edit_message_text(text, uid, message_id, reply_markup=markup)

    def pick_date(self, uid, parts, message_id):
        draft = self.drafts.get(uid)
        if (
            not draft
            or draft.get("step") != "date"
            or draft.get("picker_token") != parts[1]
        ):
            self.say(
                uid,
                "Этот календарь устарел. Продолжите текущий ввод или добавьте событие заново.",
            )
            return
        action, value = parts[2:]
        stage = draft["picker_stage"]
        today = datetime.now(ZoneInfo(draft["timezone"])).date()
        try:
            if action == "ignore":
                return
            if action == "cancel":
                self.drafts.pop(uid)
                self.bot.edit_message_reply_markup(uid, message_id, reply_markup=None)
                self.say(uid, "Добавление отменено.")
            elif action == "month" and stage == "day":
                month = datetime.strptime(value, "%Y-%m-%d").date().replace(day=1)
                if today.replace(day=1) <= month and month.year <= 2099:
                    self.show_picker(uid, month=month, message_id=message_id)
            elif action == "day" and stage == "day":
                day = datetime.strptime(value, "%Y-%m-%d").date()
                if today <= day and day.year <= 2099:
                    draft["day"] = day
                    self.show_picker(uid, "hour", message_id=message_id)
            elif action == "hour" and stage == "hour" and 0 <= int(value) <= 23:
                draft["hour"] = int(value)
                self.show_picker(uid, "minute", message_id=message_id)
            elif action == "minute" and stage == "minute" and 0 <= int(value) <= 59:
                text = f"{draft['day']:%d.%m.%Y} {draft['hour']:02d}:{int(value):02d}"
                self.advance(uid, text)
                if draft["step"] in ("repeat", "edit_fields"):
                    self.bot.edit_message_text(
                        f"Выбрано: {text} ({draft['timezone']})", uid, message_id
                    )
                else:
                    self.show_picker(uid, "hour", message_id=message_id)
            elif action == "back" and value in ("day", "hour"):
                self.show_picker(uid, value, message_id=message_id)
        except (ValueError, OverflowError):
            self.say(uid, "Не удалось выбрать дату. Попробуйте ещё раз.", ["Отмена"])

    def show_events(self, uid, period):
        zone = ZoneInfo(self.store.timezone(uid))
        now = datetime.now(UTC)
        local = now.astimezone(zone)
        if period == 7:
            local = local.replace(hour=0, minute=0, second=0, microsecond=0)
            now = local.astimezone(UTC)
            end = (local + timedelta(days=1)).astimezone(UTC)
        else:
            end = (
                local + timedelta(days=7)
                if period == 1
                else add_months(local, 1 if period == 2 else 12)
            )
        rows = []
        for event in self.store.visible_events(uid):
            for start in occurrences(event, now, end):
                date = start.astimezone(zone)
                rows.append(
                    (
                        start,
                        f"{date:%d.%m.%Y %H:%M} — {event['title']}\n"
                        f"#{event['id']} · {REPEATS[event['repeat']]} · "
                        f"{'🌐 Общее' if event['visibility'] == 'public' else '🔒 Личное'}",
                        event["id"] if event["user_id"] == uid else None,
                    )
                )
        rows.sort(key=lambda row: row[0])
        token = uuid4().hex[:12]
        self.pages[uid] = (token, [row[1] for row in rows], zone.key)
        self.page_events[uid] = (token, [row[2] for row in rows])
        self.render_page(uid, token, 0)

    def render_page(self, uid, token, page):
        snapshot = self.pages.get(uid)
        if not snapshot or snapshot[0] != token:
            self.say(uid, "Список устарел. Выберите период заново.")
            return
        _, rows, zone = snapshot
        count = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
        if not 0 <= page < count:
            return
        buttons = types.InlineKeyboardMarkup()
        event_snapshot = self.page_events.get(uid)
        if event_snapshot and event_snapshot[0] == token:
            for event_id in dict.fromkeys(
                event_snapshot[1][page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
            ):
                if event_id is None:
                    continue
                buttons.add(
                    types.InlineKeyboardButton(
                        f"✏️ Редактировать #{event_id}", callback_data=f"edit:{event_id}"
                    )
                )
        if page:
            buttons.add(
                types.InlineKeyboardButton(
                    "← Назад", callback_data=f"page:{token}:{page - 1}"
                )
            )
        if page + 1 < count:
            buttons.add(
                types.InlineKeyboardButton(
                    "Далее →", callback_data=f"page:{token}:{page + 1}"
                )
            )
        body = (
            "\n\n".join(rows[page * PAGE_SIZE : (page + 1) * PAGE_SIZE])
            or "Событий пока нет."
        )
        self.bot.send_message(
            uid,
            f"События ({zone}) · {page + 1}/{count}\n\n{body}",
            reply_markup=buttons,
        )

    def confirm_delete(self, uid, text):
        parts = text.split()
        if (
            len(parts) != 2
            or not parts[1].isascii()
            or not parts[1].isdigit()
            or len(parts[1]) > 18
        ):
            self.say(uid, "Формат: /delete 12. Номер есть в списке событий.")
            return
        event = self.store.get(uid, int(parts[1]))
        if event is None:
            self.say(uid, "Событие не найдено.")
            return
        self.drafts.pop(uid, None)
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "Удалить запись / всю серию", callback_data=f"delete:{event['id']}"
            )
        )
        self.bot.send_message(
            uid,
            f"Удалить «{event['title']}»?\nДля отмены просто вернитесь в меню.",
            reply_markup=markup,
        )

    def callback(self, call):
        self.bot.answer_callback_query(call.id)
        if call.message is None or call.message.chat.type != "private":
            return
        uid = call.from_user.id
        parts = (call.data or "").split(":")
        if len(parts) == 4 and parts[0] == "date":
            self.pick_date(uid, parts, call.message.message_id)
        elif len(parts) == 3 and parts[0] == "page" and parts[2].isdigit():
            self.render_page(uid, parts[1], int(parts[2]))
        elif (
            len(parts) == 2
            and parts[0] == "edit"
            and parts[1].isdigit()
            and len(parts[1]) <= 18
        ):
            self.begin_edit(uid, int(parts[1]))
        elif len(parts) == 2 and parts[0] == "delete" and parts[1].isdigit():
            with self.event_lock:
                deleted = self.store.delete(uid, int(parts[1]))
            self.pages.clear()
            self.page_events.clear()
            self.say(
                uid,
                "Событие удалено."
                if deleted
                else "Событие уже удалено или недоступно.",
            )

    def remind_once(self, now=None):
        with self.event_lock:
            self.deliver_reminders(now)

    def deliver_reminders(self, now=None):
        for event, start in due_reminders(self.store, now or datetime.now(UTC)):
            current = self.store.get(event["user_id"], event["id"])
            if current is None:
                continue
            for uid in self.store.recipients(current):
                if self.store.sent(event["id"], start, uid):
                    continue
                try:
                    zone = ZoneInfo(self.store.timezone(uid))
                    date = start.astimezone(zone)
                    scope = "Общее" if event["visibility"] == "public" else "Личное"
                    self.bot.send_message(
                        uid,
                        f"🔔 {scope} напоминание\n{event['title']}\n"
                        f"{date:%d.%m.%Y %H:%M} ({zone.key}) · #{event['id']}",
                    )
                    self.store.mark_sent(event["id"], start, uid)
                except Exception:
                    LOG.exception(
                        "Cannot deliver reminder for event %s to user %s",
                        event["id"],
                        uid,
                    )

    def deliver_release_updates(self):
        for notice in self.store.pending_releases():
            try:
                self.bot.send_message(notice["user_id"], notice["message"])
                self.store.mark_release_sent(notice["version"], notice["user_id"])
            except Exception as error:
                # Avoid logging Telegram exceptions: request URLs can contain tokens.
                if getattr(error, "error_code", None) == 403:
                    self.store.mark_release_sent(notice["version"], notice["user_id"])
                else:
                    self.store.mark_release_failed(notice["version"], notice["user_id"])
                LOG.warning(
                    "Cannot deliver release %s to user %s",
                    notice["version"],
                    notice["user_id"],
                )

    def reminder_loop(self):
        while not self.stop.is_set():
            try:
                self.remind_once()
                self.deliver_release_updates()
            except Exception:
                LOG.exception("Reminder scan failed")
            self.stop.wait(30)

    def run(self):
        worker = threading.Thread(target=self.reminder_loop, daemon=True)
        worker.start()
        try:
            self.bot.infinity_polling(allowed_updates=["message", "callback_query"])
        finally:
            self.stop.set()
            worker.join(timeout=10)


def main():
    load_dotenv(ROOT / ".env")
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("Укажите BOT_TOKEN в переменных окружения или корневом .env.")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    MyBot(token, Store(ROOT / "data" / "calendar.sqlite3")).run()


if __name__ == "__main__":
    main()
