"""Tests of every app action against the fake switch, through the Flask test client."""
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
    assert "show vlan id 10" in body
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


def test_change_hostname(client, access, switch_shell):
    r = post(client, access, action="hostname", hostname="SW_ANDAR1")
    body = r.get_data(as_text=True)
    assert SUCCESS in body
    assert switch_shell.state["hostname"] == "SW_ANDAR1"
    assert '<pre id="cmd-commands" class="terminal">configure terminal\nhostname SW_ANDAR1\nend</pre>' in body
    assert "show running-config | include hostname" in body
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
