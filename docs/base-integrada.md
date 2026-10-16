# Base integrada de todos os municípios

Integração de 14/10/2026: a rotina de aprendizado contínuo passa a incorporar toda a base regional existente. A ordem é **consolidar a base → revisar pela Alytha → validar com parceiros → melhorar os modelos**.

## O que entra

O inventário inclui todos os municípios da lista regional, inclusive os ainda não consultados, e cidades adicionais com dados no banco. Municípios processados, dados parciais, falhas e ausência de leituras ficam diferenciados. Uma cidade em coleta pode já possuir dados aproveitáveis, mesmo sem constar na contagem de municípios processados.

A consolidação lê um único estado do SQLite e não consulta satélite, IBGE, MapBiomas ou IA. Ela reúne:

- Fontes e contexto municipal disponíveis.
- Geometrias de todos os recortes de soja histórica mapeados.
- Observações recentes vinculadas à geometria e ao período exatos da consulta.
- Históricos de referência, preservando leituras de versões anteriores quando uma versão nova estiver parcial.
- Características e qualidade das janelas temporais, modelos exploratórios já existentes e características espaciais separadamente datadas.
- Registros humanos de campo correspondentes à geometria e à data.

Histórico anual e série recente são trilhas distintas: intervalos podem se sobrepor ou usar grades temporais diferentes. Eles não devem ser tratados como exemplos independentes da mesma área. Use `area_key` como grupo e controle sobreposição espacial e separação por safra na avaliação. Não há alvos de manejo quando faltam registros humanos, e nenhuma hipótese da IA é convertida automaticamente em alvo.

## Arquivos e acompanhamento

Cada consolidação cria uma versão em `data/outputs/regional-learning/{id}`. Versões anteriores ficam preservadas. O pacote contém `manifest.json`, `observacoes.csv`, `janelas_ml.csv`, `caracteristicas_espaciais.csv`, `registros_campo.json` e uma pasta `municipios` com os pacotes municipais e geometrias. O manifesto identifica a prontidão de cada cidade e a origem de cada pacote.

Todos os recortes com geometria mapeada entram no acompanhamento periódico, inclusive os sem leituras úteis. Isso agenda novas consultas; não significa que esses recortes já tenham dados de treinamento. As primeiras consultas dos planos importados são agendadas para cinco dias após sua inscrição. Pausas existentes são preservadas. Após a consolidação, a análise de imagens é organizada em uma fila visual por recorte, com prioridade para rasters já disponíveis.

Com o servidor ligado, novas observações, coberturas e registros de campo são verificados a cada cinco minutos para gerar uma base atualizada. Registros de inicialização gerados pela própria consolidação são excluídos dessa verificação, evitando um ciclo que recriaria a base indefinidamente. Geometrias e históricos de inicialização inalterados são reutilizados no banco.

Se o Copernicus informar falta de cota de processamento, as novas coletas compartilham uma espera de seis horas: o sistema não repete a mesma falha para cada recorte. Essa espera não impede consolidar os dados locais nem analisar a base pela IA.

## Depois, revisar pela Alytha

Abra [a página local da coleta](http://127.0.0.1:8765/coleta.html). A seção **Base integrada · aprendizado e Alytha** mostra o inventário, leituras, janelas e a fila. Os arquivos principais podem ser baixados nessa seção.

Depois de consolidar, **Iniciar análises da Alytha sobre esta base** ativa a fila visual por recorte. Ela recebe imagens reais e os dados da base; usa rasters locais ou adquire os períodos necessários quando a cota do satélite permite. Recortes sem imagens ficam pendentes. O resumo textual municipal é separado e não é apresentado como análise visual. Veja [Gemini nas imagens, qualidade e validação real](analise-visual-gemini.md).

Cada pacote municipal de contexto contém contagens completas, fontes, padrões disponíveis e uma seleção explícita de até doze recortes com características temporais. A fila visual analisa individualmente os recortes com imagens, enviando até seis PNGs por análise. Os CSVs preservam todas as observações exportadas; os indícios visuais ficam em `caracteristicas_visuais.csv`, separados dos alvos humanos.

Uma revisão concluída é reaproveitada em versões posteriores quando o pacote de evidências for idêntico. Erros do provedor criam uma espera compartilhada antes de outra tentativa. Assim, um HTTP 503 não dispara chamadas malsucedidas para todas as cidades. As respostas são interpretações auditáveis e permanecem separadas dos rótulos de campo.

## Comandos

```powershell
python -m app.regional_learning build
python -m app.regional_learning status

# Etapa posterior: ativar ou pausar a revisão dos pacotes pela IA
python -m app.regional_learning ai-on
python -m app.regional_learning ai-off
```

O servidor local precisa permanecer ligado para executar a agenda e a fila. Desligar o computador preserva o estado, mas suspende o trabalho até a próxima inicialização. As quantidades da base medem dados observados e registrados; não comprovam cultura atual, acurácia agronômica ou cobertura integral do território municipal.
