from __future__ import annotations

import json
import py_compile
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
required = [
    "compose.yaml",
    "Dockerfile",
    "requirements.lock.txt",
    "README_zh.md",
    "docs/FULL_USER_GUIDE_zh.md",
    "docs/DATA_SOURCE_AND_LICENSE_zh.md",
    "docs/API_GUIDE_zh.md",
    "docs/TROUBLESHOOTING_zh.md",
    "app/service.py",
    "worker/run_job.py",
    "worker/result_parser.py",
    "runtime_support/alphaforge_base.py",
    "tools/prepare_local_data.py",
    "tools/sync_tiingo_data.py",
    "config/universe_whitelist_v1.0.json",
    "scripts/configure.ps1",
    "scripts/configure.sh",
    "scripts/start.ps1",
    "scripts/start.sh",
    "scripts/data-sync.ps1",
    "scripts/data-sync.sh",
    "scripts/test.ps1",
    "scripts/test.sh",
    "scripts/stop.ps1",
    "scripts/stop.sh",
    "scripts/shutdown.ps1",
    "scripts/shutdown.sh",
    "scripts/uninstall.ps1",
    "scripts/uninstall.sh",
]
for relative in required:
    path = ROOT / relative
    if not path.is_file():
        raise SystemExit(f"Missing: {relative}")

for path in ROOT.rglob("*.py"):
    py_compile.compile(str(path), doraise=True)

registry = {}
for path in (ROOT / "strategies/registry").glob("*.json"):
    item = json.loads(path.read_text(encoding="utf-8"))
    sid = item["strategy_id"]
    if sid in registry:
        raise SystemExit(f"Duplicate strategy ID: {sid}")
    entry = ROOT / "strategies" / item["entry_file"]
    if not entry.is_file():
        raise SystemExit(f"Missing strategy entry: {entry}")
    registry[sid] = item

for required_strategy in [
    "classic_30_stock_top3_momentum_v1",
    "ml_30_stock_gradient_boosting_v1",
]:
    if required_strategy not in registry:
        raise SystemExit(f"Missing required strategy: {required_strategy}")

universe = json.loads(
    (ROOT / "config/universe_whitelist_v1.0.json").read_text(encoding="utf-8")
)
if len(universe.get("tradable_symbols", [])) != 30:
    raise SystemExit("Default tradable universe must contain 30 symbols")
if len(universe.get("analysis_dependencies", [])) != 2:
    raise SystemExit("Default universe must contain SPY and QQQ dependencies")
all_tickers = {
    item["lean_ticker"]
    for item in universe["tradable_symbols"] + universe["analysis_dependencies"]
}
if not {"SPY", "QQQ", "BRK.B"}.issubset(all_tickers):
    raise SystemExit("Universe is missing SPY, QQQ or BRK.B")

compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
service = compose["services"]["backtest-runtime"]
if service.get("platform") != "linux/amd64":
    raise SystemExit("Cross-platform reference service must use linux/amd64")
if "127.0.0.1:" not in service["ports"][0]:
    raise SystemExit("Service must bind to localhost by default")

for path in list((ROOT / "scripts").glob("*.sh")) + list((ROOT / "docker").glob("*.sh")):
    subprocess.run(["bash", "-n", str(path)], check=True)

for forbidden in [ROOT / ".env"]:
    if forbidden.exists():
        raise SystemExit(f"Secret file must not be packaged: {forbidden.name}")

real_data_files = list((ROOT / "workspace/data").rglob("*.zip"))
if real_data_files:
    raise SystemExit("Market-data ZIP files must not be included in the distributable")

print("PACKAGE_STATIC_VALIDATION_PASS")
