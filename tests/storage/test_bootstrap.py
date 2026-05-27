import os
import stat
import sys
from pathlib import Path

import pytest

from opentoken.storage.bootstrap import initialize_state_dir


def test_initialize_state_dir_creates_expected_directories(tmp_path: Path) -> None:
    state_dir = tmp_path / ".opentoken"

    initialize_state_dir(state_dir)

    assert (state_dir / "providers").is_dir()
    assert (state_dir / "browser").is_dir()
    assert (state_dir / "logs").is_dir()
    assert (state_dir / "opentoken").is_dir()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX-only mode bits")
def test_initialize_state_dir_is_owner_only(tmp_path: Path) -> None:
    """The state-dir tree holds provider sessions; other local users must not be
    able to even list it (which would leak which providers are logged in)."""
    state_dir = tmp_path / ".opentoken"
    initialize_state_dir(state_dir)

    for path in [state_dir, state_dir / "providers", state_dir / "browser"]:
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode & 0o077 == 0, f"{path} is {oct(mode)} — should be 0o700 owner-only"

