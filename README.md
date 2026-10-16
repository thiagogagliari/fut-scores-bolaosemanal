# Fut Scores

Uma versão independente, em Python e SQLite, do bolão semanal de futebol.
Inclui cadastro e login, palpites por partida, classificação com comparação,
histórico e um painel administrativo para gerenciar times e escudos, participantes,
rodadas, partidas, resultados e pagamentos. Palpites de outros participantes só
são enviados ao navegador depois do início da respectiva partida. Não precisa
instalar dependências externas.

Também é possível publicar na Vercel usando PostgreSQL externo. O modo local
continua usando SQLite; em produção, configure `DATABASE_URL` para apontar para
um PostgreSQL persistente.

No painel, o administrador pode incluir, renomear e excluir times, além de
fornecer um endereço HTTP/HTTPS para a imagem do escudo. Se um time for excluído,
ele deixa de ser oferecido em novos cadastros e partidas; nomes já associados a
perfis e registros antigos são preservados. O administrador também pode bloquear,
desbloquear ou excluir participantes. Excluir um participante remove suas sessões,
palpites e pagamentos. Excluir uma rodada remove também suas partidas, palpites e
pagamentos.

Os palpites são salvos automaticamente jogo a jogo assim que os dois placares
forem preenchidos; não é necessário completar todos os jogos para salvar. A tela
mostra o progresso dos palpites da rodada e o estado de salvamento de cada jogo.
O usuário pode corrigir um palpite até o horário de início daquela partida; após
o início, o jogo fica bloqueado. A classificação considera os resultados já
informados pelo administrador, inclusive os jogos apurados da rodada atual, e é
atualizada automaticamente na tela dos jogadores.
Após o início de cada partida, a comparação revela o palpite dos demais jogadores.
Quando o resultado oficial for informado, cada partida mostra o placar e os pontos
conquistados por palpite.

Ao encerrar uma rodada com resultado oficial em todas as partidas, cada jogador vê
um aviso com o(s) campeão(ões), a pontuação, os palpites exatos e a comparação jogo
a jogo com seus próprios palpites. Em caso de empate na maior pontuação, o valor
arrecadado com os pagamentos confirmados é dividido igualmente entre os campeões,
com eventuais centavos restantes atribuídos em ordem alfabética. Palpites de
placar exato são destacados em verde. Cada campeão recebe um código de confirmação
no aviso da rodada; o administrador pode conferir o mesmo código no painel da
rodada antes de validar a entrega do prêmio.

O pagamento deve ser confirmado pelo administrador antes do início da primeira
partida da rodada. O painel administrativo sinaliza quem já palpitou sem pagar e
quantos palpites registrou; ao fim do prazo, essas pessoas ficam fora da
classificação, da disputa pelo prêmio e da comparação pública de palpites. A
situação de pagamento de todos os participantes é exibida aos jogadores.

O painel administrativo apresenta a arrecadação confirmada por rodada e um
relatório de prêmios calculados e efetivamente entregues. Marcar um campeão como
pago registra a entrega confirmada pelo administrador; o histórico do bolão
mostra, para todos os jogadores, quanto foi entregue em cada rodada e o total
acumulado. O valor calculado do prêmio não é considerado pago até essa
confirmação.

Os escudos externos precisam ser configurados pelo administrador no catálogo de
times; sem uma URL de imagem válida, a interface mantém o escudo estilizado de
fallback. A área superior da conta do jogador fica verde quando o pagamento da
rodada atual está confirmado. Ela mostra a contribuição individual e o total
arrecadado na rodada, calculado pelo valor da inscrição multiplicado pelo número
de pagamentos confirmados elegíveis.

## Executar

```powershell
python app.py
```

Abra <http://127.0.0.1:8000>. O banco é criado automaticamente em
`data/futscores.sqlite3`.

Conta de demonstração:

- E-mail: `torcedor@futscores.com`
- Senha: `torcida123`

Conta de administrador local:

- E-mail: `admin@futscores.com`
- Senha: `admin123`

O admin entra pela mesma tela de login e é encaminhado ao painel de
administração. Para definir credenciais próprias, configure `FUTSCORES_ADMIN_EMAIL`
e `FUTSCORES_ADMIN_PASSWORD` antes de iniciar; elas também atualizam a conta
admin já provisionada. A senha padrão é apenas para desenvolvimento local:
ao expor o servidor na rede, é obrigatório configurar `FUTSCORES_ADMIN_PASSWORD`.

```powershell
$env:FUTSCORES_ADMIN_EMAIL = "admin@seudominio.com"
$env:FUTSCORES_ADMIN_PASSWORD = "uma-senha-forte"
python app.py
```

Para executar os testes:

```powershell
python -m unittest discover -s tests
```

Defina `PORT` para escolher outra porta. Para permitir acesso pela rede local,
defina `FUTSCORES_HOST=0.0.0.0`.

## Publicar na Vercel

1. Crie um PostgreSQL gerenciado, por exemplo pelo Marketplace da Vercel
   (Neon/Supabase), e use a URL de conexão com pool quando o provedor oferecer
   uma. A aplicação não usa o SQLite local quando `DATABASE_URL` está definido.
2. Antes de publicar ou abrir o site, importe o SQLite local para o banco remoto
   vazio. No PowerShell, carregue a URL sem gravá-la no histórico do shell e
   rode a conferência, que só lê o arquivo local:

   ```powershell
   $secureUrl = Read-Host "URL do PostgreSQL de destino" -AsSecureString
   $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureUrl)
   $env:DATABASE_URL = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
   [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
   Remove-Variable secureUrl, pointer
   python .\scripts\import_sqlite.py
   ```

   Confira as contagens. Para importar, mantenha a variável no mesmo terminal e
   execute:

   ```powershell
   python .\scripts\import_sqlite.py --apply
   Remove-Item Env:DATABASE_URL
   ```

   A importação cria o esquema no destino, aborta se encontrar dados já
   existentes e não altera nem apaga `data/futscores.sqlite3`. Se a importação
   falhar, corrija a causa e use um banco vazio antes de tentar novamente.
3. Importe este projeto na Vercel. Mantenha `vercel.json` como arquivo de
   configuração e defina o diretório raiz do projeto como a pasta que contém
   `app.py`, `api/`, `static/` e `templates/`.
4. Nas variáveis de ambiente do projeto Vercel, adicione `DATABASE_URL`,
   `FUTSCORES_ADMIN_EMAIL` e `FUTSCORES_ADMIN_PASSWORD`. Use uma senha de
   administrador forte, com pelo menos oito caracteres, e habilite as variáveis
   para Production (e Preview, se também for testar em previews). Cadastre esses
   valores diretamente no painel da Vercel; não os coloque no código, no Git ou
   nesta conversa.
5. Faça o deploy. A primeira requisição inicializa/verifica o esquema. O login
   administrativo configurado atualiza a conta de administrador importada.

O runtime da Vercel precisa de rede até o PostgreSQL; o arquivo SQLite do
computador não é enviado nem usado em produção. A dependência PostgreSQL está
declarada em `requirements.txt`. Se `DATABASE_URL` não estiver configurada no
runtime da Vercel, o app interrompe a inicialização em vez de usar um SQLite
temporário.

### Reimportar dados

O script de importação foi pensado para uma carga inicial em banco vazio. Ele
preserva IDs, cadastros, times, rodadas, partidas, palpites, pagamentos e
histórico de prêmios; não é uma sincronização contínua. Para migrar alterações
posteriores, faça um backup e prepare uma migração específica antes de executar
novamente.
