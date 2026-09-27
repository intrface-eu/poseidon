#!/usr/bin/env python3
"""Download the fixed official Lima/Debian pins into a NEW absent project-local cache.

One HTTPS-only bounded attempt per artifact; no retries, resume, overwrite, repair,
VM start, host installation, sudo, or security/signature/quarantine modification.
Failures retain partial downloads and logs. Existing caches, low disk space,
quarantine, checksum/signature failure and unsupported archive entries fail closed.
A downloaded cache is not Linux execution evidence. Use runner.py to run/stop an
owned session; it always checks pins/resources and cleans up in finally.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import subprocess
import sys
import tarfile
import time

sys.dont_write_bytecode = True
from runner import (  # noqa: E402
    ROOT, LIMA_ARCHIVE, LIMA_SHA256, IMAGE_NAME, IMAGE_URL, IMAGE_BYTES,
    IMAGE_SHA512, MIN_FREE, EnvironmentError, Cancelled, digest, host_preflight,
    isolated_environment, owned_local_path, verify_cache, write_new,
)

LIMA_URL = 'https://github.com/lima-vm/lima/releases/download/v2.2.0/' + LIMA_ARCHIVE
PINS = (
    (LIMA_URL, LIMA_ARCHIVE, 37586365, 'sha256', LIMA_SHA256, 300),
    (IMAGE_URL, IMAGE_NAME, IMAGE_BYTES, 'sha512', IMAGE_SHA512, 1200),
)


def fetch(cache: Path, env: dict, pin: tuple) -> None:
    url, name, size, algorithm, expected, deadline = pin
    if shutil.disk_usage(cache).free < MIN_FREE:
        raise EnvironmentError('at least12GiB free required before each download')
    partial = cache / 'downloads' / (name + '.partial')
    destination = cache / 'downloads' / name
    if destination.exists() or partial.exists():
        raise EnvironmentError('download destination already exists; no overwrite/resume')
    record = {'url': url, 'expected_bytes': size, 'algorithm': algorithm,
              'expected_digest': expected, 'timeout_seconds': deadline,
              'attempts': 1, 'exit': None, 'verified': False}
    command = ['/usr/bin/curl', '--disable', '--fail', '--location', '--silent', '--show-error',
               '--proto', '=https', '--proto-redir', '=https', '--noproxy', '*',
               '--connect-timeout', '30', '--max-time', str(deadline), '--max-filesize', str(size),
               '--retry', '0', '--dump-header', str(cache / 'artifacts' / (name + '.headers')),
               '--output', str(partial), url]
    record['command'] = command
    started = time.monotonic()
    try:
        with partial.open('xb'), (cache / 'artifacts' / (name + '.stdout')).open('xb') as stdout, (cache / 'artifacts' / (name + '.stderr')).open('xb') as stderr:
            result = subprocess.run(command, env=env, stdin=subprocess.DEVNULL, stdout=stdout,
                                    stderr=stderr, timeout=deadline + 10)
        record['exit'] = result.returncode
        if result.returncode:
            raise EnvironmentError(f'download exited{result.returncode}; retain partial/logs, no automatic retry')
        record['bytes'] = partial.stat().st_size
        record['actual_digest'] = digest(partial, algorithm)
        if record['bytes'] != size or record['actual_digest'] != expected:
            raise EnvironmentError('download size/checksum differs from fixed official pin')
        partial.rename(destination)
        record['verified'] = True
    except BaseException as exc:
        record['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        record['elapsed_seconds'] = time.monotonic() - started
        record['partial_retained'] = partial.exists()
        write_new(cache / 'artifacts' / (name + '.download.json'), record)


def extract_checked(archive: Path, tools: Path) -> None:
    """Extract verified bytes only; no devices, hard links, escaping links or modes."""
    tools.mkdir(mode=0o700, exist_ok=False)
    with tarfile.open(archive, 'r:gz') as bundle:
        members = bundle.getmembers()
        names = set()
        links = []
        if len(members) > 2000 or sum(m.size for m in members) > 512 * 1024**2:
            raise EnvironmentError('archive entry/expanded-size bound')
        for member in members:
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or '..' in relative.parts or relative in names:
                raise EnvironmentError('unsafe/duplicate archive path')
            names.add(relative)
            if member.isdir():
                continue
            if member.issym():
                target = PurePosixPath(member.linkname)
                resolved = (tools / relative.parent / target).resolve()
                if target.is_absolute() or not resolved.is_relative_to(tools.resolve()):
                    raise EnvironmentError('archive symlink escapes tools')
                links.append((relative, member.linkname))
            elif not member.isfile() or member.mode & 0o7000:
                raise EnvironmentError('archive special entry/privileged mode is forbidden')
        link_names = {name for name, _ in links}
        if any(any(parent in link_names for parent in PurePosixPath(m.name).parents) for m in members):
            raise EnvironmentError('archive entry traverses an archive symlink')
        for member in members:
            path = tools / PurePosixPath(member.name)
            if member.isdir():
                path.mkdir(mode=0o755, parents=True, exist_ok=True)
            elif member.isfile():
                path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                stream = bundle.extractfile(member)
                if stream is None:
                    raise EnvironmentError('unreadable archive entry')
                with stream, path.open('xb') as output:
                    shutil.copyfileobj(stream, output)
                path.chmod(member.mode & 0o777)
        for relative, target in links:
            path = tools / relative
            path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            path.symlink_to(target)


def bootstrap(path: Path) -> dict:
    cache = owned_local_path(ROOT, path)
    if cache.exists():
        raise EnvironmentError('cache must be a NEW absent directory; no overwrite/repair')
    host = host_preflight(ROOT)
    cache.mkdir(mode=0o700, parents=True, exist_ok=False)
    for part in ('downloads', 'artifacts', 'bootstrap-runtime'):
        (cache / part).mkdir(mode=0o700)
    runtime = cache / 'bootstrap-runtime'
    for part in ('home', 'lima', 'tmp'):
        (runtime / part).mkdir(mode=0o700)
    env = isolated_environment(cache, runtime)
    result = {'host': host, 'VM_started': False, 'state': 'failed', 'security_changes': False,
              'helper_sha256': digest(Path(__file__).resolve()), 'checks': []}

    def check(command, timeout=20):
        completed = subprocess.run(command, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                   text=True, timeout=timeout)
        result['checks'].append({'command': command, 'exit': completed.returncode,
                                 'stdout': completed.stdout, 'stderr': completed.stderr})
        if completed.returncode:
            raise EnvironmentError('read-only bootstrap check failed; no host/security repair')
        return completed.stdout

    def quarantine(path):
        if 'com.apple.quarantine' in check(['/usr/bin/xattr', str(path)]).splitlines():
            raise EnvironmentError('quarantine present; no bypass/removal permitted')

    try:
        fetch(cache, env, PINS[0])
        archive = cache / 'downloads' / LIMA_ARCHIVE
        quarantine(archive)
        extract_checked(archive, cache / 'tools')
        limactl = cache / 'tools/bin/limactl'
        quarantine(limactl)
        check(['/usr/bin/codesign', '--verify', '--strict', str(limactl)])
        fetch(cache, env, PINS[1])
        result['pins'] = verify_cache(cache)
        result['state'] = 'verified-cache-only-no-VM-or-ABI-claim'
        return result
    except BaseException as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        write_new(cache / 'artifacts/bootstrap.json', result)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--cache', type=Path, required=True, help='new absent directory below this project\'s .local')
    args = parser.parse_args()
    def interrupted(signum, _frame):
        raise Cancelled(signum)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    try:
        result = bootstrap(args.cache)
        print(result['state'])
        return 0
    except (EnvironmentError, OSError, ValueError, tarfile.TarError, subprocess.SubprocessError) as exc:
        print(f'bootstrap refused/failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
