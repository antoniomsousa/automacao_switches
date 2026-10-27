import socket

import pytest

from app import create_app
from tests import fake_switch


def free_port():
    with socket.socket() as s:
        s.bind((fake_switch.HOST, 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def switch_port():
    """Fake switch on a free port, so tests don't collide with a lab switch on 6000."""
    port = free_port()
    net = fake_switch.create_switch(port)
    net.start()
    yield port
    net.stop()


@pytest.fixture
def switch_shell(switch_port):
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
def access(switch_port):
    return {"ip": fake_switch.HOST, "port": str(switch_port),
            "username": fake_switch.USERNAME, "password": fake_switch.PASSWORD}
