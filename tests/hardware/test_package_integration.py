import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_json(path):
    return json.loads((ROOT / path).read_text())


class HardwarePackageIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.interface = read_json("hardware/interfaces/reference-v1.json")
        cls.links = read_json("hardware/interfaces/bom-links.json")
        cls.bom = read_json("hardware/bom/reference-v1.json")
        cls.sources = {source["id"]: source for source in read_json("hardware/bom/sources.json")["sources"]}
        cls.cad = read_json("hardware/cad/generated/reference-v1/manifest.json")

    def test_configuration_and_issued_revision_agree(self):
        for record in (self.interface, self.links, self.bom, self.cad):
            self.assertEqual(record["configuration"], "reference-v1")
        self.assertEqual(self.interface["revision"], self.cad["revision"])
        self.assertEqual(self.links["revision"], self.bom["reference"])

    def test_cad_bom_aliases_resolve_to_reference_items(self):
        part_ids = {part["id"] for part in self.bom["parts"]}
        aliases = self.links["purchased_aliases"]
        for targets in aliases.values():
            self.assertTrue(targets)
            self.assertLessEqual(set(targets), part_ids)
        checked = 0
        for assembly in self.cad["assemblies"]:
            if assembly["id"].startswith("TOP_"):
                continue
            for part in assembly["parts"]:
                part_id = part["bom_id"]
                if part_id.startswith(("CAD-", "PRINT-")):
                    self.assertTrue(part["material_id"])
                    self.assertGreater(part["volume_mm3"], 0)
                else:
                    self.assertTrue(part_id in part_ids or part_id in aliases or part_id in self.links["unresolved_reference_items"], part_id)
                checked += 1
        self.assertGreater(checked, 50)

    def test_vendor_envelopes_agree_across_lane_artifacts(self):
        reef = next(item for item in self.interface["mechanical_envelopes"] if item["assembly"] == "REEF")
        self.assertEqual(reef["battery_envelope_mm"], self.cad["parameters"]["battery_mm"])
        self.assertEqual(reef["solar_envelope_mm"], self.cad["parameters"]["solar_mm"])
        height, width, depth = self.sources["SRC-BATTERY"]["verified_facts"]["dimensions_hwd_mm_from_manual"]
        self.assertEqual(reef["battery_envelope_mm"], [width, depth, height])
        short, long, thick = self.sources["SRC-PANEL"]["verified_facts"]["dimensions_mm_as_listed"]
        self.assertEqual(reef["solar_envelope_mm"], [long, short, thick])
        self.assertEqual(self.cad["parameters"]["converter_mm"], self.sources["SRC-SD50"]["verified_facts"]["dimensions_lwh_mm"])
        h, w, d = self.sources["SRC-MPPT"]["verified_facts"]["dimensions_hwd_mm"]
        self.assertEqual(self.cad["parameters"]["mppt_mm"], [w, d, h])

    def test_uart_board_pin_identities_match_source_schedule(self):
        boards = {board["id"]: board for board in self.interface["boards"]}
        uart = boards["MCU-01"]["reserved_logical_interfaces"]["radio_uart"]
        esp = self.sources["SRC-ESP"]["verified_facts"]
        radio = self.sources["SRC-RAK"]["verified_facts"]
        self.assertEqual(uart["tx_board_pin"], esp["gpio17"])
        self.assertEqual(uart["rx_board_pin"], esp["gpio16"])
        pins = boards["RADIO-01"]["board_pins"]
        self.assertEqual(pins["UART2_RX"], radio["uart2_rx"].split("/")[0].strip())
        self.assertEqual(pins["UART2_TX"], radio["uart2_tx"].split("/")[0].strip())
        self.assertEqual(pins["3V3"], radio["stable_supply"].split("/")[0].strip())
        self.assertEqual(pins["GND"], radio["stable_ground"].split("/")[0].strip())

    def test_default_top_has_no_optional_output_parts(self):
        top = next(assembly for assembly in self.cad["assemblies"] if assembly["id"] == "TOP_PASSIVE")
        for part in top["parts"]:
            self.assertFalse(part["id"].startswith(("PROJECTOR__", "WIPER__", "ARRAY__")))
        for part in self.bom["parts"]:
            if part["assembly"] in ("PROJECTOR", "WIPER", "ARRAY"):
                self.assertEqual(part["populated_default_qty"], 0)

    def test_reference_bom_sources_and_quantities_are_explicit(self):
        self.assertFalse(self.bom["quotes_available"])
        self.assertIsNone(self.bom["quote_defaults"]["unit_price"])
        ids = [part["id"] for part in self.bom["parts"]]
        self.assertEqual(len(ids), len(set(ids)))
        for part in self.bom["parts"]:
            self.assertLessEqual(set(part["sources"]), set(self.sources))
            if part["reference_qty"] is not None:
                self.assertGreater(part["reference_qty"], 0)
                self.assertLessEqual(part["populated_default_qty"], part["reference_qty"])


if __name__ == "__main__":
    unittest.main()
