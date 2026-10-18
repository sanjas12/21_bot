# 21_bot (https://t.me/sanjas12_bot)

# Contents

## Installation

### Prerequisites
1. Install Python 3.11+ and uv.
2. Run `uv sync --locked` from the project root on Windows for development.
3. On Ubuntu, run `uv sync --locked --no-dev`.
4. Set `BOT_TOKEN` in a local `.env` file in the project root.

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
