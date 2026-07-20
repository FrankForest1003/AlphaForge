#!/usr/bin/env python3
"""Patch LEAN for one-process-per-backtest Python.NET shutdown on Linux."""

from __future__ import annotations

import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
pattern = re.compile(
    r"        public static void Shutdown\(\)\n        \{\n.*?^        \}\n",
    flags=re.MULTILINE | re.DOTALL,
)
replacement = """        public static void Shutdown()
        {
            if (_isInitialized)
            {
                Log.Trace($"PythonInitializer.Shutdown(): {Messages.PythonInitializer.Start}");
                _isInitialized = false;

                // AlphaForge launches one independent LEAN process per job.
                // Explicit Python.NET shutdown can abort on Linux when the GIL
                // finalizer runs on a different thread. The Launcher exits
                // immediately after this method, so process teardown safely
                // releases the embedded Python runtime.
                Log.Trace("PythonInitializer.Shutdown(): explicit engine shutdown skipped for one-shot worker");
                Log.Trace($"PythonInitializer.Shutdown(): {Messages.PythonInitializer.Ended}");
            }
        }
"""
updated, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit(f"Could not patch PythonInitializer.Shutdown; matches={count}")
path.write_text(updated, encoding="utf-8")
print("PYTHON_SHUTDOWN_PATCH_PASS")
