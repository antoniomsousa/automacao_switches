"""Tests of every app action against the fake switch, through the Flask test client."""
import pytest

from tests import fake_switch

SUCCESS = 'data-status="success"'


def post(client, access, **data):
    return client.post("/switch", data={**access, **data})


def test_home_redirects_to_form(client):
    r = client.get("/")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/switch")


def test_form_page(client):
    r = client.get("/switch")
    assert r.status_code == 200
    assert 'value="hostname"' in r.get_data(as_text=True)


def test_static_files(client):
    for path in ("/static/css/style.css", "/static/js/app.js", "/static/img/switch-automation.svg"):
        assert client.get(path).status_code == 200, path


def test_create_vlan(client, access, switch_shell):
    r = post(client, access, action="create_vlan", vlan_id="10", vlan_name="USUARIOS")
    body = r.get_data(as_text=True)
    assert SUCCESS in body
    assert switch_shell.state["vlans"][10] == "USUARIOS"
    # Result page shows commands, switch output and the verification show command
    assert '<pre id="cmd-commands" class="terminal">configure terminal\nvlan 10\nname USUARIOS\nend</pre>' in body
    assert "(config-vlan)#" in body
    assert "show vlan brief" in body
    assert "10   USUARIOS" in body


def test_create_vlan_rejected(client, access, switch_shell, monkeypatch):
    # Device without VLAN support (e.g. a router image) answers "% Invalid input" to "vlan <id>"
    execute = switch_shell._execute
    monkeypatch.setattr(switch_shell, "_execute",
                        lambda self, line: fake_switch.INVALID if line.startswith("vlan ") else execute(self, line))
    r = post(client, access, action="create_vlan", vlan_id="20", vlan_name="USUARIOS")
    body = r.get_data(as_text=True)
    assert SUCCESS not in body
    assert "rejeitou o comando" in body
    assert 20 not in switch_shell.state["vlans"]


def test_create_vlan_validated(client, access, switch_shell):
    body = post(client, access, action="create_vlan", vlan_id="10", vlan_name="VLAN_DADOS").get_data(as_text=True)
    assert '<tr class="check-ok">' in body
    assert "<td>VLAN 10</td><td>VLAN_DADOS</td><td>VLAN_DADOS</td>" in body


def test_create_vlan_divergence(client, access, switch_shell, monkeypatch):
    # The switch accepts "name" but keeps the default name: the result must be an alert, not a success
    execute = switch_shell._execute
    monkeypatch.setattr(switch_shell, "_execute",
                        lambda self, line: None if line.startswith("name ") else execute(self, line))
    body = post(client, access, action="create_vlan", vlan_id="20", vlan_name="VLAN_VOZ").get_data(as_text=True)
    assert SUCCESS not in body
    assert 'data-status="divergence"' in body
    assert "Configuração não padrão encontrada" in body
    assert "<li>VLAN 20: esperado VLAN_VOZ, encontrado VLAN0020</li>" in body


def test_change_hostname_divergence(client, access, switch_shell, monkeypatch):
    execute = switch_shell._execute
    monkeypatch.setattr(switch_shell, "_execute",
                        lambda self, line: None if line.startswith("hostname ") else execute(self, line))
    body = post(client, access, action="hostname", hostname="SWITCH_AUTOMATIZADO").get_data(as_text=True)
    assert 'data-status="divergence"' in body
    assert "<li>Hostname: esperado SWITCH_AUTOMATIZADO, encontrado SW-LAB</li>" in body


def test_validate_standard_config(client, access, switch_shell):
    # Fresh switch: none of the standard VLANs and the default hostname
    body = post(client, access, action="validate").get_data(as_text=True)
    assert 'data-status="divergence"' in body
    for divergence in ("VLAN 10: esperado VLAN_DADOS, encontrado (não existe)",
                       "VLAN 50: esperado VLAN_SEGURANCA, encontrado (não existe)",
                       "Hostname: esperado SWITCH_AUTOMATIZADO, encontrado SW-LAB"):
        assert "<li>%s</li>" % divergence in body

    # Configured through the frontend in one request, VLAN 50 typed with the accent as in the challenge
    post(client, access, action="create_vlan", vlan_id=["10", "20", "50"], vlan_name=["VLAN_DADOS", "VLAN_VOZ", "VLAN_SEGURANÇA"])
    post(client, access, action="hostname", hostname="SWITCH_AUTOMATIZADO")
    body = post(client, access, action="validate").get_data(as_text=True)
    assert SUCCESS in body
    assert "Divergente" not in body
    assert body.count('<tr class="check-ok">') == 4


def test_create_vlan_accented_name(client, access, switch_shell):
    body = post(client, access, action="create_vlan", vlan_id="50", vlan_name="VLAN_SEGURANÇA").get_data(as_text=True)
    assert SUCCESS in body
    assert switch_shell.state["vlans"][50] == "VLAN_SEGURANCA"
    assert "O nome VLAN_SEGURANÇA foi convertido para VLAN_SEGURANCA" in body


def test_create_several_vlans(client, access, switch_shell):
    body = post(client, access, action="create_vlan", vlan_id=["10", "20", "50"],
                vlan_name=["VLAN_DADOS", "VLAN_VOZ", "VLAN_SEGURANCA"]).get_data(as_text=True)
    assert SUCCESS in body
    assert "3 VLANs criadas com sucesso: 10 (VLAN_DADOS), 20 (VLAN_VOZ), 50 (VLAN_SEGURANCA)." in body
    assert {i: switch_shell.state["vlans"][i] for i in (10, 20, 50)} == {10: "VLAN_DADOS", 20: "VLAN_VOZ", 50: "VLAN_SEGURANCA"}
    # One config session with every VLAN, then one check per VLAN
    assert ('<pre id="cmd-commands" class="terminal">configure terminal\nvlan 10\nname VLAN_DADOS\nvlan 20\nname VLAN_VOZ\n'
            'vlan 50\nname VLAN_SEGURANCA\nend</pre>') in body
    assert body.count('<tr class="check-ok">') == 3


def test_several_vlans_one_divergent(client, access, switch_shell, monkeypatch):
    # The switch ignores the name of VLAN 20 only: the alert names that VLAN, the others are OK
    execute = switch_shell._execute
    monkeypatch.setattr(switch_shell, "_execute",
                        lambda self, line: None if line == "name VLAN_VOZ" else execute(self, line))
    body = post(client, access, action="create_vlan", vlan_id=["10", "20"],
                vlan_name=["VLAN_DADOS", "VLAN_VOZ"]).get_data(as_text=True)
    assert 'data-status="divergence"' in body
    assert "<li>VLAN 20: esperado VLAN_VOZ, encontrado VLAN0020</li>" in body
    assert body.count('<tr class="check-ok">') == 1


def test_empty_rows_are_ignored(client, access, switch_shell):
    body = post(client, access, action="create_vlan", vlan_id=["", "30", " "],
                vlan_name=["", "CFTV", ""]).get_data(as_text=True)
    assert "VLAN 30 (CFTV) criada com sucesso." in body


@pytest.mark.parametrize("ids, names, message", [
    (["10", "10"], ["A", "B"], "Linha 2: a VLAN 10 aparece mais de uma vez."),
    (["10", "4095"], ["A", "B"], "Linha 2: VLAN ID deve ser um número entre 1 e 4094."),
    (["10", "20"], ["A", "com espaco"], "Linha 2: Nome da VLAN deve ter"),
    (["", ""], ["", ""], "Informe pelo menos uma VLAN"),
])
def test_vlan_list_errors(client, ids, names, message):
    # Rejected before connecting: the switch address isn't even reachable
    access = {"ip": "192.0.2.1", "port": "22", "username": "u", "password": "p"}
    body = post(client, access, action="create_vlan", vlan_id=ids, vlan_name=names).get_data(as_text=True)
    assert 'data-status="error"' in body
    assert message in body


def test_too_many_vlans(client):
    access = {"ip": "192.0.2.1", "port": "22", "username": "u", "password": "p"}
    ids = [str(i) for i in range(2, 53)]
    body = post(client, access, action="create_vlan", vlan_id=ids, vlan_name=["V%s" % i for i in ids]).get_data(as_text=True)
    assert "no máximo 50 VLANs" in body


def test_change_hostname(client, access, switch_shell):
    r = post(client, access, action="hostname", hostname="SW_ANDAR1")
    body = r.get_data(as_text=True)
    assert SUCCESS in body
    assert switch_shell.state["hostname"] == "SW_ANDAR1"
    assert '<pre id="cmd-commands" class="terminal">configure terminal\nhostname SW_ANDAR1\nend</pre>' in body
    assert "show running-config | include ^hostname" in body
    assert '<pre id="cmd-verification" class="terminal">hostname SW_ANDAR1</pre>' in body

    # Second change starts from the new prompt
    post(client, access, action="hostname", hostname="SW-ANDAR2")
    assert switch_shell.state["hostname"] == "SW-ANDAR2"


def test_save_config(client, access, switch_shell):
    post(client, access, action="create_vlan", vlan_id="20", vlan_name="VOZ")
    assert 20 not in switch_shell.startup["vlans"]

    r = post(client, access, action="save")
    body = r.get_data(as_text=True)
    assert SUCCESS in body
    assert "[OK]" in body
    assert switch_shell.startup == switch_shell.state
    assert '<pre id="cmd-commands" class="terminal">write memory</pre>' in body
    assert "show startup-config" in body
    assert "hostname SW-LAB" in body


def test_backup(client, access, switch_shell):
    post(client, access, action="create_vlan", vlan_id="30", vlan_name="CFTV")
    r = post(client, access, action="backup")
    assert r.headers["Content-Disposition"].startswith("attachment; filename=SW-LAB_")
    config = r.get_data(as_text=True)
    assert "hostname SW-LAB" in config
    # VLANs come from show vlan brief, before the interfaces; default ones (1, 1002-1005) are left out
    assert "vlan 30\n name CFTV\n!\ninterface GigabitEthernet0/1" in config
    assert "vlan 1\n" not in config
    assert "vlan 1002" not in config


def test_validation_before_connecting(client):
    # Unreachable switch: an invalid input must be rejected without trying to connect
    access = {"ip": "192.0.2.1", "port": "22", "username": "u", "password": "p"}
    r = post(client, access, action="create_vlan", vlan_id="1002", vlan_name="X")
    assert "reservada" in r.get_data(as_text=True)


def test_invalid_port(client, access):
    r = post(client, {**access, "port": "abc"}, action="save")
    assert "Porta SSH" in r.get_data(as_text=True)


def test_invalid_action(client, access):
    r = post(client, access, action="apagar_tudo")
    assert "Ação inválida" in r.get_data(as_text=True)


def test_wrong_password(client, access, switch_shell):
    r = post(client, {**access, "password": "errada"}, action="save")
    assert "autenticação" in r.get_data(as_text=True)


def test_backup_does_not_duplicate_vtp_transparent_vlans():
    # In VTP transparent mode the running-config already lists the VLANs: don't add them again
    from types import SimpleNamespace
    from app.models.switch import Switch
    brief = "VLAN Name   Status    Ports\n---- ------ --------- -----\n1    default  active\n40   WIFI     active\n"
    sw = Switch("127.0.0.1", "u", "p")
    sw.conn = SimpleNamespace(send_command=lambda cmd: brief)
    config = "hostname SW\n!\nvlan 40\n name WIFI\n!\ninterface Gi0/1\n!\nend"
    assert sw._with_vlans(config) == config
