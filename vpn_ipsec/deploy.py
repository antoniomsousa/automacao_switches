"""Configure and validate the FortiGate <-> Palo Alto IPsec VPN.

    python -m vpn_ipsec.deploy plan        # validate params.yaml and print every API call; no device access
    python -m vpn_ipsec.deploy apply       # backup, configure both firewalls, bring the tunnel up, validate
    python -m vpn_ipsec.deploy validate    # read-only: configuration drift + tunnel status, alert on failure

Environment: FGT_TOKEN (FortiOS REST API token), PANOS_API_KEY, VPN_PSK (pre-shared key),
ALERT_WEBHOOK_URL (optional). Use --insecure only in a lab with self-signed certificates.
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime

import requests

from vpn_ipsec import fortigate, paloalto
from vpn_ipsec.alerts import send_alert
from vpn_ipsec.params import DEFAULT_PATH, ParamsError, load, read_psk

log = logging.getLogger("vpn_ipsec")
MASK = "********"


def plan(p):
    """Print the calls that apply would make, with the PSK masked."""
    print("== FortiGate %s (FortiOS REST API, applied immediately)" % p["fortigate"]["host"])
    for obj in fortigate.desired_objects(p, MASK):
        where = obj.get("key") or "%s==%s" % (obj["match"], obj["data"][obj["match"]])
        print("ensure %-28s %-22s %s" % (obj["path"], where, obj["data"]))
    print("\n== Palo Alto %s (PAN-OS XML API, candidate config + commit)" % p["paloalto"]["host"])
    for action, xpath, element in paloalto.desired_objects(p, MASK):
        print("%-4s %s\n     %s" % (action, xpath, element))
    print("commit")


def connect(p, verify):
    for var in ("FGT_TOKEN", "PANOS_API_KEY"):
        if not os.environ.get(var):
            raise ParamsError(["environment variable %s is not set" % var])
    fgt = fortigate.FortiGate(p["fortigate"]["host"], os.environ["FGT_TOKEN"], p["fortigate"]["vdom"], verify=verify)
    pan = paloalto.PaloAlto(p["paloalto"]["host"], os.environ["PANOS_API_KEY"], verify=verify)
    return fgt, pan


def apply(p, fgt, pan, wait_up=60):
    """Configure both firewalls; on failure undo what was done on each side and alert."""
    psk = read_psk(p)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fgt_objects = fortigate.desired_objects(p, psk)
    pan_objects = paloalto.desired_objects(p, psk)

    # 1. Backups: FortiGate config file, Palo Alto named snapshot of the running config
    backup_file = "fortigate_%s_%s.conf" % (p["fortigate"]["host"], stamp)
    with open(backup_file, "w", encoding="utf-8") as f:
        f.write(fgt.backup())
    snapshot = "pre-vpn-%s.xml" % stamp
    pan.save_snapshot(snapshot)
    log.info("backups: %s (FortiGate), %s (Palo Alto)", backup_file, snapshot)

    created = []
    stage = "FortiGate"
    try:
        # 2. FortiGate: each object is live as soon as it's written
        for obj in fgt_objects:
            result = fgt.ensure(obj)
            log.info("FortiGate %s %s: %s", obj["path"], obj.get("key") or obj["data"].get(obj.get("match")), result)
            if result == "created":
                created.append(obj)
        # 3. Palo Alto: stage everything in the candidate config, then a single commit
        stage = "Palo Alto"
        for action, xpath, element in pan_objects:
            pan.apply(action, xpath, element)
        log.info("Palo Alto: %s", pan.commit())
        stage = "validation"
        # 4. Bring the tunnel up from both ends, then validate
        fgt.bring_up(p["fortigate"]["tunnel_interface"], "%s-P2" % p["fortigate"]["tunnel_interface"])
        pan.bring_up("%s-GW" % p["vpn_name"], p["vpn_name"])
        problems = validate(p, fgt, pan, wait_up=wait_up, objects=(fgt_objects, pan_objects))
        if problems:
            raise RuntimeError("; ".join(problems))
    except Exception as e:
        rollback(fgt, pan, created, snapshot, committed=stage == "validation")
        send_alert("VPN %s: deploy failed at %s, changes rolled back" % (p["vpn_name"], stage), [str(e)])
        return False
    log.info("VPN %s configured and up", p["vpn_name"])
    return True


def rollback(fgt, pan, created, snapshot, committed):
    for obj in reversed(created):
        try:
            fgt.delete(obj)
        except fortigate.FortiGateError as e:
            log.error("rollback FortiGate %s: %s", obj["path"], e)
    try:
        if committed:
            pan.load_snapshot(snapshot)
            pan.commit()
        else:
            pan.revert_candidate()
    except paloalto.PaloAltoError as e:
        log.error("rollback Palo Alto: %s", e)


def validate(p, fgt, pan, wait_up=0, objects=None):
    """Problems found (empty list = OK): configuration drift on either side, then tunnel status on both."""
    fgt_objects, pan_objects = objects or (fortigate.desired_objects(p, ""), paloalto.desired_objects(p, ""))
    problems = []
    for obj in fgt_objects:
        current = fgt.find(obj)
        if current is None:
            problems.append("FortiGate: %s %s missing" % (obj["path"], obj.get("key") or obj["data"][obj["match"]]))
        elif fortigate.differences(current, obj["data"]):
            problems.append("FortiGate: %s %s differs in %s" % (obj["path"], obj.get("key") or obj["data"][obj["match"]],
                                                               ", ".join(fortigate.differences(current, obj["data"]))))
    problems += ["Palo Alto: configuration differs at %s" % x for x in pan.drift(pan_objects)]
    if problems:
        return problems

    # Tunnel status: wait a little after apply, IKE negotiation takes a few seconds
    deadline = time.monotonic() + wait_up
    while True:
        fgt_status = fgt.tunnel_status(p["fortigate"]["tunnel_interface"])
        pan_status = pan.tunnel_status(p["vpn_name"])
        down = [side for side, s in (("FortiGate", fgt_status), ("Palo Alto", pan_status)) if not (s and s["up"])]
        if not down or time.monotonic() >= deadline:
            break
        time.sleep(5)
    for side in down:
        problems.append("%s: tunnel %s is down" % (side, p["vpn_name"]))
    if len(down) == 1:
        problems.append("only one side reports the tunnel down: check proposals, proxy-IDs and routing on that side")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["plan", "apply", "validate"])
    parser.add_argument("--params", default=DEFAULT_PATH)
    parser.add_argument("--insecure", action="store_true", help="don't verify TLS certificates (lab only)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        p = load(args.params)
        if args.command == "plan":
            plan(p)
            return 0
        fgt, pan = connect(p, verify=not args.insecure)
        if args.command == "apply":
            return 0 if apply(p, fgt, pan) else 1
        problems = validate(p, fgt, pan)
    except ParamsError as e:
        for error in e.errors:
            log.error(error)
        return 2
    except (fortigate.FortiGateError, paloalto.PaloAltoError, requests.RequestException, OSError) as e:
        send_alert("VPN: could not reach the firewalls", [str(e)])
        return 1
    if problems:
        send_alert("VPN %s: validation failed" % p["vpn_name"], problems)
        return 1
    log.info("VPN %s: configuration matches on both firewalls and the tunnel is up", p["vpn_name"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
