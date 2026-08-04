from __future__ import annotations

import pytest

from app.connectors.registry import (
    ADAPTERS,
    RAIL_ORDER,
    build_adapter,
    describe_all,
    split_submission,
)
from app.connectors.sql import _reject_non_select
from app.core.config import settings
from app.core.errors import ConnectorError
from app.core.security import decrypt_credentials, encrypt_credentials
from app.models.enums import ConnectorStatus, ConnectorType


def test_credentials_round_trip() -> None:
    payload = {"username": "reader", "password": "s3cr3t!"}
    ciphertext, keys = encrypt_credentials(payload)

    assert decrypt_credentials(ciphertext) == payload
    assert keys == ["password", "username"]


def test_ciphertext_does_not_contain_the_secret() -> None:
    ciphertext, _ = encrypt_credentials({"password": "hunter2-unique-token"})
    assert "hunter2" not in ciphertext


def test_blank_values_are_dropped_before_encryption() -> None:
    _, keys = encrypt_credentials({"username": "u", "password": "", "token": None})  # type: ignore[dict-item]
    assert keys == ["username"]


def test_tampered_ciphertext_is_rejected() -> None:
    from app.core.security import CredentialDecryptionError

    ciphertext, _ = encrypt_credentials({"password": "x"})
    with pytest.raises(CredentialDecryptionError):
        decrypt_credentials(ciphertext[:-4] + "AAAA")


def test_secrets_never_land_in_config() -> None:
    config, credentials = split_submission(
        ConnectorType.POSTGRESQL,
        {
            "host": "db.example.com",
            "port": 5432,
            "database": "analytics",
            "username": "reader",
            "password": "hunter2",
        },
    )

    assert "password" not in config
    assert "username" not in config
    assert credentials == {"username": "reader", "password": "hunter2"}
    assert config["host"] == "db.example.com"


def test_every_rail_connector_declares_a_form() -> None:
    described = {item["type"] for item in describe_all()}
    assert described == {connector_type.value for connector_type in RAIL_ORDER}

    for item in describe_all():
        assert item["fields"], f"{item['type']} has no form fields"


def test_unconfigured_connectors_report_not_configured_honestly() -> None:
    for connector_type in RAIL_ORDER:
        outcome = build_adapter(connector_type, {}, {}).test()

        assert outcome.ok is False
        assert outcome.status is ConnectorStatus.NOT_CONFIGURED
        assert "not configured" in outcome.message.lower()


def test_csv_adapter_reads_a_real_file() -> None:
    settings.ensure_directories()
    (settings.uploads_dir / "conn-demo.csv").write_text(
        "date,rev\n2024-01-01,100\n2024-02-01,120\n", encoding="utf-8"
    )

    adapter = build_adapter(ConnectorType.CSV, {"file_path": "conn-demo.csv"}, {})
    outcome = adapter.test()

    assert outcome.ok is True
    assert outcome.status is ConnectorStatus.CONNECTED

    frame = adapter.fetch(schema=None, table=None, query=None, limit=10)
    assert frame.height == 2
    assert set(frame.columns) == {"date", "rev"}


@pytest.mark.parametrize("path", ["../../../etc/passwd", "..\\..\\secrets.csv", "../outside.csv"])
def test_file_adapter_refuses_path_traversal(path: str) -> None:
    outcome = build_adapter(ConnectorType.CSV, {"file_path": path}, {}).test()

    assert outcome.ok is False
    assert "uploads directory" in outcome.message


def test_file_adapter_reports_a_missing_file_clearly() -> None:
    outcome = build_adapter(ConnectorType.CSV, {"file_path": "nope.csv"}, {}).test()
    assert "No file found" in outcome.message


@pytest.mark.parametrize(
    "query",
    ["SELECT * FROM sales", "select id from t", "WITH x AS (SELECT 1) SELECT * FROM x"],
)
def test_select_queries_are_allowed(query: str) -> None:
    _reject_non_select(query)


@pytest.mark.parametrize(
    ("query", "fragment"),
    [
        ("DELETE FROM sales", "Only SELECT"),
        ("UPDATE t SET a=1", "Only SELECT"),
        ("DROP TABLE t", "Only SELECT"),
        ("SELECT 1; DROP TABLE users", "Multiple statements"),
        ("SELECT * FROM t; INSERT INTO x VALUES (1)", "Multiple statements"),
    ],
)
def test_write_queries_are_rejected(query: str, fragment: str) -> None:
    with pytest.raises(ConnectorError, match=fragment):
        _reject_non_select(query)


def test_cloud_adapters_without_drivers_stay_not_configured() -> None:
    adapter = build_adapter(
        ConnectorType.SNOWFLAKE,
        {"account": "xy123", "warehouse": "WH", "database": "DB"},
        {"username": "u", "password": "p"},
    )
    outcome = adapter.test()

    assert outcome.ok is False
    assert outcome.status is ConnectorStatus.NOT_CONFIGURED
    assert "driver" in outcome.message.lower()


def test_redshift_reuses_the_postgres_driver() -> None:
    from app.connectors.cloud import RedshiftAdapter

    assert RedshiftAdapter.supports_import is True
    assert RedshiftAdapter.default_port == 5439


def test_supabase_derives_its_host_from_the_project_reference() -> None:
    adapter = build_adapter(
        ConnectorType.SUPABASE, {"project_ref": "abcdefghijklmnop"}, {"password": "secret"}
    )

    assert adapter._resolved_host() == "db.abcdefghijklmnop.supabase.co"
    assert adapter._resolved_username() == "postgres"
    assert adapter._port() == 5432


def test_supabase_qualifies_the_role_when_going_through_the_pooler() -> None:
    adapter = build_adapter(
        ConnectorType.SUPABASE,
        {
            "project_ref": "abcdefghijklmnop",
            "host": "aws-0-eu-west-1.pooler.supabase.com",
            "port": 6543,
        },
        {"password": "secret"},
    )

    assert adapter._resolved_host() == "aws-0-eu-west-1.pooler.supabase.com"
    assert adapter._resolved_username() == "postgres.abcdefghijklmnop"


def test_supabase_honours_an_explicit_username() -> None:
    adapter = build_adapter(
        ConnectorType.SUPABASE,
        {"project_ref": "abcdefghijklmnop", "port": 6543},
        {"password": "secret", "username": "readonly_role"},
    )

    assert adapter._resolved_username() == "readonly_role"


def test_supabase_without_a_reference_or_host_says_so() -> None:
    adapter = build_adapter(ConnectorType.SUPABASE, {}, {"password": "secret"})

    with pytest.raises(ConnectorError, match="project reference"):
        adapter._resolved_host()


def test_supabase_reports_what_is_missing_before_connecting() -> None:
    outcome = build_adapter(ConnectorType.SUPABASE, {}, {}).test()

    assert not outcome.ok
    assert outcome.status is ConnectorStatus.NOT_CONFIGURED
    assert "Project reference" in outcome.message or "Database password" in outcome.message


def test_supabase_is_offered_as_an_importable_type() -> None:
    adapter_cls = ADAPTERS[ConnectorType.SUPABASE]

    assert adapter_cls.supports_import is True
    assert ConnectorType.SUPABASE in RAIL_ORDER
    keys = {field.key for field in adapter_cls.form_fields}
    assert {"project_ref", "password"} <= keys
