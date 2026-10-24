# Switch Wizard

[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=antoniomsousa_automacao_switches&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=antoniomsousa_automacao_switches)

Frontend web (Flask) para configurar switches Cisco IOS via SSH (Netmiko):

- Criar VLAN (ID + nome)
- Alterar hostname
- Salvar a configuração na NVRAM (`write memory`)
- Baixar backup da running-config

## Estrutura (MVC)

```
app/
  __init__.py                       create_app(): cria o Flask e registra os blueprints
  models/
    switch.py                       Model: classe Switch (sessão SSH e comandos no switch)
    validacao.py                    Model: regras de VLAN, hostname e porta
  controllers/
    switch_controller.py            Controller: rotas / e /switch
  templates/
    base.html                       View: layout (cabeçalho com logos, rodapé)
    switch/form.html                View: formulário
    switch/resultado.html           View: resultado / erro
  static/
    css/style.css                   Visual (cores Mercado Livre)
    js/app.js                       Validação no navegador, tela de carregamento, copiar
    img/switch-automation.svg       Logo do Switch Wizard
tests/
  fake_switch.py                    Switch Cisco IOS simulado (FakeNOS)
  conftest.py                       Fixtures do pytest
  test_switch.py                    Testes das ações contra o switch simulado
  test_validacao.py                 Testes das regras de validação
run.py                              Ponto de entrada
```

## Logo da empresa

Coloque o arquivo oficial do logo do Mercado Livre em `app/static/img/logo-meli.svg` (ou `logo-meli.png`).
O cabeçalho passa a usá-lo automaticamente; sem o arquivo, aparece um selo com o texto "mercado livre".

## Instalação

```
pip install -r requirements.txt          # para rodar
pip install -r requirements-dev.txt      # para rodar + testar
```

## Uso

```
python run.py
```

Abra http://127.0.0.1:5000 e informe IP, porta SSH, usuário e senha do switch.

## Testes sem switch real

Switch simulado em `127.0.0.1:6000` (usuário `admin` / senha `admin`), para testar pelo navegador:

```
python -m tests.fake_switch
```

Testes automatizados (sobem o próprio switch simulado numa porta livre):

```
python -m pytest
```
