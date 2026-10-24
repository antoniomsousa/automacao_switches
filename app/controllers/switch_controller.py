from datetime import datetime

from flask import Blueprint, redirect, render_template, request, Response, url_for

from app.models.switch import Switch, SwitchError
from app.models.validacao import valida_hostname, valida_porta, valida_vlan

bp = Blueprint("switch", __name__)

ACOES = {
    "criar_vlan": "Criar VLAN",
    "hostname": "Alterar hostname",
    "salvar": "Salvar configuração",
    "backup": "Backup",
}


def resultado_erro(mensagem):
    return render_template("switch/resultado.html", sucesso=False, mensagem=mensagem)


@bp.route("/")
def home():
    return redirect(url_for("switch.formulario"))


@bp.route("/switch", methods=["GET"])
def formulario():
    return render_template("switch/form.html")


@bp.route("/switch", methods=["POST"])
def executar():
    form = request.form
    acao = form.get("acao")
    if acao not in ACOES:
        return resultado_erro("Ação inválida.")

    vlan_id = form.get("vlan_id", "").strip()
    vlan_name = form.get("vlan_name", "").strip()
    hostname = form.get("hostname", "").strip()
    porta = form.get("port", "").strip() or "22"

    # Validate input before opening the SSH session
    erro = valida_porta(porta)
    if not erro and acao == "criar_vlan":
        erro = valida_vlan(vlan_id, vlan_name)
    elif not erro and acao == "hostname":
        erro = valida_hostname(hostname)
    if erro:
        return resultado_erro(erro)

    try:
        with Switch(form["ip"], form["username"], form["password"], int(porta), form.get("secret", "")) as sw:
            if acao == "backup":
                nome_sw, config = sw.running_config()
                filename = "%s_%s.cfg" % (nome_sw, datetime.now().strftime("%Y%m%d_%H%M%S"))
                return Response(config, mimetype="text/plain",
                                headers={"Content-Disposition": "attachment; filename=%s" % filename})
            if acao == "criar_vlan":
                execucao = sw.criar_vlan(vlan_id, vlan_name)
                mensagem = "VLAN %s (%s) criada com sucesso. Lembre de salvar a configuração." % (vlan_id, vlan_name)
            elif acao == "hostname":
                execucao = sw.alterar_hostname(hostname)
                mensagem = "Hostname alterado para %s. Lembre de salvar a configuração." % hostname
            else:
                execucao = sw.salvar_config()
                mensagem = "Configuração salva na NVRAM (startup-config)."
    except SwitchError as e:
        return resultado_erro(str(e))
    except Exception as e:
        return resultado_erro("Erro: %s" % e)

    return render_template("switch/resultado.html", sucesso=True, mensagem=mensagem, execucao=execucao,
                           ip=form["ip"], acao_titulo=ACOES[acao])
