from datetime import datetime

from flask import Blueprint, redirect, render_template, request, Response, url_for
from flask_wtf.csrf import CSRFError

from app.models.switch import Switch, SwitchError
from app.models.validation import validate_hostname, validate_port, validate_vlan

bp = Blueprint("switch", __name__)

ACTIONS = {
    "create_vlan": "Criar VLAN",
    "hostname": "Alterar hostname",
    "save": "Salvar configuração",
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

    vlan_id = form.get("vlan_id", "").strip()
    vlan_name = form.get("vlan_name", "").strip()
    hostname = form.get("hostname", "").strip()
    port = form.get("port", "").strip() or "22"

    # Validate input before opening the SSH session
    error = validate_port(port)
    if not error and action == "create_vlan":
        error = validate_vlan(vlan_id, vlan_name)
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
                execution = sw.create_vlan(vlan_id, vlan_name)
                message = "VLAN %s (%s) criada com sucesso. Lembre de salvar a configuração." % (vlan_id, vlan_name)
            elif action == "hostname":
                execution = sw.change_hostname(hostname)
                message = "Hostname alterado para %s. Lembre de salvar a configuração." % hostname
            else:
                execution = sw.save_config()
                message = "Configuração salva na NVRAM (startup-config)."
    except SwitchError as e:
        return error_result(str(e))
    except Exception as e:
        return error_result("Erro: %s" % e)

    return render_template("switch/result.html", success=True, message=message, execution=execution,
                           ip=form["ip"], action_title=ACTIONS[action])
