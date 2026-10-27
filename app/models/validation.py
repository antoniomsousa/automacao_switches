import re

# VLANs 1 and 1002-1005 are reserved defaults on Cisco IOS and can't be created/renamed
RESERVED_VLANS = {1, 1002, 1003, 1004, 1005}


def validate_vlan(vlan_id, vlan_name):
    if not vlan_id.isdigit() or not 1 <= int(vlan_id) <= 4094:
        return "VLAN ID deve ser um número entre 1 e 4094."
    if int(vlan_id) in RESERVED_VLANS:
        return "VLAN %s é reservada e não pode ser criada." % vlan_id
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,32}", vlan_name):
        return "Nome da VLAN deve ter 1-32 caracteres (letras, números, _ ou -), sem espaços."
    return None


def validate_hostname(hostname):
    # Cisco IOS: starts with a letter, letters/digits/hyphens/underscores, ends with letter/digit, max 63
    if not re.fullmatch(r"[A-Za-z]([A-Za-z0-9_\-]{0,61}[A-Za-z0-9])?", hostname):
        return "Hostname deve começar com letra, ter até 63 caracteres (letras, números, _ ou -) e não terminar com _ ou -."
    return None


def validate_port(port):
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        return "Porta SSH deve ser um número entre 1 e 65535."
    return None
