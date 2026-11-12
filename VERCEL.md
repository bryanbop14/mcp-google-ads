# Google Ads MCP no Vercel

Fork do [googleads/google-ads-mcp](https://github.com/googleads/google-ads-mcp)
(commit `cda8527`) adaptado para rodar como função Python no Vercel.

## O que mudou em relação ao original

| Arquivo | Para quê |
| --- | --- |
| `api/index.py` | Expõe o servidor como app ASGI em `/mcp` (Streamable HTTP, sem estado), mais as rotas de OAuth e um `/health` |
| `vercel.json` | Manda todas as rotas para a função e aumenta o timeout para 60 s |
| `requirements.txt` / `.python-version` | Dependências e Python 3.12 para o build do Vercel |
| `ads_mcp/tools_config.yaml` | Ferramentas que gravam (`labels`, `assets`) **desligadas** por padrão |
| `.github/`, `CODEOWNERS` | Removidos (CI e donos do repositório original) |

## Variáveis de ambiente (Vercel → Settings → Environment Variables)

| Variável | Valor |
| --- | --- |
| `GOOGLE_ADS_DEVELOPER_TOKEN` | Token do Centro de API da MCC |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | ID da MCC, 10 dígitos sem hífen |
| `GOOGLE_ADS_MCP_OAUTH_CLIENT_ID` | ID do cliente OAuth (tipo Aplicativo da Web) |
| `GOOGLE_ADS_MCP_OAUTH_CLIENT_SECRET` | Chave secreta desse cliente |
| `GOOGLE_ADS_MCP_BASE_URL` | `https://SEU-PROJETO.vercel.app` (sem barra no fim) |
| `GOOGLE_ADS_MCP_JWT_SIGNING_KEY` | Texto aleatório longo (`openssl rand -hex 32`) |
| `GOOGLE_ADS_MCP_STORAGE_REDIS_URL` | URL `rediss://...` do Redis (Upstash) |

## Endereços

- Saúde: `https://SEU-PROJETO.vercel.app/health` → `{"status":"ok","oauth":true}`
- Conector MCP: `https://SEU-PROJETO.vercel.app/mcp`
- Redirect OAuth (cadastrar no Google Cloud): `https://SEU-PROJETO.vercel.app/auth/callback`

## Ligar as ferramentas que gravam

Em `ads_mcp/tools_config.yaml`, troque `labels: false` e/ou `assets: false`
para `true` e faça commit. Elas pedem confirmação antes de gravar.

## Atualizar com o repositório do Google

```bash
git remote add upstream https://github.com/googleads/google-ads-mcp.git
git fetch upstream
git merge upstream/main   # resolva conflitos mantendo api/, vercel.json e este arquivo
```
