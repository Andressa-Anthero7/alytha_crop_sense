# Alytha — monitoramento de lotes

**Análises na conversa:** comparação histórica, direção em rasters locais, janela declarada, síntese de hipóteses, clima NASA POWER e pesquisa no portal Embrapa agora retornam trabalhos e evidências verificáveis. Veja [uso, fontes e limites](docs/analises-conversacionais.md).

**Operação local:** há fila persistente para análises locais com worker separado, endpoint de saúde e backup/restauração verificáveis. Isolamento por produtor e migração dos coletores externos continuam pendentes. Veja [operação e preparação de homologação](docs/operacao-local.md).

**Objetivo da IA:** a Alytha deve coordenar busca, processamento e análise conversacional, cruzando histórico, imagens Sentinel-1/2, evolução direcional, janela de plantio, meteorologia e referências agronômicas. Veja [objetivo, estado atual e sequência de implementação](docs/objetivo-ia-analitica.md).

**Inventário local na conversa:** pergunte “Quais imagens temos salvas?” para conferir históricos, prévias e rasters disponíveis sem consultar o Sentinel ou um provedor de IA. Veja [uso, contrato de evidências e limitações](docs/inventario-local.md).

**Banco e migrations:** `python -m app.migrate status` mostra as versões e `python -m app.migrate up` aplica as pendentes. O servidor inicializa o esquema antes do atendimento e usa SQLite em WAL. Veja [correção de bloqueios, comandos e backup](docs/banco-migrations.md).

**Aprendizado contínuo:** o histórico de cada área pode alimentar uma rotina persistente de releituras a cada cinco dias, revisão da Alytha, padrões de vegetação e validação com parceiros. Hipóteses automáticas ficam separadas dos rótulos humanos; novas versões supervisionadas são avaliadas como candidatas. Veja [funcionamento, ativação e limites](docs/aprendizado-continuo.md).

**Base integrada:** todos os municípios da rodada, suas leituras, recortes e pendências são consolidados antes das análises da IA. A fila visual por recorte é controlada na página da coleta. Veja [arquivos, acompanhamento e revisão regional](docs/base-integrada.md).

**Gemini nas imagens:** o fluxo visual envia PNGs reais de períodos diferentes, com cor natural quando disponível e mapas NDVI, junto das medições do recorte. Observações, hipóteses e verificações de campo ficam separadas; ausência de imagens ou erro do provedor permanece pendente. Veja [análise visual, rastreabilidade e validação real](docs/analise-visual-gemini.md).

Para demonstrações guiadas aos produtores parceiros, veja o [roteiro de validação do MVP](docs/mvp-parceiros.md). Execute `python -m app.demo_check` para conferir dependências, configuração e resultados locais antes da reunião. O painel de validação permite revisar e exportar registros de campo por área.

**Coleta regional:** digite uma cidade ou estado na busca do mapa para iniciar a coleta sistemática, com fila, cache e andamento em **Coleta automática da região**. O histórico de áreas agora aceita outros municípios, além de Sorriso. Veja [fontes, cobertura e limites](docs/coleta-regional.md).

**Base Centro-Oeste:** a rodada de desenvolvimento cobre MT, MS, GO e DF. Acompanhe o relatório com `python -m app.regional_batch status`; veja [execução, arquivos e retomada](docs/base-centro-oeste.md).

**Direção da vegetação:** a comparação espacial agora procura sequências de ganho/perda e mostra setas quando há organização espacial suficiente. Veja [método experimental e interpretação](docs/direcao-vegetacao.md).

**Índice de evolução:** o acompanhamento combina fatores em duas pontuações de 0–100, para expansão e redução vegetal, com pesos e dados ausentes visíveis. Veja [método experimental do índice](docs/indice-evolucao.md).

Aplicação local para carregar um talhão GeoJSON, consultar cenas Sentinel-2 e analisar vigor por NDVI. Requer **Python 3.10+**. O servidor e a consulta de catálogo usam apenas a biblioteca padrão; mapas e serviços externos precisam de internet.

## Rodar

```powershell
python run.py
```

Abra **http://127.0.0.1:8765**. Encerre com `Ctrl+C`. Para outra porta: `python run.py --port 8766`.

O mapa inicia sem área de análise. Pesquise uma cidade ou estado para ver sugestões do IBGE enquanto digita, ou selecione **estado → município** no painel. Aproxime o mapa, clique na caneta e marque pelo menos três vértices. **Buscar imagens** e **Consultar vigor** concluem automaticamente um desenho válido; também é possível usar **Concluir desenho** ou um clique duplo. O limite municipal serve para navegação; a análise usa o polígono desenhado.

As linhas laranjas são os limites das cenas retornadas pelo catálogo, não limites de lavouras. Ficam ocultas por padrão e podem ser ligadas em **Limites das cenas** no mapa.

Se o catálogo devolver HTML de bloqueio em vez de dados STAC, a busca tenta a alternativa GET. Contornos complexos usam uma envolvente compacta e filtram as cenas pela geometria original com Shapely; a área solicitada permanece a mesma. Consultas bem-sucedidas ficam salvas mesmo sem cadastro da área e podem ser reutilizadas durante indisponibilidade, sempre com o mesmo polígono, datas e limite de nuvens. A tela identifica o uso da base local. Listar cenas não baixa nem processa as imagens.

O seletor **Período** oferece 1, 3, 6, 9 e 12 meses contados para trás a partir da data final, além de **Personalizado** com datas livres entre 01/01/2018 e hoje. Os intervalos podem atravessar anos e abranger todo o histórico disponível. Séries NDVI longas são consultadas por ano e reunidas no mesmo gráfico; cada trecho obtido fica salvo mesmo se a fonte recusar o seguinte. No painel de histórico, **Todo o histórico** mostra vários anos juntos. Os atalhos definem a extensão do período, mantendo as leituras de até cinco dias; não transformam os dados em médias mensais.

Você também pode arrastar e soltar um GeoJSON sobre o mapa ou usar o botão de upload. Envie um arquivo `.geojson` ou `.json` de até 2 MB, com um único Polygon ou MultiPolygon. O contorno aparece no mapa e fica pronto para consultar imagens e vigor; arquivos inválidos preservam a área anterior. Use `data/sample-field.geojson` como exemplo fictício para testar. Áreas ainda não salvas ficam na sessão; **Limpar área** remove o desenho e os resultados da tela, sem apagar cadastros no banco. Um desenho em andamento pode ser cancelado sem apagar a área anterior.

## Salvar áreas e consultas

Depois de desenhar ou carregar um polígono, preencha **nome, município/UF, cultura declarada e safra declarada** no painel e clique em **Salvar área**. Use "Não confirmada" quando a cultura não for conhecida. Os dados ficam no SQLite local `data/monitoring.sqlite3`, ignorado pelo Git. Não é preciso instalar um banco externo.

As consultas de cenas e séries NDVI feitas **depois de salvar** são registradas automaticamente com seus parâmetros, resultados e data UTC. Selecione uma área em **Áreas salvas** para reabrir o polígono e, em **Consultas anteriores**, escolha um resultado. Reabrir um resultado salvo não consome uma nova consulta Copernicus. O PNG NDVI continua sendo calculado sob demanda e não é armazenado nesta entrega.

**Consultar vigor** também salva as séries bem-sucedidas de desenhos ainda não cadastrados, com sua geometria e período, para reuso local. Sem credenciais ou quando o Copernicus recusa a consulta, a aplicação procura séries da mesma área. Com as dependências geoespaciais instaladas, pode oferecer até 20 recortes salvos inteiramente dentro do desenho, identificados como amostras e destacados em roxo; suas médias não são combinadas nem extrapoladas para toda a área. Datas sem observações permanecem sem leitura. Se houver somente datas antigas, **Consultar datas salvas** ajusta explicitamente o período. Após HTTP 401/403/429, novas tentativas externas por esse botão ficam suspensas por 15 minutos; a base local continua disponível.

Após duas séries NDVI, **Comparar séries NDVI** mostra as médias dos intervalos e sua diferença. Essa comparação é descritiva: períodos e cobertura podem diferir e a média não representa produtividade. **Exportar histórico** baixa o cadastro e seus resultados em JSON. A cultura e a safra são declarações do usuário, não classificações automáticas.

O cadastro salvo mantém a geometria original; um novo desenho exige um novo cadastro. Consultas feitas antes do cadastro não entram retroativamente no histórico. O armazenamento é local e compartilhado por quem acessa esse servidor; esta entrega ainda não tem login ou separação por usuário. Para preservar o banco, use backup consistente do SQLite ou, com todos os processos parados, preserve o arquivo principal e seus auxiliares presentes. Veja [orientação de backup em WAL](docs/banco-migrations.md).

As listas e malhas simplificadas vêm das APIs oficiais de [Localidades](https://servicodados.ibge.gov.br/api/docs/localidades) e [Malhas do IBGE](https://servicodados.ibge.gov.br/api/docs/malhas?versao=3), com cache persistente no SQLite. A seleção territorial não identifica automaticamente lavouras.

Para consultas IBGE com a validação nativa de certificados do Windows, instale `python -m pip install -r requirements-network.txt`. O cliente usa `truststore` quando disponível, mantendo a verificação de certificado e hostname. Listas de estados, municípios e respostas de malhas também ficam no SQLite por sete dias e podem ser reutilizadas durante indisponibilidade da fonte; não é preciso consultar novamente todos os municípios em cada reinício.

## Estrutura

```text
app/                          Servidor, catálogo e integração opcional Earth Engine
web/                          Interface e arquivos locais do mapa
data/                         GeoJSON de exemplo e futuros resultados locais
docs/                         Levantamento, direção do produto e pesquisas
tests/                        Testes automatizados
.env.example                  Modelo de configuração
requirements-earth-engine.txt Dependência opcional do Earth Engine
run.py                        Entrada da aplicação
```

## Configuração

Copie o modelo para a raiz:

```powershell
Copy-Item .env.example .env
```

| Variável | Uso | Necessária para iniciar? |
| --- | --- | --- |
| `GOOGLE_MAPS_API_KEY` | Google Maps e busca por endereço | Não |
| `GOOGLE_MAPS_MAP_ID` | Identificador opcional do mapa Google | Não |
| `CDSE_CLIENT_ID` e `CDSE_CLIENT_SECRET` | Novas séries e camadas NDVI via Copernicus | Apenas para novas consultas externas |
| `GEE_PROJECT_ID` | Script opcional de autenticação Earth Engine | Não |
| `OPENAI_API_KEY` | Assistente de perguntas baseado nas evidências do servidor | Apenas para o assistente |
| `OPENAI_MODEL` | Modelo do assistente; padrão `gpt-4.1-mini` | Não |

Sem chave Google, o mapa usa Leaflet local e mosaicos OpenStreetMap. A busca aceita **latitude, longitude**, como `-12.5, -55.7`. Com Google Maps, habilite as APIs utilizadas e autorize a URL local nas restrições da chave.

O catálogo público não exige credenciais. Para calcular NDVI, preencha as credenciais OAuth Copernicus no `.env`; o segredo permanece no servidor. Variáveis de ambiente têm prioridade sobre o arquivo. O GeoJSON permanece na sessão do navegador; consultas enviam a geometria ao Copernicus.

## Outros comandos

```powershell
# Consultar o catálogo pelo terminal
python -m app.catalog_search --from 2026-10-01 --to 2026-10-07

# Testar o servidor e a configuração sem serviços externos
python -m unittest discover -s tests -v

# Integração opcional: instalar e autenticar Earth Engine
python -m pip install -r requirements-earth-engine.txt
python -m app.setup_earth_engine
```

O catálogo aceita `--geojson caminho/talhao.geojson`, `--max-cloud 30` e `--limit 100`. O Earth Engine ainda não participa da tela; veja [configuração](docs/earth-engine-setup.md).

## Estado do projeto

Mapa, upload, consulta pública, série e camada NDVI foram testados com um polígono fictício e credenciais locais. Seleção de localidades e desenho também permitem consultar sem upload. O Modo I.A usa OpenAI quando a chave e o saldo da conta permitem a consulta. As respostas usam evidências recuperadas no servidor; ainda falta validação agronômica com áreas conhecidas.

O NDVI representa vigor vegetal; a aplicação ainda não estima produção nem confirma propriedade ou estoque. A série aceita até um ano por consulta e restringe áreas grandes no processamento de 10 m.

[Levantamento do que temos e do que falta](docs/levantamento.md) · [Direção do produto](docs/product-direction.md) · [Plano de IA](docs/ai-area-discovery.md)
# Fontes agrícolas

**Soja histórica com possível lavoura inativa** é uma triagem experimental implementada no painel de culturas. Ao marcar, soja é selecionada automaticamente e os demais filtros ficam temporariamente desabilitados. Aproxime até o detalhe nativo de 30 m; a triagem rejeita as manchas de visão geral reduzida. O backend cruza até dez manchas menores de soja do ano selecionado com NDVI Sentinel-2 dos últimos 60 dias, em segundo plano, com andamento e resultados persistidos no SQLite. Não avalia automaticamente todos os talhões do município. `POST /api/inactive-soy` inicia/reutiliza uma consulta diária e `GET /api/inactive-soy/{id}` retorna andamento e evidências.

A regra exige três intervalos distintos com pelo menos 50 pixels válidos, cobertura válida de pelo menos 50%, dez dias entre primeiro/último intervalo, última observação em até 15 dias e NDVI médio ≤ 0,25 em todos os três. Pixels válidos são `sampleCount - noDataCount`; quando disponível usa `geometryPixelCount` para a cobertura, caso contrário usa o retângulo amostrado como denominador conservador. Nuvens, dados insuficientes, área excessiva ou falha da fonte resultam em **inconclusivo**, sem classificação de inatividade. A camada coral indica possível ausência de lavoura ativa; ao selecionar, mostra datas, NDVI e gráfico das evidências. Resultados por área são reutilizados no período diário.

O limiar é uma regra de triagem ainda sem validação agronômica. MapBiomas informa um ano de uso do solo, não comprova a safra passada; solo exposto, pós-colheita, preparo e pousio podem ter o mesmo sinal. A camada não confirma talhão vazio, cultura atual, disponibilidade para plantio ou limites cadastrais. Validado tecnicamente com testes e uma consulta real em Sorriso (referência 2025, observações até 08/10/2026); validação de campo permanece pendente. Referência da contagem de pixels: [documentação Statistical API](https://docs.sentinel-hub.com/api/latest/api/statistical/).

Os checkboxes de cultura ficam imediatamente abaixo de estado/município. A paleta do produto é compartilhada entre filtros, manchas no mapa e indicadores municipais: soja dourado, cana verde, arroz azul, algodão roxo, café marrom, citrus laranja, dendê rosa, outras temporárias turquesa e outras perenes cinza. Os nomes acompanham as cores; esta paleta visual não altera os códigos oficiais das classes. Informações complementares e ferramentas ficam em seções recolhidas.

O menu mostra o panorama agrícola municipal em hectares, filtros de culturas por checkbox, produção regional e vigor da vegetação. Todos os checkboxes começam desmarcados. Cada marcação ou desmarcação dispara imediatamente a atualização do mapa, inclusive durante uma consulta anterior; respostas antigas não substituem o filtro mais recente. Marque culturas para combinar camadas ou desmarque todas para limpar os resultados. Alterar cultura ou ano atualiza a camada automaticamente no recorte visível; a seleção histórica é removida quando deixa de corresponder ao filtro. Milho e sorgo continuam disponíveis na CONAB, sem classe específica no mapa. Cadastro/histórico e importação ficam em seções recolhidas. Validado no navegador com Google Maps e Leaflet.

A seleção de localidade atualiza a URL: `/?municipio=5107925` abre Sorriso/MT e recupera sua base municipal no servidor; `/?estado=51` abre Mato Grosso. Os links podem ser copiados e reabertos; recarregar e usar voltar/avançar restaura a seleção. O endereço do servidor local só funciona no computador que o executa.

Ao selecionar um município, o navegador solicita `/api/municipalities/{codigo_ibge}` e o **servidor** prepara um dossiê persistente em `data/monitoring.sqlite3`. Não exige baixar ou enviar arquivos. Dois trabalhadores processam cidades em segundo plano; a tela consulta o andamento. A base inclui nome/UF, GeoJSON da malha simplificada IBGE, contexto CONAB estadual de soja/milho/sorgo e resumo de cobertura **do município inteiro**, MapBiomas 2025, pixels nativos de 30 m. O raster é lido em blocos de 512 pixels e acumulado por classe, mantendo memória limitada; a primeira preparação pode levar minutos. Limite do piloto: 350 milhões de pixels por município. Embrapa aparece pendente e não é consultada automaticamente.

O dossiê pronto é reutilizado por 24 horas; uma nova solicitação depois desse período agenda atualização. Bases parciais/com erro e trabalhos interrompidos são retomados na próxima solicitação. Uma fonte indisponível não elimina as demais. Cada fonte mantém escala, ano/data e origem; CONAB permanece estadual. O assistente pode consultar esse contexto estruturado. A base municipal não cria talhões cadastrais nem executa NDVI Sentinel-2 para toda a cidade. A busca interativa de manchas MapBiomas continua por recortes visíveis menores e, com município selecionado, intersecta os polígonos com sua malha IBGE.

Instale `pip install -r requirements-geospatial.txt` para habilitar os recortes MapBiomas. Em **Culturas no mapa**, escolha ano e marque culturas: a consulta é automática, inclusive ao aproximar ou mover o mapa. Não há botão de atualizar. Clique em uma mancha colorida ou selecione uma área na lista para analisar e salvar sua origem. Coleção 11, 1985–2025, pixels nativos de 30 m, CC BY 4.0. O servidor lê o recorte remoto e processa até um milhão de pixels por classe. Recortes maiores recebem uma visão geral com resolução reduzida e amostragem categórica pelo vizinho mais próximo; a tela informa a resolução aproximada. Essa visão pode omitir manchas pequenas e não serve como estimativa precisa de hectares ou limites de talhão; o resumo municipal permanece calculado nos pixels nativos. Aproxime o mapa para o detalhe de 30 m. Limites: 200 manchas por classe e mínimo de 5 ha; a tela pode cortar uma mancha. A classificação histórica não comprova limites de talhão, titularidade ou cultura atual. Milho e sorgo não são classes específicas deste produto.

**CONAB** consulta a série oficial de grãos por UF para soja, milho e sorgo. A tabela mostra os dez últimos registros, com área em hectares, produção em toneladas e rendimento em t/ha; o importador converte as unidades do arquivo de origem. Os dados e a data de importação ficam no SQLite, com renovação após 24 horas. São estatísticas estaduais, sem estimativa para o polígono.

**Embrapa SATVeg** tem adaptador preparado, mas a consulta real aguarda acesso AgroAPI. Após obter o token, configure `EMBRAPA_ACCESS_TOKEN` no `.env` e reinicie o servidor. O botão usa o polígono selecionado e o período da linha do tempo; nesta versão aceita Polygon sem anéis internos. A série MODIS tem resolução de 250 m e intervalos de 16 dias, e não deve ser comparada diretamente com Sentinel-2. A integração externa ainda precisa ser validada com token; o histórico SATVeg não é gravado nas consultas Sentinel-2.

Fontes oficiais: [MapBiomas](https://brasil.mapbiomas.org/downloads/mapas-para-download-geotiff/), [CONAB](https://portaldeinformacoes.conab.gov.br/downloads/arquivos/SerieHistoricaGraos.txt), [AgroAPI SATVeg](https://www.agroapi.cnptia.embrapa.br/store/apis/info?name=SATVeg&provider=agroapi&version=v2).

## Histórico, machine learning e assistente

Na barra inferior, **Atividade da soja** abre um gráfico à direita e usa por padrão o **município selecionado**, sem exigir desenho nem depender do zoom. A leitura integral do MapBiomas 2025 identifica a soja dentro da malha IBGE; recortes de pelo menos 5 ha são consultados no Sentinel-2 nos últimos 60 dias. Manchas grandes são divididas em recortes de processamento de até 10 km de lado, sem representar talhões; a média pode misturar condições diferentes. O gráfico soma hectares por situação: pouca vegetação persistente, sinal baixo que não persistiu e leitura insuficiente. O andamento distingue áreas ainda sem avaliação; falhas permanecem inconclusivas. Não usa o limite de 200 manchas do recorte visível nem extrapola uma amostra para a cidade. O piloto aceita janelas municipais de até 50 milhões de pixels nativos; acima disso retorna um erro, sem apresentar amostra como total. Consultas podem demorar, têm cache e retomam após interrupção. O card acompanha automaticamente a cidade selecionada ou identificada na busca do mapa, sem seletor de recorte nem botão de iniciar a consulta. Pós-colheita, preparo e pousio podem apresentar o mesmo sinal: não confirma terra parada ou área disponível para plantio. Os contornos continuam sendo manchas MapBiomas, sem delimitação automática de talhões.

```powershell
python -m pip install -r requirements-geospatial.txt -r requirements-ml.txt
python run.py
```

Abra `http://127.0.0.1:8765/?municipio=5107925`, expanda **Histórico e manejo · piloto Sorriso** e clique em **Iniciar piloto Sorriso**. O servidor encontra uma mancha de soja histórica MapBiomas 2025 e reconstrói seu NDVI Sentinel-2 desde 2018, por ano, com cache persistente. Escolha um ano para visualizar o gráfico. Para outra área, desenhe dentro de Sorriso e use **Carregar histórico da área**. A primeira consulta depende das fontes externas e pode levar minutos; anos indisponíveis não eliminam os demais.

A análise combina regras temporais experimentais com **KMeans**, que aprende grupos de vegetação sem rótulos de manejo. Os grupos são exploratórios e retrospectivos; não representam etapas agronômicas confirmadas. **Random Forest** está implementado para aprender etapas usando registros conhecidos de campo. O treinamento exige 30 registros utilizáveis, três áreas distintas, duas etapas e pelo menos cinco registros por etapa. A avaliação separa treino e teste por geometria; áreas distintas sobrepostas exigem revisão. A acurácia interna não substitui validação externa e as probabilidades não são calibradas. Nenhum modelo supervisionado é criado com dados fictícios na aplicação.

No **Modo I.A**, pergunte sobre as evidências ou solicite filtros, por exemplo: “Mostre soja no mapa” e “Resuma o histórico desta área”. O servidor chama a [Responses API com saída estruturada](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses), envia o contexto disponível e valida referências e ações permitidas. A chave permanece no servidor. Pergunta, evidências municipais e observações temporais são enviadas à OpenAI com `store=false`; anotações livres de campo e credenciais não fazem parte do contexto. Falta de chave, limite ou saldo aparece na tela e não impede o uso do histórico e do ML local.

Históricos, rótulos e métricas ficam em `data/monitoring.sqlite3`; o modelo treinado fica em `data/models/manejo.joblib`. Ambos precisam de backup e não entram no Git. Para detalhes de validação e pendências: [piloto de IA e ML](docs/ia-ml-piloto.md).

Para Sorriso, `python -m app.ml_dataset` exporta as leituras já coletadas e as características temporais para CSV, com geometria, ficha de campo, manifesto e ZIP em `data/outputs/ml`. Exportações durante a coleta são identificadas como parciais. Hipóteses automáticas ficam separadas dos rótulos de campo. Veja [ambiente e base de Sorriso](docs/sorriso-ml.md).

## Visão espacial: cv2 + ML

O painel **Manchas de pouca vegetação · visão espacial** compara os mesmos pixels em três janelas de imagens Copernicus, desenha manchas persistentes de pelo menos 1 ha no mapa e exporta características espaciais para exploração com ML. Analisa o recorte selecionado ou a referência de Sorriso, sem representar a cidade inteira. Instale `requirements-cv.txt`. Método, uso e limites em [docs/cv2-ml.md](docs/cv2-ml.md); meta registrada em [docs/meta-cv2-ml.md](docs/meta-cv2-ml.md).

## Condições para plantio de soja

No painel de camadas, **Condições para plantio · soja** avalia clima recente, previsão de sete dias, temperatura e umidade estimadas do solo, além do NDVI já salvo do mesmo recorte. A consulta meteorológica usa Open-Meteo e não inicia coleta de imagens. Verificações de solo, drenagem, fertilidade, calendário e ZARC são declarações do usuário. Dados ausentes ou antigos impedem um resultado favorável; a triagem não é laudo de aptidão. Fontes, critérios, limites e testes em [docs/condicoes-plantio.md](docs/condicoes-plantio.md).

O painel **Ciclo da soja · estudo e planejamento** apresenta 22 temas, do planejamento à pós-colheita, com referências, possibilidades de acompanhamento e dados de campo necessários. É uma trilha de pesquisa, não um classificador automático da etapa atual. A [matriz inicial](docs/ciclo-soja-estudo.md) e a [rodada de 16/10/2026](docs/rodada-2026-10-16-soja.md) detalham o plano de integrar Sentinel-1 e janela oficial e desenvolver validação por etapa. O quadro foi ampliado para IA-29 a IA-31, preservando entregas anteriores.
