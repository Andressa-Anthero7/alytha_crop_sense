# SQLite: migrations e correção do bloqueio

Entrega em 15/10/2026. As mudanças de esquema ficam versionadas na tabela `schema_migrations` do próprio banco `data/monitoring.sqlite3`. Não há necessidade de outro banco para migrations.

## Comandos

```powershell
python -m app.migrate status
python -m app.migrate up
```

`status` consulta as versões aplicadas e pendentes sem criar um banco ausente. `up` aplica as migrations pendentes em uma transação; falhas revertem as alterações de esquema dessa execução. Não há comando de downgrade ou de apagar dados. Antes de aplicar em outra instalação, faça backup consistente e verifique a versão da aplicação.

O servidor aplica as migrations antes de atender requisições ou iniciar o monitor. Scripts que usam `storage.connect()` também inicializam a estrutura uma vez por arquivo e processo, com sincronização entre threads. As conexões seguintes não repetem `CREATE TABLE` ou `ALTER TABLE`. Bancos novos e bases legadas existentes são atendidos pela mesma sequência:

| Versão | Conteúdo |
| --- | --- |
| 1 | Áreas, análises, snapshots e eventos de campo. |
| 2 | Metadados de proveniência em áreas e eventos, preservando colunas já existentes. |
| 3 | Planos/ciclos de aprendizado, bases/revisões regionais e imagens/fila visual. |
| 4 | Índices de reutilização das análises visuais e das revisões regionais. |

## Causa encontrada

Uma inspeção da pilha do processo `run.py` encontrou a thread `learning-cycle` executando `visual_learning.register_base()`, na consulta de reutilização de análises anteriores. A rotina fazia consultas repetidas e inserções de todos os planos em uma única transação. A base tinha 15.550 planos e 46.650 trabalhos visuais, e não havia índice específico para a consulta por área, histórico, corte e status. O banco usava o modo de journal `delete`.

O servidor foi interrompido para encerrar a transação. Antes de reabrir o SQLite, o banco e o journal foram copiados para `data/outputs/database-backups/pre-migrations-20261016T001106Z/`. O nome da pasta usa UTC; a intervenção ocorreu na noite de 15/10 no fuso de São Paulo. O journal foi preservado para a recuperação automática do SQLite, sem remoção manual.

## Correção

- A inicialização do esquema foi centralizada em migrations transacionais, retirando DDL repetido dos módulos de aprendizado e análise visual.
- O SQLite passou a usar WAL. Leitores podem consultar o último estado confirmado enquanto outro acesso escreve. Isso continua permitindo apenas um escritor de cada vez.
- A consulta repetida de reutilização visual passou a ter índice por `area_key`, `dataset_id`, `cutoff` e `status`.
- A inscrição da fila prepara dados fora da transação de escrita e confirma lotes de até 100 registros. IDs existentes são preservados e uma tentativa interrompida pode retomar sem duplicar trabalhos. O marcador de registro concluído só é salvo após todos os lotes.
- Falhas na inicialização fecham a conexão; não deixam um identificador de arquivo aberto.

Para abrir a aplicação sem iniciar o monitor automático:

```powershell
python run.py --no-workers
```

Essa opção pausa a inicialização automática do monitor; não transforma toda a aplicação em modo offline. Ações de coleta e retomada solicitadas nas demais telas mantêm o comportamento existente.

## Verificação e backup

As quatro migrations foram aplicadas na base real. As contagens antes/depois foram iguais: 1 área, 22.527 snapshots, 15.550 planos, 46.650 trabalhos visuais, 6 imagens cadastradas e 5 versões regionais. `PRAGMA quick_check` retornou `ok`; `PRAGMA foreign_key_check` não retornou violações. Uma inscrição posterior de nova fila pode aumentar as contagens normalmente.

A suíte completa passou com 266 testes em SQLite temporário. Ela inclui atualização de base legada, idempotência, rollback de migration com falha, leitura durante escrita, uso do índice e retomada de inscrição visual após interrupção entre lotes.

A inscrição real da fila visual também foi concluída após a correção: o marcador passou a corresponder à base regional atual, e a fila passou de 46.650 para 62.200 trabalhos, sem executar aquisição de imagens ou revisão por provedor de IA. Uma primeira sondagem concorrente encontrou um lock transitório na abertura do SQLite; após a inicialização, o teste HTTP de leitura durante escrita retornou 200 em cerca de 0,07 s. Isso verifica esse cenário, sem prometer ausência de todos os locks possíveis no SQLite. O inventário HTTP retornou 200, banco disponível e nenhuma pendência, em cerca de 6,35 s. O servidor foi reaberto com `--no-workers` nesta fase.

Com WAL, uma cópia isolada do arquivo `.sqlite3` durante uso pode omitir transações confirmadas que ainda estão no arquivo `-wal`. Use a API de backup do SQLite para uma cópia consistente; o helper existente `app.regional_batch.backup(destino)` utiliza essa API. Em uma cópia física para recuperação, pare todos os processos que usam o banco e preserve os arquivos auxiliares presentes junto do arquivo principal. Não remova manualmente journal, WAL ou SHM para tentar liberar locks.

Relatórios locais da intervenção estão em `data/outputs/diagnostics/`; o inventário atualizado fica em `data/outputs/inventory/local-inventory.json`.
