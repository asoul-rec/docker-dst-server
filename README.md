# Don't Starve Together Dedicated Server Docker Image

Don't Starve Together dedicated server with a persistent cluster, Master and Caves
shards, automatic game/mod updates, and Supervisor process management.

Please read the whole document before putting your hands on your server. 

This fork builds on Debian 13 (`trixie-slim`, glibc 2.41), runs the 64-bit server
by default, and includes the 32-bit libraries needed by SteamCMD and the optional
`DST_SERVER_ARCH=x86` game binary. Build locally or use the GHCR images published
by this repository's CI.

----------

## Versioning

* The default build (`DST_DOWNLOAD=1`) includes the game files. A failed game
  download fails the build.
* `--build-arg DST_DOWNLOAD=0` builds a smaller image containing SteamCMD and the
  runtime libraries. The game downloads on first startup. Mount a volume at
  `/opt/dst_server` to keep that download across container replacements.
* Both builds update the game and mods on startup by default. To use an existing
  installation without contacting Steam for updates, set `DST_UPDATE_ON_START=0`
  and `DST_UPDATE_MODS_ON_START=0`. This does not put the game itself into offline
  mode; that is controlled by `offline_cluster` in `cluster.ini`.

The historical `jamesits/dst-server` tags belong to the original upstream
publisher and do not contain this fork's changes. The supplied Compose file now
builds this checkout and uses `localhost/dst-server:latest`.
Compose defaults to the slim build and caches the game in its `dst-game` named
volume. Set `DST_DOWNLOAD=1` to embed the game in the image instead.

CI publishes to `ghcr.io/<owner>/<repository>` using the current repository's
lowercase name. For this repository, the image is
`ghcr.io/asoul-rec/docker-dst-server`:

| Tag | Contents |
| --- | --- |
| `latest`, `slim` | Tested slim image from the default branch. |
| `sha-<commit>` | Slim image tagged with the full Git commit SHA. |
| `full`, `full-sha-<commit>` | Image with game files, published when a manual workflow run on the default branch enables `download_game`. |

After a successful publishing workflow, pull the slim image with:

```shell
podman pull ghcr.io/asoul-rec/docker-dst-server:slim
```

Use that image instead of `localhost/dst-server:latest` in the `podman run`
example below, or set `DST_IMAGE` to the GHCR reference in `.env` and run
`podman compose pull` followed by `podman compose up -d --no-build`.
GHCR initially creates private packages; set the package visibility to public
for anonymous pulls, or authenticate to access a private package. See
[GitHub's Container registry documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

## Features and scope

| Capability | Configuration / behavior |
| --- | --- |
| Ground and caves | Supervisor runs `Master` and `Caves` in one container, under an unprivileged game user. |
| Persistent saves | `/data/DoNotStarveTogether/Cluster_1` holds settings, saves, logs, tokens and mod configuration; `/data/ugc` holds Workshop content. |
| Initial configuration | Copies defaults when `Cluster_1` is absent; accepts a token file or `DST_CLUSTER_TOKEN`. |
| Game and Workshop updates | SteamCMD anonymously installs app `343050`; the game updates mods before launching both shards. |
| Mod collections | Add `ServerModSetup` / `ServerModCollectionSetup` calls in `mods/dedicated_server_mods_setup.lua`, and enable mods in each shard's `modoverrides.lua`. |
| World and access settings | `cluster.ini`, per-shard `worldgenoverride.lua`, `adminlist.txt`, `blocklist.txt`, `whitelist.txt`. |
| Process supervision | Restarts unexpected game exits, exposes stdout/stderr, and checks that both shards are `RUNNING`. |
| Graceful shutdown | Supervisor sends SIGINT to both shards and allows up to 300 seconds for saving. |

The bundled defaults enable Endless mode, PvP, 64 player slots, pause when empty,
and six save snapshots. Adjust these for your hardware and intended gameplay.
This image manages one fixed `Cluster_1` with two shards. It does not include a
web panel, scheduled updates/backups, automatic cluster scaling, or native ARM
support. Health checks test processes, not Klei authentication or public reachability.

## Running

### Prerequisites

 * Linux x86_64 with Podman or Docker. ARM requires external x86 emulation and is not tested.
 * You may need a public IP to make your server accessable from Internet. 
 * You need 4 UDP ports exposed to the public network. (See FAQ for details.)
 * CPU: 1 core is somewhat enough for a small-scale server (but don't try 60 ticks, start from 15 or 30).
 * Memory: budget for both shards and world generation, with extra headroom for mods and players. Monitor the real workload with `podman stats`; a small idle cluster does not establish the capacity for 64 active players.
 * Disk: allow space for the runtime image, several GB of game files, Workshop downloads, saves and build layers. Do not use the old 1.5 GiB image estimate for current game versions.

### Start server

Build and run with rootless Podman (named volumes avoid bind-mount ownership setup):

```shell
podman build --format docker --build-arg DST_DOWNLOAD=0 -t localhost/dst-server:latest .
podman volume create dst-data
podman volume create dst-game
podman run -d --name dst-server --stop-timeout 360 \
  -v dst-data:/data -v dst-game:/opt/dst_server \
  -p 10999-11000:10999-11000/udp -p 12346-12347:12346-12347/udp \
  --env-file .env localhost/dst-server:latest
podman logs -f dst-server
```

Before running, copy `.env.example` to `.env` and fill in `DST_CLUSTER_TOKEN`, or
provide `DoNotStarveTogether/Cluster_1/cluster_token.txt` inside the data volume.
You can inspect or edit rootless volume files with `podman unshare`.

For Compose, install a Compose provider (`podman-compose` or Docker Compose),
then run `podman compose up --build -d`. Docker users can run
`docker compose up --build -d`. The Compose example stores saves under `./data`
(override `DST_DATA_DIR` in `.env` to reuse your old data directory). A host path
that contains `Cluster_1` directly must instead be mounted at
`/data/DoNotStarveTogether`; `/data` contains the additional `DoNotStarveTogether`
directory. The `:Z` mount option supports private SELinux labeling on Linux.

The Compose file preserves game downloads in its `dst-game` volume across
container replacements. Do not remove that volume when you only want to rebuild
the runtime image. Saves are kept separately under `DST_DATA_DIR`.

### Stop server

Run `podman stop --time 360 dst-server` (or `docker stop --time 360 dst-server`).
Supervisor forwards SIGINT to each game process to allow saving. The Compose
file already sets a six-minute grace period. Allow up to five minutes for large
worlds to finish saving.
 
## Server Configuration

If you don't already have a set of server config in your data directory, we will generate one for you. Start server once using the command above, and you will see:
```
Creating default server config...
Please fill in `DoNotStarveTogether/Cluster_1/cluster_token.txt` with your cluster token and restart server!
```

Generate a server token from your [Klei account](https://accounts.klei.com/),
under the Don't Starve Together server section.

The token looks like `pds-g^aaaaaaaaa-q^jaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa=`. Then either set `DST_CLUSTER_TOKEN` environment variable during `docker run`, or paste the token into `your_data_directory/DoNotStarveTogether/Cluster_1/cluster_token.txt`.

If you need to add mods, change world generation config, etc., please do it now. Don't forget to edit `your_data_directory/DoNotStarveTogether/Cluster_1/cluster.ini` and get your server an unique name!

After you finish this, re-run start server command, and the server should be running.

## Build Docker image locally

Build this checkout to include this fork's updated runtime:

```shell
git clone https://github.com/asoul-rec/docker-dst-server.git docker-dst-server
cd docker-dst-server
podman build --format docker -t localhost/dst-server:latest .
# Smaller build, without downloading the game at build time:
podman build --format docker --build-arg DST_DOWNLOAD=0 -t localhost/dst-server:slim .
```

There are some arguments you can set via `--build-arg`:

* `BASE_IMAGE`: the `FROM` image (default `docker.io/library/debian:trixie-slim`; dependencies target Debian 13)
* `STEAMCMD_PATH`: where is `steamcmd.sh` in the base image
* `DST_DOWNLOAD`: set to `1` to embed DST server into the image
* `DST_USER`: the user to run server as (inside container)
* `DST_GROUP`: the group to run server as (inside container)

Runtime environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DST_CLUSTER_TOKEN` | empty | Optional alternative to a populated token file. Empty or newline-only tokens fail startup before downloading. |
| `DST_SERVER_ARCH` | `amd64` | Game binary selection: `amd64` or `x86`; SteamCMD remains 32-bit. |
| `DST_UPDATE_ON_START` | `1` | Set to `0` to skip the startup game update; game files must already exist. |
| `DST_UPDATE_MODS_ON_START` | `1` | Set to `0` to skip the startup Workshop update; needed mods must already exist. |

## Validation and CI

```shell
python3 tests/podman_smoke.py localhost/dst-server:slim
```

The smoke test uses the real container scripts and Supervisor with small fake
game/Steam executables. It checks tokens, failed updates, architecture selection,
mod ownership, health transitions, restart persistence and SIGINT shutdown. It
does not test the actual game, Steam downloads, Workshop or public connections.
Use a valid Klei token and a real game client for online acceptance testing.

GitHub Actions builds the slim image and runs ShellCheck and these Podman tests
on pushes, pull requests and a weekly schedule. Manual runs can also build the
full image. After successful builds and tests on the default branch, CI pushes
the built images directly to GHCR using `GITHUB_TOKEN` with `packages: write`.
Pull requests and other branches only build and test; they do not log in or
publish. Authentication is stored in a temporary file and removed even if a
step fails. No personal access token or Docker Hub credentials are needed.
The old Azure/DaoCloud jobs referencing the original publisher's credentials
have been removed.


## Known Issues

 * On Docker environment which doesn't support UDP port forwarding, LAN only server cannot be used. (Still you can enable Steam punchthrough and search for your server in `Online` catalog. )
 * Docker IPv6 support is another sh\*t and we currently don't have any idea on it. Help and advices are always welcomed. (see [#7](https://github.com/Jamesits/docker-dst-server/issues/7).)

## FAQ

#### How to update server or mods?

Restart the server. Updates will be downloaded automatically.

#### How to connect to a LAN only server?

Run `c_connect("IP address", port)` or `c_connect("IP address", port, "password")` in client console.

#### How to check if the server is online?

You can try the 3rd party website [Don't Starve Together Server List](https://dstserverlist.appspot.com).

#### What port does this server require?

You need to expose UDP 10999 (master) and 11000 (caves) for client to connect; udp 12346 and 12347 for steam connection. Don't NAT these ports to different port numbers.

The server use another 2 high UDP ports for unknown communication, and UDP 10998 (listen on localhost) for communication between cluster servers.

Here is a `netstat -tulpn` output on our test server:
```
Proto Recv-Q Send-Q Local Address           Foreign Address         State       PID/Program name    
udp        0      0 0.0.0.0:12346           0.0.0.0:*                           54/./dontstarve_ded 
udp        0      0 0.0.0.0:12347           0.0.0.0:*                           53/./dontstarve_ded 
udp        0      0 0.0.0.0:38223           0.0.0.0:*                           53/./dontstarve_ded 
udp        0      0 0.0.0.0:36517           0.0.0.0:*                           54/./dontstarve_ded 
udp        0      0 127.0.0.1:10998         0.0.0.0:*                           54/./dontstarve_ded 
udp        0      0 0.0.0.0:10999           0.0.0.0:*                           54/./dontstarve_ded 
udp        0      0 0.0.0.0:11000           0.0.0.0:*                           53/./dontstarve_ded 
```

#### Error! App '343050' state is 0x202 after update job.

Your disk is full.

#### Error! App '343050' state is 0x602 after update job.

Usually there is a file system permission issue preventing steamcmd from writing to your game installation directory.

#### Client high latency or lagging

Possible causes:

* High packet drop rate
* High server tick rate with low-performance clients (e.g. notebook users with tick rate 60) 

#### How can I copy local data to server?

Local data is stored in `<User Documents>\Klei\DoNotStarveTogether\<Random Number>`.

There are two situations:
1. Local data has cave enabled.\
Just copy the `Cluster_X` to server and rename to `Cluster_1`, then it should work.
2. Local data has no cave.\
Copy everything in `client_save` except `session` and `Cluster_X/save/session` to server `Cluster_1/save`.\
If your local data is not in slot 1, you also have to modify `saveindex` because the server recognize only the first slot.\
The server will create a cave for you. If you don't want the cave, you have to modify `supervisor.conf` to disable cave server.

#### How can I enable mods after copy local data to server?

Open `Cluster_X/Master/modoverrides.lua` and you will see something like `workshop-XXXXX` where `XXXXX` is a number.\
Open `Cluster_1/mods/dedicated_server_mods_setup.lua` on server and write `ServerModSetup("XXXXX")`.

## Maintainer

 * [James Swineson](https://swineson.me)
 
## Thanks

 * [Mingye Wang](https://github.com/Arthur2e5)
 * [@MephistoMMM](https://github.com/MephistoMMM)
 * [@m13253](https://github.com/m13253)
 * [@wph95](https://github.com/wph95)
 * [DaoCloud](https://daocloud.io)
 * [CodeVS](http://codevs.cn/)
 * [I Choose Death Too](https://steamcommunity.com/id/ichoosedeathtoo/)
 
## License

    Don't Starve Together Dedicated Server Docker Image
    Copyright (C) 2015-2018 James Swineson (Jamesits) and Mingye Wang (Arthur2e5)

    This program is free software; you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation; either version 2 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License along
    with this program; if not, write to the Free Software Foundation, Inc.,
    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

## References

 * [How to setup dedicated server with cave on Linux](https://steamcommunity.com/sharedfiles/filedetails/?id=590565473)
 * [How to install,configure and update mods on Dedicated Server](https://steamcommunity.com/sharedfiles/filedetails/?id=591543858)
 * [SteamCMD](https://developer.valvesoftware.com/wiki/SteamCMD)
