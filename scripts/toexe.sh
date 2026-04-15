#!/usr/bin/env bash
set -e
set -u

# Определяем директорию скрипта (где лежит этот run.sh и setup.py)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# echo $SCRIPT_DIR

# Путь к setup.py
SETUP_FILE="$SCRIPT_DIR/setup.py"
# echo $SETUP_FILE

# Проверка наличия setup.py
if [ ! -f "$SETUP_FILE" ]; then
    echo "[ERROR] setup.py не найден в $SCRIPT_DIR"
    exit 1
fi

# # Определяем Python (если есть venv рядом со скриптом, используем его)
# if [ -x "$SCRIPT_DIR/../venv/bin/python" ]; then
#     PYTHON_EXE="$SCRIPT_DIR/../venv/bin/python"
# else
#     PYTHON_EXE="python"
# fi

# Папка для сборки - на два уровня выше от скрипта
BUILD_DIR="$SCRIPT_DIR/build"

# Чистим старую сборку
echo "Cleaning previous build..."
rm -rf "$BUILD_DIR"

# Запуск сборки
echo "Building package..."
cd "$SCRIPT_DIR"
python setup.py build

# Показываем путь к exe (ищем подпапку с exe.*)
echo "Build completed successfully."
find "$BUILD_DIR" -type d -name "exe.win*" -print
