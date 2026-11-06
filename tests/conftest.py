import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from birdie.clock import FakeClock  # noqa: E402
from birdie.storage import Repository  # noqa: E402


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def repo():
    r = Repository(":memory:")
    yield r
    r.close()
