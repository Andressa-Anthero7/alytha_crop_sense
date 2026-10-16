# Levantamento da aplicação

> Documento histórico de 08/10/2026: algumas descrições abaixo foram superadas. Para o estado e o roteiro da demonstração guiada aos produtores, consulte [MVP para parceiros](mvp-parceiros.md) e execute `python -m app.demo_check` para verificar os dados locais atuais. Assistente, persistência, mapas de culturas e acompanhamento integrado já estão implementados.

Revisão em 08/10/2026, baseada no código, nos testes e no planejamento existente. Esta revisão não reconfirma preços, contratos, quotas ou condições dos fornecedores citados nos documentos históricos.

## O que já temos

| Recurso | Estado observado | Onde está |
| --- | --- | --- |
| Aplicação independente | Servidor Python local; inicia sem Node, Django, banco ou instalação de pacotes | `run.py`, `app/web_app.py` |
| Mapa sem credenciais | Leaflet local com mosaicos OpenStreetMap; busca por coordenadas | `web/index.html`, `web/vendor/leaflet/` |
| Google Maps opcional | Implementado; endereço e geocodificação dependem de chave e APIs habilitadas. Sem validação real nesta revisão | `web/index.html`, `.env.example` |
| Upload de talhão | Uma geometria Polygon/MultiPolygon, direta ou em Feature/FeatureCollection; limite de 2 MB; permanece na sessão | `web/index.html`, `app/catalog_search.py` |
| Catálogo Sentinel-2 | Consulta STAC por polígono, datas e nuvens, lista metadados e desenha cenas; validado com chamada real no navegador e terminal | `app/catalog_search.py`, `/api/search` |
| Série NDVI | Código do Statistical API com máscara SCL, pixel de 10 m, intervalos de cinco dias e gráfico; até um ano por consulta | `app/web_app.py`, `/api/ndvi-series` |
| Camada NDVI | Código para imagem PNG por data e sobreposição no mapa | `app/web_app.py`, `/api/ndvi-map` |
| Configuração | `.env` na raiz, variáveis de ambiente com prioridade; segredo OAuth não sai em `/api/config` | `.env.example`, `app/web_app.py` |
| Earth Engine | Script de autenticação e inicialização; não consulta nem classifica dados | `app/setup_earth_engine.py` |
| Testes | 26 testes HTTP, configuração, armazenamento, adaptadores e triagem de inatividade; consultas reais e fluxo no navegador Google/Leaflet verificados | `tests/test_standalone.py`, `tests/test_sources.py`, `tests/test_municipalities.py`, `tests/test_inactive_soy.py` |
| Possível lavoura inativa | Filtro experimental de soja histórica + NDVI recente; até 10 manchas nativas por recorte, evidências e camada coral. Consulta real em Sorriso identificou um candidato | Não comprova safra passada ou área vazia. Regra de NDVI ainda exige validação agronômica/de campo |
| Planejamento | Direção do produto, pesquisa de fontes e planilha com 29 tarefas | `docs/`, `docs/plano-implementacao-ia.xlsx` |

**Atualização após os testes:** credenciais locais recuperadas; Google Maps, catálogo, série e camada NDVI testados com o polígono fictício em agosto de 2026. Foram retornadas nove cenas e seis pontos na série. Seleção de estado/município via IBGE e desenho de área estão implementados. Ainda precisamos de validação agronômica em áreas conhecidas; esses testes confirmam apenas o fluxo técnico.

## O que ainda não temos

| Necessidade | Situação atual | O que será necessário |
| --- | --- | --- |
| Descoberta de áreas produtoras | Modo I.A apenas recebe um prompt e mostra aviso | Busca estruturada por região, cultura e safra; fonte de raster; recorte, agrupamento e camada de candidatos |
| MapBiomas | Recorte remoto Coleção 11 (1985–2025, 30 m), seleção de manchas agrícolas e origem salva; consulta real validada | Confirmar campo/cultura atual; manchas recortadas não são cadastro de talhões |
| CONAB | Importação real da série de grãos, cache local e tabela por UF/safra para soja, milho e sorgo | Estatísticas estaduais não estimam produtividade do polígono |
| IBGE e base municipal | Seleção de cidade agenda dossiê persistente no backend: limite IBGE, CONAB estadual e resumo MapBiomas 2025 do município inteiro; processamento em blocos e reutilização por 24 h | Sorriso validado em consulta real, 10.669.746 pixels; limites administrativos não identificam talhões. IA ainda sem provedor |
| Embrapa SATVeg | Adaptador e configuração preparados; botão bloqueado sem credencial | Obter token AgroAPI e validar consulta real MODIS |
| CAR | Sem integração | Definir fonte e acesso; cadastro não comprova titularidade |
| Classificação de soja, milho e sorgo | Não existe modelo nem conjunto de amostras | Geometrias rotuladas por cultura/safra, referência de campo, baseline e validação independente; sorgo exige dados próprios |
| Cadastro de produtor e lote | Cadastro local de área, município, cultura/safra declaradas e geometria já entregue | Vincular produtor/lote, definir edição e revisão |
| Histórico e evidências | Catálogo e séries NDVI persistidos no SQLite, reabertura, comparação descritiva e exportação JSON já entregues | Adicionar versões de processamento, revisão humana, imagens, relatório e backups operacionais |
| Monitoramento contínuo | Consultas manuais | Agendamento, cache, retomada após falhas, alertas e controle de chamadas |
| Revisão operacional | Sem parecer do analista ou fluxo de decisão | Estados, justificativas, anexos e histórico da revisão |
| Serviço de IA | Não há endpoint, provedor ou modelo conectado | Definir uma tarefa concreta e seus critérios; o primeiro detector pode ser geoespacial sem LLM |
| Uso por uma equipe | Servidor local sem autenticação e separação de usuários | API e servidor adequados à operação, controle de acesso, persistência e implantação |
| Validação geoespacial completa | Verifica tipo e presença de coordenadas; não garante polígono válido | Validar coordenadas, anéis, área, auto-interseções e limites antes de chamar provedores |
| Tratamento de falhas e observabilidade | Erros básicos retornados na API | Cobrir respostas reais dos provedores, timeouts, quotas, limites, logs e métricas; sem expor segredos |

## Sequência proposta

1. **Validar o monitoramento atual:** obter credenciais CDSE e um talhão autorizado, testar série e imagem NDVI, registrar resultados esperados e casos sem observações válidas. Aceite: os dois fluxos reais funcionam e os erros são compreensíveis.
2. **Guardar as análises:** definir cadastro mínimo e esquema de evidências; escolher armazenamento, persistir consultas e exportar um relatório simples. Aceite: reabrir o talhão e recuperar a mesma análise com fonte e parâmetros.
3. **Fazer um piloto de descoberta:** selecionar uma região, cultura e safra; escolher acesso aos dados históricos; implementar recorte e agrupamento de pixels com regras explícitas. Aceite: candidatos aparecem no mapa com metadados e incertezas.
4. **Comparar com referências de campo:** reunir amostras e revisão agronômica; medir erros por cultura, região e safra antes de chamar o resultado de classificação. Aceite: métricas e limites documentados, com casos inconclusivos preservados.
5. **Preparar a operação:** usuários, revisão, agendamento, cache, implantação, backups e acompanhamento das integrações conforme volume de uso.

## Informações que precisamos definir juntas

- Objetivo da primeira entrega: acompanhar talhões conhecidos ou descobrir novas áreas candidatas?
- Região/município, cultura, safra e quantidade de talhões do piloto.
- Geometrias autorizadas e referência de campo disponíveis.
- Acesso CDSE para testar NDVI; acesso e processamento dos mapas históricos se o foco for descoberta.
- Quais resultados precisam ser salvos e quem revisará as evidências.
- Uso local por uma pessoa ou compartilhado pela equipe, e orçamento para dados/processamento quando necessário.

## Como ler o planejamento existente

A planilha contém 29 tarefas, incluindo escopo, dados, modelo, produto, backend, validação e governança. Ela é um plano, não uma confirmação do código entregue. O Modo I.A permanece sem busca implementada, enquanto CDSE foi configurado e testado após o levantamento inicial. As atualizações desta nota prevalecem para o levantamento técnico.

As pesquisas de fornecedores foram preservadas. Antes de escolher ou contratar fontes, será necessário rever as informações oficiais atuais e comparar com os requisitos do piloto.
