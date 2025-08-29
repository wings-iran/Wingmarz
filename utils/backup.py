import asyncio
import os
from pathlib import Path
from datetime import datetime
import zipfile

import config


def _add_path_to_zip(zip_file: zipfile.ZipFile, source_path: Path, base_dir: Path, exclude_paths: set[Path] | None = None) -> None:
    exclude_paths = exclude_paths or set()
    if source_path.is_file():
        if source_path in exclude_paths:
            return
        arcname = source_path.relative_to(base_dir) if source_path.is_absolute() and base_dir in source_path.parents else source_path.name
        zip_file.write(source_path, arcname=str(arcname))
        return
    for root, _, files in os.walk(source_path):
        root_path = Path(root)
        for f in files:
            file_path = root_path / f
            if file_path in exclude_paths:
                continue
            try:
                arcname = file_path.relative_to(base_dir) if base_dir in file_path.parents else file_path.name
            except Exception:
                arcname = file_path.name
            zip_file.write(file_path, arcname=str(arcname))


async def create_backup_zip() -> Path:
    """Create a zip backup of bot data and return the path to the zip file.

    Contents:
    - Database file (config.DATABASE_PATH)
    - Data directory (parent of DATABASE_PATH), if exists
    - bot.log (if exists in CWD)
    - logs directory (./logs or /app/logs if exists)
    """
    db_path = Path(config.DATABASE_PATH).resolve()
    base_dir = db_path.parent if db_path.exists() else Path.cwd()

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    backup_name = f"backup-{timestamp}.zip"
    # Prefer storing backup next to DB (often a persistent volume)
    output_dir = base_dir if base_dir.exists() else Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)
    backup_zip_path = output_dir / backup_name

    with zipfile.ZipFile(backup_zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Database file
        if db_path.exists():
            _add_path_to_zip(zf, db_path, base_dir)

        # Data directory (parent of DB)
        if base_dir.exists():
            # Only include directory if it's likely a dedicated data dir
            # e.g., '/app/data'; skip if base_dir is project root with many files
            try:
                if base_dir.name.lower() in ("data", "storage"):
                    _add_path_to_zip(zf, base_dir, base_dir, exclude_paths={backup_zip_path})
            except Exception:
                pass

        # bot.log in current working directory
        bot_log = Path.cwd() / "bot.log"
        if bot_log.exists():
            _add_path_to_zip(zf, bot_log, Path.cwd())

        # logs directory in CWD or /app/logs
        candidate_logs = [Path.cwd() / "logs", Path("/app/logs")] 
        for logs_dir in candidate_logs:
            if logs_dir.exists() and logs_dir.is_dir():
                _add_path_to_zip(zf, logs_dir, logs_dir)

    return backup_zip_path

