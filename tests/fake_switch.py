"""
Switch Cisco IOS simulado com FakeNOS, para testar o app sem um switch real.

Uso:  python -m tests.fake_switch
      -> SSH em 127.0.0.1 porta 6000, usuário admin / senha admin

Suporta: configure terminal, vlan <id>, name <nome>, no vlan <id>, hostname <nome>,
end/exit, write memory, show running-config, show startup-config, show vlan brief,
show vlan id <id>, e "| include <texto>" nos comandos show.
O estado (hostname, VLANs, startup-config) é mantido entre conexões SSH até o processo parar.
"""
import copy
import re
import threading
import time
import types

import fakenos.core.servers as fakenos_servers
import fakenos.plugins.servers.ssh_server_paramiko as fakenos_ssh
from fakenos import FakeNOS
from fakenos.plugins.shell.cmd_shell import CMDShell


class _ThreadDaemon(threading.Thread):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("daemon", True)
        super().__init__(*args, **kwargs)


# After a rejected login FakeNOS leaves its connection thread waiting forever; as a non-daemon
# thread it keeps Python from exiting (the CI job hung after the tests). Make its threads daemon.
_threading_daemon = types.SimpleNamespace(**{**vars(threading), "Thread": _ThreadDaemon})
fakenos_servers.threading = _threading_daemon
fakenos_ssh.threading = _threading_daemon

HOST = "127.0.0.1"
PORT = 6000
USERNAME = "admin"
PASSWORD = "admin"

INVALID = "% Invalid input detected at '^' marker."
INITIAL_STATE = {"hostname": "SW-LAB", "vlans": {1: "default", 1002: "fddi-default", 1003: "token-ring-default",
                                                  1004: "fddinet-default", 1005: "trnet-default"}}


class SwitchShell(CMDShell):
    # Shared by every SSH session, so changes survive between the app's connections
    state = copy.deepcopy(INITIAL_STATE)
    startup = copy.deepcopy(INITIAL_STATE)
    lock = threading.Lock()

    @classmethod
    def reset(cls):
        cls.state = copy.deepcopy(INITIAL_STATE)
        cls.startup = copy.deepcopy(INITIAL_STATE)

    def __init__(self, *args, **kwargs):
        kwargs["base_prompt"] = self.state["hostname"]
        super().__init__(*args, **kwargs)
        # Logged-in user has privilege 15, like most switches: start in enable mode
        self.mode = "exec"
        self.editing_vlan = None
        self._set_prompt()

    def _set_prompt(self):
        self.base_prompt = self.state["hostname"]
        suffix = {"exec": "#", "config": "(config)#", "config-vlan": "(config-vlan)#"}[self.mode]
        self.prompt = self.base_prompt + suffix

    def default(self, line):
        line = " ".join(line.split())
        with self.lock:
            result = self._execute(line)
        if result is True:
            return True
        self._set_prompt()
        if result:
            self.writeline(result)
        return False

    def _execute(self, line):
        if line in ("terminal length 0", "terminal width 511", "enable"):
            return None

        if self.mode == "exec":
            if "|" in line:
                command, _, filter_ = line.partition("|")
                m = re.fullmatch(r"\s*include (.+)", filter_)
                if not m:
                    return INVALID
                output = self._execute(command.strip())
                return "\n".join(l for l in output.splitlines() if re.search(m.group(1), l))
            if line in ("configure terminal", "conf t"):
                self.mode = "config"
                return "Enter configuration commands, one per line.  End with CNTL/Z."
            if line in ("write mem", "write memory", "wr", "copy running-config startup-config"):
                SwitchShell.startup = copy.deepcopy(self.state)
                return "Building configuration...\n[OK]"
            if line in ("show running-config", "show run"):
                return self._render_config(self.state)
            if line == "show startup-config":
                return self._render_config(self.startup)
            if line == "show vlan brief":
                return self._render_vlans()
            m = re.fullmatch(r"show vlan id (\d+)", line)
            if m:
                vlan_id = int(m.group(1))
                if vlan_id not in self.state["vlans"]:
                    return "VLAN id %d not found in current VLAN database" % vlan_id
                return self._render_vlans([vlan_id])
            if line == "exit":
                return True
            return INVALID

        # config / config-vlan
        if line == "end":
            self.mode = "exec"
            return None
        if line == "exit":
            self.mode = "config" if self.mode == "config-vlan" else "exec"
            return None

        m = re.fullmatch(r"vlan (\d+)", line)
        if m:
            vlan_id = int(m.group(1))
            if not 1 <= vlan_id <= 4094:
                return INVALID
            self.state["vlans"].setdefault(vlan_id, "VLAN%04d" % vlan_id)
            self.editing_vlan = vlan_id
            self.mode = "config-vlan"
            return None

        m = re.fullmatch(r"no vlan (\d+)", line)
        if m:
            self.state["vlans"].pop(int(m.group(1)), None)
            return None

        m = re.fullmatch(r"hostname (\S+)", line)
        if m:
            self.state["hostname"] = m.group(1)
            self.mode = "config"
            return None

        m = re.fullmatch(r"name (\S+)", line)
        if m and self.mode == "config-vlan":
            self.state["vlans"][self.editing_vlan] = m.group(1)
            return None

        return INVALID

    def _render_vlans(self, ids=None):
        lines = ["VLAN Name                             Status    Ports",
                  "---- -------------------------------- --------- -------------------------------"]
        for vlan_id, name in sorted(self.state["vlans"].items()):
            if ids is None or vlan_id in ids:
                lines.append("%-4d %-32s active" % (vlan_id, name))
        return "\n".join(lines)

    @staticmethod
    def _render_config(state):
        lines = ["Building configuration...", "", "Current configuration:", "!",
                  "version 15.2", "service timestamps log datetime msec", "!",
                  "hostname %s" % state["hostname"], "!"]
        # Like a real switch in VTP server mode, VLANs live in vlan.dat and aren't listed here
        for i in range(1, 9):
            lines += ["interface GigabitEthernet0/%d" % i, " switchport mode access", "!"]
        lines += ["line vty 0 15", " login local", " transport input ssh", "!", "end"]
        return "\n".join(lines)


def create_switch(port=PORT):
    inventory = {
        "hosts": {
            "SW-LAB": {
                "username": USERNAME,
                "password": PASSWORD,
                "port": port,
                "platform": "cisco_ios",
                "server": {"plugin": "ParamikoSshServer", "configuration": {"address": HOST, "timeout": 1}},
            }
        }
    }
    net = FakeNOS(inventory=inventory)
    # FakeNOS only accepts "CMDShell" in the inventory, so swap in our subclass under that name
    net.shell_plugins["CMDShell"] = SwitchShell
    return net


if __name__ == "__main__":
    net = create_switch()
    net.start()
    print("Switch simulado rodando em %s:%d (usuário %s / senha %s). Ctrl+C para parar." % (HOST, PORT, USERNAME, PASSWORD))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        net.stop()
