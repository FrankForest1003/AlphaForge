import json
from pathlib import Path
import tempfile
import threading

from app.io_utils import atomic_write_text


def test_atomic_write_never_exposes_partial_json():
    with tempfile.TemporaryDirectory() as temporary_directory:
        path = Path(temporary_directory) / "job.json"
        atomic_write_text(path, json.dumps({"generation": -1}))
        failures = []

        def writer():
            for generation in range(250):
                atomic_write_text(
                    path,
                    json.dumps(
                        {
                            "generation": generation,
                            "payload": "x" * 8_192,
                        }
                    ),
                )

        thread = threading.Thread(target=writer)
        thread.start()
        while thread.is_alive():
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                failures.append(error)
        thread.join()

        assert failures == []
        assert list(path.parent.glob(f".{path.name}.*.tmp")) == []
