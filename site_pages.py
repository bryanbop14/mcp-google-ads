"""Public HTML pages of the server: home, privacy policy and terms of service.

Google's OAuth brand verification needs a home page that describes the app and
public links to the privacy policy and the terms of service on the same domain.
"""

import html
import os

APP_NAME = "Riole Google Ads MCP"
COMPANY = "Riole Eletrônica Ltda."
CNPJ = "76.617.927/0001-37"
ADDRESS = "Rua Luiz Andreta, 209, Atuba, Colombo/PR, CEP 83.413-240, Brasil"
CONTACT_EMAIL = os.environ.get("SITE_CONTACT_EMAIL", "comercial@riole.com.br")
UPDATED = "24 de novembro de 2026"

_CSS = """
:root{--red:#DE1819;--ink:#212529;--muted:#5c636a;--line:#e5e7eb;--bg:#fafafa}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
color:var(--ink);background:var(--bg);line-height:1.65}
header{background:var(--ink);color:#fff;border-bottom:4px solid var(--red)}
header .wrap{display:flex;align-items:center;justify-content:space-between;
gap:16px;padding:18px 20px}
header a{color:#fff;text-decoration:none}
.brand{font-weight:700;letter-spacing:.2px}
nav a{margin-left:18px;font-size:.95rem;opacity:.85}
nav a:hover{opacity:1}
.wrap{max-width:760px;margin:0 auto}
main .wrap{padding:36px 20px 56px}
h1{font-size:1.9rem;line-height:1.25;margin:0 0 8px}
h2{font-size:1.15rem;margin:32px 0 8px}
p,li{font-size:1rem}
ul{padding-left:22px}
.muted{color:var(--muted);font-size:.92rem}
.card{background:#fff;border:1px solid var(--line);border-radius:10px;
padding:20px 22px;margin:24px 0}
code{background:#f1f3f5;padding:1px 6px;border-radius:4px;font-size:.92em}
a{color:#b31314}
footer{border-top:1px solid var(--line);background:#fff}
footer .wrap{padding:20px;font-size:.88rem;color:var(--muted)}
"""


def _layout(title: str, body: str) -> str:
    verification = os.environ.get("GOOGLE_SITE_VERIFICATION", "").strip()
    meta = (
        f'<meta name="google-site-verification" '
        f'content="{html.escape(verification)}">'
        if verification
        else ""
    )
    email = html.escape(CONTACT_EMAIL)
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{meta}<title>{html.escape(title)}</title><style>{_CSS}</style></head>
<body>
<header><div class="wrap">
<a class="brand" href="/">{APP_NAME}</a>
<nav><a href="/privacidade">Privacidade</a><a href="/termos">Termos</a></nav>
</div></header>
<main><div class="wrap">{body}</div></main>
<footer><div class="wrap">
{COMPANY} &middot; CNPJ {CNPJ} &middot; {ADDRESS}<br>
Contato: <a href="mailto:{email}">{email}</a> &middot;
<a href="/privacidade">Política de privacidade</a> &middot;
<a href="/termos">Termos de serviço</a>
</div></footer>
</body></html>"""


def home() -> str:
    return _layout(
        APP_NAME,
        f"""<h1>{APP_NAME}</h1>
<p>Ferramenta interna da {COMPANY} que conecta assistentes de IA autorizados à
Google Ads API, para que a equipe de marketing da Riole consulte e gerencie as
contas de anúncios da própria empresa.</p>
<div class="card">
<p><strong>O que a ferramenta faz</strong></p>
<ul>
<li>Consulta relatórios de campanhas, palavras-chave, anúncios e termos de pesquisa
das contas do Google Ads da Riole.</li>
<li>Faz ajustes de gestão (palavras-chave, negativas, anúncios, orçamentos e lances)
somente quando o usuário pede, depois de uma simulação e de confirmação explícita.</li>
<li>Consulta o Planejador de Palavras-chave para estimar volume de busca.</li>
</ul>
</div>
<p>O acesso é restrito a usuários autorizados da Riole, que entram com a própria
conta Google. A ferramenta não é oferecida a clientes nem ao público.</p>
<p class="muted">Endereço técnico do servidor MCP: <code>/mcp</code></p>""",
    )


def privacy() -> str:
    email = html.escape(CONTACT_EMAIL)
    return _layout(
        f"Política de privacidade · {APP_NAME}",
        f"""<h1>Política de privacidade</h1>
<p class="muted">Última atualização: {UPDATED}</p>
<p>Esta política explica como o {APP_NAME} ("ferramenta"), operado pela
{COMPANY} (CNPJ {CNPJ}), trata as informações obtidas quando um usuário autorizado
entra com a conta Google para usar a ferramenta.</p>

<h2>1. Quem pode usar</h2>
<p>A ferramenta é de uso interno da Riole e só pode ser usada por pessoas autorizadas
pela empresa para gerenciar as contas do Google Ads da Riole.</p>

<h2>2. Dados acessados</h2>
<p>Com o consentimento dado na tela de login do Google, a ferramenta recebe:</p>
<ul>
<li><strong>Identificação básica da conta Google</strong> (escopos <code>openid</code>,
<code>userinfo.email</code> e <code>userinfo.profile</code>): e-mail, nome e
identificador da conta, usados para autenticar o usuário.</li>
<li><strong>Acesso à Google Ads API</strong> (escopo
<code>https://www.googleapis.com/auth/adwords</code>): dados das contas do Google Ads
às quais o próprio usuário já tem acesso, como campanhas, anúncios, palavras-chave,
orçamentos, métricas e termos de pesquisa.</li>
</ul>

<h2>3. Como os dados são usados</h2>
<ul>
<li>Para responder às consultas e executar as ações pedidas pelo próprio usuário no
assistente de IA conectado.</li>
<li>Alterações nas contas do Google Ads só são feitas por pedido do usuário, depois
de uma simulação e de confirmação explícita.</li>
<li>Os dados não são vendidos, não são compartilhados com terceiros para publicidade
e não são usados para treinar modelos de IA nem para outra finalidade.</li>
</ul>

<h2>4. Armazenamento e segurança</h2>
<ul>
<li>A ferramenta guarda apenas os tokens de autenticação OAuth, criptografados, pelo
tempo necessário para manter a sessão do usuário.</li>
<li>Os dados do Google Ads não são armazenados em banco de dados: são lidos da Google
Ads API no momento de cada consulta e devolvidos ao usuário.</li>
<li>O provedor de hospedagem (Vercel) pode manter registros técnicos temporários de
funcionamento, como data, rota acessada e mensagens de erro, para diagnóstico.</li>
<li>Toda a comunicação é feita por conexão criptografada (HTTPS).</li>
</ul>

<h2>5. Compartilhamento</h2>
<p>As informações circulam apenas entre o usuário, o assistente de IA que ele
conectou, a ferramenta e as APIs do Google. Não há compartilhamento com outras
empresas, exceto quando exigido por lei ou ordem judicial.</p>

<h2>6. Uso limitado dos dados das APIs do Google</h2>
<p>O uso e a transferência de informações recebidas das APIs do Google seguem a
<a href="https://developers.google.com/terms/api-services-user-data-policy">Política de
dados do usuário dos serviços de API do Google</a>, incluindo os requisitos de uso
limitado (Limited Use).</p>

<h2>7. Seus direitos (LGPD)</h2>
<p>Nos termos da Lei Geral de Proteção de Dados (Lei nº 13.709/2018), você pode pedir
confirmação de tratamento, acesso, correção ou exclusão dos seus dados pelo e-mail
<a href="mailto:{email}">{email}</a>.</p>
<p>Você também pode revogar o acesso da ferramenta à sua conta Google a qualquer
momento em
<a href="https://myaccount.google.com/permissions">myaccount.google.com/permissions</a>.
Ao revogar, os tokens deixam de funcionar.</p>

<h2>8. Alterações desta política</h2>
<p>Esta política pode ser atualizada. A data no topo indica a versão em vigor.</p>

<h2>9. Contato</h2>
<p>{COMPANY} &middot; {ADDRESS}<br>
E-mail: <a href="mailto:{email}">{email}</a></p>""",
    )


def terms() -> str:
    email = html.escape(CONTACT_EMAIL)
    return _layout(
        f"Termos de serviço · {APP_NAME}",
        f"""<h1>Termos de serviço</h1>
<p class="muted">Última atualização: {UPDATED}</p>
<p>Estes termos regem o uso do {APP_NAME} ("ferramenta"), operado pela {COMPANY}
(CNPJ {CNPJ}). Ao entrar com a conta Google e usar a ferramenta, o usuário concorda
com estes termos.</p>

<h2>1. Finalidade</h2>
<p>A ferramenta conecta assistentes de IA à Google Ads API para consultar e gerenciar
as contas de anúncios da Riole. É uma ferramenta interna, sem fins comerciais, e não
é oferecida a clientes nem ao público.</p>

<h2>2. Usuários autorizados</h2>
<ul>
<li>Somente pessoas autorizadas pela Riole podem usar a ferramenta.</li>
<li>Cada usuário entra com a própria conta Google e só acessa as contas do Google Ads
às quais essa conta já tem permissão.</li>
<li>O usuário é responsável por manter a conta Google segura e por não compartilhar o
acesso.</li>
</ul>

<h2>3. Uso aceitável</h2>
<ul>
<li>Usar a ferramenta apenas para gerenciar as contas do Google Ads da Riole.</li>
<li>Revisar e confirmar cada alteração antes de aplicá-la. A ferramenta simula as
mudanças e só grava depois da confirmação do usuário.</li>
<li>Cumprir as políticas do Google Ads, os
<a href="https://developers.google.com/google-ads/api/docs/api-policy/terms">Termos e
condições da Google Ads API</a> e a legislação aplicável.</li>
<li>Não tentar burlar limites, controles de acesso ou a segurança da ferramenta.</li>
</ul>

<h2>4. Responsabilidade pelas alterações</h2>
<p>As decisões sobre campanhas, orçamentos, lances, palavras-chave e anúncios são do
usuário que as confirma. A Riole não se responsabiliza por resultados de campanhas
nem por alterações confirmadas pelo próprio usuário.</p>

<h2>5. Disponibilidade</h2>
<p>A ferramenta é fornecida "no estado em que se encontra", sem garantia de
funcionamento ininterrupto. Ela depende de serviços de terceiros (Google Ads API,
login do Google e hospedagem na Vercel), que podem ficar indisponíveis ou mudar.</p>

<h2>6. Privacidade</h2>
<p>O tratamento de dados segue a <a href="/privacidade">Política de privacidade</a>.</p>

<h2>7. Suspensão do acesso</h2>
<p>A Riole pode suspender ou encerrar o acesso de qualquer usuário a qualquer momento,
por exemplo, quando ele deixar de fazer parte da equipe ou descumprir estes termos.
O usuário pode deixar de usar a ferramenta e revogar o acesso a qualquer momento em
<a href="https://myaccount.google.com/permissions">myaccount.google.com/permissions</a>.</p>

<h2>8. Alterações dos termos</h2>
<p>Estes termos podem ser atualizados. A data no topo indica a versão em vigor.</p>

<h2>9. Lei aplicável</h2>
<p>Estes termos são regidos pelas leis da República Federativa do Brasil. Fica eleito
o foro da comarca de Colombo/PR para resolver eventuais questões.</p>

<h2>10. Contato</h2>
<p>{COMPANY} &middot; {ADDRESS}<br>
E-mail: <a href="mailto:{email}">{email}</a></p>""",
    )


ROUTES = {
    "/": home,
    "/privacidade": privacy,
    "/privacy": privacy,
    "/termos": terms,
    "/terms": terms,
}
