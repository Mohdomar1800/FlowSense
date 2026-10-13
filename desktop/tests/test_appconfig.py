"""Desktop configuration: first-run file with a generated secret, parsing, and environment precedence."""

import os

import appconfig


def test_first_run_creates_config_with_unique_secret(tmp_path):
    first = appconfig.ensure_config(tmp_path / "a.env")
    second = appconfig.ensure_config(tmp_path / "b.env")
    secret_a = appconfig.parse_config(first.read_text())["JWT_SECRET_KEY"]
    secret_b = appconfig.parse_config(second.read_text())["JWT_SECRET_KEY"]
    assert len(secret_a) >= 60 and secret_a != secret_b
    assert secret_a != "change-me-in-env"


def test_existing_config_is_never_overwritten(tmp_path):
    path = tmp_path / "config.env"
    path.write_text("POSTGRES_HOST=db.example\n")
    appconfig.ensure_config(path)
    assert path.read_text() == "POSTGRES_HOST=db.example\n"


def test_parse_ignores_comments_blank_lines_and_quotes():
    text = '# comment\n\nPOSTGRES_DB = "focus"\nredis_enabled=false\nnot a setting\nEMPTY=\n'
    assert appconfig.parse_config(text) == {"POSTGRES_DB": "focus", "REDIS_ENABLED": "false", "EMPTY": ""}


def test_environment_variables_win_over_the_file(tmp_path, monkeypatch):
    path = tmp_path / "config.env"
    path.write_text("FLOWSENSE_TEST_A=from-file\nFLOWSENSE_TEST_B=from-file\n")
    monkeypatch.setenv("FLOWSENSE_TEST_A", "from-env")
    monkeypatch.delenv("FLOWSENSE_TEST_B", raising=False)
    appconfig.load_config(path)
    assert os.environ["FLOWSENSE_TEST_A"] == "from-env"
    assert os.environ["FLOWSENSE_TEST_B"] == "from-file"
    monkeypatch.delenv("FLOWSENSE_TEST_B")
