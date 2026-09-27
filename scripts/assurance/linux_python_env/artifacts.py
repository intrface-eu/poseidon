"""Pinned public artifact transfer/extraction and installed-wheel provenance.

Only download() performs network I/O. Callers run it in the owned guest under
an aggregate deadline. No retry, alternate URL, build or package install exists.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import time
import tomllib
from urllib.parse import unquote, urlparse
import urllib.request
import zipfile

UV_VERSION = "0.12.3"
UV_PIN = {"url": "https://github.com/astral-sh/uv/releases/download/0.12.3/uv-aarch64-unknown-linux-gnu.tar.gz", "sha256": "bb66cb52e7b1823aed1183630d8d8e5c958840d584a4c55ec10a4cfc168dcca2", "size": 20423730}
PYTHON_PINS = {
    "3.11.15": {"key": "cpython-3.11.15-linux-aarch64-gnu", "url": "https://github.com/astral-sh/python-build-standalone/releases/download/20260807/cpython-3.11.15%2B20260807-aarch64-unknown-linux-gnu-install_only_stripped.tar.gz", "sha256": "2290f3a9115ee2cd0928a7fc1f3f918142705fba3efa04dc64ffe6e5bae3245f"},
    "3.12.13": {"key": "cpython-3.12.13-linux-aarch64-gnu", "url": "https://github.com/astral-sh/python-build-standalone/releases/download/20260807/cpython-3.12.13%2B20260807-aarch64-unknown-linux-gnu-install_only_stripped.tar.gz", "sha256": "11e713ae1f969385907a76533cc554f6b2e3f1a84896009f91c3fc871034a170"},
}
PUBLIC_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com", "files.pythonhosted.org"}
MAX_ARTIFACT_BYTES = 256 * 1024**2


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            value.update(block)
    return value.hexdigest()


def public_url(url: str) -> str:
    parts = urlparse(url)
    if parts.scheme != "https" or parts.hostname not in PUBLIC_HOSTS or parts.username or parts.password or parts.port not in (None, 443) or parts.fragment:
        raise ValueError("artifact URL must be an explicit public HTTPS artifact host")
    return url


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        public_url(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


def download(pin: dict, target: Path, *, deadline: int = 300) -> dict:
    public_url(pin["url"])
    if not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]):
        raise ValueError("artifact needs an explicit SHA256 pin")
    if target.exists() or target.is_symlink() or target.parent.resolve() != target.parent:
        raise ValueError("download target must be new and not traverse symlinks")
    if not 1 <= deadline <= 600:
        raise ValueError("artifact download needs a bounded deadline")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), PublicRedirect())
    request = urllib.request.Request(pin["url"], headers={"User-Agent": "poseidon-assurance-tranche3"})
    started = time.monotonic()
    total = 0
    digest = hashlib.sha256()
    # One request only, no resume/retry. A failed partial artifact stays owned.
    with opener.open(request, timeout=min(30, deadline)) as response, target.open("xb") as output:
        public_url(response.geturl())
        if response.status != 200:
            raise ValueError("artifact server did not return200")
        while True:
            if time.monotonic() - started > deadline:
                raise TimeoutError("artifact download deadline exceeded")
            block = response.read(1024**2)
            if not block:
                break
            total += len(block)
            if total > MAX_ARTIFACT_BYTES or ("size" in pin and total > pin["size"]):
                raise ValueError("artifact exceeds pinned size/bound")
            output.write(block)
            digest.update(block)
    if digest.hexdigest() != pin["sha256"] or ("size" in pin and total != pin["size"]):
        raise ValueError("download does not match pinned SHA256/size")
    return {"url": pin["url"], "sha256": digest.hexdigest(), "size": total, "file": str(target), "elapsed_seconds": time.monotonic() - started}


def relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or str(path) != name or "\\" in name:
        raise ValueError("escaping/noncanonical archive path")
    return path


def extract(archive: Path, expected_hash: str, destination: Path, *, prefix: str) -> dict:
    """Extract pinned tool distributions; bounded, no devices or escaping links."""
    if sha256(archive) != expected_hash:
        raise ValueError("refusing extraction before artifact hash verification")
    if destination.exists() or destination.is_symlink() or destination.parent.resolve() != destination.parent:
        raise ValueError("extraction destination must be new with regular parents")
    expected_prefix = relative(prefix)
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if not 1 <= len(members) <= 100000 or sum(m.size for m in members) > 2 * 1024**3:
            raise ValueError("tool archive exceeds extraction bounds")
        seen = set()
        links = set()
        for member in members:
            name = relative(member.name.rstrip("/"))
            if name.parts[:len(expected_prefix.parts)] != expected_prefix.parts:
                raise ValueError("artifact has an unexpected top-level directory")
            if member.name.rstrip("/") in seen or not (member.isfile() or member.isdir() or member.issym()):
                raise ValueError("duplicate, device or unsupported artifact member")
            if member.mode & 0o6000:
                raise ValueError("setuid/setgid artifact member is forbidden")
            seen.add(member.name.rstrip("/"))
            if member.issym():
                target = PurePosixPath(member.linkname)
                if target.is_absolute():
                    raise ValueError("absolute tool symlink forbidden")
                # Resolve link components lexically without consulting host paths.
                parts = list(name.parent.parts)
                for part in target.parts:
                    if part == "..":
                        if len(parts) <= len(expected_prefix.parts):
                            raise ValueError("tool link escapes the distribution")
                        parts.pop()
                    elif part != ".":
                        parts.append(part)
                links.add(name)
        for member in members:
            if any(parent in links for parent in relative(member.name.rstrip("/")).parents):
                raise ValueError("archive writes through a symlink ancestor")
        destination.mkdir(mode=0o700)
        # Prefix stays inside destination: no rename, global install or PATH edit.
        bundle.extractall(destination, filter="data")
    root = destination / prefix
    return {"archive_sha256": expected_hash, "root": str(root), "members": len(members)}


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def filename_tags(filename: str) -> set[str]:
    if not filename.endswith(".whl"):
        raise ValueError("third-party source distribution is forbidden")
    _, python, abi, platforms = filename[:-4].rsplit("-", 3)
    return {f"{p}-{a}-{s}" for p in python.split(".") for a in abi.split(".") for s in platforms.split(".")}


def lock_wheel(lock: dict, installed: dict) -> dict:
    """Match the actual installed WHEEL tags to one exact locked artifact."""
    packages = [p for p in lock["package"] if normalize(p["name"]) == normalize(installed["name"]) and p["version"] == installed["version"]]
    if len(packages) != 1 or "registry" not in packages[0].get("source", {}):
        raise ValueError("installed third-party distribution is not one exact registry lock entry")
    tags = set(installed["tags"])
    matches = []
    for wheel in packages[0].get("wheels", []):
        name = unquote(PurePosixPath(urlparse(wheel["url"]).path).name)
        if filename_tags(name) == tags:
            matches.append(wheel | {"filename": name})
    if len(matches) != 1:
        raise ValueError("installed WHEEL tags do not select one exact locked wheel; no fallback")
    selected = matches[0]
    public_url(selected["url"])
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", selected["hash"]):
        raise ValueError("locked wheel lacks SHA256")
    return selected


def wheel_payload(archive: Path, installed: dict) -> dict:
    """Verify retained wheel payload against actual installed package bytes.

    Entry-point scripts and installation RECORD are installer-generated and are
    reported separately, not misrepresented as byte-identical archive files.
    """
    base = Path(installed["site_packages"])
    if not base.is_absolute() or base.resolve() != base:
        raise ValueError("installed package root must be a regular absolute path")
    checked = []
    generated = []
    with zipfile.ZipFile(archive) as wheel:
        names = wheel.namelist()
        if len(names) != len(set(names)) or len(names) > 100000 or sum(i.file_size for i in wheel.infolist()) > 512 * 1024**2:
            raise ValueError("wheel has duplicate/oversized members")
        records = [name for name in names if name.endswith(".dist-info/RECORD")]
        if len(records) != 1:
            raise ValueError("wheel needs one RECORD")
        for name in names:
            relative(name.rstrip("/"))
            if stat.S_ISLNK(wheel.getinfo(name).external_attr >> 16):
                raise ValueError("wheel symlink member forbidden")
        rows = list(csv.reader(io.StringIO(wheel.read(records[0]).decode())))
        declared = set()
        for name, encoded_hash, size in rows:
            path = relative(name)
            if name in declared or name not in names:
                raise ValueError("wheel RECORD duplicate/missing entry")
            declared.add(name)
            raw = wheel.read(name)
            if name == records[0]:
                generated.append(name)
                continue
            if not encoded_hash.startswith("sha256=") or not size.isdecimal() or len(raw) != int(size):
                raise ValueError("wheel RECORD needs exact SHA256/size")
            expected = encoded_hash.removeprefix("sha256=")
            if base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=") != expected:
                raise ValueError("wheel RECORD payload hash mismatch")
            if path.parts[0].endswith(".data"):
                # Do not silently bless path remapping or source-generated scripts.
                if len(path.parts) < 3 or path.parts[1] not in {"purelib", "platlib"}:
                    raise ValueError("wheel data/scripts layout needs explicit review; lane cannot be qualified")
                path = PurePosixPath(*path.parts[2:])
            target = base / path
            if target.resolve() != target or not target.is_file() or sha256(target) != hashlib.sha256(raw).hexdigest():
                raise ValueError(f"installed package differs from retained wheel: {name}")
            checked.append(name)
        if {name for name in names if not name.endswith("/")} != declared:
            raise ValueError("wheel contains undeclared payload")
    return {"checked_payload_files": len(checked), "installer_generated_records": generated,
            "payload_sha256_verified": True}


# Run in the selected managed interpreter, not the Debian controller interpreter.
INSTALLED_QUERY = '''import importlib.metadata as m,json,sys
items=[]
for d in m.distributions():
 w=d.read_text("WHEEL")
 if w is None: raise RuntimeError("installed distribution lacks WHEEL: "+d.metadata["Name"])
 items.append({"name":d.metadata["Name"],"version":d.version,"tags":[l[5:] for l in w.splitlines() if l.startswith("Tag: ")],"site_packages":str(d.locate_file("").resolve())})
print(json.dumps({"python":list(sys.version_info[:3]),"executable":sys.executable,"distributions":sorted(items,key=lambda x:x["name"].lower())},sort_keys=True))
'''
