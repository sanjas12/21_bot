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
1. Run `.\start.bat` from PowerShell or `start.bat` from cmd.

### Usage (Ubuntu)
1. Run `bash start.sh`.

Both launchers load the root `.env` file and run `src/main.py` through uv.
Direct launch from the project root:

```sh
uv run --locked --no-dev --env-file .env python src/main.py
```


### TODO

### help
https://www.freecodecamp.org/news/how-to-create-a-telegram-bot-using-python/
