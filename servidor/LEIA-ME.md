# Jarvis HAIZEN no servidor (Hostinger VPS)

O Jarvis roda 24 h num VPS Ubuntu 24.04, abre em `https://seu-dominio` de qualquer lugar (PC,
notebook, celular) e só entra quem fizer login com o e-mail Google autorizado. As pastas dos
clientes continuam no seu Google Drive (o servidor monta o Drive em `/srv/drive`).

## 1. Antes: VPS, domínio e DNS

1. Hostinger → VPS **KVM 2** (mínimo) ou **KVM 4** (recomendado), **Ubuntu 24.04 LTS**, sem painel.
2. No DNS do domínio, crie um registro **A**: nome `jarvis` (ou o subdomínio que escolher) →
   IP do VPS. Espere alguns minutos.

## 2. Login do Google (cliente OAuth "Aplicativo da Web")

1. [console.cloud.google.com](https://console.cloud.google.com) → o mesmo projeto do Google Ads
   (ou um novo) → **APIs e serviços → Credenciais → Criar credenciais → ID do cliente OAuth**.
2. Tipo: **Aplicativo da Web**. Nome: `Jarvis servidor`.
3. **URIs de redirecionamento autorizados**, adicione os dois:
   - `https://SEU-DOMINIO/auth/google/retorno`  (login no Jarvis)
   - `https://SEU-DOMINIO/oauth/google-ads`      (reconectar o Google Ads pelo servidor, se precisar)
4. Copie o **ID do cliente** e a **Chave secreta**.
5. Se a tela de consentimento estiver em "Teste", adicione o seu e-mail em **Usuários de teste**.

## 2b. Cliente próprio para o Drive (recomendado)

O cliente compartilhado do rclone está sendo desativado pelo Google. No mesmo projeto:
1. **APIs e serviços → Biblioteca → Google Drive API → Ativar**.
2. **Credenciais → Criar credenciais → ID do cliente OAuth → App para computador**, nome `rclone Drive`.
3. Guarde o ID e a chave; use-os em `rclone authorize "drive" "ID" "CHAVE"` e no `sudo jarvis drive`.

## 3. Instalar (no terminal do VPS: painel da Hostinger → Terminal do navegador)

```bash
curl -fsSL https://raw.githubusercontent.com/Hiago-lc/jarvisGPT/main/servidor/instalar.sh -o instalar.sh
sudo bash instalar.sh
```

Ele pergunta o domínio e o seu e-mail, e instala tudo (Python, ffmpeg, navegador, HTTPS, Claude
Code, serviço que reinicia sozinho). Pode rodar de novo sem problema.

## 4. Os 4 passos de uma vez só

```bash
sudo jarvis drive          # conecta o Google Drive (usa o rclone no seu PC para autorizar)
sudo nano /etc/jarvis/jarvis.env   # cole HAIZEN_GOOGLE_LOGIN_ID e HAIZEN_GOOGLE_LOGIN_SEGREDO; Ctrl+O, Enter, Ctrl+X
sudo jarvis claude         # login do Claude Code com a sua assinatura (/login)
sudo jarvis importar       # traz os dados do PC: usa o .jarvispack mais novo de "Meu Drive/JARVIS - migracao"
sudo jarvis iniciar
```

Abra `https://SEU-DOMINIO` e entre com o Google.

Depois de importar, **desligue o início automático do Jarvis no PC** (ou deixe o PC só com a
janela de voz ligada ao servidor): dois Jarvis com o mesmo banco rodariam as rotinas em dobro.

## Dia a dia

| Comando | Para quê |
|---|---|
| `sudo jarvis status` | ver se está rodando (Jarvis, Drive e HTTPS) |
| `sudo jarvis logs` | últimas linhas do registro |
| `sudo jarvis reiniciar` | reiniciar |
| `sudo jarvis atualizar` | baixar a versão nova do GitHub e reiniciar |

Também dá para atualizar pela própria central: **Sistema → Atualizar Jarvis**.

## Onde fica cada coisa

- Código: `/opt/jarvis` · Dados (banco, configurações): `/var/lib/jarvis/dados`
- Configuração e chave dos segredos: `/etc/jarvis` (só o usuário `jarvis` lê)
- Drive: `/srv/drive` (CLIENTES, JARVIS - backups, JARVIS - migracao)
- O backup diário do banco continua indo para `Meu Drive/JARVIS - backups`.
