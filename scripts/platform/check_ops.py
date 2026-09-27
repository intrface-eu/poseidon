"""Static configuration checks only; does not run Docker or contact services."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "ops/compose"


def check():
    config = json.loads((COMPOSE / "compose.json").read_text())
    services = config["services"]
    if set(services) != {"postgres", "redis", "mosquitto", "chirpstack"}:
        raise ValueError("unexpected operations service set")
    for name, service in services.items():
        if not re.fullmatch(r"[^:]+:\d+\.\d+(?:\.\d+)?(?:-[a-z0-9]+)?", service["image"]):
            raise ValueError(f"{name}: image tag is not a fixed version")
        if service.get("restart") != "no" or service.get("privileged") or service.get("network_mode") == "host":
            raise ValueError(f"{name}: autonomous or privileged services are not approved")
        if any(not port.startswith("127.0.0.1:") for port in service.get("ports", [])):
            raise ValueError(f"{name}: non-loopback host publication")
        if service["networks"] != ["services"]:
            raise ValueError(f"{name}: unexpected network access")
        if "max-size" not in service["logging"]["options"]:
            raise ValueError(f"{name}: logs are unbounded")
    if config["networks"] != {"services": {"internal": True}}:
        raise ValueError("network must be isolated")
    broker = (COMPOSE / "mosquitto.conf").read_text()
    for required in ("allow_anonymous false", "message_size_limit 16384", "password_file", "cafile", "certfile", "keyfile", "max_queued_messages 1000"):
        if required not in broker:
            raise ValueError("broker authentication, TLS or queue bound is absent")
    acl = (COMPOSE / "mosquitto.acl").read_text()
    if "topic write #" in acl or "topic readwrite" in acl or "/command/" in acl:
        raise ValueError("unexpected broad command/write ACL")
    for file in ("chirpstack.toml.example", "region_eu868.toml.example"):
        tomllib.loads((COMPOSE / file).read_text())
    if "REPLACE_WITH_PRIVATE_REDIS_PASSWORD" not in (COMPOSE / "redis.conf.example").read_text():
        raise ValueError("Redis template must not contain a usable default credential")
    return {"state": "static_checks_passed", "services": len(services), "docker_executed": False,
            "remaining": ["container schema/runtime validation", "image digest/architecture/security review", "private credentials/certificates", "real network-server/gateway test"]}


if __name__ == "__main__":
    print(json.dumps(check(), indent=2))
