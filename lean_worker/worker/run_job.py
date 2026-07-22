#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, "/app")
from worker.result_parser import parse_log_file  # noqa: E402


class WorkerError(RuntimeError):
    pass


class ExclusiveFileLock:
    def __init__(self, path: Path, wait_seconds: int, metadata: dict[str, Any]):
        self.path = path
        self.wait_seconds = wait_seconds
        self.metadata = metadata
        self.acquired = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.wait_seconds
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(self.metadata, handle, ensure_ascii=False, indent=2)
                self.acquired = True
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise WorkerError(f"LEAN runtime is busy: {self.path}")
                time.sleep(0.5)

    def __exit__(self, exc_type, exc, tb):
        if self.acquired:
            self.path.unlink(missing_ok=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def replace_jsonc_scalar(text: str, key: str, value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False)
    pattern = re.compile(
        rf'(?m)^(?P<indent>\s*)"{re.escape(key)}"\s*:\s*'
        rf'(?P<old>"(?:\\.|[^"])*"|true|false|null|-?\d+(?:\.\d+)?)'
    )
    updated, count = pattern.subn(lambda m: f'{m.group("indent")}"{key}": {rendered}', text, count=1)
    if count != 1:
        raise WorkerError(f"Active config key not found: {key}")
    return updated


def replace_jsonc_container(text: str, key: str, value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    pattern = re.compile(
        rf'(?m)^(?P<prefix>\s*"{re.escape(key)}"\s*:\s*)(?P<opening>[{{[])'
    )
    match = pattern.search(text)
    if match is None:
        raise WorkerError(f"Active config key not found: {key}")

    # LEAN's stock config.json stores ``parameters`` as a multi-line JSONC
    # object containing comments. A one-line regex silently missed that block,
    # so requested experiment parameters were recorded in the manifest but the
    # engine ran strategy defaults. Find the balanced container while ignoring
    # braces in strings and JSONC comments, then replace only its value.
    opening = match.group("opening")
    closing = "}" if opening == "{" else "]"
    start = match.start("opening")
    depth = 0
    in_string = False
    escaped = False
    line_comment = False
    block_comment = False

    index = start
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""

        if line_comment:
            if char in "\r\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                index += 2
            else:
                index += 1
            continue
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == "/" and next_char == "/":
            line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            block_comment = True
            index += 2
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                end = index + 1
                return text[:start] + rendered + text[end:]
        index += 1

    raise WorkerError(f"Unterminated config container: {key}")


def build_job_config(template: str, algorithm_class: str, algorithm_file: Path, data_folder: Path, parameters: dict[str, Any]) -> str:
    config = template
    required = {
        "algorithm-type-name": algorithm_class,
        "algorithm-language": "Python",
        "algorithm-location": algorithm_file.as_posix(),
        "data-folder": data_folder.as_posix() + "/",
    }
    for key, value in required.items():
        config = replace_jsonc_scalar(config, key, value)
    for key, value in {"close-automatically": True, "show-missing-data-logs": True}.items():
        try:
            config = replace_jsonc_scalar(config, key, value)
        except WorkerError:
            print(f"WORKER_CONFIG_OPTIONAL_KEY_SKIPPED={key}")
    try:
        config = replace_jsonc_container(config, "parameters", parameters)
    except WorkerError:
        print("WORKER_CONFIG_OPTIONAL_KEY_SKIPPED=parameters")
    return config


def resolve_python_dll() -> Path:
    import sysconfig
    candidates: list[Path] = []
    if os.environ.get("PYTHONNET_PYDLL"):
        candidates.append(Path(os.environ["PYTHONNET_PYDLL"]))
    name = sysconfig.get_config_var("LDLIBRARY")
    libdir = sysconfig.get_config_var("LIBDIR")
    if name and libdir:
        candidates.append(Path(libdir) / name)
    candidates.extend(sorted((Path(sys.prefix) / "lib").glob("libpython3.11.so*")))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise WorkerError("Python 3.11 shared library was not found")


def stream_process(command: list[str], cwd: Path, env: dict[str, str], log_path: Path, timeout: int) -> tuple[int, bool]:
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        start_new_session=True,
    )

    def pump() -> None:
        assert process.stdout is not None
        with log_path.open("w", encoding="utf-8", newline="\n") as handle:
            for line in process.stdout:
                print(line, end="")
                handle.write(line)
                handle.flush()

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    timed_out = False
    try:
        exit_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        import signal
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        exit_code = process.wait(timeout=30)
    reader.join(timeout=30)
    return exit_code, timed_out


def package_versions() -> dict[str, str]:
    names = ["numpy", "pandas", "scipy", "scikit-learn", "joblib", "xgboost", "lightgbm", "fastapi", "pydantic"]
    result = {}
    for name in names:
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = "not-installed"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--algorithm", required=True, type=Path)
    parser.add_argument("--algorithm-class", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-marker")
    parser.add_argument("--worker-config", required=True, type=Path)
    parser.add_argument("--parameters-json", default="{}")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()

    config = json.loads(args.worker_config.read_text(encoding="utf-8"))
    lean_root = Path(config["lean_root"]).resolve()
    runtime_root = Path(config["runtime_root"]).resolve()
    data_folder = Path(config["data_folder"]).resolve()
    dotnet = Path(config["dotnet_executable"]).resolve()
    support_source = Path(config["runtime_support_file"]).resolve()
    parameters = json.loads(args.parameters_json)

    release_dir = lean_root / "Launcher/bin/Release"
    launcher = release_dir / "QuantConnect.Lean.Launcher.dll"
    release_config = release_dir / "config.json"
    source_config = lean_root / "Launcher/config.json"
    template_config = source_config if source_config.is_file() else release_config
    for required in [args.algorithm, support_source, launcher, release_config, template_config, data_folder, dotnet]:
        if not required.exists():
            raise WorkerError(f"Required path not found: {required}")

    run_id = args.run_id
    job_dir = runtime_root / "jobs" / run_id
    result_dir = runtime_root / "results" / run_id
    model_dir = runtime_root / "models" / run_id
    lock_path = runtime_root / "locks/lean-launcher.lock"
    if job_dir.exists() or result_dir.exists():
        raise WorkerError(f"Run directory already exists: {run_id}")
    job_dir.mkdir(parents=True)
    result_dir.mkdir(parents=True)
    model_dir.mkdir(parents=True, exist_ok=True)

    job_main = job_dir / "main.py"
    job_support = job_dir / "alphaforge_base.py"
    job_config = job_dir / "config.json"
    console_log = result_dir / "console.log"
    detail_path = result_dir / "alphaforge_details.json"
    result_path = result_dir / "result.json"
    manifest_path = result_dir / "manifest.json"
    shutil.copy2(args.algorithm, job_main)
    shutil.copy2(support_source, job_support)

    generated = build_job_config(
        template_config.read_text(encoding="utf-8-sig"),
        args.algorithm_class,
        job_main,
        data_folder,
        parameters,
    )
    job_config.write_text(generated, encoding="utf-8", newline="\n")

    lean_commit_path = lean_root / "LEAN_COMMIT.txt"
    catalog_root = data_folder / "alphaforge-catalog"
    dataset_manifest_path = catalog_root / "dataset_manifest.json"
    quality_report_path = catalog_root / "quality_report.json"
    dataset_manifest = (
        json.loads(dataset_manifest_path.read_text(encoding="utf-8"))
        if dataset_manifest_path.is_file()
        else None
    )
    quality_report = (
        json.loads(quality_report_path.read_text(encoding="utf-8"))
        if quality_report_path.is_file()
        else None
    )

    manifest = {
        "schema_version": "1.1",
        "run_id": run_id,
        "created_at_utc": utc_now(),
        "runtime_version": os.environ.get("ALPHAFORGE_RUNTIME_VERSION", "1.1.3"),
        "lean_commit": lean_commit_path.read_text().strip() if lean_commit_path.is_file() else None,
        "dataset": {
            "manifest": dataset_manifest,
            "quality_summary": {
                "ready": quality_report.get("ready") if quality_report else None,
                "common_end_date": quality_report.get("common_end_date") if quality_report else None,
                "missing_symbols": quality_report.get("missing_symbols", []) if quality_report else [],
                "failed_quality_symbols": quality_report.get("failed_quality_symbols", []) if quality_report else [],
            },
            "manifest_sha256": sha256_file(dataset_manifest_path) if dataset_manifest_path.is_file() else None,
            "quality_report_sha256": sha256_file(quality_report_path) if quality_report_path.is_file() else None,
        },
        "strategy": {
            "source": str(args.algorithm),
            "job_copy": str(job_main),
            "class_name": args.algorithm_class,
            "sha256": sha256_file(job_main),
            "parameters": parameters,
        },
        "environment": {
            "python": sys.version,
            "packages": package_versions(),
            "platform": "linux/amd64",
            "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
        },
    }
    write_json(manifest_path, manifest)

    backup = release_config.read_bytes()
    exit_code = None
    timed_out = False
    python_dll = resolve_python_dll()
    with ExclusiveFileLock(lock_path, int(config.get("lock_wait_seconds", 60)), {"run_id": run_id, "pid": os.getpid()}):
        try:
            release_config.write_text(generated, encoding="utf-8", newline="\n")
            env = os.environ.copy()
            env["PYTHONNET_PYDLL"] = str(python_dll)
            env["ALPHAFORGE_RUN_ID"] = run_id
            env["ALPHAFORGE_RUN_DIR"] = str(result_dir)
            env["ALPHAFORGE_MODEL_DIR"] = str(model_dir)
            env["DOTNET_ROOT"] = str(dotnet.resolve().parent)
            env["DOTNET_ROOT_X64"] = str(dotnet.resolve().parent)
            env["PATH"] = f"{dotnet.parent}:{dotnet.resolve().parent}:{Path(sys.prefix) / 'bin'}:{env.get('PATH', '')}"
            exit_code, timed_out = stream_process(
                [str(dotnet), str(launcher)],
                release_dir,
                env,
                console_log,
                args.timeout_seconds,
            )
        finally:
            release_config.write_bytes(backup)

    result = parse_log_file(
        console_log,
        detail_path=detail_path,
        exit_code=exit_code,
        run_id=run_id,
        algorithm_class=args.algorithm_class,
        algorithm_file=str(job_main),
        expected_marker=args.expected_marker,
        timed_out=timed_out,
        manifest=manifest,
    )
    result["artifacts"] = {
        "result": str(result_path),
        "console_log": str(console_log),
        "details": str(detail_path) if detail_path.is_file() else None,
        "manifest": str(manifest_path),
        "generated_config": str(job_config),
        "model_directory": str(model_dir),
    }
    write_json(result_path, result)
    print(f"RUN_ID={run_id}")
    print(f"STATUS={result['status']}")
    print(f"RESULT={result_path}")
    return 0 if result["status"] == "completed" else (124 if result["status"] == "timeout" else 1)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except WorkerError as exc:
        print(f"WORKER_ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
