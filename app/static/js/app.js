// Client-side checks mirror app/models/validation.py; the server validates again
var RESERVED_VLANS = new Set([1, 1002, 1003, 1004, 1005]);

var VALIDATIONS = {
    vlan_id: function (v) {
        if (!/^\d+$/.test(v) || +v < 1 || +v > 4094) return "VLAN ID deve ser um número entre 1 e 4094.";
        if (RESERVED_VLANS.has(+v)) return "VLAN " + v + " é reservada e não pode ser criada.";
    },
    vlan_name: function (v) {
        // Accents are removed by the server (VLAN_SEGURANÇA -> VLAN_SEGURANCA), so check the name without them
        var ascii = v.normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
        if (!/^[A-Za-z0-9_-]{1,32}$/.test(ascii)) return "1-32 caracteres: letras, números, _ ou -, sem espaços.";
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
    create_vlan: "Criando as VLANs no switch...",
    hostname: "Alterando o hostname...",
    save: "Salvando a configuração na NVRAM...",
    validate: "Comparando a configuração do switch com o padrão..."
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
    if (button.value === "create_vlan") firstInvalid = firstInvalid || markRepeatedVlans();
    if (firstInvalid) firstInvalid.focus();
    return !firstInvalid;
}

// VLAN list: several rows of ID + name, all sent in the same request

var STANDARD_VLANS = [["10", "VLAN_DADOS"], ["20", "VLAN_VOZ"], ["50", "VLAN_SEGURANCA"]];

function vlanRows() {
    return Array.prototype.slice.call(document.querySelectorAll("#vlan-rows .vlan-row"));
}

function rowInputs(row) {
    return [row.querySelector("[name=vlan_id]"), row.querySelector("[name=vlan_name]")];
}

// First repeated VLAN ID, flagged on its field (the server checks it too)
function markRepeatedVlans() {
    var seen = {};
    var repeated = null;
    vlanRows().forEach(function (row) {
        var input = rowInputs(row)[0];
        var id = String(+input.value);
        if (seen[id] && !repeated) {
            markError(input, "VLAN repetida na lista.");
            repeated = input;
        }
        seen[id] = true;
    });
    return repeated;
}

// Rows left completely empty are dropped before sending, as long as one row remains
function removeEmptyRows() {
    vlanRows().forEach(function (row) {
        var empty = rowInputs(row).every(function (input) { return !input.value.trim(); });
        if (empty && vlanRows().length > 1) row.remove();
    });
}

function addVlanRow(id, name) {
    var rows = document.getElementById("vlan-rows");
    var row = rows.querySelector(".vlan-row").cloneNode(true);
    var inputs = rowInputs(row);
    inputs[0].value = id || "";
    inputs[1].value = name || "";
    inputs.forEach(function (input) {
        markError(input, "");
        bindInput(input);
    });
    bindRemove(row.querySelector(".remove-vlan"));
    rows.appendChild(row);
    return row;
}

function bindRemove(button) {
    button.addEventListener("click", function () {
        if (vlanRows().length > 1) button.closest(".vlan-row").remove();
    });
}

function fillStandard() {
    vlanRows().slice(1).forEach(function (row) { row.remove(); });
    var first = rowInputs(vlanRows()[0]);
    first[0].value = STANDARD_VLANS[0][0];
    first[1].value = STANDARD_VLANS[0][1];
    first.forEach(function (input) { markError(input, ""); });
    STANDARD_VLANS.slice(1).forEach(function (vlan) { addVlanRow(vlan[0], vlan[1]); });
}

// Enter would submit with the form's first button (Criar VLANs); use the button of the section being typed in instead
function bindInput(input) {
    input.addEventListener("keydown", function (e) {
        if (e.key !== "Enter") return;
        e.preventDefault();
        var button = input.closest(".section").querySelector("button[name=action]");
        if (button) button.click();
    });
    input.addEventListener("input", function () {
        if (input.classList.contains("invalid")) validateField(input);
    });
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
            if (button.value === "create_vlan") removeEmptyRows();
            if (!validateSections(button)) e.preventDefault();
        });
    });

    form.querySelectorAll("input").forEach(bindInput);
    form.querySelectorAll(".remove-vlan").forEach(bindRemove);
    document.getElementById("add-vlan").addEventListener("click", function () {
        rowInputs(addVlanRow())[0].focus();
    });
    document.getElementById("fill-standard").addEventListener("click", fillStandard);

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
