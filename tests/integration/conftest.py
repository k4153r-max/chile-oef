import os
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from chile_oef.db import models  # noqa: F401
from chile_oef.db.base import Base


@pytest.fixture
def postgis_engine() -> Generator[Engine, None, None]:
    database_url = os.getenv("CHILE_OEF_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("CHILE_OEF_TEST_DATABASE_URL is not configured")
    database_name = make_url(database_url).database or ""
    if not database_name.endswith("_test"):
        raise RuntimeError("integration tests refuse to modify a database not ending in _test")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
