// Client-side checks mirror app/models/validation.py; the server validates again
var RESERVED_VLANS = [1, 1002, 1003, 1004, 1005];

var VALIDATIONS = {
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

var MESSAGES = {
    create_vlan: "Criando a VLAN no switch...",
    hostname: "Alterando o hostname...",
    save: "Salvando a configuração na NVRAM..."
};

function markError(input, message) {
    var error = input.closest(".field").querySelector(".field-error");
    input.classList.toggle("invalid", !!message);
    if (error) error.textContent = message || "";
}

function validateField(input) {
    var value = input.value.trim();
    var rule = VALIDATIONS[input.dataset.validate || input.name];
    var message = "";
    if (input.required && !value) message = "Campo obrigatório.";
    else if (rule && (value || input.dataset.validate)) message = rule(value) || "";
    markError(input, message);
    return !message;
}

// Connection section plus the section of the clicked button
function validateSections(button) {
    var inputs = Array.prototype.slice.call(document.querySelectorAll(".connection input"));
    inputs = inputs.concat(Array.prototype.slice.call(button.closest(".section").querySelectorAll("input[data-validate]")));
    var firstInvalid = null;
    inputs.forEach(function (input) {
        if (!validateField(input) && !firstInvalid) firstInvalid = input;
    });
    if (firstInvalid) firstInvalid.focus();
    return !firstInvalid;
}

function remember(form) {
    try {
        form.querySelectorAll("[data-remember]").forEach(function (input) {
            localStorage.setItem("switch-wizard:" + input.name, input.value);
        });
    } catch (e) { /* storage unavailable: nothing to remember */ }
}

function restore(form) {
    try {
        form.querySelectorAll("[data-remember]").forEach(function (input) {
            var value = localStorage.getItem("switch-wizard:" + input.name);
            if (value) input.value = value;
        });
    } catch (e) { /* storage unavailable */ }
}

var form = document.getElementById("form-switch");
if (form) {
    restore(form);

    form.querySelectorAll("button[name=action]").forEach(function (button) {
        button.addEventListener("click", function (e) {
            if (!validateSections(button)) e.preventDefault();
        });
    });

    // Enter would submit with the form's first button (Criar VLAN); use the button of the section being typed in instead
    form.querySelectorAll("input").forEach(function (input) {
        input.addEventListener("keydown", function (e) {
            if (e.key !== "Enter") return;
            e.preventDefault();
            var button = input.closest(".section").querySelector("button[name=action]");
            if (button) button.click();
        });
        input.addEventListener("input", function () {
            if (input.classList.contains("invalid")) validateField(input);
        });
    });

    form.querySelectorAll(".toggle-password").forEach(function (button) {
        button.addEventListener("click", function () {
            var input = button.parentNode.querySelector("input");
            var show = input.type === "password";
            input.type = show ? "text" : "password";
            button.textContent = show ? "Ocultar" : "Mostrar";
        });
    });

    form.addEventListener("submit", function (e) {
        var action = e.submitter?.value;
        remember(form);
        if (action === "backup") {
            // A download doesn't leave the page, so only flag the button for a moment
            var button = e.submitter;
            var text = button.innerHTML;
            button.textContent = "Gerando backup...";
            setTimeout(function () { button.disabled = true; }, 0);
            setTimeout(function () { button.innerHTML = text; button.disabled = false; }, 5000);
            return;
        }
        var ip = form.querySelector("[name=ip]").value.trim();
        document.getElementById("loading-text").textContent =
            "Conectando em " + ip + ". " + (MESSAGES[action] || "");
        document.getElementById("loading").hidden = false;
    });

    // Back button from the result page restores the page from cache with the overlay still showing
    window.addEventListener("pageshow", function () {
        document.getElementById("loading").hidden = true;
    });
}

document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.addEventListener("click", function () {
        var text = document.getElementById(button.dataset.copy).textContent;
        var done = function () {
            button.textContent = "Copiado!";
            setTimeout(function () { button.textContent = "Copiar"; }, 1500);
        };
        // The app runs on 127.0.0.1 (a secure context), so the Clipboard API is available
        navigator.clipboard.writeText(text).then(done).catch(function () {
            button.textContent = "Erro ao copiar";
            setTimeout(function () { button.textContent = "Copiar"; }, 1500);
        });
    });
});
