from unittest.mock import patch
import pytest
from v8_installer.install import configure_firewall
from v8_installer.plan import PlanError


def test_firewall_configuration_is_offline_and_ipv6_enabled(tmp_path):
    path = tmp_path / "etc/default/ufw"
    path.parent.mkdir(parents=True)
    path.write_text('IPV6=no\nDEFAULT_INPUT_POLICY="ACCEPT"\nDEFAULT_OUTPUT_POLICY="DROP"\nDEFAULT_FORWARD_POLICY="ACCEPT"\n')
    with patch("subprocess.run", side_effect=AssertionError("No live network mutation allowed")):
        configure_firewall(tmp_path)
        configure_firewall(tmp_path)
    assert 'IPV6=yes' in path.read_text()
    assert 'DEFAULT_FORWARD_POLICY="DROP"' in path.read_text()
    assert 'DEFAULT_INPUT_POLICY="DROP"' in path.read_text()
    assert 'DEFAULT_OUTPUT_POLICY="ACCEPT"' in path.read_text()
    assert 'ENABLED=yes' in (tmp_path / "etc/ufw/ufw.conf").read_text()
    path.write_text('unknown format\n')
    with pytest.raises(PlanError):
        configure_firewall(tmp_path)
