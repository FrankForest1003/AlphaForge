import json
from pathlib import Path

from worker.run_job import build_job_config


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
