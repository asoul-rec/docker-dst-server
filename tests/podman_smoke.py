#!/usr/bin/env python3
"""Exercise the real container lifecycle with deterministic game/Steam fixtures.

No Klei token or Steam connection is needed. This checks container orchestration;
it does not claim to test game downloads, Workshop, or public matchmaking.
"""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


IMAGE = sys.argv[1] if len(sys.argv) > 1 else "localhost/dst-server:modernized"
NAME = f"dst-smoke-{uuid.uuid4().hex[:10]}"
ROOT = Path(tempfile.mkdtemp(prefix="dst-smoke-"))
ROOT.chmod(0o755)
FIXTURES = ROOT / "fixtures"
FIXTURES.mkdir()


def podman(*args, check=True):
    result = subprocess.run(
        ["podman", *map(str, args)], text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    if check and result.returncode:
        raise RuntimeError(f"podman {args[0]} failed ({result.returncode}):\n{result.stdout}")
    return result


def expect_failure(result, message):
    assert result.returncode != 0, result.stdout
    assert message in result.stdout, result.stdout


def wait_healthy():
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if podman("exec", NAME, "healthcheck.sh", check=False).returncode == 0:
            return
        time.sleep(0.5)
    raise AssertionError(podman("logs", NAME).stdout)


# The fixture refuses root, writes to the persisted mods folder during mod
# updates, and records the exact shutdown signal for each supervised shard.
(FIXTURES / "game").write_text('''#!/usr/bin/python3
import os
from pathlib import Path
import signal
import sys

if "-version" in sys.argv:
    print(Path(__file__).resolve().parent.name)
    sys.exit(0)
assert os.geteuid() != 0, "game must run as the unprivileged user"
if "-only_update_server_mods" in sys.argv:
    Path("/data/DoNotStarveTogether/Cluster_1/mods/.update-ok").write_text(str(os.geteuid()))
    sys.exit(0)
shard = sys.argv[sys.argv.index("-shard") + 1]
def shutdown(signum, _frame):
    Path("/data/shutdown-" + shard).write_text(signal.Signals(signum).name)
    sys.exit(0)
signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)
while True:
    signal.pause()
''')
(FIXTURES / "steamcmd").write_text('''#!/bin/sh
exit "${TEST_STEAM_EXIT_CODE:-0}"
''')
for fixture in FIXTURES.iterdir():
    fixture.chmod(0o755)

SETUP = '''
set -eu
install -D -m 0755 /test-fixtures/game /opt/dst_server/bin64/dontstarve_dedicated_server_nullrenderer_x64
install -D -m 0755 /test-fixtures/game /opt/dst_server/bin/dontstarve_dedicated_server_nullrenderer
mkdir -p /opt/dst_server/mods
cp -a /opt/dst_default_config/DoNotStarveTogether/Cluster_1/mods/. /opt/dst_server/mods/
# Shorten only the fixture's startup wait; production keeps 40 seconds.
sed -i 's/startsecs=40/startsecs=2/g' /etc/supervisor/supervisor.conf
exec entrypoint.sh "$@"
'''
COMMAND = [IMAGE, "-c", SETUP, "--", "supervisord", "-c", "/etc/supervisor/supervisor.conf", "-n"]


def fixture_run(data, *options, detach=False):
    data.mkdir(exist_ok=True)
    args = ["run", "-v", f"{data}:/data:Z", "-v", f"{FIXTURES}:/test-fixtures:ro,Z",
            "-e", "STEAMCMD_PATH=/test-fixtures/steamcmd", "--entrypoint", "bash"]
    args += ["-d", "--name", NAME] if detach else ["--rm"]
    return podman(*args, *options, *COMMAND, check=False)


try:
    info = json.loads(podman("info", "--format", "json").stdout)
    print(f"Podman rootless: {info['host']['security']['rootless']}", flush=True)
    result = podman("run", "--rm", IMAGE, "getconf", "GNU_LIBC_VERSION")
    assert result.stdout.strip() == "glibc 2.41", result.stdout
    print(result.stdout.strip(), flush=True)

    # Previously an unavailable supervisorctl/socket could report healthy.
    assert podman("run", "--rm", IMAGE, "healthcheck.sh", check=False).returncode != 0
    result = fixture_run(ROOT / "missing-token")
    expect_failure(result, "Please fill in")
    assert "Updating server" not in result.stdout
    print("PASS: missing token and missing Supervisor fail before startup", flush=True)

    result = fixture_run(ROOT / "blank-token", "-e", "DST_CLUSTER_TOKEN=\r\n")
    expect_failure(result, "Cluster token must not be empty")
    result = fixture_run(ROOT / "bad-flag", "-e", "DST_UPDATE_ON_START=invalid")
    expect_failure(result, "must be 0 or 1")
    result = fixture_run(ROOT / "steam-failure", "-e", "DST_CLUSTER_TOKEN=fixture-token",
                         "-e", "TEST_STEAM_EXIT_CODE=23")
    assert result.returncode == 23, result.stdout
    print("PASS: invalid configuration and Steam update failures are rejected", flush=True)

    for arch, expected in [("amd64", "bin64"), ("x86", "bin"), ("invalid", None)]:
        result = podman("run", "--rm", "-v", f"{FIXTURES}:/test-fixtures:ro,Z",
                        "-e", f"DST_SERVER_ARCH={arch}", "--entrypoint", "bash", IMAGE,
                        "-c", SETUP.replace('exec entrypoint.sh "$@"', 'exec "$@"'), "--",
                        "dontstarve_dedicated_server_nullrenderer", "-version", check=False)
        if expected:
            assert result.returncode == 0 and result.stdout.strip() == expected, result.stdout
        else:
            expect_failure(result, "unknown architecture")
    print("PASS: architecture wrappers select amd64/x86 and reject unknown values", flush=True)

    data = ROOT / "running"
    shutil.copytree(Path(__file__).resolve().parents[1] / "dst_default_config", data)
    shutil.rmtree(data / "DoNotStarveTogether/Cluster_1/mods")
    result = fixture_run(data, "-e", "DST_CLUSTER_TOKEN=fixture-token\r\n", detach=True)
    assert result.returncode == 0, result.stdout
    assert podman("exec", NAME, "healthcheck.sh", check=False).returncode != 0
    wait_healthy()
    podman("healthcheck", "run", NAME)
    state = json.loads(podman("inspect", NAME).stdout)[0]["State"]
    assert state["Health"]["Status"] == "healthy", state
    cluster = data / "DoNotStarveTogether/Cluster_1"
    assert (cluster / "cluster_token.txt").read_bytes() == b"fixture-token"
    assert int((cluster / "mods/.update-ok").read_text()) > 0
    assert podman("exec", NAME, "readlink", "/opt/dst_server/mods").stdout.strip() == "/data/DoNotStarveTogether/Cluster_1/mods"
    print("PASS: token normalization, writable mods, both unprivileged shards and health", flush=True)

    podman("exec", NAME, "supervisorctl", "-c", "/etc/supervisor/supervisor.conf", "stop", "dst-server:dst-server-cave")
    assert podman("exec", NAME, "healthcheck.sh", check=False).returncode != 0
    print("PASS: health fails when one shard stops", flush=True)

    podman("restart", "--time", "30", NAME)
    wait_healthy()
    assert (cluster / "cluster_token.txt").read_bytes() == b"fixture-token"
    assert (cluster / "mods/.update-ok").exists()
    print("PASS: restart preserves configuration and the persisted mods symlink", flush=True)

    podman("stop", "--time", "30", NAME)
    state = json.loads(podman("inspect", NAME).stdout)[0]["State"]
    assert state["ExitCode"] == 0, state
    for shard in ["Master", "Caves"]:
        assert (data / f"shutdown-{shard}").read_text() == "SIGINT"
    print("PASS: podman stop sends SIGINT to both shards and exits cleanly", flush=True)

    podman("rm", NAME)
    offline_data = ROOT / "skip-updates"
    result = fixture_run(offline_data, "-e", "DST_CLUSTER_TOKEN=fixture-token",
                         "-e", "TEST_STEAM_EXIT_CODE=23", "-e", "DST_UPDATE_ON_START=0",
                         "-e", "DST_UPDATE_MODS_ON_START=0", detach=True)
    assert result.returncode == 0, result.stdout
    wait_healthy()
    assert "Updating server" not in podman("logs", NAME).stdout
    assert not (offline_data / "DoNotStarveTogether/Cluster_1/mods/.update-ok").exists()
    podman("stop", "--time", "30", NAME)
    print("PASS: disabling startup updates works with an unavailable Steam service", flush=True)
    print("All container smoke checks passed (fixture game; no online game assertion).", flush=True)
except BaseException:
    print(podman("logs", NAME, check=False).stdout, file=sys.stderr)
    raise
finally:
    podman("rm", "-f", NAME, check=False)
    # Container-owned bind mounts can belong to subordinate rootless UIDs.
    podman("unshare", "rm", "-rf", "--", ROOT, check=False)
