import pytest

from app.models.validacao import valida_hostname, valida_porta, valida_vlan


@pytest.mark.parametrize("vlan_id, nome", [("2", "A"), ("10", "USUARIOS"), ("4094", "VLAN_X-1")])
def test_vlan_valida(vlan_id, nome):
    assert valida_vlan(vlan_id, nome) is None


@pytest.mark.parametrize("vlan_id, nome, trecho", [
    ("", "A", "entre 1 e 4094"),
    ("4095", "A", "entre 1 e 4094"),
    ("abc", "A", "entre 1 e 4094"),
    ("1", "A", "reservada"),
    ("1002", "A", "reservada"),
    ("10", "", "1-32 caracteres"),
    ("10", "com espaco", "1-32 caracteres"),
    ("10", "X" * 33, "1-32 caracteres"),
])
def test_vlan_invalida(vlan_id, nome, trecho):
    assert trecho in valida_vlan(vlan_id, nome)


@pytest.mark.parametrize("hostname", ["S", "SW1", "SW-ANDAR1", "SW_ANDAR1", "A" * 63])
def test_hostname_valido(hostname):
    assert valida_hostname(hostname) is None


@pytest.mark.parametrize("hostname", ["", "1SW", "_SW", "SW_", "SW-", "SW ANDAR", "SW.LAB", "A" * 64])
def test_hostname_invalido(hostname):
    assert valida_hostname(hostname) is not None


@pytest.mark.parametrize("porta, ok", [("22", True), ("65535", True), ("0", False), ("65536", False), ("x", False)])
def test_porta(porta, ok):
    assert (valida_porta(porta) is None) == ok
