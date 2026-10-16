# Direção do produto: monitoramento agrícola Alytha

## Objetivo

A direção definida em 15/10/2026 é desenvolver a Alytha como IA conversacional de assistência e análise dos dados coletados e refinados pelo sistema, coordenando ferramentas e cruzando histórico, imagens, evolução espacial, janela de plantio, meteorologia e conhecimento agronômico. O [objetivo da IA analítica](objetivo-ia-analitica.md) registra os requisitos, as capacidades existentes e as integrações a construir.

Construir uma ferramenta de análise por talhão que una delimitação espacial, imagens multitemporais, indicadores de vegetação e evidências revisáveis. A referência de produto é a experiência de mapear e acompanhar lavouras do SojaMaps; a aplicação Alytha também precisa ligar cada observação ao produtor, à safra e ao lote comercial correspondente.

## Etapas

1. **Talhão e safra:** carregar o polígono GeoJSON autorizado, identificar cultura e safra declaradas e guardar a origem do dado.
2. **Observações de satélite:** procurar cenas por área e período, mostrando data de aquisição, resolução, nuvens e fonte.
3. **Vigor:** calcular NDVI por talhão e por intervalos temporais, mascarando nuvens, sombras, água e pixels sem dado. Guardar contagem de pixels válidos e parâmetros da análise.
4. **Leitura operacional:** permitir que analista ou agrônomo registre interpretação, divergência, vistoria e evidência complementar.
5. **Integração de risco:** avaliar classificação de cultura, previsão de etapa/colheita e comparação com estimativas declaradas somente após validação em campo.
6. **Conexão ao lote:** levar as observações selecionadas para o processo de validação como evidência datada, sem aprovar lote automaticamente.

## Fontes planejadas

- **Sentinel-2 L2A:** fonte inicial. As bandas vermelha e infravermelha têm pixel nativo de 10 m; a missão tem revisita nominal de cinco dias no equador com dois satélites, sujeita a nuvens e disponibilidade real da cena.
- **Landsat 8/9:** fonte complementar de histórico, com bandas multiespectrais de 30 m e arquivo de longo prazo.
- **PlanetScope:** opção comercial de maior frequência e resolução, sujeita a proposta, cobertura, créditos de processamento, licença e aprovação de uso em produto Alytha.
- **Serasa Crop Monitor:** adaptador futuro após contrato, documentação de API, sandbox e autorização comercial.

## Estado desta PoC

> Esta seção registra uma etapa anterior. Em 13/10/2026 o produto já tem persistência local, fontes agrícolas, histórico, acompanhamento integrado e assistente. A preparação atual está em [MVP para parceiros](mvp-parceiros.md). As pendências agronômicas continuam relevantes.

A página permite carregar um polígono individual e consultar o catálogo Sentinel-2. Há código para desenhar a evolução NDVI em intervalos de cinco dias quando houver credenciais OAuth CDSE no arquivo `.env` na raiz. A integração NDVI ainda precisa de validação real com credenciais. O processamento usa o Statistical API do Sentinel Hub; não existe persistência de análises. Ao executar a consulta, o polígono e o período são enviados ao Copernicus. O gráfico representa a média de NDVI dos pixels válidos, não produtividade estimada.

Para habilitar a série, copie `.env.example` para `.env`, preencha `CDSE_CLIENT_ID` e `CDSE_CLIENT_SECRET` criados na conta Copernicus Data Space e reinicie o servidor local. Nunca coloque o segredo CDSE em variável `VITE_` nem no navegador. A autenticação OAuth e o fluxo Stats API seguem a documentação do Copernicus.

## Validação antes de comercializar

NDVI é indicador de vigor, não identificação certa de soja, estimativa de sacas ou prova de titularidade/estoque. Classificação de cultura e previsão de safra exigem histórico fenológico, dados rotulados, condições regionais e safras variadas, calibração por agrônomo e comparação com vistoria/notas/romaneios. Resultados inconclusivos precisam permanecer inconclusivos.

## Fontes técnicas

- [Copernicus: missão e revisita do Sentinel-2](https://documentation.dataspace.copernicus.eu/Data/SentinelMissions/Sentinel2.html)
- [Copernicus: Sentinel Hub Process API e NDVI](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Process.html)
- [Copernicus: OAuth e criação de credenciais](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Overview/Authentication.html)
- [Copernicus: Statistical API](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Statistical.html)
- [USGS: Landsat 8/9, resolução e revisita](https://www.usgs.gov/centers/eros/science/usgs-eros-archive-landsat-archives-landsat-8-9-operational-land-imager-and)
- [Planet: produto agrícola e preços comerciais](https://account.planet.com/pricing/agriculture/)
- [UNEMAT/GAAF: SojaMaps](https://pesquisa.unemat.br/gaaf/sojasat)
