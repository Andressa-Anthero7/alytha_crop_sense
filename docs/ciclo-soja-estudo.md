# Ciclo da soja · matriz inicial de estudo

Pesquisa inicial em 16/10/2026. Esta matriz descreve o que estudar e implementar; não diagnostica a área selecionada. O catálogo pode ser consultado no painel de camadas, em **Ciclo da soja · estudo e planejamento**.

As fases fenológicas e os manejos transversais não são uma sequência de dias fixa. Cultivar, ambiente e manejo alteram o ciclo; manejos podem ocorrer em várias fases. O rótulo automático de aumento do verde permanece **sinal — possível plantio ou rebrota**.

## Temas e evidências

### Antes do plantio

| Tema | Pergunta | Proposta no sistema | Informação de campo / limite |
|---|---|---|---|
| Planejamento da safra e rotação | Qual cultura e safra estamos acompanhando neste recorte? | Relacionar geometria, safra, histórico e eventos; manter custos como registros do produtor. | Histórico de culturas, plano de rotação, orçamento e restrições de uso. Imagem de soja histórica não confirma soja atual nem área legalmente disponível. [Embrapa · Tecnologias de produção de soja · 2020](https://www.infoteca.cnptia.embrapa.br/handle/doc/1123928) |
| Janela sanitária e ZARC | A data pretendida atende ao calendário e ao ZARC desta área? | Planejado: conclusão dentro/fora/pendente, mantendo calendário sanitário, referência agronômica e janela declarada separados. | Município, safra, tipo de solo, grupo de cultivar, manejo e nível de risco. Sentinel-1 e NDVI não determinam a janela oficial. Dados atuais ainda são declarações do usuário na avaliação de plantio. [MAPA · Zoneamento Agrícola de Risco Climático](https://www.gov.br/agricultura/pt-br/assuntos/riscos-seguro/programa-nacional-de-zoneamento-agricola-de-risco-climatico/zoneamento-agricola) |
| Amostragem e análise do solo | Existe análise de solo representativa e atual? | Planejado: associar laudos, pontos de amostragem, datas e pendências ao talhão. | Laudo, textura, acidez, nutrientes e avaliação de compactação. NDVI e radar não substituem análise de fertilidade nem medem pH diretamente. [Embrapa · Tecnologias de produção de soja · 2020](https://www.infoteca.cnptia.embrapa.br/handle/doc/1123928) |
| Correção, conservação e cobertura do solo | As correções e a conservação foram verificadas? | Planejado: registrar operações e procurar mudanças espaciais a conferir em campo. | Recomendação técnica, operações realizadas, palhada, erosão e drenagem. Mudança no radar também pode ser rugosidade ou umidade; não comprova preparo. [Embrapa · Tecnologias de produção de soja · 2020](https://www.infoteca.cnptia.embrapa.br/handle/doc/1123928), [ESA · Umidade do solo por observação da Terra](https://knowledge-hub-gda.esa.int/eo_capability/soil-moisture/) |
| Cultivar e qualidade das sementes | A cultivar e o lote estão identificados? | Planejado: vincular grupo de cultivar e documentos do lote à safra e ao ZARC. | Cultivar, lote, germinação, vigor e destino da produção. Satélites não comprovam cultivar, vigor ou qualidade sanitária da semente. [Embrapa · Tecnologias de produção de soja · 2020](https://www.infoteca.cnptia.embrapa.br/handle/doc/1123928), [MAPA · Zoneamento Agrícola de Risco Climático](https://www.gov.br/agricultura/pt-br/assuntos/riscos-seguro/programa-nacional-de-zoneamento-agricola-de-risco-climatico/zoneamento-agricola) |
| Tratamento de sementes e inoculação | O tratamento e a inoculação foram registrados? | Planejado: registrar data, origem e operação; não inferir aplicação pelo sinal do satélite. | Registros do lote, produtos utilizados e avaliação de nodulação. Não indicar dose ou produto automaticamente; nodulação exige avaliação das raízes. [Embrapa · Tecnologias de produção de soja · 2020](https://www.infoteca.cnptia.embrapa.br/handle/doc/1123928) |
| Manejo da cobertura antes da semeadura | O que ocupa a área antes da semeadura? | Comparar cobertura e manchas; relacionar reduções a eventos declarados. | Espécies presentes, cobertura, operações e respectivas datas. Queda do NDVI não confirma dessecação, produto aplicado ou ausência de plantas daninhas. [Embrapa · Tecnologias de produção de soja · 2020](https://www.infoteca.cnptia.embrapa.br/handle/doc/1123928) |

### Implantação

| Tema | Pergunta | Proposta no sistema | Informação de campo / limite |
|---|---|---|---|
| Condição e execução da semeadura | Há condição para programar a semeadura? | Já disponível: triagem de clima e solo estimado. Planejado: integrar janela oficial e radar à conclusão. | Umidade na semente, temperatura, contato solo-semente, regulagem, população e data real. Estimativa meteorológica não comprova aptidão física local; radar ainda não está integrado. [Embrapa · Condições para instalação da lavoura](https://www.embrapa.br/en/web/agencia-de-informacao-tecnologica/cultivos/soja/pre-producao/instalacao-da-lavoura/aspectos-a-serem-considerados), [Copernicus · Sentinel-1 GRD · documentação](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S1GRD.html), [ESA · Umidade do solo por observação da Terra](https://knowledge-hub-gda.esa.int/eo_capability/soil-moisture/) |
| Estabelecimento e estande · VE/VC | O aumento do verde é uniforme ou há falhas? | Já disponível: sinal de possível plantio ou rebrota e manchas de ganho. Planejado: relacionar essas evidências ao estande registrado. | Contagem de plantas, falhas, espécie e data de semeadura. VE/VC são estádios técnicos para observação de campo. O sinal automático permanece 'possível plantio ou rebrota'; não confirma estádio. [Embrapa · Estádios fenológicos da soja](https://bioinfo.cnpso.embrapa.br/seca/index.php?Itemid=435&catid=84&id=74:estadios-fenologicos&option=com_content&view=article) |

### Desenvolvimento

| Tema | Pergunta | Proposta no sistema | Informação de campo / limite |
|---|---|---|---|
| Crescimento vegetativo · V1 a Vn | A cobertura evolui de forma homogênea? | Comparar NDVI, faixa sazonal, organização das manchas e clima. Planejado: validar características com estádios de campo. | Contagem de nós, altura, cobertura e observação da cultura. NDVI não conta nós; vigor alto não comprova ausência de problema. [Embrapa · Estádios fenológicos da soja](https://bioinfo.cnpso.embrapa.br/seca/index.php?Itemid=435&catid=84&id=74:estadios-fenologicos&option=com_content&view=article) |

### Reprodução

| Tema | Pergunta | Proposta no sistema | Informação de campo / limite |
|---|---|---|---|
| Florescimento · R1/R2 | A fase foi confirmada e há condição hídrica a acompanhar? | Planejado: associar confirmação de campo, clima e anomalias; emitir atenção com evidência datada. | Flores observadas, cultivar e data da observação. Sem inspeção ou modelo validado, o sistema não identifica flores pelo NDVI. [Embrapa · Estádios fenológicos da soja](https://bioinfo.cnpso.embrapa.br/seca/index.php?Itemid=435&catid=84&id=74:estadios-fenologicos&option=com_content&view=article) |
| Formação de vagens · R3/R4 | Há vagens confirmadas e mudança de condição da área? | Planejado: alinhar observações de vagens a clima, vigor e heterogeneidade espacial. | Inspeção de vagens e registro do estádio. Satélites não contam vagens nem atribuem a causa de abortamento. [Embrapa · Estádios fenológicos da soja](https://bioinfo.cnpso.embrapa.br/seca/index.php?Itemid=435&catid=84&id=74:estadios-fenologicos&option=com_content&view=article) |
| Enchimento de grãos · R5/R6 | Há alteração de vigor durante a fase confirmada? | Planejado: cruzar condição hídrica, anomalias de cobertura e registros da fase. | Avaliação de grãos, estádio e condição das plantas. Índice de vegetação não mede diretamente massa ou produtividade dos grãos. [Embrapa · Estádios fenológicos da soja](https://bioinfo.cnpso.embrapa.br/seca/index.php?Itemid=435&catid=84&id=74:estadios-fenologicos&option=com_content&view=article) |

### Final do ciclo

| Tema | Pergunta | Proposta no sistema | Informação de campo / limite |
|---|---|---|---|
| Maturação · R7/R8 | A queda de verde acompanha a fase observada? | Planejado: comparar perda de verde com estádio confirmado e eventos da área. | Cor de vagens, maturação e umidade dos grãos. Queda do NDVI isolada não distingue maturação, dessecação, doença ou colheita. [Embrapa · Estádios fenológicos da soja](https://bioinfo.cnpso.embrapa.br/seca/index.php?Itemid=435&catid=84&id=74:estadios-fenologicos&option=com_content&view=article) |
| Colheita e perdas | Que setores foram colhidos e quais perdas foram medidas? | Já há manchas e direção de redução vegetal quando detectáveis. Planejado: compará-las ao registro real da operação. | Data, umidade, áreas colhidas, regulagem e medição de perdas. Uma flecha de mudança não é trajeto da máquina nem medição de perdas. [Embrapa · Tecnologias de produção de soja · 2020](https://www.infoteca.cnptia.embrapa.br/handle/doc/1123928) |
| Secagem, armazenamento e qualidade | O lote foi acompanhado na unidade armazenadora? | Planejado: relacionar lote, origem e medições da pós-colheita. | Umidade, temperatura, secagem, danos e inspeções do lote. Sentinel-1 e Sentinel-2 não verificam qualidade interna de silos ou grãos. [Embrapa · Armazenamento do grão de soja com qualidade · 2023](https://www.infoteca.cnptia.embrapa.br/infoteca/bitstream/doc/1155426/1/Circ-Tec-196.pdf) |
| Entressafra, voluntárias e próxima rotação | O verde posterior é cobertura planejada, rebrota ou plantas voluntárias? | Comparar a sequência pós-colheita com eventos e imagens; manter hipóteses alternativas. | Espécies presentes, manejo da cobertura e plano da próxima safra. Verde novo não comprova soja voluntária nem descumprimento de vazio sanitário. [Embrapa · Tecnologias de produção de soja · 2020](https://www.infoteca.cnptia.embrapa.br/handle/doc/1123928), [MAPA · Zoneamento Agrícola de Risco Climático](https://www.gov.br/agricultura/pt-br/assuntos/riscos-seguro/programa-nacional-de-zoneamento-agricola-de-risco-climatico/zoneamento-agricola) |

### Manejo ao longo do ciclo

| Tema | Pergunta | Proposta no sistema | Informação de campo / limite |
|---|---|---|---|
| Água, clima e irrigação | Há indícios de restrição hídrica a verificar? | Já há chuva, previsão, solo modelado e chuva menos ET₀. Planejado: balanço parametrizado e apoio de radar. | Textura, retenção de água, raízes, chuva local e irrigação aplicada. Chuva menos ET₀ não é balanço hídrico do talhão. Radar precisa separar umidade de vegetação e rugosidade. [Embrapa · Condições para instalação da lavoura](https://www.embrapa.br/en/web/agencia-de-informacao-tecnologica/cultivos/soja/pre-producao/instalacao-da-lavoura/aspectos-a-serem-considerados), [ESA · Umidade do solo por observação da Terra](https://knowledge-hub-gda.esa.int/eo_capability/soil-moisture/) |
| Plantas daninhas | O aumento de verde pertence à cultura ou a outras plantas? | Planejado: priorizar inspeção em manchas divergentes e vincular espécies registradas. | Identificação de espécies, distribuição e observações de resistência. Mancha verde não identifica espécie nem autoriza tratamento. [Embrapa · Tecnologias de produção de soja · 2020](https://www.infoteca.cnptia.embrapa.br/handle/doc/1123928) |
| Manejo integrado de pragas | Há amostragens que sustentem a decisão de manejo? | Planejado: registrar amostras e destacar anomalias para vistoria. | Praga identificada, contagem, dano, inimigos naturais e estádio. NDVI baixo não identifica inseto nem determina aplicação preventiva. [Embrapa · Tecnologias de produção de soja · 2020](https://www.infoteca.cnptia.embrapa.br/handle/doc/1123928) |
| Doenças e nematoides | A causa de uma mancha foi investigada? | Planejado: acompanhar recorrência espacial e clima favorável a investigação, sem diagnóstico automático. | Sintomas, inspeção, laudos e histórico sanitário. Anomalia espectral não distingue doença, nematoide, deficiência, seca ou compactação. [Embrapa · Tecnologias de produção de soja · 2020](https://www.infoteca.cnptia.embrapa.br/handle/doc/1123928) |
| Operações, aplicações e rastreabilidade | O evento observado coincide com uma operação registrada? | Planejado: histórico auditável de operações, dados meteorológicos e resultados posteriores. | Operador, data, equipamento, condições e orientação técnica. Sem receituário automático, indicação de dose ou inferência de produto por imagem; regras vigentes devem ser conferidas. [Embrapa · Tecnologias de produção de soja · 2020](https://www.infoteca.cnptia.embrapa.br/handle/doc/1123928) |

## Próximas entregas

- **Janela oficial e ZARC na conclusão** — Planejado · IA-13 e IA-29. Identificar município e safra; cruzar calendário sanitário e ZARC com solo, cultivar, manejo e nível de risco. Se faltar condição aplicável, manter pendência.
- **Sentinel-1 para condição da superfície** — Pesquisa de integração · IA-17 e IA-18. Validar séries radar compatíveis, alinhadas ao Sentinel-2 e à chuva, antes de interpretar mudança de umidade. Sem aquisição automática nesta rodada.
- **Acompanhamento de todo o ciclo** — Catálogo inicial disponível · IA-30 e IA-31. Definir dados, regras e casos de validação por etapa. O catálogo não significa que a etapa já é reconhecida pelo sistema.

Pesquisa, protocolo e critérios de aceite: [rodada-2026-10-16-soja.md](rodada-2026-10-16-soja.md). Nenhum reconhecimento de etapa, regra agronômica ou modelo é considerado validado apenas por constar nesta matriz.
