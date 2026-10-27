import pytest

from app.models import compliance
from app.models.validation import to_ascii, validate_hostname, validate_port, validate_vlan


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


@pytest.mark.parametrize("typed, ascii", [("VLAN_SEGURANÇA", "VLAN_SEGURANCA"), ("AÇÃO_é", "ACAO_e"), ("VLAN_DADOS", "VLAN_DADOS")])
def test_to_ascii(typed, ascii):
    assert to_ascii(typed) == ascii
    assert validate_vlan("50", to_ascii(typed)) is None


def test_non_latin_name_still_rejected():
    assert validate_vlan("50", to_ascii("VLAN_€")) is not None


SHOW_VLAN_BRIEF = """VLAN Name                             Status    Ports
---- -------------------------------- --------- -------------------------------
1    default                          active    Et0/0, Et0/1
10   VLAN_DADOS                       active
20   VLAN_VOICE                       active
1002 fddi-default                     act/unsup
"""


def test_standard_checks():
    checks = compliance.standard_checks(SHOW_VLAN_BRIEF, "hostname LAB_MELI")
    assert [(c.item, c.ok) for c in checks] == [("VLAN 10", True), ("VLAN 20", False), ("VLAN 50", False), ("Hostname", False)]
    assert [c.divergence for c in checks if not c.ok] == [
        "VLAN 20: esperado VLAN_VOZ, encontrado VLAN_VOICE",
        "VLAN 50: esperado VLAN_SEGURANCA, encontrado (não existe)",
        "Hostname: esperado SWITCH_AUTOMATIZADO, encontrado LAB_MELI",
    ]


def test_parse_hostname_missing():
    assert compliance.hostname_check("", "SW").found == "(não encontrado)"
