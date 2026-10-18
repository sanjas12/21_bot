"""SQLite storage and calendar recurrence, independent of Telegram."""

import calendar
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPEATS = {
    "once": "Однократно",
    "daily": "Ежедневно",
    "weekly": "Еженедельно",
    "monthly": "Ежемесячно",
    "yearly": "Ежегодно",
}


def add_months(value, count):
    year, month = divmod(value.year * 12 + value.month - 1 + count, 12)
    month += 1
    return value.replace(
        year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1])
    )


def occurrences(event, after, before):
    """UTC occurrences in [after, before); monthly dates retain original anchor."""
    base = datetime.fromisoformat(event["starts"]).replace(
        tzinfo=ZoneInfo(event["timezone"])
    )
    local = after.astimezone(base.tzinfo)
    repeat = event["repeat"]
    step = 1 if repeat == "daily" else 7
    if repeat in ("daily", "weekly"):
        index = max(0, (local.date() - base.date()).days // step - 1)
    elif repeat in ("monthly", "yearly"):
        months = (local.year - base.year) * 12 + local.month - base.month
        index = max(0, months // (1 if repeat == "monthly" else 12) - 1)
    else:
        index = 0
    while True:
        try:
            if repeat in ("daily", "weekly"):
                current = base + timedelta(days=index * step)
            elif repeat in ("monthly", "yearly"):
                current = add_months(base, index * (1 if repeat == "monthly" else 12))
            else:
                current = base
            current = current.astimezone(UTC)
        except (ValueError, OverflowError):
            return
        if current >= before:
            return
        if current >= after:
            yield current
        if repeat == "once":
            return
        index += 1


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, timezone TEXT NOT NULL DEFAULT 'Europe/Moscow');
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    title TEXT NOT NULL, starts TEXT NOT NULL, timezone TEXT NOT NULL,
                    repeat TEXT NOT NULL, reminder INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS events_user ON events(user_id);
                CREATE TABLE IF NOT EXISTS reminders (
                    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                    occurrence TEXT NOT NULL, PRIMARY KEY(event_id,occurrence));
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(events)")}
            if "created_at" not in columns:
                db.execute(
                    "ALTER TABLE events ADD COLUMN created_at TEXT NOT NULL DEFAULT ''"
                )
            if "visibility" not in columns:
                db.execute(
                    "ALTER TABLE events ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'"
                )
            db.executescript("""
                CREATE TABLE IF NOT EXISTS deliveries (
                    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id), occurrence TEXT NOT NULL,
                    PRIMARY KEY(event_id,user_id,occurrence));
                INSERT OR IGNORE INTO deliveries(event_id,user_id,occurrence)
                    SELECT r.event_id,e.user_id,r.occurrence FROM reminders r
                    JOIN events e ON e.id=r.event_id;
                DELETE FROM reminders;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def ensure_user(self, uid):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO users(id) VALUES (?)", (uid,))

    def timezone(self, uid):
        with self.connect() as db:
            row = db.execute("SELECT timezone FROM users WHERE id=?", (uid,)).fetchone()
            return row[0] if row else "Europe/Moscow"

    def set_timezone(self, uid, zone):
        ZoneInfo(zone)
        self.ensure_user(uid)
        with self.connect() as db:
            db.execute("UPDATE users SET timezone=? WHERE id=?", (zone, uid))

    def add(self, uid, draft, reminder):
        self.ensure_user(uid)
        with self.connect() as db:
            result = db.execute(
                """INSERT INTO events
                (user_id,title,starts,timezone,repeat,reminder,created_at,visibility) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    uid,
                    draft["title"],
                    draft["starts"],
                    draft["timezone"],
                    draft["repeat"],
                    reminder,
                    datetime.now(UTC).isoformat(),
                    draft.get("visibility", "public"),
                ),
            )
            return result.lastrowid

    def events(self, uid=None):
        with self.connect() as db:
            if uid is None:
                return db.execute("SELECT * FROM events WHERE reminder>=0").fetchall()
            return db.execute(
                "SELECT * FROM events WHERE user_id=? ORDER BY starts,id", (uid,)
            ).fetchall()

    def get(self, uid, event_id):
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM events WHERE id=? AND user_id=?", (event_id, uid)
            ).fetchone()

    def visible_events(self, uid):
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM events WHERE user_id=? OR visibility='public' ORDER BY starts,id",
                (uid,),
            ).fetchall()

    def recipients(self, event):
        if event["visibility"] == "private":
            return [event["user_id"]]
        with self.connect() as db:
            return [row[0] for row in db.execute("SELECT id FROM users")]

    def delete(self, uid, event_id):
        with self.connect() as db:
            return bool(
                db.execute(
                    "DELETE FROM events WHERE id=? AND user_id=?", (event_id, uid)
                ).rowcount
            )

    def update(self, uid, event_id, draft):
        """Commit a complete edit atomically; reject stale or foreign records."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM events WHERE id=? AND user_id=?", (event_id, uid)
            ).fetchone()
            if row is None or dict(row) != draft["original"]:
                return False
            timing = ("starts", "timezone", "repeat", "reminder")
            changed = any(row[key] != draft[key] for key in timing)
            now = datetime.now(UTC).isoformat()
            db.execute(
                """UPDATE events SET title=?, starts=?, timezone=?, repeat=?,
                       reminder=?, created_at=?, visibility=? WHERE id=? AND user_id=?""",
                (
                    draft["title"],
                    draft["starts"],
                    draft["timezone"],
                    draft["repeat"],
                    draft["reminder"],
                    now if changed else row["created_at"],
                    draft["visibility"],
                    event_id,
                    uid,
                ),
            )
            if changed:
                db.execute(
                    "DELETE FROM deliveries WHERE event_id=? AND occurrence>=?",
                    (event_id, now),
                )
            return True

    def sent(self, event_id, start, uid=None):
        with self.connect() as db:
            if uid is None:
                owner = db.execute(
                    "SELECT user_id FROM events WHERE id=?", (event_id,)
                ).fetchone()
                uid = owner[0] if owner else None
            return (
                db.execute(
                    "SELECT 1 FROM deliveries WHERE event_id=? AND occurrence=? AND user_id=?",
                    (event_id, start.isoformat(), uid),
                ).fetchone()
                is not None
            )

    def mark_sent(self, event_id, start, uid=None):
        with self.connect() as db:
            if uid is None:
                owner = db.execute(
                    "SELECT user_id FROM events WHERE id=?", (event_id,)
                ).fetchone()
                if owner is None:
                    return
                uid = owner[0]
            db.execute(
                "INSERT OR IGNORE INTO deliveries(event_id,user_id,occurrence) "
                "SELECT id, ?, ? FROM events WHERE id=?",
                (uid, start.isoformat(), event_id),
            )


def due_reminders(store, now):
    """Catch up within 24h of due time and at most 1h after the event."""
    for event in store.events():
        lead = timedelta(minutes=event["reminder"])
        for start in occurrences(
            event, now - timedelta(hours=1), now + lead + timedelta(seconds=1)
        ):
            due = start - lead
            if event["created_at"]:
                due = max(due, datetime.fromisoformat(event["created_at"]))
            if now - timedelta(hours=24) <= due <= now and any(
                not store.sent(event["id"], start, uid)
                for uid in store.recipients(event)
            ):
                yield event, start
