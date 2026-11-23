# Google Ads MCP no Vercel

Fork do [googleads/google-ads-mcp](https://github.com/googleads/google-ads-mcp)
(commit `cda8527`) adaptado para rodar como função Python no Vercel.

## O que mudou em relação ao original

| Arquivo | Para quê |
| --- | --- |
| `api/index.py` | Expõe o servidor como app ASGI em `/mcp` (Streamable HTTP, sem estado), mais as rotas de OAuth e um `/health` |
| `vercel.json` | Manda todas as rotas para a função e aumenta o timeout para 60 s |
| `requirements.txt` / `.python-version` | Dependências e Python 3.12 para o build do Vercel |
| `ads_mcp/tools/management.py` | Ferramentas de gestão de campanhas (ver abaixo) |
| `ads_mcp/tools/keyword_planner.py` | Planejador de Palavras-chave: volume de busca e ideias (ver abaixo) |
| `ads_mcp/tools_config.yaml` | Todas as ferramentas ligadas, incluindo `management`, `labels` e `assets` |
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
| `GOOGLE_ADS_MCP_STORAGE_REDIS_URL` | URL `rediss://...` do Redis. Opcional: se a integração Upstash do Vercel foi criada com o prefixo `GOOGLE_ADS_MCP_STORAGE_REDIS`, o servidor lê `GOOGLE_ADS_MCP_STORAGE_REDIS_REDIS_URL` sozinho |

## Obrigatório: desligar a Vercel Authentication

Em **Settings → Deployment Protection**, a **Vercel Authentication** precisa estar
desligada para a produção. Com ela ligada, o Claude e o ChatGPT recebem um redirect
para o login do Vercel e nunca chegam ao servidor (o navegador de quem está logado no
Vercel funciona normalmente, o que esconde o problema). O servidor já se protege com
o login do Google.

## Login do Google

Na tela de consentimento, a permissão do **Google Ads** vem com uma caixa de seleção:
ela precisa ser marcada, senão o servidor recusa a autorização.

## Endereços

- Saúde: `https://SEU-PROJETO.vercel.app/health` → `{"status":"ok","oauth":true}`
- Conector MCP: `https://SEU-PROJETO.vercel.app/mcp`
- Redirect OAuth (cadastrar no Google Cloud): `https://SEU-PROJETO.vercel.app/auth/callback`

## Ferramentas de gestão (`management`)

| Ferramenta | O que faz |
| --- | --- |
| `create_search_campaign` | Cria campanha de Pesquisa completa (orçamento, segmentação, negativas, grupo, palavras-chave e anúncio) — **sempre pausada** |
| `update_campaign` | Ativa, pausa, remove, renomeia, muda orçamento diário ou data final |
| `create_ad_group` / `update_ad_group` | Cria grupo (com palavras e anúncio) / ativa, pausa, remove, muda CPC |
| `create_responsive_search_ad` / `update_ad_status` | Cria anúncio responsivo / ativa, pausa ou remove anúncio |
| `add_keywords` / `update_keywords` | Adiciona palavras-chave / pausa, ativa, exclui ou muda CPC |
| `add_negative_keywords` / `remove_negative_keywords` | Negativas no nível de campanha ou grupo |
| `link_campaign_assets` | Vincula/desvincula sitelinks, frases de destaque etc. a uma campanha |
| `create_bidding_data_exclusions` / `remove_bidding_data_exclusions` | Exclusões de dados para o lance automático ignorar dias com rastreamento falho |
| `update_campaign_settings` | Liga/desliga parceiros de pesquisa e Rede de Display; opção de local (presença ou interesse) |
| `set_campaign_bidding` | Troca a estratégia de lances (Maximizar cliques, conversões, valor, CPC manual) |
| `manage_campaign_targeting` | Locais (incluir/excluir), idiomas, ajuste por dispositivo e programação de anúncios |
| `create_negative_keyword_list` / `update_negative_keyword_list` | Listas de negativas compartilhadas entre campanhas |
| `set_recommendation_auto_apply` | Pausa ou reativa as recomendações aplicadas automaticamente |
| `update_conversion_actions` | Ação principal/secundária, contagem e ocultar |
| `set_campaign_conversion_goals` | Quais metas de conversão a campanha usa para otimizar |
| `update_responsive_search_ad` | Edita títulos, descrições, URL e caminhos de um anúncio existente |

Todas usam **propor e confirmar**: a primeira chamada (`validate_only=True`) valida na
API do Google sem alterar nada e devolve um `checksum`; só a segunda chamada, com o
mesmo `checksum`, grava. Para desligar um grupo de ferramentas, troque para `false` em
`ads_mcp/tools_config.yaml`.

## Planejador de Palavras-chave (`planner`)

| Ferramenta | O que faz |
| --- | --- |
| `keyword_volumes` | Volume médio mensal de busca, concorrência e faixa de lance do topo da página para uma lista de palavras (até 10.000) — igual a "Ver volume de pesquisa e previsões" |
| `keyword_ideas` | Ideias de palavras a partir de até 20 palavras-semente e/ou o URL de uma página, com volume — igual a "Descobrir novas palavras-chave" |

Só leitura: não alteram nada na conta. Padrão: Brasil (`2076`) e português (`1014`);
outros locais e idiomas por `location_ids` e `language_id`. O token de desenvolvedor
precisa de um nível de acesso cujo uso permitido inclua pesquisa de palavras-chave
(KeywordPlanIdeaService); se não incluir, a API devolve erro de autorização.

## Atualizar com o repositório do Google

```bash
git remote add upstream https://github.com/googleads/google-ads-mcp.git
git fetch upstream
git merge upstream/main   # resolva conflitos mantendo api/, vercel.json e este arquivo
```
