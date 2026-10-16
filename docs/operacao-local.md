# Fila, backup e preparação de homologação

Incremento de 15/10/2026: avanços parciais de IA-24 a IA-26. Não equivale a liberação de produção.

## Fila local durável

`POST /api/assistant/jobs` recebe uma pergunta analítica e `dataset_id`, devolvendo HTTP 202 com ID. Somente comparação histórica, direção, janela declarada, síntese e calendário regional são aceitos. Busca externa, meteorologia, coleta Sentinel e chamadas a modelos de linguagem não entram na fila de repetição local.

Execute a API com `python run.py --no-workers` e, em outro processo, `python -m app.analysis_worker`. `--once` processa um trabalho. A análise síncrona pela conversa permanece disponível sem esse processo adicional.

A migration 5 adiciona `analytical_jobs`. Deduplicação considera parâmetros e versões dos dados locais. Reservas de execução duram cinco minutos, com renovação a cada 30 segundos; no máximo dois trabalhos locais possuem reserva ativa. Reinício permite recuperar reservas expiradas. Três interrupções encerram o trabalho com erro. Um token de reserva impede que um worker antigo publique por cima do resultado de seu substituto.

GET `/api/assistant/work/{id}` acompanha trabalhos e resultados. GET `/api/health` mostra conectividade do banco, versão, estados, reservas expiradas e tempo médio da fila local. Esses números não medem custos nem disponibilidade dos fornecedores.

Os coletores antigos continuam com mecanismos próprios. Migrar todos os trabalhos de satélite e IA externa para a arquitetura durável, com limites por fornecedor e tratamento de consumo ambíguo após falha, permanece pendente em IA-24. Não prometer repetição exatamente uma vez de chamadas externas.

## Backup e restauração

```powershell
python -m app.backup create
python -m app.backup restore CAMINHO.zip --destination PASTA_NOVA
```

O modo `core` captura SQLite pela Backup API, modelos, rasters e arquivos visuais de origem. Omite exportações regeneráveis. `--full` inclui os arquivos da árvore `data`, sem `.env`, auxiliares SQLite e temporários. Backups ficam em `local_backups`, fora da árvore copiada e do Git. Restauração exige uma pasta nova, valida caminhos, tamanhos, hashes, integridade SQLite e contagens por tabela.

A consistência do banco não é um snapshot global simultâneo de todos os workers. Cada artefato é conferido antes/depois da cópia; mudanças durante captura cancelam o backup. Para uma cópia operacional completa, pare os produtores de artefatos antes do modo full, preserve a configuração secreta por um canal separado e teste os vínculos absolutos de arquivos no ambiente destino.

Foi executada restauração local de um backup core real com 61 arquivos, banco íntegro e contagens coincidentes. O ambiente principal foi preservado. Backup externo, política de retenção e ensaio operacional completo em outra máquina continuam pendentes.

## Receita de homologação

`Dockerfile.homologacao`, `compose.homologacao.yaml` e `requirements-homologacao.txt` preparam API e worker analítico em processos separados, com volume compartilhado e porta restrita a `127.0.0.1`. O worker local não recebe o arquivo de segredos. A imagem não copia `.env`, banco ou backups.

As dependências foram fixadas a partir das distribuições instaladas no ambiente testado. Docker não está instalado neste computador; build Linux, permissões do volume e inicialização do Compose ainda não foram executados. Não apresentar a receita como ambiente homologado.

Quando houver Docker, o comando de ensaio é `docker compose -f compose.homologacao.yaml up --build`. Não publicar esta imagem diretamente: ela ainda usa o servidor local e não implementa autenticação de produtores.

## Identidade e isolamento — IA-25 pendente

Antes da implementação, separar as entidades `organization`, `user`, `membership`, `area_owner` e a autoria de eventos/trabalhos. A sessão autenticada deve determinar a organização no servidor, sem aceitar `organization_id` do corpo como autorização. Áreas, geometrias, eventos, exportações, trabalhos, arquivos e conversas precisam da mesma verificação de propriedade.

Caches públicos de IBGE, CONAB e cobertura agrícola podem ter compartilhamento explícito; cadastro e anotações privadas não podem herdar essa permissão. A atribuição de registros antigos exige revisão: não transferir todo o banco ao primeiro usuário criado. Workers devem carregar a organização do trabalho persistido e validar o destino dos artefatos.

O aceite exige testes em todos os endpoints, IDs adivinhados, listagem, exportações, downloads e execução por worker: usuário A não acessa recursos de B. A escolha do provedor de identidade, organização inicial, usuários do piloto e política de reivindicação de áreas continua aberta. Nenhum login parcial foi exposto como isolamento pronto.
