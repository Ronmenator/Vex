"""Backup manager — auto-backup before destructive file operations."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class BackupEntry:
    """Record of a file backup."""

    original_path: str
    backup_path: str
    timestamp: str
    tool_name: str
    size_bytes: int


class BackupManager:
    """Creates and manages file backups in .vex/backups/."""

    def __init__(self, workspace_root: str) -> None:
        self._workspace = Path(workspace_root)
        self._backup_dir = self._workspace / ".vex" / "backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        self._log_file = self._backup_dir / "backups.jsonl"

    def create_backup(self, file_path: Path, tool_name: str = "unknown") -> str | None:
        """Backup a file before modification. Returns backup path or None if file doesn't exist."""
        if not file_path.is_file():
            return None

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        rel = file_path.relative_to(self._workspace)
        safe_name = str(rel).replace("/", "_").replace("\\", "_")
        backup_path = self._backup_dir / f"{ts}_{safe_name}"

        shutil.copy2(file_path, backup_path)

        entry = BackupEntry(
            original_path=str(rel),
            backup_path=str(backup_path),
            timestamp=datetime.now(timezone.utc).isoformat(),
            tool_name=tool_name,
            size_bytes=file_path.stat().st_size,
        )
        self._log_entry(entry)
        return str(backup_path)

    def restore(self, backup_path: str) -> bool:
        """Restore a file from backup."""
        bp = Path(backup_path)
        if not bp.is_file():
            return False

        # Find original path from log
        for entry in self.list_backups():
            if entry.backup_path == backup_path:
                target = self._workspace / entry.original_path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(bp, target)
                return True
        return False

    def list_backups(self, path_filter: str | None = None) -> list[BackupEntry]:
        """List all backups, optionally filtered by original path."""
        entries: list[BackupEntry] = []
        if not self._log_file.exists():
            return entries

        for line in self._log_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                entry = BackupEntry(**data)
                if path_filter and entry.original_path != path_filter:
                    continue
                entries.append(entry)
            except (json.JSONDecodeError, TypeError):
                continue
        return entries

    def _log_entry(self, entry: BackupEntry) -> None:
        with open(self._log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.__dict__) + "\n")
