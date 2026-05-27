import os
from pathlib import Path

from opentoken.config.app_config import load_or_create_app_config


def initialize_state_dir(state_dir: Path) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    # 0700 on the state-dir tree: individual credential/blob files are already
    # owner-only, but a 0755 directory still lets other local users on a
    # shared host LIST contents — leaking which providers the user has logged
    # into and observing .tmp/.lock siblings. Owner-only directory makes the
    # whole subtree opaque to anyone else. chmod is best-effort (no-op on
    # platforms where it's unsupported).
    try:
        os.chmod(state_dir, 0o700)
    except OSError:
        pass
    for name in ("providers", "browser", "logs", "opentoken", "files", "uploads"):
        subdir = state_dir / name
        subdir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(subdir, 0o700)
        except OSError:
            pass
    load_or_create_app_config(state_dir / "config.json")
    return state_dir
