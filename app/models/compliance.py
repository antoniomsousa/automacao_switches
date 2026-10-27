import re
from dataclasses import dataclass

# Standard configuration from the challenge. VLAN 50 is "VLAN_SEGURANCA": the frontend converts accented
# letters to ASCII (VLAN_SEGURANÇA -> VLAN_SEGURANCA), see validation.to_ascii
STANDARD_HOSTNAME = "SWITCH_AUTOMATIZADO"
STANDARD_VLANS = {10: "VLAN_DADOS", 20: "VLAN_VOZ", 50: "VLAN_SEGURANCA"}

# A VLAN line in show vlan brief / show vlan id: "10   VLAN_DADOS   active   Gi0/1"
VLAN_LINE = re.compile(r"^(\d+)\s+(\S+)\s+(?:active|act/|sus)", re.M)


@dataclass
class Check:
    """One item of the switch compared with the desired configuration."""
    item: str
    expected: str
    found: str

    @property
    def ok(self):
        return self.expected == self.found

    @property
    def divergence(self):
        return "%s: esperado %s, encontrado %s" % (self.item, self.expected, self.found)


def parse_vlans(output):
    """{vlan_id: name} from show vlan brief or show vlan id."""
    return {int(vlan_id): name for vlan_id, name in VLAN_LINE.findall(output)}


def parse_hostname(output):
    m = re.search(r"^hostname (\S+)", output, re.M)
    return m.group(1) if m else None


def vlan_check(output, vlan_id, vlan_name):
    found = parse_vlans(output).get(int(vlan_id))
    return Check("VLAN %s" % vlan_id, vlan_name, found or "(não existe)")


def hostname_check(output, hostname):
    return Check("Hostname", hostname, parse_hostname(output) or "(não encontrado)")


def standard_checks(vlans_output, hostname_output):
    """The switch compared with the standard configuration: each standard VLAN, then the hostname."""
    vlans = parse_vlans(vlans_output)
    checks = [Check("VLAN %d" % vlan_id, name, vlans.get(vlan_id, "(não existe)"))
              for vlan_id, name in sorted(STANDARD_VLANS.items())]
    checks.append(hostname_check(hostname_output, STANDARD_HOSTNAME))
    return checks
