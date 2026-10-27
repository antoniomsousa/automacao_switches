from datetime import datetime

from flask import Blueprint, redirect, render_template, request, Response, url_for
from flask_wtf.csrf import CSRFError

from app.models.switch import Switch, SwitchError
from app.models.validation import validate_hostname, validate_port, validate_vlan_list

bp = Blueprint("switch", __name__)

ACTIONS = {
    "create_vlan": "Criar VLANs",
    "hostname": "Alterar hostname",
    "save": "Salvar configuração",
    "validate": "Validar configuração",
    "backup": "Backup",
}


def error_result(message):
    return render_template("switch/result.html", success=False, message=message)


@bp.app_errorhandler(CSRFError)
def invalid_csrf(e):
    return error_result("Formulário expirado ou inválido. Recarregue a página e tente novamente."), 400


@bp.route("/", methods=["GET"])
def home():
    return redirect(url_for("switch.form_page"))


@bp.route("/switch", methods=["GET"])
def form_page():
    return render_template("switch/form.html")


@bp.route("/switch", methods=["POST"])
def execute():
    form = request.form
    action = form.get("action")
    if action not in ACTIONS:
        return error_result("Ação inválida.")

    hostname = form.get("hostname", "").strip()
    port = form.get("port", "").strip() or "22"

    # Validate input before opening the SSH session
    error = validate_port(port)
    if not error and action == "create_vlan":
        vlans, converted, error = validate_vlan_list(form.getlist("vlan_id"), form.getlist("vlan_name"))
    elif not error and action == "hostname":
        error = validate_hostname(hostname)
    if error:
        return error_result(error)

    try:
        with Switch(form["ip"], form["username"], form["password"], int(port), form.get("secret", "")) as sw:
            if action == "backup":
                switch_name, config = sw.running_config()
                filename = "%s_%s.cfg" % (switch_name, datetime.now().strftime("%Y%m%d_%H%M%S"))
                return Response(config, mimetype="text/plain",
                                headers={"Content-Disposition": "attachment; filename=%s" % filename})
            if action == "create_vlan":
                execution = sw.create_vlans(vlans)
                created = ", ".join("%s (%s)" % vlan for vlan in vlans)
                if len(vlans) == 1:
                    message = "VLAN %s criada com sucesso." % created
                else:
                    message = "%d VLANs criadas com sucesso: %s." % (len(vlans), created)
                message += " Lembre de salvar a configuração."
                for typed, name in converted:
                    message += " O nome %s foi convertido para %s (ASCII, sem acentos)." % (typed, name)
            elif action == "hostname":
                execution = sw.change_hostname(hostname)
                message = "Hostname alterado para %s. Lembre de salvar a configuração." % hostname
            elif action == "validate":
                execution = sw.check_standard()
                message = "O switch está com a configuração padrão (VLANs 10, 20, 50 e hostname)."
            else:
                execution = sw.save_config()
                message = "Configuração salva na NVRAM (startup-config)."
    except SwitchError as e:
        return error_result(str(e))
    except Exception as e:
        return error_result("Erro: %s" % e)

    # The switch accepted the commands, but its configuration differs from what was asked: alert, don't report success
    divergences = execution.divergences
    if divergences:
        message = "A configuração do switch não corresponde à desejada."
    return render_template("switch/result.html", success=True, message=message, execution=execution,
                           divergences=divergences, ip=form["ip"], action_title=ACTIONS[action])
