from dataclasses import dataclass

from netmiko import ConnectHandler
from netmiko.exceptions import ConfigInvalidException, NetmikoAuthenticationException, NetmikoTimeoutException

# IOS error messages after a rejected config command
ERRO_IOS = r"^% (Invalid input|Incomplete command|Ambiguous command)|not allowed"


class SwitchError(Exception):
    """Error with a message that can be shown to the user."""


@dataclass
class Execucao:
    """What was done on the switch: commands sent, switch output, and a show command confirming the result."""
    comandos: list
    saida: str
    verificacao_cmd: str
    verificacao: str


class Switch:
    """SSH session to a Cisco IOS switch. Use as a context manager: `with Switch(...) as sw:`."""

    def __init__(self, ip, usuario, senha, porta=22, secret=""):
        self.dispositivo = {
            "device_type": "cisco_ios",
            "host": ip,
            "port": porta,
            "username": usuario,
            "password": senha,
            "secret": secret,
        }
        self.conn = None

    def __enter__(self):
        try:
            self.conn = ConnectHandler(**self.dispositivo)
        except NetmikoAuthenticationException:
            raise SwitchError("Falha de autenticação no switch.")
        except NetmikoTimeoutException:
            raise SwitchError("Timeout ao conectar no switch %s." % self.dispositivo["host"])
        if self.dispositivo["secret"]:
            self.conn.enable()
        return self

    def __exit__(self, *args):
        self.conn.disconnect()

    def _execucao(self, comandos, saida, verificacao_cmd):
        return Execucao(comandos, saida, verificacao_cmd, self.conn.send_command(verificacao_cmd))

    def _configura(self, comandos, **kwargs):
        """send_config_set, raising SwitchError if the switch rejects a command."""
        try:
            return self.conn.send_config_set(comandos, error_pattern=ERRO_IOS, **kwargs)
        except ConfigInvalidException as e:
            raise SwitchError("O switch rejeitou o comando: %s" % e)

    def criar_vlan(self, vlan_id, vlan_name):
        comandos = ["vlan %s" % vlan_id, "name %s" % vlan_name]
        saida = self._configura(comandos)
        # send_config_set wraps the commands in configure terminal / end
        return self._execucao(["configure terminal", *comandos, "end"], saida, "show vlan id %s" % vlan_id)

    def alterar_hostname(self, hostname):
        comandos = ["hostname %s" % hostname]
        # The prompt changes with the hostname, so skip command echo verification and re-read the prompt
        saida = self._configura(comandos, cmd_verify=False)
        self.conn.set_base_prompt()
        return self._execucao(["configure terminal", *comandos, "end"], saida, "show running-config | include hostname")

    def salvar_config(self):
        saida = self.conn.save_config(cmd="write memory")
        return self._execucao(["write memory"], saida, "show startup-config")

    def running_config(self):
        """Return (hostname, running-config)."""
        config = self.conn.send_command("show running-config")
        hostname = self.conn.find_prompt().rstrip("#>")
        return hostname, config
