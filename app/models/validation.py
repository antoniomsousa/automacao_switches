import re
import unicodedata

# VLANs 1 and 1002-1005 are reserved defaults on Cisco IOS and can't be created/renamed
RESERVED_VLANS = {1, 1002, 1003, 1004, 1005}
# VLANs per request: keeps one SSH config session short
MAX_VLANS = 50


def to_ascii(name):
    """Drop accents (VLAN_SEGURANÇA -> VLAN_SEGURANCA): IOS VLAN names should be plain ASCII, and a non-ASCII
    name can be stored or echoed differently over SSH, breaking the comparison after configuring it."""
    return "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))


def validate_vlan(vlan_id, vlan_name):
    if not vlan_id.isdigit() or not 1 <= int(vlan_id) <= 4094:
        return "VLAN ID deve ser um número entre 1 e 4094."
    if int(vlan_id) in RESERVED_VLANS:
        return "VLAN %s é reservada e não pode ser criada." % vlan_id
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,32}", vlan_name):
        return "Nome da VLAN deve ter 1-32 caracteres (letras, números, _ ou -), sem espaços."
    return None


def validate_vlan_list(ids, names):
    """Rows of the form -> (vlans, converted, error).

    vlans: [(vlan_id, ascii name)] of the filled rows (fully empty rows are skipped);
    converted: [(typed name, ascii name)] for names that had accents; error: first problem found, or None.
    """
    vlans, converted, seen = [], [], set()
    for line, (vlan_id, typed) in enumerate(zip(ids, names), start=1):
        vlan_id, typed = vlan_id.strip(), typed.strip()
        if not vlan_id and not typed:
            continue
        name = to_ascii(typed)
        error = validate_vlan(vlan_id, name)
        if error:
            return [], [], "Linha %d: %s" % (line, error)
        if int(vlan_id) in seen:
            return [], [], "Linha %d: a VLAN %s aparece mais de uma vez." % (line, vlan_id)
        seen.add(int(vlan_id))
        vlans.append((vlan_id, name))
        if name != typed:
            converted.append((typed, name))
    if not vlans:
        return [], [], "Informe pelo menos uma VLAN (ID e nome)."
    if len(vlans) > MAX_VLANS:
        return [], [], "Envie no máximo %d VLANs por vez." % MAX_VLANS
    return vlans, converted, None


def validate_hostname(hostname):
    # Cisco IOS: starts with a letter, letters/digits/hyphens/underscores, ends with letter/digit, max 63
    if not re.fullmatch(r"[A-Za-z]([A-Za-z0-9_\-]{0,61}[A-Za-z0-9])?", hostname):
        return "Hostname deve começar com letra, ter até 63 caracteres (letras, números, _ ou -) e não terminar com _ ou -."
    return None


def validate_port(port):
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        return "Porta SSH deve ser um número entre 1 e 65535."
    return None
