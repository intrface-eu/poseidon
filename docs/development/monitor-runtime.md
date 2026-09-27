# Local monitor runtime

This starts the local monitor API and operator UI for one operator on the same machine. Both services bind to `127.0.0.1`. The workspace key creates a local single-operator session; it is not production authentication, multi-user access control, or Internet hosting.

## Setup

Install Python 3.11, [uv](https://docs.astral.sh/uv/), Bun, and Make. From the repository root, install the locked dependencies:

```sh
make setup
```

`UV_PYTHON` selects the interpreter for the API environment when needed:

```sh
make setup UV_PYTHON=3.11
```

## Start and log in

Start the API and Next development server:

```sh
make dev
```

To serve the already built Next bundle on the same loopback boundary:

```sh
make build-ui
make serve
```

`make serve` is local built-bundle verification. It is not production readiness or an external deployment. Both modes wait for API and UI readiness, then print the local UI URL, API health URL, and token-file path. They do not print the token. The default workspace is `.local/monitor` and its access file is `.local/monitor/access.token`.

`--ui-mode dev` is the default and runs `bun run dev`; `--ui-mode production` runs `bun run start` and requires `make build-ui` first. To use another workspace or ports:

```sh
python3 scripts/dev.py start --ui-mode dev --data-dir .local/monitor-demo --api-port 8181 --ui-port 3100 --readiness-timeout 30
```

The launcher checks both loopback ports before starting. If either belongs to another process, it exits without stopping that process.

Open the printed UI URL. In a separate terminal, request the local token only when you need to enter it:

```sh
python3 scripts/dev.py token --data-dir .local/monitor
```

The helper reads only `access.token`, rejects missing or symlinked paths, and requires that group and other users cannot read the file.

## Shutdown

Press `Ctrl-C` in the terminal running `make dev`. The manager sends a graceful stop to only the API and UI process groups it launched, waits briefly, then uses a bounded forced stop if needed. It does not daemonize services or stop unrelated processes.

## Tests

After setup:

```sh
make check
make test
make build-ui
```

`make test-python` runs the standard-library Python suites without API or UI dependency commands. Browser checks, when present, run only as bounded local tests and must close their browser process.
