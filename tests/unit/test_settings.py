from chile_oef.app.settings import Settings


def test_database_url_normalizes_bare_postgres_scheme() -> None:
    """Render (and Heroku-style) managed Postgres hands out `postgres://`
    connection strings; SQLAlchemy only picks the psycopg3 driver this
    app depends on for the explicit `postgresql+psycopg://` scheme.
    """
    settings = Settings(database_url="postgres://user:pass@host:5432/db")
    assert settings.database_url == "postgresql+psycopg://user:pass@host:5432/db"


def test_database_url_normalizes_bare_postgresql_scheme() -> None:
    settings = Settings(database_url="postgresql://user:pass@host:5432/db")
    assert settings.database_url == "postgresql+psycopg://user:pass@host:5432/db"


def test_database_url_leaves_explicit_driver_scheme_untouched() -> None:
    settings = Settings(database_url="postgresql+psycopg://user:pass@host:5432/db")
    assert settings.database_url == "postgresql+psycopg://user:pass@host:5432/db"
