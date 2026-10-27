// Client-side checks mirror app/models/validacao.py; the server validates again
var RESERVED_VLANS = [1, 1002, 1003, 1004, 1005];

var VALIDACOES = {
    vlan_id: function (v) {
        if (!/^\d+$/.test(v) || +v < 1 || +v > 4094) return "VLAN ID deve ser um número entre 1 e 4094.";
        if (RESERVED_VLANS.includes(+v)) return "VLAN " + v + " é reservada e não pode ser criada.";
    },
    vlan_name: function (v) {
        if (!/^[A-Za-z0-9_-]{1,32}$/.test(v)) return "1-32 caracteres: letras, números, _ ou -, sem espaços.";
    },
    hostname: function (v) {
        if (!/^[A-Za-z]([A-Za-z0-9_-]{0,61}[A-Za-z0-9])?$/.test(v))
            return "Comece com letra; use letras, números, _ ou -; não termine com _ ou -.";
    },
    port: function (v) {
        if (!/^\d+$/.test(v) || +v < 1 || +v > 65535) return "Porta entre 1 e 65535.";
    }
};

var MENSAGENS = {
    criar_vlan: "Criando a VLAN no switch...",
    hostname: "Alterando o hostname...",
    salvar: "Salvando a configuração na NVRAM..."
};

function marcaErro(input, mensagem) {
    var erro = input.closest(".campo").querySelector(".erro-campo");
    input.classList.toggle("invalido", !!mensagem);
    if (erro) erro.textContent = mensagem || "";
}

function validaCampo(input) {
    var valor = input.value.trim();
    var regra = VALIDACOES[input.dataset.validar || input.name];
    var mensagem = "";
    if (input.required && !valor) mensagem = "Campo obrigatório.";
    else if (regra && (valor || input.dataset.validar)) mensagem = regra(valor) || "";
    marcaErro(input, mensagem);
    return !mensagem;
}

// Connection section plus the section of the clicked button
function validaSecoes(botao) {
    var inputs = Array.prototype.slice.call(document.querySelectorAll(".conexao input"));
    inputs = inputs.concat(Array.prototype.slice.call(botao.closest(".secao").querySelectorAll("input[data-validar]")));
    var primeiroInvalido = null;
    inputs.forEach(function (input) {
        if (!validaCampo(input) && !primeiroInvalido) primeiroInvalido = input;
    });
    if (primeiroInvalido) primeiroInvalido.focus();
    return !primeiroInvalido;
}

function lembrar(form) {
    try {
        form.querySelectorAll("[data-lembrar]").forEach(function (input) {
            localStorage.setItem("switch-wizard:" + input.name, input.value);
        });
    } catch (e) { /* storage unavailable: nothing to remember */ }
}

function restaurar(form) {
    try {
        form.querySelectorAll("[data-lembrar]").forEach(function (input) {
            var valor = localStorage.getItem("switch-wizard:" + input.name);
            if (valor) input.value = valor;
        });
    } catch (e) { /* storage unavailable */ }
}

var form = document.getElementById("form-switch");
if (form) {
    restaurar(form);

    form.querySelectorAll("button[name=acao]").forEach(function (botao) {
        botao.addEventListener("click", function (e) {
            if (!validaSecoes(botao)) e.preventDefault();
        });
    });

    // Enter would submit with the form's first button (Criar VLAN); use the button of the section being typed in instead
    form.querySelectorAll("input").forEach(function (input) {
        input.addEventListener("keydown", function (e) {
            if (e.key !== "Enter") return;
            e.preventDefault();
            var botao = input.closest(".secao").querySelector("button[name=acao]");
            if (botao) botao.click();
        });
        input.addEventListener("input", function () {
            if (input.classList.contains("invalido")) validaCampo(input);
        });
    });

    form.querySelectorAll(".mostrar-senha").forEach(function (botao) {
        botao.addEventListener("click", function () {
            var input = botao.parentNode.querySelector("input");
            var mostrar = input.type === "password";
            input.type = mostrar ? "text" : "password";
            botao.textContent = mostrar ? "Ocultar" : "Mostrar";
        });
    });

    form.addEventListener("submit", function (e) {
        var acao = e.submitter?.value;
        lembrar(form);
        if (acao === "backup") {
            // A download doesn't leave the page, so only flag the button for a moment
            var botao = e.submitter;
            var texto = botao.innerHTML;
            botao.textContent = "Gerando backup...";
            setTimeout(function () { botao.disabled = true; }, 0);
            setTimeout(function () { botao.innerHTML = texto; botao.disabled = false; }, 5000);
            return;
        }
        var ip = form.querySelector("[name=ip]").value.trim();
        document.getElementById("carregando-texto").textContent =
            "Conectando em " + ip + ". " + (MENSAGENS[acao] || "");
        document.getElementById("carregando").hidden = false;
    });

    // Back button from the result page restores the page from cache with the overlay still showing
    window.addEventListener("pageshow", function () {
        document.getElementById("carregando").hidden = true;
    });
}

document.querySelectorAll("[data-copiar]").forEach(function (botao) {
    botao.addEventListener("click", function () {
        var texto = document.getElementById(botao.dataset.copiar).textContent;
        var feito = function () {
            botao.textContent = "Copiado!";
            setTimeout(function () { botao.textContent = "Copiar"; }, 1500);
        };
        // The app runs on 127.0.0.1 (a secure context), so the Clipboard API is available
        navigator.clipboard.writeText(texto).then(feito).catch(function () {
            botao.textContent = "Erro ao copiar";
            setTimeout(function () { botao.textContent = "Copiar"; }, 1500);
        });
    });
});
