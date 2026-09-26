import pytest

from pkdb import testing


@pytest.fixture(scope="session")
def pg():
    if not testing.setup():
        pytest.skip("нет PostgreSQL для тестов: задайте PK_TEST_PG_URL или установите pgserver")
    return True


@pytest.fixture
def repo(pg):
    """Тестовые базы: каталог из 28 предприятий первичного сбора, пустые журналы сбора. Рабочие базы не трогаются."""
    testing.load_seed()
    return pg
