"""Palo Alto side: desired objects for the VPN and a small PAN-OS XML API client (/api/?type=...).

PAN-OS changes go to the candidate configuration and only take effect on commit, so the deploy script can
revert the candidate if any step fails, and roll back to a saved snapshot if the commit or validation fails.
"""
import ipaddress
import time
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import requests

from vpn_ipsec.params import paloalto_proposals

DEVICE = "/config/devices/entry[@name='localhost.localdomain']"
# Elements PAN-OS returns encrypted, so they can't be compared on read-back
SECRET_TAGS = {"key"}


class PaloAltoError(Exception):
    pass


def members(*values):
    return "".join("<member>%s</member>" % escape(v) for v in values)


def desired_objects(p, psk):
    """(action, xpath, element) in order. 'edit' replaces the whole entry (idempotent); 'set' merges into a list."""
    pan, fgt = p["paloalto"], p["fortigate"]
    prop = paloalto_proposals(p)
    name = p["vpn_name"]
    vsys = "%s/vsys/entry[@name='%s']" % (DEVICE, pan["vsys"])
    vr = "%s/network/virtual-router/entry[@name='%s']" % (DEVICE, pan["virtual_router"])
    tun = pan["tunnel_interface"]
    ike_profile, ipsec_profile, gateway = "%s-IKE" % name, "%s-IPSEC" % name, "%s-GW" % name
    local, remote = "%s-local" % name, "%s-remote" % name
    prefix = ipaddress.ip_network(p["tunnel_network"]).prefixlen
    yes_no = {True: "yes", False: "no"}

    def entry(path, entry_name, body):
        xpath = "%s/entry[@name='%s']" % (path, entry_name)
        return ("edit", xpath, "<entry name=\"%s\">%s</entry>" % (escape(entry_name), body))

    return [
        entry(DEVICE + "/network/ike/crypto-profiles/ike-crypto-profiles", ike_profile,
              "<encryption>%s</encryption><hash>%s</hash><dh-group>%s</dh-group><lifetime><seconds>%d</seconds></lifetime>"
              % (members(prop["ike_encryption"]), members(prop["ike_hash"]), members(prop["ike_dh"]), p["ike"]["lifetime"])),
        entry(DEVICE + "/network/ike/crypto-profiles/ipsec-crypto-profiles", ipsec_profile,
              "<esp><encryption>%s</encryption><authentication>%s</authentication></esp>"
              "<dh-group>%s</dh-group><lifetime><seconds>%d</seconds></lifetime>"
              % (members(prop["esp_encryption"]), members(prop["esp_authentication"]), prop["esp_dh"], p["ipsec"]["lifetime"])),
        # Lets the tunnel answer ping, used by the tunnel monitor on both ends
        entry(DEVICE + "/network/profiles/interface-management-profile", "%s-ping" % name, "<ping>yes</ping>"),
        entry(DEVICE + "/network/interface/tunnel/units", tun,
              "<ip><entry name=\"%s/%d\"/></ip><interface-management-profile>%s-ping</interface-management-profile>"
              "<comment>%s</comment>" % (pan["tunnel_ip"], prefix, escape(name), escape(name))),
        # A layer 3 interface must belong to a virtual router, a zone and the vsys
        ("set", vr + "/interface", members(tun)),
        ("set", vsys + "/import/network/interface", members(tun)),
        entry(vsys + "/zone", pan["vpn_zone"], "<network><layer3>%s</layer3></network>" % members(tun)),
        entry(DEVICE + "/network/ike/gateway", gateway,
              "<authentication><pre-shared-key><key>%s</key></pre-shared-key></authentication>"
              "<protocol><version>ikev2</version><ikev2><ike-crypto-profile>%s</ike-crypto-profile>"
              "<dpd><enable>%s</enable></dpd></ikev2></protocol>"
              "<protocol-common><nat-traversal><enable>%s</enable></nat-traversal></protocol-common>"
              "<local-address><interface>%s</interface><ip>%s</ip></local-address>"
              "<peer-address><ip>%s</ip></peer-address>"
              % (escape(psk), ike_profile, yes_no[p["ike"]["dpd"]], yes_no[p["ike"]["nat_traversal"]],
                 pan["wan_interface"], pan["wan_ip"], ipaddress.ip_interface(fgt["wan_ip"]).ip)),
        # Proxy-ID mirrors the FortiGate phase2 selectors (local/remote swapped); IKEv2 needs them to match
        entry(DEVICE + "/network/tunnel/ipsec", name,
              "<tunnel-interface>%s</tunnel-interface>"
              "<auto-key><ike-gateway><entry name=\"%s\"/></ike-gateway><ipsec-crypto-profile>%s</ipsec-crypto-profile>"
              "<proxy-id><entry name=\"%s\"><local>%s</local><remote>%s</remote><protocol><any/></protocol></entry></proxy-id>"
              "</auto-key><tunnel-monitor><enable>yes</enable><destination-ip>%s</destination-ip></tunnel-monitor>"
              % (tun, gateway, ipsec_profile, "%s-lans" % name, pan["lan_network"], fgt["lan_network"], fgt["tunnel_ip"])),
        entry(vr + "/routing-table/ip/static-route", "%s-route" % name,
              "<destination>%s</destination><interface>%s</interface><metric>10</metric>" % (fgt["lan_network"], tun)),
        entry(vsys + "/address", local, "<ip-netmask>%s</ip-netmask>" % pan["lan_network"]),
        entry(vsys + "/address", remote, "<ip-netmask>%s</ip-netmask>" % fgt["lan_network"]),
        entry(vsys + "/rulebase/security/rules", "%s-out" % name,
              "<from>%s</from><to>%s</to><source>%s</source><destination>%s</destination>"
              "<source-user>%s</source-user><application>%s</application><service>%s</service>"
              "<action>allow</action><log-end>yes</log-end>"
              % (members(pan["lan_zone"]), members(pan["vpn_zone"]), members(local), members(remote),
                 members("any"), members("any"), members("any"))),
        entry(vsys + "/rulebase/security/rules", "%s-in" % name,
              "<from>%s</from><to>%s</to><source>%s</source><destination>%s</destination>"
              "<source-user>%s</source-user><application>%s</application><service>%s</service>"
              "<action>allow</action><log-end>yes</log-end>"
              % (members(pan["vpn_zone"]), members(pan["lan_zone"]), members(remote), members(local),
                 members("any"), members("any"), members("any"))),
    ]


def contains(actual, desired):
    """True if every leaf of `desired` exists in `actual` with the same text (children matched by tag and name)."""
    if desired.tag in SECRET_TAGS:
        return True
    children = list(desired)
    if not children:
        return (actual.text or "").strip() == (desired.text or "").strip()
    for child in children:
        candidates = [c for c in actual if c.tag == child.tag and c.get("name") == child.get("name")]
        if not any(contains(c, child) for c in candidates):
            return False
    return True


class PaloAlto:
    """PAN-OS XML API with an API key (generated with type=keygen)."""

    def __init__(self, host, api_key, verify=True, timeout=30, session=None):
        self.url = "https://%s/api/" % host
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers["X-PAN-KEY"] = api_key
        self.session.verify = verify

    def _call(self, **params):
        r = self.session.post(self.url, data=params, timeout=self.timeout)
        if r.status_code >= 400:
            raise PaloAltoError("HTTP %d: %s" % (r.status_code, r.text[:300]))
        root = ET.fromstring(r.text)
        if root.get("status") != "success":
            msg = " ".join(t.strip() for t in root.itertext() if t.strip())
            raise PaloAltoError("%s %s: %s" % (params.get("type"), params.get("action", ""), msg[:300]))
        return root

    def op(self, cmd):
        return self._call(type="op", cmd=cmd)

    def apply(self, action, xpath, element):
        self._call(type="config", action=action, xpath=xpath, element=element)

    def running(self, xpath):
        """Element at xpath in the running configuration, or None."""
        root = self._call(type="config", action="show", xpath=xpath)
        result = root.find("result")
        return result[0] if result is not None and len(result) else None

    def drift(self, objects):
        """xpaths whose running configuration doesn't contain the desired element."""
        drifted = []
        for action, xpath, element in objects:
            desired = ET.fromstring("<wrap>%s</wrap>" % element if action == "set" else element)
            actual = self.running(xpath)
            if action == "set":
                # Members merged into a list: each desired member must be present
                ok = actual is not None and {m.text for m in desired} <= {m.text for m in actual.iter("member")}
            else:
                ok = actual is not None and contains(actual, desired)
            if not ok:
                drifted.append(xpath)
        return drifted

    def save_snapshot(self, name):
        self.op("<save><config><to>%s</to></config></save>" % escape(name))

    def load_snapshot(self, name):
        self.op("<load><config><from>%s</from></config></load>" % escape(name))

    def revert_candidate(self):
        self.op("<revert><config></config></revert>")

    def commit(self, poll_interval=5, max_wait=600):
        """Commit the candidate configuration and wait for the job; raises if it fails."""
        root = self._call(type="commit", cmd="<commit></commit>")
        job = root.findtext(".//job")
        if not job:
            return "no changes to commit"
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            # The response is wrapped in <result> too, so read status/result inside <job>
            status = self.op("<show><jobs><id>%s</id></jobs></show>" % job).find(".//job")
            if status is not None and status.findtext("status") == "FIN":
                if status.findtext("result") != "OK":
                    details = status.find("details")
                    text = " ".join(t.strip() for t in details.itertext() if t.strip()) if details is not None else ""
                    raise PaloAltoError("commit job %s failed: %s" % (job, text))
                return "commit job %s OK" % job
            time.sleep(poll_interval)
        raise PaloAltoError("commit job %s did not finish in %ds" % (job, max_wait))

    def bring_up(self, gateway, tunnel):
        self.op("<test><vpn><ike-sa><gateway>%s</gateway></ike-sa></vpn></test>" % escape(gateway))
        self.op("<test><vpn><ipsec-sa><tunnel>%s</tunnel></ipsec-sa></vpn></test>" % escape(tunnel))

    def tunnel_status(self, tunnel):
        """{'up': bool} from 'show vpn flow name <tunnel>' (state 'active' when the IPsec SA is up)."""
        root = self.op("<show><vpn><flow><name>%s</name></flow></vpn></show>" % escape(tunnel))
        states = [e.text for e in root.iter("state")]
        if not states:
            return None
        return {"up": "active" in states}
