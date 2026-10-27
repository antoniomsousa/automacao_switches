import re
from dataclasses import dataclass, field

from netmiko import ConnectHandler
from netmiko.exceptions import ConfigInvalidException, NetmikoAuthenticationException, NetmikoTimeoutException

from app.models import compliance
from app.models.validation import RESERVED_VLANS

# IOS error messages after a rejected config command
IOS_ERROR = r"^% (Invalid input|Incomplete command|Ambiguous command)|not allowed"
SHOW_VLANS = "show vlan brief"
SHOW_HOSTNAME = "show running-config | include ^hostname"


class SwitchError(Exception):
    """Error with a message that can be shown to the user."""


@dataclass
class Execution:
    """What was done on the switch: commands sent, switch output, a show command confirming the result,
    and the checks comparing that show output with the desired configuration."""
    commands: list
    output: str
    verification_cmd: str
    verification: str
    checks: list = field(default_factory=list)

    @property
    def divergences(self):
        return [c.divergence for c in self.checks if not c.ok]


class Switch:
    """SSH session to a Cisco IOS switch. Use as a context manager: `with Switch(...) as sw:`."""

    def __init__(self, ip, username, password, port=22, secret=""):
        self.device = {
            "device_type": "cisco_ios",
            "host": ip,
            "port": port,
            "username": username,
            "password": password,
            "secret": secret,
        }
        self.conn = None

    def __enter__(self):
        try:
            self.conn = ConnectHandler(**self.device)
        except NetmikoAuthenticationException:
            raise SwitchError("Falha de autenticação no switch.")
        except NetmikoTimeoutException:
            raise SwitchError("Timeout ao conectar no switch %s." % self.device["host"])
        if self.device["secret"]:
            self.conn.enable()
        return self

    def __exit__(self, *args):
        self.conn.disconnect()

    def _execution(self, commands, output, verification_cmd):
        return Execution(commands, output, verification_cmd, self.conn.send_command(verification_cmd))

    def _configure(self, commands, **kwargs):
        """send_config_set, raising SwitchError if the switch rejects a command."""
        try:
            return self.conn.send_config_set(commands, error_pattern=IOS_ERROR, **kwargs)
        except ConfigInvalidException as e:
            raise SwitchError("O switch rejeitou o comando: %s" % e)

    def create_vlans(self, vlans):
        """Create [(vlan_id, vlan_name), ...] in a single config session, then check each one on the switch."""
        commands = [command for vlan_id, vlan_name in vlans for command in ("vlan %s" % vlan_id, "name %s" % vlan_name)]
        output = self._configure(commands)
        # send_config_set wraps the commands in configure terminal / end
        execution = self._execution(["configure terminal", *commands, "end"], output, SHOW_VLANS)
        execution.checks = [compliance.vlan_check(execution.verification, vlan_id, vlan_name) for vlan_id, vlan_name in vlans]
        return execution

    def change_hostname(self, hostname):
        commands = ["hostname %s" % hostname]
        # The prompt changes with the hostname, so skip command echo verification and re-read the prompt
        output = self._configure(commands, cmd_verify=False)
        self.conn.set_base_prompt()
        execution = self._execution(["configure terminal", *commands, "end"], output, SHOW_HOSTNAME)
        execution.checks = [compliance.hostname_check(execution.verification, hostname)]
        return execution

    def save_config(self):
        output = self.conn.save_config(cmd="write memory")
        return self._execution(["write memory"], output, "show startup-config")

    def check_standard(self):
        """Compare the switch with the standard configuration (VLANs 10/20/50 and hostname); changes nothing."""
        vlans = self.conn.send_command(SHOW_VLANS)
        execution = Execution([SHOW_VLANS, SHOW_HOSTNAME], vlans, SHOW_HOSTNAME, self.conn.send_command(SHOW_HOSTNAME))
        execution.checks = compliance.standard_checks(vlans, execution.verification)
        return execution

    def running_config(self):
        """Return (hostname, running-config including the VLANs)."""
        config = self.conn.send_command("show running-config")
        hostname = self.conn.find_prompt().rstrip("#>")
        return hostname, self._with_vlans(config)

    def _with_vlans(self, config):
        """In VTP server/client mode IOS keeps VLANs in vlan.dat, not in the running-config:
        add the ones from show vlan brief that the config doesn't already have."""
        brief = self.conn.send_command(SHOW_VLANS)
        in_config = {int(i) for i in re.findall(r"^vlan (\d+)$", config, re.M)}
        missing = [(i, name) for i, name in compliance.parse_vlans(brief).items()
                   if i not in RESERVED_VLANS and i not in in_config]
        if not missing:
            return config
        block = "! VLANs do vlan.dat (show vlan brief)\n" + "".join("vlan %s\n name %s\n!\n" % v for v in missing)
        # Before the interfaces, so switchport access vlan refers to VLANs that already exist on restore
        m = re.search(r"^(?:interface .*|end)$", config, re.M)
        pos = m.start() if m else len(config)
        return config[:pos] + block + config[pos:]
