"""Load and validate params.yaml, and translate the vendor-neutral proposals into each vendor's names."""
import ipaddress
import os
import re
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).with_name("params.yaml")

# Vendor-neutral name -> (FortiOS name, PAN-OS name)
P1_ENCRYPTION = {"aes128": ("aes128", "aes-128-cbc"), "aes256": ("aes256", "aes-256-cbc")}
P2_ENCRYPTION = {**P1_ENCRYPTION, "aes128gcm": ("aes128gcm", "aes-128-gcm"), "aes256gcm": ("aes256gcm", "aes-256-gcm")}
INTEGRITY = {"sha256": ("sha256", "sha256"), "sha384": ("sha384", "sha384"), "sha512": ("sha512", "sha512")}
DH_GROUPS = {14, 19, 20, 21}

MIN_PSK_LENGTH = 16


class ParamsError(Exception):
    """Invalid parameters; .errors lists every problem found, not just the first."""

    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def load(path=DEFAULT_PATH):
    with open(path, encoding="utf-8") as f:
        params = yaml.safe_load(f)
    validate(params)
    return params


def validate(p):
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)
        return condition

    try:
        tunnel = ipaddress.ip_network(p["tunnel_network"])
        fgt, pan, ike, ipsec = p["fortigate"], p["paloalto"], p["ike"], p["ipsec"]
        fgt_wan = ipaddress.ip_interface(fgt["wan_ip"])
        pan_wan = ipaddress.ip_interface(pan["wan_ip"])
        lans = [ipaddress.ip_network(fgt["lan_network"]), ipaddress.ip_network(pan["lan_network"])]
        tunnel_ips = [ipaddress.ip_address(fgt["tunnel_ip"]), ipaddress.ip_address(pan["tunnel_ip"])]
    except (KeyError, TypeError) as e:
        raise ParamsError(["missing parameter: %s" % e])
    except ValueError as e:
        raise ParamsError([str(e)])

    # Tunnel /30: each end gets one of the two usable addresses
    if check(tunnel.prefixlen == 30, "tunnel_network must be a /30 (got /%d)" % tunnel.prefixlen):
        check(sorted(tunnel_ips) == list(tunnel.hosts()),
              "tunnel IPs must be the two usable addresses of %s: %s" % (tunnel, ", ".join(map(str, tunnel.hosts()))))
    check(fgt_wan.ip != pan_wan.ip, "the two WAN IPs must be different")
    check(not lans[0].overlaps(lans[1]), "the LAN networks overlap: %s and %s" % tuple(lans))
    for lan in lans:
        check(not lan.overlaps(tunnel), "LAN %s overlaps the tunnel network %s" % (lan, tunnel))

    # Interface names each vendor accepts
    check(len(fgt["tunnel_interface"]) <= 15, "FortiGate tunnel_interface must have at most 15 characters")
    check(re.fullmatch(r"tunnel\.\d{1,4}", pan["tunnel_interface"]), "Palo Alto tunnel_interface must be tunnel.<1-9999>")

    # Proposals: only algorithms both vendors support, so phase 1/2 always match
    check(ike.get("version") == 2, "only IKEv2 is supported")
    check(ike.get("encryption") in P1_ENCRYPTION, "ike.encryption must be one of %s" % sorted(P1_ENCRYPTION))
    check(ike.get("integrity") in INTEGRITY, "ike.integrity must be one of %s" % sorted(INTEGRITY))
    check(ike.get("dh_group") in DH_GROUPS, "ike.dh_group must be one of %s" % sorted(DH_GROUPS))
    check(ipsec.get("encryption") in P2_ENCRYPTION, "ipsec.encryption must be one of %s" % sorted(P2_ENCRYPTION))
    check(is_gcm(ipsec) or ipsec.get("integrity") in INTEGRITY, "ipsec.integrity must be one of %s" % sorted(INTEGRITY))
    check(ipsec.get("pfs_group") in DH_GROUPS, "ipsec.pfs_group must be one of %s" % sorted(DH_GROUPS))
    # Ranges accepted by both FortiOS and PAN-OS
    check(isinstance(ike.get("lifetime"), int) and 600 <= ike["lifetime"] <= 86400, "ike.lifetime must be 600-86400 seconds")
    check(isinstance(ipsec.get("lifetime"), int) and 180 <= ipsec["lifetime"] <= 86400, "ipsec.lifetime must be 180-86400 seconds")
    check(ipsec.get("lifetime", 0) < ike.get("lifetime", 0), "ipsec.lifetime should be shorter than ike.lifetime")

    if errors:
        raise ParamsError(errors)


def is_gcm(ipsec):
    return str(ipsec.get("encryption", "")).endswith("gcm")


def read_psk(p):
    psk = os.environ.get(p["psk_env"], "")
    if len(psk) < MIN_PSK_LENGTH:
        raise ParamsError(["environment variable %s must hold a pre-shared key of at least %d characters"
                           % (p["psk_env"], MIN_PSK_LENGTH)])
    return psk


def fortigate_proposals(p):
    """FortiOS names: phase1 'aes256-sha256', phase2 'aes256-sha256' or 'aes256gcm' (no integrity with GCM)."""
    ike, ipsec = p["ike"], p["ipsec"]
    p1 = "%s-%s" % (P1_ENCRYPTION[ike["encryption"]][0], INTEGRITY[ike["integrity"]][0])
    p2_enc = P2_ENCRYPTION[ipsec["encryption"]][0]
    p2 = p2_enc if is_gcm(ipsec) else "%s-%s" % (p2_enc, INTEGRITY[ipsec["integrity"]][0])
    return {"phase1": p1, "phase1_dh": str(ike["dh_group"]), "phase2": p2, "phase2_dh": str(ipsec["pfs_group"])}


def paloalto_proposals(p):
    """PAN-OS names: 'aes-256-cbc', 'sha256', 'group14'; ESP authentication is 'none' with GCM."""
    ike, ipsec = p["ike"], p["ipsec"]
    return {
        "ike_encryption": P1_ENCRYPTION[ike["encryption"]][1],
        "ike_hash": INTEGRITY[ike["integrity"]][1],
        "ike_dh": "group%d" % ike["dh_group"],
        "esp_encryption": P2_ENCRYPTION[ipsec["encryption"]][1],
        "esp_authentication": "none" if is_gcm(ipsec) else INTEGRITY[ipsec["integrity"]][1],
        "esp_dh": "group%d" % ipsec["pfs_group"],
    }
