#!/bin/bash

# версия: 0.1

# Назначение: полностью подготавливает окружение разработки проекта.
# Скрипт удаляет существующую .venv, создаёт её заново, устанавливает runtime-,
# dev- и build-зависимости, а затем устанавливает Git hooks pre-commit.
# Поддерживает uv и fallback на pip, а также онлайн- и офлайн-установку из
# локального каталога python_Library на дисках D, E или F.
# Ход выполнения и ошибки записываются в каталог logs/.
# ВАЖНО: запуск удаляет текущую .venv вместе с установленными в ней пакетами.

# uv + интернет → uv sync (если есть pyproject.toml) или uv pip install -r requirements.txt
# uv + офлайн → uv sync --no-index --find-links=... или uv pip install --no-index
# нет uv + интернет → fallback на pip install -r requirements.txt
# нет uv + офлайн → fallback на pip install --no-index -f ...

set -e

# Определяем абсолютные пути
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT"

SCRIPT_NAME=$(basename "$0" .sh)

cd "$PROJECT_ROOT" || exit 1

# ── НАСТРОЙКА ЛОГИРОВАНИЯ ───────────────────────────────────────────────────

LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/${SCRIPT_NAME}_$(date +%Y%m%d_%H%M%S).log"
ERROR_LOG="$LOG_DIR/${SCRIPT_NAME}_errors.log"

# Функция логирования
log() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "$timestamp - $1" | tee -a "$LOG_FILE"
}

# Функция логирования ошибок
log_error() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "$timestamp - ❌ $1" | tee -a "$LOG_FILE" "$ERROR_LOG"
}

# Функция логирования успеха
log_success() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "$timestamp - ✅ $1" | tee -a "$LOG_FILE"
}

# Функция логирования предупреждений
log_warning() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "$timestamp - ⚠ $1" | tee -a "$LOG_FILE"
}

# Обработчик ошибок
error_handler() {
    local line_no=$1
    local command=$2
    local exit_code=$3

    log_error "Ошибка на строке $line_no"
    log_error "Команда: $command"
    log_error "Код возврата: $exit_code"
    log_error "Текущая директория: $(pwd)"
    log_error "Скрипт завершен с ошибкой. Лог: $LOG_FILE"

    exit $exit_code
}

trap 'error_handler ${LINENO} "$BASH_COMMAND" $?' ERR

# ── Вспомогательные функции ───────────────────────────────────────────────────

activate_venv() {
    local venv_path=$1
    if [[ -f "$venv_path/Scripts/activate" ]]; then
        source "$venv_path/Scripts/activate"
        log_success "venv активирована (Windows): $venv_path"
    elif [[ -f "$venv_path/bin/activate" ]]; then
        source "$venv_path/bin/activate"
        log_success "venv активирована (Linux/Mac): $venv_path"
    else
        log_error "Скрипт activate не найден в $venv_path"
        exit 1
    fi
}

# Проверка интернета
check_internet() {
    if command -v python >/dev/null 2>&1; then
        python -c "import urllib.request; urllib.request.urlopen('https://pypi.org/simple/', timeout=3)" 2>/dev/null && return 0
    fi

    return 1
}

# --- CONFIG ---
PIP_VERSION="25.0.1"

log "=== НАЧАЛО BOOTSTRAP ==="
log "Лог-файл: $LOG_FILE"
log "Корень проекта: $PROJECT_ROOT"
log "Директория бэкенда: $BACKEND_DIR"

# Поиск LOCAL_PACKAGES_DIR на дисках D, E, F
LOCAL_PACKAGES_DIR=""
for drive in d e f; do
    candidate="/$drive/temp/python_Library"
    if [[ -d "$candidate" ]]; then
        LOCAL_PACKAGES_DIR="$candidate"
        log_success "Локальный каталог найден: $LOCAL_PACKAGES_DIR"
        break
    fi
done

if [[ -z "$LOCAL_PACKAGES_DIR" ]]; then
    log_warning "Локальный каталог python_Library не найден ни на одном из дисков (d/e/f)"
fi

# --- CLEAN ---
log "Удаляем старые .venv ..."
rm -rf .venv "$BACKEND_DIR/.venv"
log_success ".venv удалены"

# --- DETECT UV ---
if command -v uv >/dev/null 2>&1; then
    HAS_UV=1
    log_success "uv найден"
else
    HAS_UV=0
    log_warning "uv не найден -> fallback на pip"
fi

# Проверка интернета
log "Проверка доступа в интернет..."
if check_internet; then
    NET_OK=0
    log_success "Интернет доступен"
else
    NET_OK=1
    log_warning "Интернет НЕ доступен"
fi

# --- DETECT PROJECT TYPE ---
USE_PYPROJECT=0
REQUIREMENTS_FILE=""
VENV_LOCATION=""

log "Поиск файлов зависимостей в: $BACKEND_DIR"

if [ -f "$BACKEND_DIR/pyproject.toml" ]; then
    USE_PYPROJECT=1
    VENV_LOCATION="$BACKEND_DIR/.venv"
    log_success "pyproject.toml найден: $BACKEND_DIR/pyproject.toml"
    if [ -f "$BACKEND_DIR/requirements.txt" ]; then
	REQUIREMENTS_FILE="$BACKEND_DIR/requirements.txt"
    	VENV_LOCATION="$BACKEND_DIR/.venv"
    	log_success "requirements.txt найден: $REQUIREMENTS_FILE"
    fi
elif [ -f "$BACKEND_DIR/requirements.txt" ]; then
    REQUIREMENTS_FILE="$BACKEND_DIR/requirements.txt"
    VENV_LOCATION="$BACKEND_DIR/.venv"
    log_success "requirements.txt найден: $REQUIREMENTS_FILE"
elif [ -f "$PROJECT_ROOT/requirements.txt" ]; then
    REQUIREMENTS_FILE="$PROJECT_ROOT/requirements.txt"
    VENV_LOCATION="$PROJECT_ROOT/.venv"
    log_success "requirements.txt найден в корне проекта"
else
    log_error "Файлы зависимостей не найдены (искали $BACKEND_DIR/pyproject.toml и requirements.txt)"
    exit 1
fi

if [ $NET_OK -ne 0 ] && [ ! -d "$LOCAL_PACKAGES_DIR" ]; then
    log_error "Нет интернета и нет офлайн-каталога: $LOCAL_PACKAGES_DIR"
    exit 1
fi

# --- MODE FLAGS ---
USE_OFFLINE=0
[ $NET_OK -ne 0 ] && USE_OFFLINE=1

PIP_ARGS=()
[ $USE_OFFLINE -eq 1 ] && PIP_ARGS+=(--no-index --find-links="$LOCAL_PACKAGES_DIR")

if [ $USE_OFFLINE -eq 1 ]; then
    log "Режим: ОФЛАЙН"
else
    log "Режим: ОНЛАЙН"
fi

# ─────────────────────────────────────────────────────────────────────────────
# INSTALL WITH UV
# ─────────────────────────────────────────────────────────────────────────────
install_with_uv() {
    log "=== УСТАНОВКА ЧЕРЕЗ UV ==="

    if [ $USE_PYPROJECT -eq 1 ]; then
        log "Переход в директорию бэкенда: $BACKEND_DIR"
        cd "$BACKEND_DIR"

        log "Создание виртуального окружения..."
        uv venv
        log_success "Виртуальное окружение создано в $BACKEND_DIR/.venv"

        UV_ARGS=(--group build --group dev)
        [ $USE_OFFLINE -eq 1 ] && UV_ARGS+=(--no-index --find-links="$LOCAL_PACKAGES_DIR")

        log "Выполнение: uv sync ${UV_ARGS[*]}"
        uv sync "${UV_ARGS[@]}"
        log_success "Зависимости установлены через uv sync"

        cd "$PROJECT_ROOT"
    else
        # Обработка requirements.txt
        local work_dir="$(dirname "$REQUIREMENTS_FILE")"
        cd "$work_dir"

        log "Создание виртуального окружения в $work_dir..."
        uv venv
        log_success "Виртуальное окружение создано"

        local req_basename="$(basename "$REQUIREMENTS_FILE")"
        log "Выполнение: uv pip install из $req_basename"

        uv pip install "${PIP_ARGS[@]}" -r "$req_basename" --dry-run
        log "Dry-run выполнен успешно"

        uv pip install "${PIP_ARGS[@]}" -r "$req_basename"
        log_success "Зависимости установлены через uv pip"

        cd "$PROJECT_ROOT"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# INSTALL WITH PIP
# ─────────────────────────────────────────────────────────────────────────────
install_with_pip() {
    log "=== УСТАНОВКА ЧЕРЕЗ PIP ==="

    local work_dir="$BACKEND_DIR"
    [ -n "$REQUIREMENTS_FILE" ] && work_dir="$(dirname "$REQUIREMENTS_FILE")"

    cd "$work_dir"

    log "Создание виртуального окружения в $work_dir..."
    python3 -m venv .venv || python -m venv .venv
    log_success "Виртуальное окружение создано"

    activate_venv ".venv"

    # обновление pip
    log "Обновление pip до версии $PIP_VERSION..."
    python -m pip install "${PIP_ARGS[@]}" --upgrade pip=="$PIP_VERSION"
    log_success "Pip обновлен"

    if python -m pip install --help | grep -q -- "--dry-run"; then
        log "Выполнение dry-run..."
        pip install "${PIP_ARGS[@]}" -r "$REQUIREMENTS_FILE" --dry-run
        log_success "Dry-run выполнен"
    else
        log_warning "pip без --dry-run, пропускаем проверку"
    fi

    log "Установка зависимостей из $REQUIREMENTS_FILE..."
    pip install "${PIP_ARGS[@]}" -r "$REQUIREMENTS_FILE"
    log_success "Зависимости установлены через pip"

    cd "$PROJECT_ROOT"
}

# ─────────────────────────────────────────────────────────────────────────────
# INSTALL GIT HOOKS
# ─────────────────────────────────────────────────────────────────────────────
install_hooks() {
    log "=== УСТАНОВКА GIT HOOKS ==="

    if [ ! -d "$PROJECT_ROOT/.git" ]; then
        log_warning "Это не git репозиторий, пропускаем установку хуков"
        return 0
    fi

    # Активируем окружение, чтобы получить доступ к pre-commit
    activate_venv "$VENV_LOCATION"

    log "Установка pre-commit hooks..."
    if pre-commit install 2>/dev/null; then
        log_success "Git hooks установлены"
    else
        log_warning "pre-commit не найден в окружении. Убедитесь, что он есть в зависимостях."
    fi
    pre-commit install --hook-type commit-msg 2>/dev/null || true

    # Деактивация окружения (для чистоты)
    deactivate 2>/dev/null || true
}

# ─────────────────────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────────────────────
START_TIME=$(date +%s)

if [ $HAS_UV -eq 1 ]; then
    install_with_uv
else
    install_with_pip
fi

install_hooks

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

log_success "=== ГОТОВО ==="
log_success "Окружение + зависимости + git hooks готовы"
log_success "Время выполнения: ${DURATION} секунд"
log_success "Полный лог: $LOG_FILE"

echo ""
echo "🎉 ГОТОВО: окружение + зависимости + git hooks готовы"
echo "📝 Лог сохранен в: $LOG_FILE"
