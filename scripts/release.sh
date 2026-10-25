#!/bin/bash

# версия: 0.3

# Сам release.sh автоматически объединять ветки не должен: выпуск релиза и
# решение о переносе изменений в основную ветку лучше оставлять отдельными операциями.
# Использовать только для выпуска готовой версии из основной ветки, когда все
# изменения уже закоммичены и рабочее дерево Git чистое. Запускать в Windows
# из Git Bash командой `bash scripts/release.sh`: скрипт обновляет основную ветку,
# запускает тесты, повышает версию проекта, создаёт коммит и тег,
# а затем публикует GitHub Release. Для обычной разработки не запускать.

# Версия проекта хранится в [project].version; Commitizen не требуется.
# После проверок обновляет docs/CHANGELOG.md, создаёт коммит и тег,
# публикует GitHub Release через gh с тем же разделом изменений.
# Публикация запускает автодеплой. Для работы нужны uv, Git и gh auth login.

set -euo pipefail

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

for tool in uv gh; do
    command -v "$tool" >/dev/null || { log_error "Не найден $tool. Установите его перед выпуском."; exit 1; }
done
gh auth status || { log_error "Выполните gh auth login перед выпуском."; exit 1; }
REPOSITORY=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
git fetch --tags origin

# ─── Выбор основной ветки ────────────────────────────────────
# origin/HEAD определяет приоритет, если существуют обе ветки.
RELEASE_BRANCH=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD || true)
RELEASE_BRANCH=${RELEASE_BRANCH#origin/}
case "$RELEASE_BRANCH" in
    main|master) ;;
    *) RELEASE_BRANCH="" ;;
esac
if [ -z "$RELEASE_BRANCH" ]; then
    for candidate in main master; do
        if git show-ref --verify --quiet "refs/heads/$candidate" ||
           git show-ref --verify --quiet "refs/remotes/origin/$candidate"; then
            RELEASE_BRANCH=$candidate
            break
        fi
    done
fi
if [ -z "$RELEASE_BRANCH" ]; then
    log_error "Не найдена основная ветка main или master (локально или в origin)."
    exit 1
fi
log_info "Ветка релиза: $RELEASE_BRANCH"

# ─── Git: переключаемся на основную ветку ─────────────────────
echo ""
log_info "Переключаемся на $RELEASE_BRANCH"
if ! git checkout "$RELEASE_BRANCH"; then
    log_error "Не удалось переключиться на $RELEASE_BRANCH"
    exit 1
fi

log_info "Получаем изменения с remote"
if ! git pull --ff-only origin "$RELEASE_BRANCH"; then
    log_error "Не удалось выполнить git pull. Проверь подключение к remote."
    exit 1
fi
log_ok "$RELEASE_BRANCH актуальна"

# release.sh не объединяет ветки автоматически, но не должен выпускать
# устаревшую основную ветку, если в локальном develop остались неслитые изменения.
if git show-ref --verify --quiet refs/heads/develop; then
    if ! git merge-base --is-ancestor develop "$RELEASE_BRANCH"; then
        log_error "Ветка develop содержит изменения, которых ещё нет в основную ветку."
        log_error "Релиз из устаревшей $RELEASE_BRANCH отменён. Выполни:"
        log_error "  git checkout $RELEASE_BRANCH"
        log_error "  git merge --ff-only develop"
        log_error "Затем повторно запусти bash scripts/release.sh."
        exit 1
    fi
    log_ok "Все локальные изменения develop уже включены в основную ветку"
elif [ "$START_BRANCH" = "develop" ]; then
    log_error "До переключения была активна develop, но локальная ветка больше не найдена."
    exit 1
else
    log_warn "Локальная ветка develop не найдена — проверка её слияния пропущена."
fi

# ─── Проверка новых коммитов ──────────────────────────────────
# Не выпускаем повторный релиз без новых коммитов.
LAST_RELEASE_TAG=""
while IFS= read -r candidate; do
    if [[ "$candidate" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        LAST_RELEASE_TAG=$candidate
        break
    fi
done < <(git tag --merged HEAD --sort=-version:refname)
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
if ! uv sync --locked --group dev; then
    log_error "Не удалось подготовить окружение для тестов! Релиз отменён."
    exit 1
fi
log_ok "Тестовое окружение готово"

log_info "Проверяем синтаксис Python"
if ! uv run --locked python -m compileall -q src tests; then
    log_error "Синтаксическая проверка не прошла! Релиз отменён."
    exit 1
fi
log_ok "Синтаксис Python проверен"

log_info "Запускаем все тесты из каталога tests"
if ! uv run --locked python -m unittest discover -s tests -v; then
    log_error "Тесты не прошли! Релиз отменён."
    exit 1
fi
log_ok "Все тесты прошли успешно"

log_info "Запускаем pre-commit, включая mypy"
if ! uv run --locked pre-commit run --all-files; then
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

# ─── Выбор версии ────────────────────────────────────────────
CURRENT=$(uv run --locked python scripts/release_version.py current)
PATCH=$(uv run --locked python scripts/release_version.py next patch)
MINOR=$(uv run --locked python scripts/release_version.py next minor)
MAJOR=$(uv run --locked python scripts/release_version.py next major)
echo "Текущая версия: $CURRENT"
echo "1) Авто по коммитам (breaking → major, feat → minor, остальные → patch)"
echo "2) PATCH: $PATCH"
echo "3) MINOR: $MINOR"
echo "4) MAJOR: $MAJOR"
echo "5) Вручную"
echo "0) Отмена"
read -r -p "Выбор (0-5): " choice
case "$choice" in
    1) kind=auto ;;
    2) kind=patch ;;
    3) kind=minor ;;
    4) kind=major ;;
    5) read -r -p "Версия MAJOR.MINOR.PATCH: " kind ;;
    0) exit 0 ;;
    *) log_error "Некорректный выбор"; exit 1 ;;
esac
NEW_VERSION=$(uv run --locked python scripts/release_version.py next "$kind" "$LAST_RELEASE_TAG")
TAG="v$NEW_VERSION"
for candidate in "$TAG" "$NEW_VERSION"; do
    if git show-ref --verify --quiet "refs/tags/$candidate"; then
        log_error "Тег $candidate уже существует. Выберите другую версию."
        exit 1
    fi
done
read -r -p "Выпустить $CURRENT → $NEW_VERSION и запустить автодеплой? (y/n): " confirm
[ "$confirm" = y ] || { log_info "Отменено"; exit 0; }

uv run --locked python scripts/release_version.py write "$NEW_VERSION"
uv run --frozen python scripts/update_changelog.py "$NEW_VERSION" "$LAST_RELEASE_TAG"
uv lock
uv sync --locked --group dev
uv run --locked pre-commit run --all-files
# Include the helper in checks: pre-commit's mypy hook checks only src/.
uv run --locked ruff check scripts/release_version.py scripts/update_changelog.py
uv run --locked python -m unittest discover -s tests -v
test "$(uv run --locked python scripts/release_version.py current)" = "$NEW_VERSION"
git add -- pyproject.toml uv.lock docs/CHANGELOG.md
git commit -m "bump: release $NEW_VERSION"
test -z "$(git status --porcelain)" || { log_error "После коммита остались изменения"; exit 1; }
git tag -a "$TAG" -m "Release $NEW_VERSION"
# Send only this release tag together with the branch; never push unrelated tags.
git push --atomic origin "$RELEASE_BRANCH" "refs/tags/$TAG"
NOTES_FILE=$(mktemp)
trap 'EXIT_CODE=$?; rm -f -- "$NOTES_FILE"; if [ "$EXIT_CODE" -ne 0 ]; then log_error "Ошибка публикации. См. $LOG_FILE"; fi' EXIT
uv run --locked python -c 'import sys; from pathlib import Path; sys.path.insert(0, "src"); from changelog import release_notes; Path(sys.argv[2]).write_text(release_notes(Path("docs/CHANGELOG.md").read_text(encoding="utf-8"), sys.argv[1]), encoding="utf-8")' "$TAG" "$NOTES_FILE"
if ! gh release create "$TAG" --repo "$REPOSITORY" --verify-tag --title "$TAG" --notes-file "$NOTES_FILE"; then
    log_error "Коммит и тег отправлены, но GitHub Release не опубликован."
    log_error "Повторите публикацию через Releases на GitHub, скопировав раздел $NEW_VERSION из docs/CHANGELOG.md. Тег уже отправлен."
    exit 1
fi
log_ok "GitHub Release $TAG опубликован. Автодеплой запущен; результат смотрите в Actions."
log_info "Лог: $LOG_FILE"
