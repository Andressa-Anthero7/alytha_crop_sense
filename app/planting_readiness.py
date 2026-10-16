"""Explainable soybean planting screening; weather models are not field sensors."""
import json
import math
from datetime import date, datetime, timedelta, timezone
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import inactive_soy, local_ndvi, research, storage

API = 'https://api.open-meteo.com/v1/forecast'
DOCS = 'https://open-meteo.com/en/docs'
AGRONOMY = 'https://www.embrapa.br/en/web/agencia-de-informacao-tecnologica/cultivos/soja/pre-producao/instalacao-da-lavoura/aspectos-a-serem-considerados'
DAILY = {'precipitation_sum': 'mm', 'temperature_2m_min': '°C',
         'temperature_2m_max': '°C', 'et0_fao_evapotranspiration': 'mm'}
HOURLY = {'soil_temperature_6cm': '°C', 'soil_moisture_3_to_9cm': 'm³/m³'}
CHOICES = {
    'soil_condition': {'unknown', 'adequate', 'dry', 'waterlogged'},
    'drainage': {'unknown', 'adequate', 'problem'},
    'fertility': {'unknown', 'verified', 'needs_correction'},
    'calendar': {'unknown', 'verified', 'outside'},
    'zarc': {'unknown', 'verified', 'outside'},
    'water_management': {'rainfed', 'irrigated'},
}


def field_inputs(data):
    if not isinstance(data, dict):
        raise ValueError('As verificações de campo precisam ser um objeto.')
    result = {}
    for key, choices in CHOICES.items():
        value = data.get(key, 'rainfed' if key == 'water_management' else 'unknown')
        if not isinstance(value, str) or value not in choices:
            raise ValueError('Opção inválida para a verificação de campo: ' + key)
        result[key] = value
    return result


def point_for(geometry):
    from shapely.geometry import shape
    area = shape(geometry)
    if area.is_empty or not area.is_valid:
        raise ValueError('Selecione um polígono válido para avaliar o plantio.')
    west, south, east, north = area.bounds
    if not all(math.isfinite(v) for v in area.bounds) or not (-180 <= west <= east <= 180 and -85 <= south <= north <= 85):
        raise ValueError('Coordenadas fora dos limites meteorológicos.')
    if east-west > .5 or north-south > .5:
        raise ValueError('Selecione um recorte menor que 0,5 grau por lado; uma única célula meteorológica não representa toda essa área.')
    point = area.representative_point()
    return {'latitude': round(point.y, 5), 'longitude': round(point.x, 5)}


def numeric(value, low, high):
    return value if type(value) in (int, float) and math.isfinite(value) and low <= value <= high else None


def normalize(payload, today):
    """Validate units and align by exact dates; missing measurements stay missing."""
    if not isinstance(payload, dict) or payload.get('timezone') != 'America/Sao_Paulo':
        raise ValueError('A fonte não confirmou o fuso horário da consulta.')
    result = {'days': [], 'soil_hours': []}
    for group, variables in [('daily', DAILY), ('hourly', HOURLY)]:
        units, raw = payload.get(group+'_units', {}), payload.get(group, {})
        if not isinstance(units, dict) or not isinstance(raw, dict):
            raise ValueError('Resposta meteorológica inválida.')
        if any(units.get(key) != unit for key, unit in variables.items()):
            raise ValueError('Unidades meteorológicas inesperadas; avaliação não calculada.')
        times = raw.get('time')
        if not isinstance(times, list) or len(times) > 1000 or len(set(times)) != len(times):
            raise ValueError('Datas meteorológicas inválidas ou repetidas.')
        if any(not isinstance(raw.get(key), list) or len(raw[key]) != len(times) for key in variables):
            raise ValueError('Séries meteorológicas desalinhadas.')
        for index, stamp in enumerate(times):
            try:
                when = date.fromisoformat(stamp) if group == 'daily' else datetime.strptime(stamp, '%Y-%m-%dT%H:%M').date()
            except (ValueError, TypeError):
                raise ValueError('Data meteorológica inválida.') from None
            if not today-timedelta(days=14) <= when <= today+timedelta(days=7):
                continue
            row = {'date': when.isoformat(), 'time': stamp}
            for key in variables:
                bounds = (0, 1) if key.startswith('soil_moisture') else (0, 3000) if key == 'precipitation_sum' else (0, 100) if key.startswith('et0') else (-80, 70)
                row[key] = numeric(raw[key][index], *bounds)
            if group == 'daily':
                if row['temperature_2m_min'] is not None and row['temperature_2m_max'] is not None and row['temperature_2m_min'] > row['temperature_2m_max']:
                    row['temperature_2m_min'] = row['temperature_2m_max'] = None
                result['days'].append(row)
            else:
                result['soil_hours'].append(row)
    return result


def fetch_weather(geometry, today, allow_network=True):
    point = point_for(geometry)
    params = {**point, 'daily': ','.join(DAILY), 'hourly': ','.join(HOURLY),
              'start_date': (today-timedelta(days=14)).isoformat(),
              'end_date': (today+timedelta(days=7)).isoformat(),
              'timezone': 'America/Sao_Paulo'}
    key = 'planting-weather:v1:' + research.fingerprint(params)
    cached = storage.source_snapshot(key)
    age = None
    if cached:
        age = datetime.now(timezone.utc)-datetime.fromisoformat(cached['fetched_at'])
        if age < timedelta(hours=3):
            return {**cached['result'], 'cache': {'hit': True, 'stale': False}}
    if not allow_network:
        return {**cached['result'], 'cache': {'hit': True, 'stale': True}} if cached else None
    url = API + '?' + urlencode(params)
    try:
        with urlopen(Request(url, headers={'Accept':'application/json', 'User-Agent':'AlythaCropSense/1.0'}), timeout=25) as response:
            binary = response.read(2_000_001)
        if len(binary) > 2_000_000:
            raise ValueError('Resposta meteorológica acima do limite.')
        payload = json.loads(binary)
        values = normalize(payload, today)
    except (OSError, ValueError, URLError, TypeError) as exc:
        if cached:
            return {**cached['result'], 'cache': {'hit': True, 'stale': True},
                    'warning': 'A atualização falhou; dados salvos estão desatualizados.'}
        raise ValueError('Não foi possível obter os dados de clima e solo. Nenhuma condição favorável foi presumida; tente novamente.') from exc
    result = {**values, 'source': 'Open-Meteo · modelos meteorológicos', 'url': url,
              'documentation_url': DOCS, 'requested_point': point,
              'grid_point': {'latitude': payload.get('latitude'), 'longitude': payload.get('longitude'), 'elevation_m': payload.get('elevation')},
              'fetched_at': storage.now(), 'timezone': 'America/Sao_Paulo',
              'kind': 'modeled_weather_and_forecast', 'is_field_sensor': False}
    storage.source_snapshot(key, result)
    return {**result, 'cache': {'hit': False, 'stale': False}}


def evaluate(weather, inputs, today, ndvi=None):
    factors = []
    def add(key, label, status, reading, value=None, unit=None, source='Open-Meteo · estimativa regional'):
        factors.append({'key': key, 'label': label, 'status': status, 'reading': reading,
                        'value': value, 'unit': unit, 'source': source})
    days = {row['date']: row for row in (weather or {}).get('days', [])}
    def aggregate(first, last, variable):
        values = []
        for offset in range((last-first).days+1):
            row = days.get((first+timedelta(days=offset)).isoformat(), {})
            value = row.get(variable)
            if value is None: return None
            values.append(value)
        return round(sum(values), 2)
    yesterday = today-timedelta(days=1)
    rain7 = aggregate(today-timedelta(days=7), yesterday, 'precipitation_sum')
    rain14 = aggregate(today-timedelta(days=14), yesterday, 'precipitation_sum')
    future = aggregate(today+timedelta(days=1), today+timedelta(days=7), 'precipitation_sum')
    et0 = aggregate(today-timedelta(days=7), yesterday, 'et0_fao_evapotranspiration')
    # Historical model estimates and forecasts remain separate; today is partial.
    for key, label, value in [('rain7','Chuva nos 7 dias completos anteriores',rain7),
                              ('rain14','Chuva nos 14 dias completos anteriores',rain14),
                              ('forecast7','Chuva prevista nos próximos 7 dias',future)]:
        add(key,label,'context' if value is not None else 'missing',
            f'{value:g} mm.' if value is not None else 'Série incompleta; dias ausentes não foram tratados como zero.',value,'mm')
    balance = round(rain7-et0,2) if rain7 is not None and et0 is not None else None
    add('balance','Chuva menos evapotranspiração de referência · 7 dias','context' if balance is not None else 'missing',
        f'{balance:g} mm. Indicador climático; não é balanço de água do talhão.' if balance is not None else 'Faltam chuva ou ET₀ para o período completo.',balance,'mm')
    soil = [p for p in (weather or {}).get('soil_hours',[]) if p['date']==yesterday.isoformat()]
    temperatures = [p['soil_temperature_6cm'] for p in soil if p.get('soil_temperature_6cm') is not None]
    moisture = [p['soil_moisture_3_to_9cm'] for p in soil if p.get('soil_moisture_3_to_9cm') is not None]
    temperature = round(sum(temperatures)/len(temperatures),1) if len(temperatures)>=18 else None
    add('soil_temperature','Temperatura média estimada do solo · 6 cm · ontem',
        'missing' if temperature is None else 'favorable' if 20<=temperature<=30 else 'attention',
        'Dados horários insuficientes.' if temperature is None else f'{temperature:g} °C. Referência para soja: 20 a 30 °C (Embrapa).',temperature,'°C')
    moisture_mean = round(sum(moisture)/len(moisture),3) if len(moisture)>=18 else None
    add('soil_moisture','Umidade volumétrica estimada do solo · 3–9 cm · ontem',
        'context' if moisture_mean is not None else 'missing',
        f'{moisture_mean:g} m³/m³. Depende da textura e da retenção de água; confirme umidade na profundidade da semente.' if moisture_mean is not None else 'Dados de umidade do solo insuficientes.',moisture_mean,'m³/m³')
    if rain7 is not None and future is not None and inputs['water_management']=='rainfed' and rain7<10 and future<10:
        add('dry_spell','Reposição hídrica em sequeiro','attention','Pouca chuva recente e prevista (< 10 mm em cada janela de 7 dias). Alerta experimental; não comprova solo seco.')
    forecast_rows = [days.get((today+timedelta(days=i)).isoformat(),{}) for i in range(1,8)]
    intense = [row.get('precipitation_sum') for row in forecast_rows if row.get('precipitation_sum') is not None and row['precipitation_sum']>=50]
    if intense or (future is not None and future>=100):
        add('heavy_rain','Previsão de chuva intensa','attention','Previsão ≥ 50 mm em um dia ou ≥ 100 mm em 7 dias. Verifique drenagem e trafegabilidade; limiares exploratórios, não previsão de alagamento.')
    highs=[row['temperature_2m_max'] for row in forecast_rows if row.get('temperature_2m_max') is not None]
    lows=[row['temperature_2m_min'] for row in forecast_rows if row.get('temperature_2m_min') is not None]
    if len(highs)<7 or len(lows)<7:
        add('air_temperature','Temperatura do ar prevista','missing','Faltam mínimas ou máximas para os sete dias.')
    elif max(highs)>=35 or min(lows)<=10:
        add('air_temperature','Temperatura do ar prevista','attention',f'Mínima {min(lows):g} °C e máxima {max(highs):g} °C. Alerta exploratório de extremo térmico; confirme a temperatura do solo.')
    else:
        add('air_temperature','Temperatura do ar prevista','context',f'Mínima {min(lows):g} °C e máxima {max(highs):g} °C nos sete dias.')
    checks = [
        ('soil_condition','Condição do solo na profundidade da semente','adequate',{'dry':'Solo seco informado.','waterlogged':'Solo encharcado informado.'},'Umidade e condição física adequadas informadas pelo usuário.'),
        ('drainage','Drenagem e trafegabilidade','adequate',{'problem':'Problemas de drenagem ou trafegabilidade informados.'},'Drenagem e trafegabilidade verificadas pelo usuário.'),
        ('fertility','Análise e correção do solo','verified',{'needs_correction':'Correções pendentes informadas.'},'Análise e correções verificadas pelo usuário.'),
        ('calendar','Calendário sanitário local','verified',{'outside':'Fora do calendário permitido, conforme informado.'},'Calendário sanitário verificado pelo usuário.'),
        ('zarc','ZARC · município, cultivar e solo','verified',{'outside':'Fora da janela ZARC consultada, conforme informado.'},'ZARC verificado pelo usuário para município, cultivar e solo.'),
    ]
    for key,label,good,bad,reading in checks:
        value=inputs[key]
        add(key,label,'favorable' if value==good else 'attention' if value in bad else 'missing',
            reading if value==good else bad.get(value,'Ainda não verificado. Não foi presumido a partir do satélite.'),source='Informação de campo fornecida pelo usuário')
    if ndvi:
        age=(today-date.fromisoformat(ndvi['date'])).days
        add('ndvi','Cobertura vegetal · Sentinel-2 salvo','context' if age<=15 else 'missing',
            f"NDVI {ndvi['ndvi_mean']:.3f} em {ndvi['date']}; cobertura {ndvi['valid_fraction']*100:.1f}%. "+('Revisar ocupação e manejo da área; não mede umidade nem fertilidade.' if age<=15 else 'Leitura antiga; não representa a condição atual.'),
            ndvi['ndvi_mean'],source='Copernicus Sentinel-2 · mesmo recorte · base salva')
    else:
        add('ndvi','Cobertura vegetal · Sentinel-2 salvo','missing','Sem leitura recente de qualidade do mesmo recorte. Nenhuma imagem foi coletada.',source='Base local')
    stale = bool((weather or {}).get('cache',{}).get('stale'))
    if not weather or stale:
        add('freshness','Atualização meteorológica','missing','Dados meteorológicos indisponíveis ou desatualizados; não representam uma atualização das condições.')
    attention = [f['key'] for f in factors if f['status']=='attention']
    missing = [f['key'] for f in factors if f['status']=='missing']
    status = 'attention' if attention else 'incomplete' if missing else 'favorable'
    title = {'attention':'Pontos de atenção antes do plantio','incomplete':'Avaliação incompleta · aptidão não confirmada',
             'favorable':'Condições favoráveis nos parâmetros avaliados'}[status]
    return {'version':1,'crop':'soja','as_of':today.isoformat(),'status':status,'title':title,
            'factors':factors,'attention':attention,'missing':missing,'field_inputs':inputs,
            'weather':weather,'satellite':ndvi,'agronomy_url':AGRONOMY,
            'periods':{'recent_from':(today-timedelta(days=14)).isoformat(),'recent_to':yesterday.isoformat(),
                       'forecast_from':(today+timedelta(days=1)).isoformat(),'forecast_to':(today+timedelta(days=7)).isoformat()},
            'note':'Triagem para soja, não laudo de aptidão nem autorização de plantio. Meteorologia e solo são estimativas de grade para um ponto do recorte, não sensores de campo nem mapas de 10 m. Previsões podem mudar. Calendário e ZARC são verificações declaradas pelo usuário. Solo, sementes, sanidade, restrições ambientais e condição operacional precisam de avaliação local. Não identifica áreas legalmente disponíveis.'}


def consult(geometry, data, allow_network=True):
    inputs=field_inputs(data)
    point_for(geometry)
    today=inactive_soy.today()
    problem=None
    try:
        climate=fetch_weather(geometry,today,allow_network)
    except ValueError as exc:
        climate=None;problem=str(exc)
    series,_,_=local_ndvi.local_series(geometry,(today-timedelta(days=60)).isoformat(),today.isoformat())
    exact=next((s for s in series if s['scope']=='exact_area'),None)
    usable=[p for p in (exact or {}).get('points',[]) if numeric(p.get('valid_fraction'),.5,1) is not None
            and numeric(p.get('valid_pixels'),50,1e12) is not None]
    ndvi=max(usable,key=lambda p:p['date']) if usable else None
    result=evaluate(climate,inputs,today,ndvi)
    result['geometry']=geometry
    if problem:result['weather_error']=problem
    return result
