import pytest

from app.models.validation import validate_hostname, validate_port, validate_vlan


@pytest.mark.parametrize("vlan_id, name", [("2", "A"), ("10", "USUARIOS"), ("4094", "VLAN_X-1")])
def test_valid_vlan(vlan_id, name):
    assert validate_vlan(vlan_id, name) is None


@pytest.mark.parametrize("vlan_id, name, snippet", [
    ("", "A", "entre 1 e 4094"),
    ("4095", "A", "entre 1 e 4094"),
    ("abc", "A", "entre 1 e 4094"),
    ("1", "A", "reservada"),
    ("1002", "A", "reservada"),
    ("10", "", "1-32 caracteres"),
    ("10", "com espaco", "1-32 caracteres"),
    ("10", "X" * 33, "1-32 caracteres"),
])
def test_invalid_vlan(vlan_id, name, snippet):
    assert snippet in validate_vlan(vlan_id, name)


@pytest.mark.parametrize("hostname", ["S", "SW1", "SW-ANDAR1", "SW_ANDAR1", "A" * 63])
def test_valid_hostname(hostname):
    assert validate_hostname(hostname) is None


@pytest.mark.parametrize("hostname", ["", "1SW", "_SW", "SW_", "SW-", "SW ANDAR", "SW.LAB", "A" * 64])
def test_invalid_hostname(hostname):
    assert validate_hostname(hostname) is not None


@pytest.mark.parametrize("port, ok", [("22", True), ("65535", True), ("0", False), ("65536", False), ("x", False)])
def test_port(port, ok):
    assert (validate_port(port) is None) == ok
