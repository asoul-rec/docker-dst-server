#!/bin/bash
set -Eeuo pipefail
export LC_ALL=C.UTF-8

if ! status="$(supervisorctl -c /etc/supervisor/supervisor.conf status)"; then
    printf '%s\n' "${status}" >&2
    exit 1
fi

# Both configured shards must have completed Supervisor's startup period.
printf '%s\n' "${status}" | awk '
    $1 == "dst-server:dst-server-master" && $2 == "RUNNING" { master = 1 }
    $1 == "dst-server:dst-server-cave" && $2 == "RUNNING" { caves = 1 }
    END { exit !(NR == 2 && master && caves) }
'
