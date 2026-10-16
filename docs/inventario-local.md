# Inventário local pela Alytha

Entrega inicial em 15/10/2026, ligada a IA-01, IA-02 e ao início de IA-03 do [quadro de implementação](quadro-implementacao-ia.xlsx).

## Uso na conversa

Pergunte “Quais imagens temos salvas?”, “Que dados temos disponíveis?” ou “Mostre o inventário local”. A Alytha executa uma consulta local e retorna a quantidade de históricos, prévias e rasters, com limitações. A resposta não depende de chave ou chamada a um provedor de linguagem.

A seleção atual de município/estado, histórico, geometria e data limita a consulta. Para outra localidade, selecione-a no mapa antes de perguntar. Sem seleção, a consulta inventaria a base local do sistema. Este recurso usa o modelo de acesso local existente; não introduz isolamento entre produtores.

O inventário não inicia workers, não retoma coletas interrompidas, não lê o `.env` e não consulta Sentinel, Embrapa ou internet. O SQLite é aberto em modo somente leitura, sem criar tabelas ou executar migrações. Banco ocupado ou ausente aparece como pendência; não significa ausência de históricos.

## API e exportação

`GET /api/local-inventory` aceita `dataset_id`, `municipality_code`, `state_code` e `map_date` como parâmetros opcionais. A geometria selecionada também é considerada quando a consulta vem de `POST /api/assistant`.

```powershell
python -m app.local_inventory --output data/outputs/inventory/local-inventory.json
python -m app.local_inventory --municipality-code 5107925 --map-date 2026-10-15
```

O comando só escreve um relatório quando `--output` é informado. O arquivo gerado é um retrato da inspeção, não um cache atualizado automaticamente.

## Contrato de evidências v1

Cada item da lista `evidence` contém:

| Campo | Significado |
| --- | --- |
| `id`, `contract_version`, `kind` | Identidade estável, versão do contrato e tipo do recurso. |
| `source`, `scope`, `area_key`, `period` | Origem declarada, escala, vínculo de recorte e período conhecido. Campos desconhecidos permanecem nulos. |
| `provenance` | Recurso local relativo à pasta de dados ou chave SQLite, método e versão do inventário. |
| `quality` | Disponibilidade, verificação de integridade e indicadores conhecidos. Contagem de observações não representa qualidade agronômica. |
| `data` | Metadados específicos: dimensões, número de bandas, resolução declarada, versão de renderização ou informações do histórico. |

Os tipos iniciais são `ndvi_history`, `image_preview` e `raster`. Esse contrato já é usado pelo inventário; a migração das evidências de outros módulos ainda está pendente em IA-02.

Uma série NDVI não implica existência das bandas originais no disco. Para rasters, o inventário lê o cabeçalho quando rasterio está instalado e não deduz o significado das bandas apenas pela contagem. O tamanho de pixel é informado em unidades do CRS. Metadados das prévias conservam a resolução nativa declarada pelo renderizador.

Prévias ausentes ou cujo SHA-256 diverge do metadado não entram na contagem de prévias disponíveis. Referências a arquivos fora da pasta de dados não são lidas. Metadados ilegíveis geram pendências explícitas.

Históricos têm lista limitada a 100 entradas; o total e os vínculos de imagens consideram todos os históricos correspondentes. O corte temporal filtra observações e exclui imagens cujo período termina depois do corte. O estado do trabalho e a data de gravação do snapshot são os atualmente salvos, não uma reconstrução do estado do banco naquela data. Arquivos sem vínculo de área ou período verificável ficam fora de consultas filtradas.

## Verificação e situação real

Os 17 testes de `tests/test_local_inventory.py` cobrem leitura sem escrita, ausência de rede, filtros de área e período, arquivos ausentes ou alterados, banco indisponível, limite da lista, contrato, conversa e endpoint HTTP. Os 44 testes existentes de `test_assistant*.py` passaram com o banco global substituído por um SQLite temporário durante a execução, evitando acesso à base de trabalho.

A primeira inspeção real desta entrega confirmou seis prévias NDVI disponíveis, nenhuma prévia em cor natural e três arquivos raster. Naquele momento o banco apresentou bloqueio de leitura; os históricos não foram contados, e o relatório inicial registrou `database_available: false`. Nenhum processo foi interrompido durante essa primeira inspeção.

Atualização posterior em 15/10/2026: o bloqueio foi corrigido em uma intervenção de banco, com backup, migrations e gravação em lotes; veja [banco e migrations](banco-migrations.md). O inventário real passou a retornar `database_available: true`, sem pendências, e identificou 17.602 históricos correspondentes, incluindo versões e sementes regionais. Esses registros não representam 17.602 talhões independentes. A lista detalhada permanece limitada a 100 históricos, com as contagens de observações dessa lista separadas do total. IA-01 foi revisada após essa verificação.

O próximo incremento deve ampliar o contrato e expor análises históricas/direcionais e janela declarada como ferramentas conversacionais com resultados verificáveis. O inventário não executa essas análises nem implementa meteorologia, radar ou busca web.
