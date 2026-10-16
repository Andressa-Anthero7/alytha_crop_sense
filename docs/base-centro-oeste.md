# Base de desenvolvimento do Centro-Oeste

Coleta iniciada em 13/10/2026, usando o pipeline regional. Listas oficiais do IBGE consultadas na inicialização: MT 142 municípios, MS 79, GO 246 e DF 1 unidade municipal equivalente (Brasília), total 468. As regiões administrativas do DF não são tratadas como municípios separados.

## Execução atual

O servidor local e o monitor foram iniciados como processos em segundo plano. O servidor atende em `http://127.0.0.1:8765`. Dois trabalhadores regionais executam a coleta, inicialmente DF e GO, com MS e MT na fila. A coleta completa depende de internet, disponibilidade e cota Copernicus e pode levar dias. Desligar ou suspender o computador interrompe o trabalho.

Os dados entram na base utilizada pela aplicação, `data/monitoring.sqlite3`. A base anterior não foi apagada. Uma cópia SQLite anterior à coleta fica em `data/outputs/centro-oeste/baseline-before.sqlite3`.

## Acompanhamento e artefatos

Abra `http://127.0.0.1:8765/coleta.html` para acompanhar progresso geral, estados e recortes em processamento. A tela e o monitor atualizam a cada 10 segundos e avisam quando o relatório fica antigo. `python -m app.regional_batch status` mostra o último relatório salvo pelo monitor.

O mapa municipal usa malhas simplificadas do IBGE e colore os municípios por andamento: completo, parcial, carregando, falha e fila. Clicar mostra os recortes e leituras coletados. As cores não indicam cultura ou vigor. A malha disponível nesta fonte inclui 467 das 468 unidades da rodada; Boa Esperança do Norte/MT permanece no relatório sem contorno disponível. Para recriar o arquivo cartográfico local, execute `python -m app.collection_map`.

Os filtros de situação, causa e nome/UF se aplicam ao mapa e à lista de municípios; os indicadores gerais continuam cobrindo a rodada inteira. As pendências discriminam Sentinel-2, MapBiomas, IBGE, CONAB, limites, recortes ausentes, leituras insuficientes e perfis ML. Uma cidade pode ter várias pendências e aparecer em mais de uma causa. A lista mostra 100 linhas por vez e permite carregar mais.

Históricos antigos permitem recuperar os anos cuja consulta falhou, mas nem sempre preservam o erro técnico. Nesse caso aparece “motivo técnico não registrado”, sem atribuir a falha a nuvens ou quota. Consultas novas registram erros HTTP, timeout e limites sem expor credenciais ou respostas privadas. Sem soja histórica e sem recorte de pelo menos 5 ha são resultados diferentes de uma falha ao ler MapBiomas. A falta de classificação recente não confirma falha da API.

Em `data/outputs/centro-oeste/`:

- `manifest.json`: identificação da rodada, escopo, IDs das quatro varreduras e progresso.
- `roster-{UF}.json`: lista municipal oficial, origem e data de obtenção.
- `scan-{UF}.json`: andamento por município, atualizado pelo monitor.
- `server.*.log` e `monitor.*.log`: logs locais; arquivos `.pid` identificam os processos iniciados.
- `baseline-collected.sqlite3`: cópia da base ao terminar a rodada, inclusive quando houver pendências. Só é criada depois de as quatro varreduras encerrarem.

O monitor marca `finished_with_pending` quando há cidades/fontes incompletas. Não considera falha, ausência de imagens ou dados inconclusivos como conclusão agronômica. Histórico desde 2018 pertence aos recortes de referência; a base não terá histórico integral de todos os pixels do Centro-Oeste. Permanecem os [limites de processamento municipal](coleta-regional.md).

## Retomada

Nesta rodada, as consultas ao Copernicus usam uma requisição por vez, com intervalo mínimo de 5 segundos após cada resposta. O token de acesso é reutilizado durante sua validade. Erros HTTP 429 recebem até duas novas tentativas, com espera crescente e respeito ao prazo informado pelo serviço. Isso reduz pressão sobre a API, mas não corrige falta de autorização, ausência de imagens ou quota esgotada. As cidades já encerradas permanecem preservadas para revisão posterior.

Depois de reiniciar o computador, execute `python run.py` e, em outro terminal, `python -m app.regional_batch watch`. O monitor consulta os IDs persistidos e o servidor retoma varreduras interrompidas. Se a inicialização das quatro regiões tiver sido interrompida, execute primeiro `python -m app.regional_batch start`.

O comando `start` reutiliza o manifesto existente: não apaga a base nem inicia outra rodada diária. Atualizações futuras devem ser identificadas como novas rodadas, preservando este material. Cidades encerradas com pendências não entram em repetição infinita; devem ser revisadas antes de uma nova tentativa.

Antes de usar como conjunto de avaliação: revisar cobertura, datas das consultas filhas, cidades com falha, leituras suficientes e independência espacial dos recortes. A coleta regional prepara observações; os registros de campo e a validação com produtores continuam necessários.

## Cobertura de treinamento no mapa

O mapa abre na visao de dados usados no treinamento: roxo indica municipio com modelo exploratorio salvo; cinza indica ausencia de modelo registrado. O filtro Treinamento restringe mapa e lista. Ao selecionar um municipio, aparecem a quantidade de recortes, perfis e a data de corte. A opcao Andamento da coleta recupera as cores de progresso. A cobertura municipal nao significa que todos os pixels foram usados: somente recortes com series suficientes entram nos modelos. Um modelo pode coexistir com pendencias no historico regional. Os indicadores leem os modelos salvos no SQLite, inclusive treinamentos feitos fora do monitor.
