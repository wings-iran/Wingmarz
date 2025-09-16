import asyncio
import os
from pathlib import Path
from datetime import datetime
import zipfile

import config


def _path_norm(p: Path) -> Path:
    try:
        return p.resolve()
    except Exception:
        return p


def _is_excluded(file_path: Path, exclude_paths: set[Path]) -> bool:
    fp = _path_norm(file_path)
    for ex in (exclude_paths or set()):
        exn = _path_norm(ex)
        try:
            # Exclude if exact match or inside an excluded directory
            if fp == exn or exn in fp.parents:
                return True
        except Exception:
            # Best-effort; ignore path resolution errors
            pass
    # Additionally exclude any prior backup zip files by name to prevent recursive growth
    name_lower = fp.name.lower()
    if name_lower.startswith("backup-") and name_lower.endswith(".zip"):
        return True
    return False


def _add_path_to_zip(zip_file: zipfile.ZipFile, source_path: Path, base_dir: Path, exclude_paths: set[Path] | None = None) -> None:
    exclude_paths = exclude_paths or set()
    if source_path.is_file():
        if _is_excluded(source_path, exclude_paths):
            return
        arcname = source_path.relative_to(base_dir) if source_path.is_absolute() and base_dir in source_path.parents else source_path.name
        zip_file.write(source_path, arcname=str(arcname))
        return
    for root, _, files in os.walk(source_path):
        root_path = Path(root)
        # Skip entire directory trees that are excluded
        if _is_excluded(root_path, exclude_paths):
            continue
        for f in files:
            file_path = root_path / f
            if _is_excluded(file_path, exclude_paths):
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
    # Detect actual database path and a reasonable base directory
    def _detect_db_and_base() -> tuple[Path, Path]:
        try:
            configured = (getattr(config, "DATABASE_PATH", "") or "").strip()
        except Exception:
            configured = ""
        candidates: list[Path] = []
        if configured:
            try:
                candidates.append(Path(configured).expanduser().resolve())
            except Exception:
                candidates.append(Path(configured))
        # Common locations
        common_relatives = [
            Path("data") / "bot_database.db",
            Path("bot_database.db"),
        ]
        common_absolutes = [
            Path("/app/data/bot_database.db"),
        ]
        cwd = Path.cwd()
        for rel in common_relatives:
            try:
                candidates.append((cwd / rel).resolve())
            except Exception:
                candidates.append(cwd / rel)
        candidates.extend(common_absolutes)

        # Pick the first existing file
        for cand in candidates:
            try:
                if cand.exists() and cand.is_file():
                    return cand, cand.parent
            except Exception:
                continue
        # Fallback: use configured (may not exist) and cwd as base
        fallback = candidates[0] if candidates else (cwd / "bot_database.db")
        try:
            fallback = fallback.resolve()
        except Exception:
            pass
        return fallback, (fallback.parent if fallback.parent.exists() else cwd)

    db_path, base_dir = _detect_db_and_base()

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    backup_name = f"backup-{timestamp}.zip"
    # Determine backup output directory
    # Prefer configured BACKUP_DIR; otherwise use a dedicated 'backups' folder next to the DB (often a persistent volume)
    configured_backup_dir = (getattr(config, "BACKUP_DIR", "") or "").strip()
    if configured_backup_dir:
        output_dir = Path(configured_backup_dir).expanduser().resolve()
    else:
        output_dir = (base_dir / "backups").resolve()
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
                    # Exclude the backups output directory and any prior backup zips to avoid recursive growth
                    exclude: set[Path] = {backup_zip_path}
                    # Avoid duplicating the database file inside the directory snapshot
                    try:
                        if db_path.exists():
                            exclude.add(db_path)
                    except Exception:
                        pass
                    try:
                        # Only add output_dir to exclusions if it's inside base_dir
                        if _path_norm(base_dir) in _path_norm(output_dir).parents or _path_norm(base_dir) == _path_norm(output_dir):
                            exclude.add(output_dir)
                    except Exception:
                        pass
                    _add_path_to_zip(zf, base_dir, base_dir, exclude_paths=exclude)
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

