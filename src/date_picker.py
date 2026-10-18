"""Inline calendar and time keyboards for Telegram."""

import calendar
from datetime import timedelta

from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

MONTHS = (
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)


def picker(stage, token, today, month=None, day=None, hour=None):
    markup = InlineKeyboardMarkup()

    def button(label, action, value=""):
        return InlineKeyboardButton(
            label, callback_data=f"date:{token}:{action}:{value}"
        )

    if stage == "day":
        month = month or today.replace(day=1)
        markup.row(button(f"{MONTHS[month.month - 1]} {month.year}", "ignore"))
        markup.row(
            *[
                button(label, "ignore")
                for label in ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
            ]
        )
        for week in calendar.Calendar().monthdayscalendar(month.year, month.month):
            row = []
            for number in week:
                selected = month.replace(day=number) if number else None
                row.append(
                    button(str(number), "day", selected.isoformat())
                    if selected and selected >= today
                    else button("·", "ignore")
                )
            markup.row(*row)
        nav = []
        previous = month - timedelta(days=1)
        following = (month + timedelta(days=32)).replace(day=1)
        if previous >= today.replace(day=1):
            nav.append(button("←", "month", previous.replace(day=1).isoformat()))
        if following.year <= 2099:
            nav.append(button("→", "month", following.isoformat()))
        if nav:
            markup.row(*nav)
        markup.row(
            button("Сегодня", "day", today.isoformat()),
            button("Завтра", "day", (today + timedelta(days=1)).isoformat()),
        )
        text = "Выберите день в календаре."
    elif stage == "hour":
        for first in range(0, 24, 6):
            markup.row(
                *[
                    button(f"{value:02d}", "hour", str(value))
                    for value in range(first, first + 6)
                ]
            )
        markup.row(button("← К дате", "back", "day"))
        text = f"{day:%d.%m.%Y} — выберите час (00–23)."
    else:
        for first in (0, 30):
            markup.row(
                *[
                    button(f"{value:02d}", "minute", str(value))
                    for value in range(first, first + 30, 5)
                ]
            )
        markup.row(button("← К часам", "back", "hour"))
        text = f"{day:%d.%m.%Y}, {hour:02d}:… — выберите минуты."
    markup.row(button("Отмена", "cancel"))
    return text, markup
