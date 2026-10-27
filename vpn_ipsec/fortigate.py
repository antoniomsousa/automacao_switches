"""FortiGate side: desired objects for the VPN and a small FortiOS REST API client (/api/v2/cmdb, /api/v2/monitor).

Changes apply immediately on FortiOS (no commit), so objects are created in dependency order and removed in
reverse order on rollback.
"""
import ipaddress

import requests

from vpn_ipsec.params import fortigate_proposals

# Fields FortiOS never returns in clear text, so they can't be compared on read-back
SECRET_FIELDS = {"psksecret"}


class FortiGateError(Exception):
    pass


def names(*values):
    """FortiOS list-of-names format: [{"name": "port1"}, ...]."""
    return [{"name": v} for v in values]


def desired_objects(p, psk):
    """Objects in creation order. Each one: path, data, and how to find it (key=mkey in the URL, or match=field)."""
    fgt, pan = p["fortigate"], p["paloalto"]
    prop = fortigate_proposals(p)
    tun = fgt["tunnel_interface"]
    local, remote = "%s-local" % p["vpn_name"], "%s-remote" % p["vpn_name"]
    tunnel_net = ipaddress.ip_network(p["tunnel_network"])

    return [
        {"path": "firewall/address", "key": local,
         "data": {"name": local, "subnet": fgt["lan_network"], "comment": "LAN %s" % p["vpn_name"]}},
        {"path": "firewall/address", "key": remote,
         "data": {"name": remote, "subnet": pan["lan_network"], "comment": "Remote LAN %s" % p["vpn_name"]}},
        {"path": "vpn.ipsec/phase1-interface", "key": tun, "data": {
            "name": tun, "type": "static", "interface": fgt["wan_interface"], "ike-version": "2",
            "remote-gw": str(ipaddress.ip_interface(pan["wan_ip"]).ip), "peertype": "any",
            "proposal": prop["phase1"], "dhgrp": prop["phase1_dh"], "keylife": p["ike"]["lifetime"],
            "authmethod": "psk", "psksecret": psk, "net-device": "disable",
            "dpd": "on-idle" if p["ike"]["dpd"] else "disable",
            "nattraversal": "enable" if p["ike"]["nat_traversal"] else "disable",
        }},
        {"path": "vpn.ipsec/phase2-interface", "key": "%s-P2" % tun, "data": {
            "name": "%s-P2" % tun, "phase1name": tun, "proposal": prop["phase2"],
            "pfs": "enable", "dhgrp": prop["phase2_dh"], "keylifeseconds": p["ipsec"]["lifetime"],
            "src-addr-type": "name", "src-name": local, "dst-addr-type": "name", "dst-name": remote,
        }},
        # The phase1-interface creates the tunnel interface; give it its /30 address and allow ping (tunnel monitor)
        {"path": "system/interface", "key": tun, "update_only": True, "data": {
            "name": tun, "ip": "%s 255.255.255.255" % fgt["tunnel_ip"],
            "remote-ip": "%s %s" % (pan["tunnel_ip"], tunnel_net.netmask), "allowaccess": "ping",
        }},
        {"path": "router/static", "match": "comment", "id": "seq-num", "data": {
            "dst": pan["lan_network"], "device": tun, "comment": "%s route" % p["vpn_name"],
        }},
        # Blackhole with a worse distance: if the tunnel drops, traffic to the remote LAN isn't sent out the WAN
        {"path": "router/static", "match": "comment", "id": "seq-num", "data": {
            "dst": pan["lan_network"], "blackhole": "enable", "distance": 254,
            "comment": "%s blackhole" % p["vpn_name"],
        }},
        {"path": "firewall/policy", "match": "name", "id": "policyid", "data": {
            "name": "%s-out" % p["vpn_name"], "srcintf": names(fgt["lan_interface"]), "dstintf": names(tun),
            "srcaddr": names(local), "dstaddr": names(remote), "action": "accept", "schedule": "always",
            "service": names("ALL"), "nat": "disable", "logtraffic": "all",
        }},
        {"path": "firewall/policy", "match": "name", "id": "policyid", "data": {
            "name": "%s-in" % p["vpn_name"], "srcintf": names(tun), "dstintf": names(fgt["lan_interface"]),
            "srcaddr": names(remote), "dstaddr": names(local), "action": "accept", "schedule": "always",
            "service": names("ALL"), "nat": "disable", "logtraffic": "all",
        }},
    ]


def _normalize(value):
    # Lists of {"name": ...} come back with extra keys (q_origin_key); compare only the names
    if isinstance(value, list):
        return sorted(v.get("name") if isinstance(v, dict) else v for v in value)
    # FortiOS returns "10.20.0.0 255.255.255.0" for a subnet sent as "10.20.0.0/24"
    text = str(value)
    if "." not in text:
        return text
    try:
        return ipaddress.ip_interface(text.replace(" ", "/")).with_prefixlen
    except ValueError:
        return text


def differences(current, desired):
    """Fields of `desired` whose value on the device differs (secrets skipped)."""
    return [k for k, v in desired.items()
            if k not in SECRET_FIELDS and _normalize(current.get(k, "")) != _normalize(v)]


class FortiGate:
    """FortiOS REST API with an API token (System > Administrators > REST API Admin)."""

    def __init__(self, host, token, vdom="root", verify=True, timeout=15, session=None):
        self.base = "https://%s/api/v2" % host
        self.vdom = vdom
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers["Authorization"] = "Bearer %s" % token
        self.session.verify = verify

    def _request(self, method, path, **kwargs):
        params = {"vdom": self.vdom, **kwargs.pop("params", {})}
        r = self.session.request(method, "%s/%s" % (self.base, path), params=params, timeout=self.timeout, **kwargs)
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise FortiGateError("%s %s -> HTTP %d: %s" % (method, path, r.status_code, r.text[:300]))
        return r.json()

    @staticmethod
    def _cmdb(path, mkey=None):
        return "cmdb/%s" % path if mkey is None else "cmdb/%s/%s" % (path, mkey)

    def find(self, obj):
        """Current object on the device, or None."""
        if "key" in obj:
            body = self._request("GET", self._cmdb(obj["path"], obj["key"]))
        else:
            field = obj["match"]
            body = self._request("GET", self._cmdb(obj["path"]), params={"filter": "%s==%s" % (field, obj["data"][field])})
        results = (body or {}).get("results") or []
        return results[0] if results else None

    def ensure(self, obj):
        """Create or update the object to match the desired data. Returns 'created', 'updated' or 'unchanged'."""
        current = self.find(obj)
        if current is None:
            if obj.get("update_only"):
                raise FortiGateError("%s %s does not exist" % (obj["path"], obj["key"]))
            self._request("POST", self._cmdb(obj["path"]), json=obj["data"])
            return "created"
        if not differences(current, obj["data"]):
            return "unchanged"
        mkey = obj.get("key") or current[obj["id"]]
        self._request("PUT", self._cmdb(obj["path"], mkey), json=obj["data"])
        return "updated"

    def delete(self, obj):
        current = self.find(obj)
        if current is not None and not obj.get("update_only"):
            mkey = obj.get("key") or current[obj["id"]]
            self._request("DELETE", self._cmdb(obj["path"], mkey))

    def backup(self):
        """Full configuration as text (kept by the deploy script before any change)."""
        r = self.session.get("%s/monitor/system/config/backup" % self.base, params={"scope": "global"},
                             timeout=self.timeout)
        if r.status_code >= 400:
            raise FortiGateError("config backup -> HTTP %d" % r.status_code)
        return r.text

    def bring_up(self, p1name, p2name):
        self._request("POST", "monitor/vpn/ipsec/tunnel_up", json={"p1name": p1name, "p2name": p2name})

    def tunnel_status(self, p1name):
        """{'up': bool, 'incoming_bytes': int, 'outgoing_bytes': int} from the IPsec monitor, None if not found."""
        body = self._request("GET", "monitor/vpn/ipsec") or {}
        for tunnel in body.get("results", []):
            if tunnel.get("name") == p1name:
                proxies = tunnel.get("proxyid", [])
                return {
                    "up": any(px.get("status") == "up" for px in proxies),
                    "incoming_bytes": tunnel.get("incoming_bytes", 0),
                    "outgoing_bytes": tunnel.get("outgoing_bytes", 0),
                }
        return None
