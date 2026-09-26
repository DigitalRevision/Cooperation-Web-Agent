import pytest

from app import auth, bundle, main, repo   # импорт app добавляет корень проекта в путь поиска (пакет pkdb)
from pkdb import testing


@pytest.fixture(scope="session", autouse=True)
def pg():
    if not testing.setup():
        pytest.skip("нет PostgreSQL для тестов: задайте PK_TEST_PG_URL или установите pgserver")
    testing.load_seed()
    return True


@pytest.fixture(autouse=True)
def clean_db(pg):
    """Каждый тест — с пустыми пользовательскими базами и свежим каталогом в памяти API."""
    testing.clear_user_data()
    auth._staff_known.clear()
    auth._new_sessions.clear()   # ограничители частоты считают все запросы тестового клиента одним адресом
    main._hits.clear()
    repo.drop_cache()
    bundle.reset()
    yield
