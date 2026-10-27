import socket

import pytest

from app import create_app
from tests import fake_switch


def porta_livre():
    with socket.socket() as s:
        s.bind((fake_switch.HOST, 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def porta_switch():
    """Fake switch on a free port, so tests don't collide with a lab switch on 6000."""
    porta = porta_livre()
    net = fake_switch.cria_switch(porta)
    net.start()
    yield porta
    net.stop()


@pytest.fixture
def switch_fake(porta_switch):
    """Shell class of the fake switch, with state reset before each test."""
    fake_switch.SwitchShell.reset()
    return fake_switch.SwitchShell


@pytest.fixture
def client():
    app = create_app()
    # CSRF has its own tests (test_csrf.py); the rest post the form directly
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client()


@pytest.fixture
def acesso(porta_switch):
    return {"ip": fake_switch.HOST, "port": str(porta_switch),
            "username": fake_switch.USERNAME, "password": fake_switch.PASSWORD}
