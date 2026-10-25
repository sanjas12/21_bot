#!/usr/bin/env bash
# Called over SSH by the release workflow. Never removes data/ or .env.
set -euo pipefail
umask 077
export PATH="/root/.local/bin:$PATH"
export GIT_TERMINAL_PROMPT=0

tag=${1:?Release tag required}
revision=${2:?Tested commit required}
[[ "$tag" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "$revision" =~ ^[0-9a-f]{40}$ ]]
cd /root/21_bot
exec 9>/root/21_bot-deploy.lock
flock -n 9 || { echo 'Another deployment is running'; exit 1; }
test -z "$(git status --porcelain)" || { echo 'Working tree is not clean'; exit 1; }
test -f .env
test -f data/calendar.sqlite3
command -v uv >/dev/null
systemctl is-active --quiet 21-bot.service

git fetch --no-tags origin "refs/tags/$tag"
test "$(git rev-parse 'FETCH_HEAD^{commit}')" = "$revision" || {
    echo 'Release tag does not match the tested commit'; exit 1;
}
# Reject releases which could overwrite persistent local files.
test -z "$(git ls-tree -r --name-only "$revision" -- data .env .venv)" || {
    echo 'Release contains persistent local paths'; exit 1;
}
previous=$(git rev-parse HEAD)
mkdir -p /root/21_bot-backups
chmod 700 /root/21_bot-backups
backup=$(mktemp -d /root/21_bot-backups/deploy-XXXXXXXX)
stopped=0
changed=0
recover() {
    result=$?
    trap - EXIT
    if (( result != 0 && stopped )); then
        echo "Deployment failed. Backup: $backup"
        systemctl stop 21-bot.service || true
        if (( changed )); then
            if git checkout --detach "$previous" && uv sync --locked --no-dev; then
                systemctl start 21-bot.service || true
            else
                echo 'Code rollback failed; service left stopped. Manual recovery required.'
            fi
        else
            systemctl start 21-bot.service || true
        fi
        # Do not overwrite live user data automatically after a failed start.
        echo 'Database backup is available for manual recovery if needed.'
    fi
    exit "$result"
}
trap recover EXIT

systemctl stop 21-bot.service
stopped=1
cp -a data "$backup/"
cp -a .env "$backup/"
printf '%s\n' "$previous" > "$backup/previous-commit"
changed=1
git checkout --detach "$revision"
uv sync --locked --no-dev
uv run --locked --no-dev python -m compileall -q src
systemctl start 21-bot.service
pid=$(systemctl show -p MainPID --value 21-bot.service)
restarts=$(systemctl show -p NRestarts --value 21-bot.service)
for attempt in {1..10}; do
    sleep 2
    systemctl is-active --quiet 21-bot.service
    test "$pid" != 0
    test "$(systemctl show -p MainPID --value 21-bot.service)" = "$pid"
    test "$(systemctl show -p NRestarts --value 21-bot.service)" = "$restarts"
done
# Notifications are queued only after the new process passed the health check.
# A notification failure must not roll back a successfully deployed application.
stopped=0
uv run --locked --no-dev python src/release_updates.py "$tag" || {
    echo 'Deployment succeeded, but release notification could not be queued.'
    exit 1
}
echo "Deployed $tag ($revision). Backup: $backup"
