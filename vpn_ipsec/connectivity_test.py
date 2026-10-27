"""Test connectivity through the IPsec tunnel. Run it from a host in one of the LANs.

    python -m vpn_ipsec.connectivity_test --site fortigate --remote-host 10.20.0.10 --tcp 10.20.0.10:443

Checks, in order (each one isolates a different layer):
  1. ping the local firewall's tunnel IP   -> host reaches its own firewall
  2. ping the remote firewall's tunnel IP  -> the tunnel itself carries traffic (169.255.1.0/30)
  3. ping hosts in the remote LAN          -> routes, phase2 selectors and firewall policies on both ends
  4. TCP connect to host:port              -> applications pass, not just ICMP
Exits 1 and sends an alert (vpn_ipsec.alerts) if any check fails.
"""
import argparse
import ipaddress
import logging
import platform
import re
import socket
import subprocess
import sys
import time

from vpn_ipsec.alerts import send_alert
from vpn_ipsec.params import DEFAULT_PATH, load


def ip_address(value):
    """The value as a normalized IP address; anything else (e.g. "-f" read as a ping option) is rejected."""
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        raise argparse.ArgumentTypeError("not an IP address: %r" % value) from None


def ping(host, count=4, timeout=2):
    """(packet loss %, average RTT ms or None) using the system ping."""
    windows = platform.system() == "Windows"
    cmd = ["ping", "-n" if windows else "-c", str(int(count)), "-w" if windows else "-W",
           str(timeout * 1000 if windows else timeout), ip_address(host)]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=count * (timeout + 1) + 5).stdout
    return parse_ping(out)


def parse_ping(output):
    # Loss is printed as "0% packet loss" on Linux and "0% loss" or "0% de perda" on Windows (English or
    # Portuguese); the average RTT as the second value of "min/avg/max/mdev" on Linux, "Average" or "Média" on Windows
    loss = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)% (?:packet loss|loss|de perda|perda)", output)
    avg = re.search(r"= [\d.]+/([\d.]+)/", output) or re.search(r"(?:Average|M[ée]dia) = (\d+)ms", output)
    return (float(loss.group(1)) if loss else 100.0), (float(avg.group(1)) if avg else None)


def tcp_check(host, port, timeout=3):
    """Connect time in ms, or None if the port can't be reached."""
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return (time.monotonic() - start) * 1000
    except OSError:
        return None


def build_checks(p, site, remote_hosts, tcp_targets):
    local, remote = ("fortigate", "paloalto") if site == "fortigate" else ("paloalto", "fortigate")
    checks = [("ping", p[local]["tunnel_ip"], "local tunnel IP (%s)" % local),
              ("ping", p[remote]["tunnel_ip"], "remote tunnel IP (%s)" % remote)]
    checks += [("ping", h, "remote LAN host") for h in remote_hosts]
    for target in tcp_targets:
        host, _, port = target.rpartition(":")
        checks.append(("tcp", (ip_address(host), int(port)), "TCP %s" % target))
    return checks


def run(checks, count, max_loss):
    failures = []
    for kind, target, label in checks:
        if kind == "ping":
            loss, avg = ping(target, count)
            ok = loss <= max_loss
            detail = "%s: %.0f%% loss%s" % (target, loss, ", avg %.1f ms" % avg if avg is not None else "")
        else:
            ms = tcp_check(*target)
            ok = ms is not None
            detail = "%s:%d %s" % (target[0], target[1], "connected in %.0f ms" % ms if ok else "unreachable")
        print("[%s] %-28s %s" % ("OK" if ok else "FAIL", label, detail))
        if not ok:
            failures.append("%s - %s" % (label, detail))
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", choices=["fortigate", "paloalto"], required=True,
                        help="side of the tunnel this host is on")
    parser.add_argument("--remote-host", action="append", default=[], type=ip_address,
                        help="IP of a host in the remote LAN to ping (repeatable)")
    parser.add_argument("--tcp", action="append", default=[], metavar="IP:PORT", help="TCP port to test (repeatable)")
    parser.add_argument("--count", type=int, default=4, help="pings per target")
    parser.add_argument("--max-loss", type=float, default=25.0, help="highest acceptable packet loss %%")
    parser.add_argument("--params", default=DEFAULT_PATH)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    p = load(args.params)
    failures = run(build_checks(p, args.site, args.remote_host, args.tcp), args.count, args.max_loss)
    if failures:
        send_alert("VPN %s: connectivity test failed from the %s side" % (p["vpn_name"], args.site), failures)
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
