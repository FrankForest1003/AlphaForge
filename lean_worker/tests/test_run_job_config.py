import json
from pathlib import Path

from worker.run_job import build_job_config, install_runtime_observer


def test_build_job_config_replaces_multiline_jsonc_parameters():
    template = """
{
  "algorithm-type-name": "OldAlgorithm",
  "algorithm-language": "CSharp",
  "algorithm-location": "old.py",
  "data-folder": "old-data/",
  "close-automatically": false,
  "show-missing-data-logs": false,
  "parameters": {
    // The stock LEAN template contains comments and multiple lines here.
    "ema-fast": 10,
    "nested-sample": {"brace-in-string": "}"}
  },
  "next-setting": true
}
"""
    requested = {
        "start_date": "2025-01-02",
        "symbols": "MSFT,AAPL,NVDA,GOOGL,AMZN",
        "slippage_bps": "5",
    }

    generated = build_job_config(
        template,
        "RequestedAlgorithm",
        algorithm_file=Path("/tmp/main.py"),
        data_folder=Path("/data"),
        parameters=requested,
    )

    compact_parameters = json.dumps(
        requested, ensure_ascii=False, separators=(",", ":")
    )
    assert f'"parameters": {compact_parameters}' in generated
    assert '"ema-fast": 10' not in generated
    assert '"next-setting": true' in generated


def test_runtime_observer_wraps_job_copy_without_rewriting_original_class(tmp_path):
    algorithm = tmp_path / "main.py"
    algorithm.write_text(
        "class UserStrategy:\n"
        "    def initialize(self):\n"
        "        self.ready = True\n"
        "\n"
        "    def on_data(self, data):\n"
        "        self.data = data\n",
        encoding="utf-8",
    )

    wrapper = install_runtime_observer(algorithm, "UserStrategy")
    installed = algorithm.read_text(encoding="utf-8")

    assert wrapper == "UserStrategy"
    assert "class UserStrategy:" in installed
    assert "def _af_user_initialize(self):" in installed
    assert "def _af_user_on_data(self, data):" in installed
    assert "def initialize(self):" in installed
    assert "_AlphaForgeRuntimeObserver.on_data(" in installed
    assert "class AlphaForgeObservedAlgorithm" not in installed
