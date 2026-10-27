"""Part 2: VPN parameters, the FortiGate/Palo Alto automation (against in-memory APIs) and the connectivity test."""
import copy

import pytest

from tests.fake_firewalls import FakeFortiOS, FakePanOS, FakeResponse
from vpn_ipsec import alerts, connectivity_test, deploy, params
from vpn_ipsec.fortigate import FortiGate
from vpn_ipsec.paloalto import PaloAlto

PSK = "s3cr3t-psk-for-tests"


@pytest.fixture
def p():
    return params.load()


@pytest.fixture
def firewalls(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # the FortiGate backup file is written in the current directory
    monkeypatch.setenv("VPN_PSK", PSK)
    monkeypatch.delenv("ALERT_WEBHOOK_URL", raising=False)
    fos, pan = FakeFortiOS(), FakePanOS()
    return fos, pan, FortiGate("fgt", "token", session=fos), PaloAlto("pan", "key", session=pan)


def broken(p, change):
    bad = copy.deepcopy(p)
    change(bad)
    with pytest.raises(params.ParamsError) as e:
        params.validate(bad)
    return " ".join(e.value.errors)


# Parameters

def test_default_params_are_valid(p):
    assert p["tunnel_network"] == "169.255.1.0/30"
    assert (p["fortigate"]["tunnel_ip"], p["paloalto"]["tunnel_ip"]) == ("169.255.1.1", "169.255.1.2")


@pytest.mark.parametrize("change, message", [
    (lambda b: b.update(tunnel_network="169.255.1.0/29"), "must be a /30"),
    (lambda b: b["paloalto"].update(tunnel_ip="169.255.1.5"), "two usable addresses"),
    (lambda b: b["paloalto"].update(lan_network="10.10.0.0/16"), "LAN networks overlap"),
    (lambda b: b["fortigate"].update(lan_network="169.255.1.0/24"), "overlaps the tunnel network"),
    (lambda b: b["paloalto"].update(wan_ip="203.0.113.1/24"), "WAN IPs must be different"),
    (lambda b: b["fortigate"].update(tunnel_interface="NAME-LONGER-THAN-15"), "at most 15"),
    (lambda b: b["paloalto"].update(tunnel_interface="tun10"), "tunnel.<1-9999>"),
    (lambda b: b["ike"].update(version=1), "only IKEv2"),
    (lambda b: b["ike"].update(encryption="3des"), "ike.encryption"),
    (lambda b: b["ike"].update(dh_group=2), "ike.dh_group"),
    (lambda b: b["ipsec"].update(integrity="md5"), "ipsec.integrity"),
    (lambda b: b["ipsec"].update(lifetime=30000), "shorter than ike.lifetime"),
    (lambda b: b.pop("tunnel_network"), "missing parameter"),
    (lambda b: b["fortigate"].update(wan_ip="not-an-ip"), "does not appear to be"),
])
def test_invalid_params(p, change, message):
    assert message in broken(p, change)


def test_reports_all_errors_at_once(p):
    errors = broken(p, lambda b: (b["ike"].update(encryption="des"), b["ipsec"].update(pfs_group=5)))
    assert "ike.encryption" in errors
    assert "ipsec.pfs_group" in errors


def test_proposals_translated_per_vendor(p):
    assert params.fortigate_proposals(p) == {"phase1": "aes256-sha256", "phase1_dh": "14",
                                             "phase2": "aes256-sha256", "phase2_dh": "14"}
    pan = params.paloalto_proposals(p)
    assert (pan["ike_encryption"], pan["ike_dh"], pan["esp_authentication"]) == ("aes-256-cbc", "group14", "sha256")


def test_gcm_in_phase2(p):
    p["ipsec"]["encryption"] = "aes256gcm"
    params.validate(p)
    assert params.fortigate_proposals(p)["phase2"] == "aes256gcm"
    assert params.paloalto_proposals(p)["esp_authentication"] == "none"


def test_psk_comes_from_environment(p, monkeypatch):
    monkeypatch.setenv("VPN_PSK", "short")
    with pytest.raises(params.ParamsError):
        params.read_psk(p)
    monkeypatch.setenv("VPN_PSK", PSK)
    assert params.read_psk(p) == PSK


# Automation

def test_plan_masks_psk(p, capsys, monkeypatch):
    monkeypatch.setenv("VPN_PSK", PSK)
    assert deploy.main(["plan"]) == 0
    out = capsys.readouterr().out
    assert PSK not in out
    assert "vpn.ipsec/phase1-interface" in out
    assert "<proxy-id><entry name=\"FGT-PA-lans\"><local>10.20.0.0/24</local><remote>10.10.0.0/24</remote>" in out


def test_apply_configures_both_sides_and_validates(p, firewalls):
    fos, pan, fgt, pa = firewalls
    assert deploy.apply(p, fgt, pa, wait_up=0)
    phase1 = fos.tables["vpn.ipsec/phase1-interface"][0]
    assert (phase1["remote-gw"], phase1["proposal"], phase1["dhgrp"]) == ("198.51.100.1", "aes256-sha256", "14")
    assert fos.tables["system/interface"][0]["remote-ip"] == "169.255.1.2 255.255.255.252"
    assert len(fos.tables["firewall/policy"]) == 2
    gateway = next(v for k, v in pan.running.items() if "ike/gateway" in k)
    assert "<peer-address><ip>203.0.113.1</ip></peer-address>" in gateway
    assert "<key>%s</key>" % PSK in gateway
    assert deploy.validate(p, fgt, pa) == []


def test_apply_is_idempotent(p, firewalls):
    fos, pan, fgt, pa = firewalls
    deploy.apply(p, fgt, pa, wait_up=0)
    writes = len([c for c in fos.calls if c[0] in ("POST", "PUT")])
    assert deploy.apply(p, fgt, pa, wait_up=0)
    # Second run: only the tunnel_up call writes, every object is already as desired
    assert len([c for c in fos.calls if c[0] in ("POST", "PUT")]) == writes + 1
    assert len(fos.tables["firewall/policy"]) == 2


def test_validate_detects_drift(p, firewalls):
    fos, pan, fgt, pa = firewalls
    deploy.apply(p, fgt, pa, wait_up=0)
    fos.tables["vpn.ipsec/phase1-interface"][0]["proposal"] = "aes128-sha1"
    xpath = next(k for k in pan.running if "ipsec-crypto-profiles" in k)
    pan.running[xpath] = pan.running[xpath].replace("group14", "group2")
    problems = deploy.validate(p, fgt, pa)
    assert "FortiGate: vpn.ipsec/phase1-interface VPN-TO-PA differs in proposal" in problems
    assert any("Palo Alto: configuration differs" in x and "ipsec-crypto-profiles" in x for x in problems)


def test_validate_tunnel_down_on_one_side(p, firewalls):
    fos, pan, fgt, pa = firewalls
    deploy.apply(p, fgt, pa, wait_up=0)
    pan.tested = False
    problems = deploy.validate(p, fgt, pa)
    assert problems == ["Palo Alto: tunnel FGT-PA is down",
                        "only one side reports the tunnel down: check proposals, proxy-IDs and routing on that side"]


def test_commit_failure_rolls_back_and_alerts(p, firewalls, caplog):
    fos, _, fgt, _ = firewalls
    pan = FakePanOS(commit_ok=False)
    assert not deploy.apply(p, fgt, PaloAlto("pan", "key", session=pan), wait_up=0)
    # FortiGate objects created by this run were removed, Palo Alto candidate reverted
    assert fos.tables["vpn.ipsec/phase1-interface"] == []
    assert fos.tables["firewall/policy"] == []
    assert any(op.startswith("<revert>") for op in pan.ops)
    assert "deploy failed at Palo Alto" in caplog.text
    assert "tunnel.10 is not in a zone" in caplog.text


def test_tunnel_not_up_rolls_back_to_snapshot(p, firewalls, monkeypatch):
    fos, pan, fgt, pa = firewalls
    monkeypatch.setattr(pa, "bring_up", lambda *a: None)  # Palo Alto never negotiates
    assert not deploy.apply(p, fgt, pa, wait_up=0)
    assert any(op.startswith("<load><config><from>pre-vpn-") for op in pan.ops)
    assert fos.tables["vpn.ipsec/phase1-interface"] == []


def test_validate_without_credentials(monkeypatch):
    monkeypatch.delenv("FGT_TOKEN", raising=False)
    assert deploy.main(["validate"]) == 2


# Alerts and connectivity test

def test_alert_posted_to_webhook(monkeypatch):
    sent = []

    class Session:
        def post(self, url, json, timeout):
            sent.append((url, json))
            return FakeResponse(200, {})

    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://hooks.example/x")
    assert alerts.send_alert("VPN down", ["FortiGate: tunnel down"], session=Session())
    assert sent == [("https://hooks.example/x", {"text": "VPN down\n- FortiGate: tunnel down"})]


def test_broken_webhook_does_not_hide_failure(monkeypatch):
    class Session:
        def post(self, url, json, timeout):
            return FakeResponse(500, {})

    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://hooks.example/x")
    assert not alerts.send_alert("VPN down", [], session=Session())


@pytest.mark.parametrize("output, expected", [
    ("4 packets transmitted, 4 received, 0% packet loss, time 3004ms\nrtt min/avg/max/mdev = 1.0/2.5/4.0/0.5 ms", (0.0, 2.5)),
    ("Pacotes: Enviados = 4, Recebidos = 2, Perdidos = 2 (50% de perda),\nMínimo = 1ms, Máximo = 3ms, Média = 2ms", (50.0, 2.0)),
    ("Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),\nMinimum = 1ms, Maximum = 2ms, Average = 1ms", (0.0, 1.0)),
    ("ping: unknown host", (100.0, None)),
])
def test_parse_ping(output, expected):
    assert connectivity_test.parse_ping(output) == expected


def test_connectivity_checks_per_side(p):
    checks = connectivity_test.build_checks(p, "paloalto", ["10.10.0.5"], ["10.10.0.5:443"])
    assert [c[1] for c in checks] == ["169.255.1.2", "169.255.1.1", "10.10.0.5", ("10.10.0.5", 443)]


def test_connectivity_main(monkeypatch, caplog, capsys):
    monkeypatch.delenv("ALERT_WEBHOOK_URL", raising=False)
    # Tunnel answers, the remote LAN host doesn't (e.g. missing policy on the far side)
    monkeypatch.setattr(connectivity_test, "ping", lambda host, count: (0.0, 3.0) if host.startswith("169.") else (100.0, None))
    monkeypatch.setattr(connectivity_test, "tcp_check", lambda host, port: 12.0)
    assert connectivity_test.main(["--site", "fortigate", "--remote-host", "10.20.0.10", "--tcp", "10.20.0.10:22"]) == 1
    out = capsys.readouterr().out
    assert "[OK] remote tunnel IP (paloalto)" in out
    assert "[FAIL] remote LAN host" in out
    assert "connectivity test failed from the fortigate side" in caplog.text

    monkeypatch.setattr(connectivity_test, "ping", lambda host, count: (0.0, 3.0))
    assert connectivity_test.main(["--site", "fortigate", "--remote-host", "10.20.0.10"]) == 0
