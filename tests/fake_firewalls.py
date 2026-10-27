"""In-memory FortiOS REST API and PAN-OS XML API, plugged into the clients as their requests session."""
import json as jsonlib
import re
from urllib.parse import urlparse


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else jsonlib.dumps(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError("HTTP %d" % self.status_code)


ID_FIELDS = {"firewall/policy": "policyid", "router/static": "seq-num"}


class FakeFortiOS:
    """Behaves like FortiOS for the calls vpn_ipsec.fortigate makes, including how it formats what it returns."""

    def __init__(self):
        self.headers = {}
        self.verify = True
        self.tables = {}
        self.tunnel_up = False
        self.calls = []

    def _table(self, path):
        return self.tables.setdefault(path, [])

    @staticmethod
    def _stored(data):
        # FortiOS answers subnets as "addr mask" and adds q_origin_key to lists of names
        out = {}
        for k, v in data.items():
            if k in ("subnet", "dst") and "/" in str(v):
                import ipaddress
                net = ipaddress.ip_network(v)
                v = "%s %s" % (net.network_address, net.netmask)
            elif isinstance(v, list):
                v = [{**item, "q_origin_key": item["name"]} for item in v]
            out[k] = v
        out.pop("psksecret", None)  # never returned in clear text
        return out

    def _find(self, path, key):
        field = ID_FIELDS.get(path, "name")
        return next((o for o in self._table(path) if str(o.get(field)) == str(key)), None)

    def request(self, method, url, params=None, timeout=None, json=None):
        path = urlparse(url).path.replace("/api/v2/", "")
        self.calls.append((method, path))
        if path == "monitor/vpn/ipsec/tunnel_up":
            self.tunnel_up = True
            return FakeResponse(200, {"status": "success"})
        if path == "monitor/vpn/ipsec":
            results = [{"name": o["name"], "incoming_bytes": 10, "outgoing_bytes": 10,
                        "proxyid": [{"p2name": "x", "status": "up" if self.tunnel_up else "down"}]}
                       for o in self._table("vpn.ipsec/phase1-interface")]
            return FakeResponse(200, {"results": results})

        _, rest = path.split("cmdb/", 1)
        parts = rest.split("/")
        table, key = "/".join(parts[:2]), "/".join(parts[2:]) or None
        if method == "GET":
            if key:
                obj = self._find(table, key)
                return FakeResponse(200, {"results": [obj]}) if obj else FakeResponse(404, {})
            field, _, value = (params or {}).get("filter", "").partition("==")
            return FakeResponse(200, {"results": [o for o in self._table(table) if str(o.get(field)) == value]})
        if method == "POST":
            obj = self._stored(json)
            if table in ID_FIELDS:
                obj[ID_FIELDS[table]] = len(self._table(table)) + 1
            self._table(table).append(obj)
            if table == "vpn.ipsec/phase1-interface":
                self._table("system/interface").append({"name": json["name"], "ip": "0.0.0.0 0.0.0.0"})
            return FakeResponse(200, {"status": "success"})
        if method == "PUT":
            self._find(table, key).update(self._stored(json))
            return FakeResponse(200, {"status": "success"})
        if method == "DELETE":
            self.tables[table] = [o for o in self._table(table) if o is not self._find(table, key)]
            return FakeResponse(200, {"status": "success"})
        raise AssertionError(method)

    def get(self, url, params=None, timeout=None):
        return FakeResponse(200, text="#config-version=FGT\nconfig system global\nend\n")


def ok(result=""):
    return FakeResponse(200, text='<response status="success"><result>%s</result></response>' % result)


class FakePanOS:
    """Candidate and running configuration keyed by xpath; commit copies candidate to running."""

    def __init__(self, commit_ok=True):
        self.headers = {}
        self.verify = True
        self.candidate = {}
        self.running = {}
        self.commit_ok = commit_ok
        self.ops = []
        self.tested = False

    def post(self, url, data, timeout=None):
        kind = data["type"]
        if kind == "config":
            xpath, action = data["xpath"], data["action"]
            if action == "edit":
                self.candidate[xpath] = data["element"]
            elif action == "set":
                self.candidate[xpath] = self.candidate.get(xpath, "") + data["element"]
            elif action == "show":
                element = self.running.get(xpath)
                if element is None:
                    return ok()
                element = re.sub(r"<key>.*?</key>", "<key>-AQ==encrypted</key>", element)
                tag = xpath.rsplit("/", 1)[-1]
                return ok(element if element.startswith("<entry") else "<%s>%s</%s>" % (tag, element, tag))
            return ok()
        if kind == "commit":
            if not self.commit_ok:
                return FakeResponse(200, text='<response status="success"><result><job>7</job></result></response>')
            self.running = dict(self.candidate)
            return FakeResponse(200, text='<response status="success"><result><job>7</job></result></response>')
        if kind == "op":
            cmd = data["cmd"]
            self.ops.append(cmd)
            if cmd.startswith("<show><jobs>"):
                result = "OK" if self.commit_ok else "FAIL"
                return ok("<job><status>FIN</status><result>%s</result><details><line>%s</line></details></job>"
                          % (result, "Configuration committed" if self.commit_ok else "tunnel.10 is not in a zone"))
            if cmd.startswith("<test>"):
                self.tested = True
            if cmd.startswith("<show><vpn><flow>"):
                up = self.tested and bool(self.running)
                return ok("<IPSec><entry><name>FGT-PA</name><state>%s</state></entry></IPSec>" % ("active" if up else "init"))
            if cmd.startswith("<revert>"):
                self.candidate = dict(self.running)
            return ok()
        raise AssertionError(kind)
