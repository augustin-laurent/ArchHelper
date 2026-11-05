import pytest
from v8_installer import i18n


def test_catalogs_are_in_parity():
    assert set(i18n._FR) == set(i18n._EN)


@pytest.fixture
def resolve(monkeypatch):
    def reset():
        monkeypatch.setattr(i18n, "_current", None)
    reset()
    return reset


def test_resolution_env_then_file_then_french(resolve, monkeypatch, tmp_path):
    monkeypatch.delenv("V8_LANG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    resolve()
    assert i18n.resolve_code() == "fr"

    file = tmp_path / "omarchy" / "language"
    file.parent.mkdir()
    file.write_text("en\n")
    resolve()
    assert i18n.resolve_code() == "en"

    monkeypatch.delenv("XDG_CONFIG_HOME")
    resolve()
    assert i18n.resolve_code() == "fr"  # nothing anywhere: French floor

    monkeypatch.setenv("V8_LANG", "not a language")
    resolve()
    assert i18n.resolve_code() == "fr"


def test_base_and_exact_catalogs_and_t_fallback(resolve, monkeypatch):
    monkeypatch.setenv("V8_LANG", "fr")
    resolve()
    assert i18n.t("ui.title") == "Installation de V8"
    monkeypatch.setenv("V8_LANG", "en-GB")  # no en-GB catalog: base "en" wins
    resolve()
    assert i18n.t("ui.title") == "V8 installation"
    assert i18n.t("no.such.key") == "no.such.key"


def test_every_key_answers_in_both_catalogs():
    for key in i18n._EN:
        assert i18n.t(key) != key
