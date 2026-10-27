"""CSRF protection on the form POST."""
import re

import pytest

from app import create_app


@pytest.fixture
def client_csrf():
    return create_app().test_client()


def test_post_sem_token_rejeitado(client_csrf):
    r = client_csrf.post("/switch", data={"acao": "salvar"})
    assert r.status_code == 400
    assert "Recarregue a página" in r.get_data(as_text=True)


def test_post_com_token_do_formulario(client_csrf):
    pagina = client_csrf.get("/switch").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', pagina).group(1)
    # Invalid VLAN: passes CSRF and stops at validation, before any SSH connection
    r = client_csrf.post("/switch", data={"csrf_token": token, "acao": "criar_vlan", "vlan_id": "0", "vlan_name": "X"})
    assert r.status_code == 200
    assert "VLAN ID deve ser" in r.get_data(as_text=True)
