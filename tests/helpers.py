from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_WORKSPACE = PROJECT_ROOT / ".test-tmp"


class FixtureTestCase(unittest.TestCase):
    def setUp(self) -> None:
        TEST_WORKSPACE.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="m1-", dir=TEST_WORKSPACE)
        self.workspace = Path(self.temporary.name)
        self.game = self.make_game("game")
        self.workshop = self.game / "left4dead2/addons/workshop"

    def tearDown(self) -> None:
        # Resolve and check the absolute cleanup target before recursive removal.
        target = self.workspace.resolve(strict=True)
        if target.parent != TEST_WORKSPACE.resolve(strict=True) or not target.name.startswith("m1-"):
            raise AssertionError("Refusing cleanup outside the dedicated test workspace")
        self.temporary.cleanup()

    def make_game(self, name: str, *, workshop: bool = True) -> Path:
        game = self.workspace / name
        addons = game / "left4dead2/addons"
        addons.mkdir(parents=True)
        if workshop:
            (addons / "workshop").mkdir()
        return game

    def put(self, relative: str, content: bytes = b"synthetic fixture; not a VPK") -> Path:
        path = self.game / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def symlink_or_skip(self, link: Path, target: Path, *, directory: bool = False) -> None:
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"OS does not permit this synthetic symlink: {type(error).__name__}, winerror={getattr(error, 'winerror', None)}")


class FakeScandir:
    """Allow deterministic duplicate-entry and mid-enumeration race tests."""

    def __init__(self, names: list[str], *, fail_after: bool = False) -> None:
        self.names = names
        self.fail_after = fail_after

    def __enter__(self):
        def entries():
            for name in self.names:
                yield SimpleNamespace(name=name)
            if self.fail_after:
                raise OSError("Synthetic interrupted enumeration")
        return entries()

    def __exit__(self, *args) -> None:
        pass
