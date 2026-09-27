"""Static assets only; these checks never launch Docker or a broker."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("poseidon_ops_check", ROOT / "scripts/platform/check_ops.py")
check_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_module)


class OperationsAssetTests(unittest.TestCase):
    def test_pinned_local_config_static_validation(self):
        result = check_module.check()
        self.assertEqual(result["services"], 4)
        self.assertFalse(result["docker_executed"])

    def test_static_checker_rejects_public_host_binding(self):
        with tempfile.TemporaryDirectory(prefix="poseidon-ops-assets-") as directory:
            root = Path(directory)
            for name in ("compose.json", "mosquitto.conf", "mosquitto.acl", "chirpstack.toml.example", "region_eu868.toml.example", "redis.conf.example"):
                shutil.copyfile(check_module.COMPOSE / name, root / name)
            data = json.loads((root / "compose.json").read_text())
            data["services"]["mosquitto"]["ports"] = ["0.0.0.0:8883:8883"]
            (root / "compose.json").write_text(json.dumps(data))
            previous = check_module.COMPOSE
            try:
                check_module.COMPOSE = root
                with self.assertRaisesRegex(ValueError, "non-loopback"):
                    check_module.check()
            finally:
                check_module.COMPOSE = previous


if __name__ == "__main__":
    unittest.main()
