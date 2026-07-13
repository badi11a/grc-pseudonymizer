"""Tests for ${ENV_VAR} substitution in config.load()."""
from __future__ import annotations

import os

import pytest
import yaml

from pseudonymize import config as cfg_mod


@pytest.fixture
def config_file(tmp_path):
    def _write(data: dict):
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump(data), encoding="utf-8")
        return str(path)
    return _write


def test_plain_values_are_unaffected(config_file, monkeypatch):
    path = config_file({
        "db_url": "postgresql://user:pass@localhost/db",
        "fpe": {"key": "2b7e151628aed2a6abf7158809cf4f3c", "tweak": "", "alphabet": "0123456789"},
        "hmac_key": "literal-secret",
    })
    cfg = cfg_mod.load(path)
    assert cfg["fpe"]["key"] == "2b7e151628aed2a6abf7158809cf4f3c"
    assert cfg["hmac_key"] == b"literal-secret"


def test_env_var_is_substituted(config_file, monkeypatch):
    monkeypatch.setenv("TEST_FPE_KEY", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    monkeypatch.setenv("TEST_HMAC_KEY", "super-secret-from-env")
    path = config_file({
        "db_url": "postgresql://user:pass@localhost/db",
        "fpe": {"key": "${TEST_FPE_KEY}", "tweak": "", "alphabet": "0123456789"},
        "hmac_key": "${TEST_HMAC_KEY}",
    })
    cfg = cfg_mod.load(path)
    assert cfg["fpe"]["key"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert cfg["hmac_key"] == b"super-secret-from-env"


def test_missing_env_var_raises(config_file, monkeypatch):
    monkeypatch.delenv("TEST_MISSING_VAR", raising=False)
    path = config_file({
        "db_url": "postgresql://user:pass@localhost/db",
        "fpe": {"key": "${TEST_MISSING_VAR}", "tweak": "", "alphabet": "0123456789"},
        "hmac_key": "x",
    })
    with pytest.raises(ValueError, match="TEST_MISSING_VAR"):
        cfg_mod.load(path)


def test_env_var_inside_larger_string(config_file, monkeypatch):
    monkeypatch.setenv("TEST_HOST", "prod-db.internal")
    path = config_file({
        "db_url": "postgresql://user:pass@${TEST_HOST}/mydb",
        "fpe": {"key": "2b7e151628aed2a6abf7158809cf4f3c", "tweak": "", "alphabet": "0123456789"},
        "hmac_key": "x",
    })
    cfg = cfg_mod.load(path)
    assert cfg["db_url"] == "postgresql://user:pass@prod-db.internal/mydb"
