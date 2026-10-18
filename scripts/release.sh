#!/bin/bash

# версия: 0.1

# Сам release.sh автоматически объединять ветки не должен: выпуск релиза и
# решение о переносе изменений в master лучше оставлять отдельными операциями.
# Использовать только для выпуска готовой версии из ветки master, когда все
# изменения уже закоммичены и рабочее дерево Git чистое. Запускать в Windows
# из Git Bash командой `bash scripts/release.sh`: скрипт обновляет master,
# запускает тесты, повышает версию через Commitizen, создаёт коммит и тег,
# а затем отправляет релиз в origin. Для обычной разработки не запускать.

# 1. Логирование        — пишет лог в logs/release_ДАТА.log
# 2. Git checkout       — переключается на master, pull и проверяет develop
# 3. Проверки           — синтаксис, все тесты, pre-commit и mypy
# 4. Коммиты            — показывает что войдёт в релиз
# 5. Меню               — авто / PATCH / MINOR / MAJOR / вручную
# 6. Bump               — cz bump с выбранным типом
# 7. Проверка версий    — сравнивает pyproject.toml и _version.py
# 8. Push               — только если версии совпали

set -e

# Переходим в корень проекта (папка выше scripts/)
cd "$(dirname "$0")/.."

# ─── Логирование ──────────────────────────────────────────────
LOG_DIR="logs"
LOG_FILE="$LOG_DIR/release_$(date '+%Y%m%d_%H%M%S').log"
mkdir -p "$LOG_DIR"

# Всё что идёт в терминал — дублируется в файл
exec > >(tee -a "$LOG_FILE") 2>&1

log_info()  { echo "[INFO]  $(date '+%H:%M:%S') $1"; }
log_ok()    { echo "[OK]    $(date '+%H:%M:%S') $1"; }
log_warn()  { echo "[WARN]  $(date '+%H:%M:%S') $1"; }
log_error() { echo "[ERROR] $(date '+%H:%M:%S') $1"; }

# Ловим любой выход из скрипта
trap 'EXIT_CODE=$?; if [ $EXIT_CODE -ne 0 ]; then log_error "Скрипт завершился с ошибкой (код $EXIT_CODE). См. $LOG_FILE"; fi' EXIT

log_info "Запуск release.sh"
log_info "Рабочая папка: $(pwd)"
log_info "Git версия: $(git --version)"
log_info "Log файл: $LOG_FILE"

START_BRANCH=$(git branch --show-current)

# ─── Кодировка ────────────────────────────────────────────────
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
# На Windows uv иногда не может создавать hardlink между кэшем и проектом.
export UV_LINK_MODE=copy

# ─── Предварительная проверка Git ─────────────────────────────
if [ -n "$(git status --porcelain)" ]; then
    log_error "Рабочее дерево Git содержит незакоммиченные изменения."
    log_error "Закоммить или отложи их перед запуском release.sh."
    exit 1
fi

# ─── Git: переключаемся на master ─────────────────────────────
echo ""
log_info "Переключаемся на master"
if ! git checkout master; then
    log_error "Не удалось переключиться на master"
    exit 1
fi

log_info "Получаем изменения с remote"
if ! git pull origin master; then
    log_error "Не удалось выполнить git pull. Проверь подключение к remote."
    exit 1
fi
log_ok "master актуален"

# release.sh не объединяет ветки автоматически, но не должен выпускать
# устаревший master, если в локальном develop остались неслитые изменения.
if git show-ref --verify --quiet refs/heads/develop; then
    if ! git merge-base --is-ancestor develop master; then
        log_error "Ветка develop содержит изменения, которых ещё нет в master."
        log_error "Релиз из устаревшего master отменён. Выполни:"
        log_error "  git checkout master"
        log_error "  git merge --ff-only develop"
        log_error "Затем повторно запусти bash scripts/release.sh."
        exit 1
    fi
    log_ok "Все локальные изменения develop уже включены в master"
elif [ "$START_BRANCH" = "develop" ]; then
    log_error "До переключения была активна develop, но локальная ветка больше не найдена."
    exit 1
else
    log_warn "Локальная ветка develop не найдена — проверка её слияния пропущена."
fi

# ─── Проверка новых коммитов ──────────────────────────────────
# Commitizen не создаёт обычный релиз, если после последнего тега нет коммитов.
LAST_RELEASE_TAG=$(git describe --tags --match '[0-9]*' --abbrev=0 2>/dev/null || true)
if [ -n "$LAST_RELEASE_TAG" ]; then
    NEW_COMMIT_COUNT=$(git rev-list "$LAST_RELEASE_TAG"..HEAD --count)
    if [ "$NEW_COMMIT_COUNT" -eq 0 ]; then
        log_error "После релиза $LAST_RELEASE_TAG нет новых коммитов."
        log_error "Сначала закоммить изменения и тесты, затем повтори запуск release.sh."
        exit 1
    fi
    log_info "После релиза $LAST_RELEASE_TAG найдено коммитов: $NEW_COMMIT_COUNT"
else
    log_warn "Корректные релизные теги не найдены — будет обработана вся история коммитов."
fi

# ─── Тесты ────────────────────────────────────────────────────
echo ""
log_info "Синхронизируем зависимости для тестов из uv.lock"
if ! uv sync --frozen --group dev; then
    log_error "Не удалось подготовить окружение для тестов! Релиз отменён."
    exit 1
fi
log_ok "Тестовое окружение готово"

log_info "Проверяем синтаксис Python"
if ! uv run --frozen python -m compileall -q src tests; then
    log_error "Синтаксическая проверка не прошла! Релиз отменён."
    exit 1
fi
log_ok "Синтаксис Python проверен"

log_info "Запускаем все тесты из каталога tests"
if ! uv run --frozen pytest tests; then
    log_error "Тесты не прошли! Релиз отменён."
    exit 1
fi
log_ok "Все тесты прошли успешно"

log_info "Запускаем pre-commit, включая mypy"
if ! uv run --frozen pre-commit run --all-files; then
    log_error "Pre-commit-проверки не прошли! Исправь изменения и повтори релиз."
    exit 1
fi
log_ok "Pre-commit-проверки прошли успешно"

if [ -n "$(git status --porcelain)" ]; then
    log_error "Проверки изменили файлы или создали незакоммиченные изменения."
    log_error "Проверь git diff, закоммить исправления и повтори релиз."
    exit 1
fi

# ─── Коммиты с последнего релиза ──────────────────────────────
echo ""
log_info "Коммиты с последнего релиза:"

if [ -z "$LAST_RELEASE_TAG" ]; then
    log_warn "Теги не найдены — показываем все коммиты"
    git log --oneline
else
    log_info "Последний тег: $LAST_RELEASE_TAG"
    git log "$LAST_RELEASE_TAG"..HEAD --oneline
fi

# ─── Текущая версия и предполагаемые bump'ы ───────────────────
echo ""
log_info "Определяем версии"

if ! CURRENT=$(uv run --frozen cz version --project 2>&1); then
    log_error "Не удалось получить текущую версию: $CURRENT"
    exit 1
fi

PATCH=$(uv run --frozen cz bump --increment PATCH --dry-run 2>&1 | grep "tag to create" | awk '{print $NF}')
MINOR=$(uv run --frozen cz bump --increment MINOR --dry-run 2>&1 | grep "tag to create" | awk '{print $NF}')
MAJOR=$(uv run --frozen cz bump --increment MAJOR --dry-run 2>&1 | grep "tag to create" | awk '{print $NF}')

log_info "Текущая версия: $CURRENT"

echo ""
echo "Выбери тип релиза:"
echo "  1) Авто    — определить по коммитам (feat/fix)"
echo "  2) PATCH   — $CURRENT → $PATCH"
echo "  3) MINOR   — $CURRENT → $MINOR"
echo "  4) MAJOR   — $CURRENT → $MAJOR"
echo "  5) Вручную — ввести версию"
echo "  0) Отмена"
echo ""
read -p "Выбор (0-5): " choice
log_info "Выбор пользователя: $choice"

# ─── Bump ─────────────────────────────────────────────────────
do_bump() {
    local label=$1
    shift
    log_info "Запускаем: $*"
    if ! "$@"; then
        log_error "Ошибка при bump: $label"
        exit 1
    fi
    log_ok "Bump выполнен: $label"
}

case $choice in
    1)
        uv run --frozen cz bump --dry-run
        read -p "Продолжить? (y/n): " confirm
        [ "$confirm" = "y" ] && do_bump "авто" uv run --frozen cz bump || { log_info "Отменено."; exit 0; }
        ;;
    2)
        read -p "Продолжить? $CURRENT → $PATCH (y/n): " confirm
        [ "$confirm" = "y" ] && do_bump "PATCH" uv run --frozen cz bump --increment PATCH || { log_info "Отменено."; exit 0; }
        ;;
    3)
        read -p "Продолжить? $CURRENT → $MINOR (y/n): " confirm
        [ "$confirm" = "y" ] && do_bump "MINOR" uv run --frozen cz bump --increment MINOR || { log_info "Отменено."; exit 0; }
        ;;
    4)
        read -p "Продолжить? $CURRENT → $MAJOR (y/n): " confirm
        [ "$confirm" = "y" ] && do_bump "MAJOR" uv run --frozen cz bump --increment MAJOR || { log_info "Отменено."; exit 0; }
        ;;
    5)
        read -p "Введи версию (например 1.2.0): " manual_version
        if [[ ! "$manual_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([+-][0-9A-Za-z.-]+)?$ ]]; then
            log_error "Некорректный формат версии: $manual_version"
            exit 1
        fi
        read -p "Продолжить? $CURRENT → $manual_version (y/n): " confirm
        if [ "$confirm" = "y" ]; then
            do_bump "manual $manual_version" uv run --frozen cz bump "$manual_version"
        else
            log_info "Отменено."
            exit 0
        fi
        ;;
    0)
        log_info "Отменено пользователем."
        exit 0
        ;;
    *)
        log_error "Неверный выбор: $choice"
        exit 1
        ;;
esac

# ─── Проверка версий после bump ───────────────────────────────
verify_versions() {
    local expected=$1

    VER_TOML=$(awk '
        /^\[tool\.commitizen\]$/ { in_commitizen = 1; next }
        /^\[/ { in_commitizen = 0 }
        in_commitizen && /^version = / {
            split($0, parts, "\"")
            print parts[2]
            exit
        }
    ' pyproject.toml)
    VER_PY=$(grep '__version__' src/_version.py | head -1 | awk -F'"' '{print $2}')

    log_info "Проверка версий после bump:"
    log_info "  pyproject.toml  → $VER_TOML"
    log_info "  src/_version.py → $VER_PY"

    if [ "$VER_TOML" = "$expected" ] && [ "$VER_PY" = "$expected" ]; then
        log_ok "Версии совпадают: $expected ✅"
    else
        log_error "Версии НЕ совпадают!"
        log_error "  Ожидалось:      $expected"
        log_error "  pyproject.toml: $VER_TOML"
        log_error "  _version.py:    $VER_PY"
        exit 1
    fi
}

NEW_VERSION=$(git describe --tags --exact-match HEAD 2>/dev/null || true)
if [ -z "$NEW_VERSION" ]; then
    log_error "После bump на текущем коммите не найден релизный тег."
    exit 1
fi
verify_versions "$NEW_VERSION"

# ─── Push ─────────────────────────────────────────────────────
log_info "Пушим в remote"
if ! git push origin master; then
    log_error "Не удалось отправить ветку master"
    exit 1
fi
if ! git push origin --tags; then
    log_error "Не удалось отправить релизные теги"
    exit 1
fi

echo ""
log_ok "Релиз готов! Версия: $(git describe --tags)"
log_info "Лог сохранён: $LOG_FILE"
