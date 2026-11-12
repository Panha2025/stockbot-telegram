"""Load and atomically save inventory JSON without damaging corrupted files."""

import json
import os
from pathlib import Path
import tempfile


class DataFileError(RuntimeError):
    """Data could not be opened safely; keep the original file unchanged."""


class InventoryStorage:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return {"version": 1, "next_id": 1, "products": []}
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DataFileError(
                f"Cannot read inventory file '{self.path}': {exc}. "
                "The file was not changed; fix or back it up before reopening."
            ) from exc
        if (
            not isinstance(data, dict)
            or type(data.get("version")) is not int
            or data["version"] != 1
            or type(data.get("next_id")) is not int
            or data["next_id"] < 1
            or not isinstance(data.get("products"), list)
        ):
            raise DataFileError(
                f"Inventory file '{self.path}' has an unexpected structure. "
                "The original file was not changed."
            )
        return data

    def save(self, data):
        temporary_path = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=".inventory-", suffix=".tmp", delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        except (OSError, TypeError, ValueError) as exc:
            raise DataFileError(
                f"Could not save inventory to '{self.path}': {exc}. "
                "The previous saved file has been preserved."
            ) from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
