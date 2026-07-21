from pathlib import Path
import json
import unittest


class RegistryTests(unittest.TestCase):
    def test_registry_entries(self):
        root = Path(__file__).resolve().parents[1]
        seen = set()
        for path in (root / "strategies/registry").glob("*.json"):
            item = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn(item["strategy_id"], seen)
            seen.add(item["strategy_id"])
            self.assertTrue((root / "strategies" / item["entry_file"]).is_file())
        self.assertGreaterEqual(len(seen), 2)


if __name__ == "__main__":
    unittest.main()
