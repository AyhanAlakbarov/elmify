import pytest

from tests.funding.conftest import make_run as _make_run


@pytest.fixture
def make_run():
    return _make_run
