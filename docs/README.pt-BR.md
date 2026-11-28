<div align="center">

# 🧭 DuMate Daily

**Bônus diário de login do Baidu DuMate · plano booster · várias contas · status → claim → status / points**

[简体中文](../README.md) · [English](README.en.md) · [繁體中文](README.zh-Hant.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Português (BR)](README.pt-BR.md)

<img src="https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
<img src="https://img.shields.io/badge/License-MIT-F472B6?style=for-the-badge" />

</div>

> [!IMPORTANT]
> Este projeto é gratuito. É proibido revender, colocar atrás de pagamento,
> cobrar por implantação, redistribuir para captação, fingir ser o autor ou
> remover avisos de copyright. Consulte [NOTICE.md](../NOTICE.md).

## Função

DuMate Daily é um projeto independente mantido originalmente pela L0NE-6.
Ele verifica o bônus diário, envia um único claim quando disponível e lê
novamente o estado e os pontos acumulados.

| Item | Descrição |
| :--- | :--- |
| Entrada | `DUMATE_COOKIES`, `DUMATE_COOKIE` ou `DUMATE_COOKIE_FILE` |
| Saída | JSON por conta e um JSON final de resumo |
| Ambiente | Python 3.9+, `requests`; `cryptography` para importar o desktop |
| Implantação | Windows, Linux, Qinglong, GitHub Actions |
| Sucesso | `hasIssued=true` e delta positivo de `totalPoints` |

## Fluxo de Confirmação

```text
GET loginBonusInfo
  ├─ hasIssued=true  -> ALREADY_CLAIMED
  └─ hasIssued=false -> POST loginBonus {}
                         -> GET loginBonusInfo
                         -> hasIssued precisa ser true
                         -> totalPoints precisa aumentar
                         -> GET quota_overview
```

HTTP 200 ou um POST bem-sucedido isolado não é sucesso.

## Plano Booster (mesmo script)

O bônus de login e o plano booster rodam em **um script, uma execução, um resultado** —
sem segundo ponto de entrada. Depois do login o script lê o status do plano, envia cada
tarefa pendente (apenas `task_id`) e sorteia conforme as tentativas restantes. Prêmios
físicos são resgatados com `--contact`.

```text
GET  growth-plan/page/status
POST growth-plan/tasks                   -> tarefas pendentes
POST growth-plan/task/complete {task_id} -> reward_count -> tentativas
GET  growth-plan/draw/status
POST growth-plan/draw (X-Bce-Request-Id)
POST growth-plan/prize/claim {draw_record_id, contact}
```

Nem toda tarefa pode ser concluída automaticamente. Tarefas com `query` ou `suiteName`
exigem evidência real, e tarefas de assinatura exigem assinatura ativa; elas são marcadas
como `needs_evidence`. A decisão final é do servidor — o script envia `task_id` e nunca
fabrica comportamento. Sorteio/resgate passam pela assinatura acs+banti da Baidu, então uma
resposta de risco é reportada como `RISK_BLOCKED`, nunca como sucesso.

`--no-booster` · `--booster-only` · `--booster-dry-run` · `--no-draw` ·
`--max-draw N` · `--contact CONTACT` · `--task ID|NAME`

## Credenciais

O Cookie deve vir de uma requisição a `console.bce.baidu.com` e conter:

- `bce-sessionid`: necessário para status e claim;
- `bce-user-info`: enviado como `csrftoken`, necessário para claim.

`DUMATE_COOKIES` aceita uma conta por linha:

```text
account-1|bce-sessionid=<value>; bce-user-info=<value>
account-2|bce-sessionid=<value>; bce-user-info=<value>
```

Rótulos em formato de telefone são mascarados. Cookie e CSRF nunca entram no
JSON de saída ou nos relatórios.

## Execução Local

```bash
python -m pip install -r requirements.txt
export DUMATE_COOKIE='bce-sessionid=<value>; bce-user-info=<value>'
python dumate_daily.py
```

Somente status:

```bash
python dumate_daily.py --query
```

Somente a segunda conta:

```bash
python dumate_daily.py --only 2
```

## Importar Sessão do Desktop

```bash
python dumate_login.py --from-desktop --verify
```

O helper lê `auth.json` e `.cookie-key`, descriptografa AES-256-GCM, filtra os
Cookies do host do console e grava `~/.dumate-cookies`. Ele não escreve no
diretório de dados do DuMate.

```bash
python dumate_login.py --from-desktop --output /private/dumate-cookies --verify
export DUMATE_COOKIE_FILE=/private/dumate-cookies
python dumate_daily.py
```

## Qinglong

1. Instale `requests` e `cryptography`.
2. Envie `dumate_daily.py`.
3. Configure `DUMATE_COOKIES` ou `DUMATE_COOKIE`.
4. Crie uma tarefa com `task dumate_daily.py`.
5. Execute uma vez por dia às 00:13 de Pequim.

## GitHub Actions

O workflow executa testes em cada push para `main`. A execução diária faz o
claim e envia um relatório JSON como artifact. Sem Secret de credenciais, o
claim agendado é ignorado com um notice SKIPPED explícito.

| Secret | Obrigatório | Valor |
| :--- | :---: | :--- |
| `DUMATE_COOKIES` | Um dos dois | Cookies de várias contas |
| `DUMATE_COOKIE` | Um dos dois | Cookie de uma conta |

O cron é `13 16 * * *` UTC, 00:13 no horário de Pequim.

## Critérios de Sucesso

- `ALREADY_CLAIMED`: `hasIssued=true` antes do claim.
- `CLAIMED`: `hasIssued=true` depois do claim e `totalPoints` aumentou.
- `CLAIM_NOT_APPLIED`: ainda não emitido depois do POST.
- `CREDIT_UNCONFIRMED`: emitido, mas os pontos não aumentaram.
- `AUTH_EXPIRED`: página de login, redirecionamento de login, HTTP 401/403.

## Testes

```bash
python -m unittest discover -s tests -v
python -m compileall -q .
python -m ruff check dumate_daily.py dumate_login.py tests
```

Os testes usam fake sessions e não acessam o serviço real.

## Privacidade

O repositório não armazena credenciais nem dados pessoais. Arquivos de Cookie,
autenticação do desktop, relatórios e logs são ignorados pelo Git.

## Aviso

Use apenas para automação pessoal lícita. Regras, interfaces, elegibilidade e
saldos são controlados pelo provedor do serviço. O uso é por sua conta e risco.

---

[Voltar ao README chinês](../README.md) · [Política de uso](../NOTICE.md) · [Doação e Star History](../README.md#star-trail)
