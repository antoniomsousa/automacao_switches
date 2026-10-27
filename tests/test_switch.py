"""Tests of every app action against the fake switch, through the Flask test client."""
from tests import fake_switch

SUCESSO = 'data-status="sucesso"'


def post(client, acesso, **dados):
    return client.post("/switch", data={**acesso, **dados})


def test_home_redireciona_para_formulario(client):
    r = client.get("/")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/switch")


def test_formulario(client):
    r = client.get("/switch")
    assert r.status_code == 200
    assert 'value="hostname"' in r.get_data(as_text=True)


def test_arquivos_estaticos(client):
    for caminho in ("/static/css/style.css", "/static/js/app.js", "/static/img/switch-automation.svg"):
        assert client.get(caminho).status_code == 200, caminho


def test_criar_vlan(client, acesso, switch_fake):
    r = post(client, acesso, acao="criar_vlan", vlan_id="10", vlan_name="USUARIOS")
    corpo = r.get_data(as_text=True)
    assert SUCESSO in corpo
    assert switch_fake.state["vlans"][10] == "USUARIOS"
    # Result page shows commands, switch output and the verification show command
    assert '<pre id="cmd-comandos" class="terminal">configure terminal\nvlan 10\nname USUARIOS\nend</pre>' in corpo
    assert "(config-vlan)#" in corpo
    assert "show vlan id 10" in corpo
    assert "10   USUARIOS" in corpo


def test_criar_vlan_rejeitada(client, acesso, switch_fake, monkeypatch):
    # Device without VLAN support (e.g. a router image) answers "% Invalid input" to "vlan <id>"
    executa = switch_fake._executa
    monkeypatch.setattr(switch_fake, "_executa",
                        lambda self, line: fake_switch.INVALID if line.startswith("vlan ") else executa(self, line))
    r = post(client, acesso, acao="criar_vlan", vlan_id="20", vlan_name="USUARIOS")
    corpo = r.get_data(as_text=True)
    assert SUCESSO not in corpo
    assert "rejeitou o comando" in corpo
    assert 20 not in switch_fake.state["vlans"]


def test_alterar_hostname(client, acesso, switch_fake):
    r = post(client, acesso, acao="hostname", hostname="SW_ANDAR1")
    corpo = r.get_data(as_text=True)
    assert SUCESSO in corpo
    assert switch_fake.state["hostname"] == "SW_ANDAR1"
    assert '<pre id="cmd-comandos" class="terminal">configure terminal\nhostname SW_ANDAR1\nend</pre>' in corpo
    assert "show running-config | include hostname" in corpo
    assert '<pre id="cmd-verificacao" class="terminal">hostname SW_ANDAR1</pre>' in corpo

    # Second change starts from the new prompt
    post(client, acesso, acao="hostname", hostname="SW-ANDAR2")
    assert switch_fake.state["hostname"] == "SW-ANDAR2"


def test_salvar_config(client, acesso, switch_fake):
    post(client, acesso, acao="criar_vlan", vlan_id="20", vlan_name="VOZ")
    assert 20 not in switch_fake.startup["vlans"]

    r = post(client, acesso, acao="salvar")
    corpo = r.get_data(as_text=True)
    assert SUCESSO in corpo and "[OK]" in corpo
    assert switch_fake.startup == switch_fake.state
    assert '<pre id="cmd-comandos" class="terminal">write memory</pre>' in corpo
    assert "show startup-config" in corpo
    assert "vlan 20\n name VOZ" in corpo


def test_backup(client, acesso, switch_fake):
    post(client, acesso, acao="criar_vlan", vlan_id="30", vlan_name="CFTV")
    r = post(client, acesso, acao="backup")
    assert r.headers["Content-Disposition"].startswith("attachment; filename=SW-LAB_")
    config = r.get_data(as_text=True)
    assert "hostname SW-LAB" in config
    assert "vlan 30\n name CFTV" in config


def test_validacao_antes_de_conectar(client):
    # Unreachable switch: an invalid input must be rejected without trying to connect
    acesso = {"ip": "192.0.2.1", "port": "22", "username": "u", "password": "p"}
    r = post(client, acesso, acao="criar_vlan", vlan_id="1002", vlan_name="X")
    assert "reservada" in r.get_data(as_text=True)


def test_porta_invalida(client, acesso):
    r = post(client, {**acesso, "port": "abc"}, acao="salvar")
    assert "Porta SSH" in r.get_data(as_text=True)


def test_acao_invalida(client, acesso):
    r = post(client, acesso, acao="apagar_tudo")
    assert "Ação inválida" in r.get_data(as_text=True)


def test_senha_errada(client, acesso, switch_fake):
    r = post(client, {**acesso, "password": "errada"}, acao="salvar")
    assert "autenticação" in r.get_data(as_text=True)
