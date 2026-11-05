from types import SimpleNamespace

import pytest

from v8_installer.install import configure_locale
from v8_installer.plan import PlanError


@pytest.mark.parametrize('selected,entry,expected', [
    ('fr_FR.UTF-8', '#fr_FR.UTF-8 UTF-8\n', 'fr_FR.UTF-8'),
    ('aa_ER', 'aa_ER UTF-8\n', 'aa_ER.UTF-8'),
    ('sr_RS@latin', '#sr_RS@latin UTF-8\n', 'sr_RS.UTF-8@latin'),
    ('sr_RS@latin', '#sr_RS.UTF-8@latin UTF-8\n', 'sr_RS.UTF-8@latin'),
])
def test_locale_generation_handles_modifiers_and_previously_enabled_entries(tmp_path, selected, entry, expected):
    etc = tmp_path / 'etc'
    etc.mkdir()
    (etc/'locale.gen').write_text(entry)
    calls = []
    configure_locale(SimpleNamespace(target=tmp_path, arch_chroot=calls.append), selected)
    assert not (etc/'locale.gen').read_text().startswith('#')
    assert (etc/'locale.conf').read_text() == f'LANG={expected}\n'
    assert calls == ['locale-gen']


def test_locale_generation_rejects_missing_or_wrong_encoding(tmp_path):
    etc = tmp_path/'etc'
    etc.mkdir()
    (etc/'locale.gen').write_text('#fr_FR ISO-8859-1\n')
    calls = []
    with pytest.raises(PlanError):
        configure_locale(SimpleNamespace(target=tmp_path, arch_chroot=calls.append), 'fr_FR.UTF-8')
    assert not calls


def test_builtin_c_utf8_does_not_require_locale_gen_entry(tmp_path):
    calls = []
    configure_locale(SimpleNamespace(target=tmp_path, arch_chroot=calls.append), 'C.UTF-8')
    assert (tmp_path/'etc/locale.conf').read_text() == 'LANG=C.UTF-8\n'
    assert not calls
