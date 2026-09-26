import pytest

from pkdb import testing


@pytest.fixture(scope="session")
def pg():
    if not testing.setup():
        pytest.skip("нет PostgreSQL для тестов: задайте PK_TEST_PG_URL или установите pgserver")
    return True
