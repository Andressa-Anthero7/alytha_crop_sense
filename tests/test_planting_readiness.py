import copy
import io
import json
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from app import planting_readiness as planting

TODAY=date(2026,10,16)
GEOMETRY={'type':'Polygon','coordinates':[[[-55.81,-12.5],[-55.80,-12.5],[-55.80,-12.51],[-55.81,-12.51],[-55.81,-12.5]]]}


def weather_fixture():
    dates=[(TODAY+timedelta(days=i)).isoformat() for i in range(-14,8)]
    hourly=[(TODAY-timedelta(days=1)).isoformat()+f'T{hour:02d}:00' for hour in range(24)]
    return {'timezone':'America/Sao_Paulo','daily_units':dict(planting.DAILY),'hourly_units':dict(planting.HOURLY),
            'daily':{'time':dates,'precipitation_sum':[5.0]*22,'temperature_2m_min':[22]*22,'temperature_2m_max':[30]*22,'et0_fao_evapotranspiration':[4]*22},
            'hourly':{'time':hourly,'soil_temperature_6cm':[25]*24,'soil_moisture_3_to_9cm':[.25]*24}}


def favorable_inputs():
    return planting.field_inputs({'soil_condition':'adequate','drainage':'adequate','fertility':'verified','calendar':'verified','zarc':'verified'})


NDVI={'date':'2026-10-13','ndvi_mean':.2,'valid_fraction':.9,'valid_pixels':100}


class PlantingTests(unittest.TestCase):
    def normalized(self):
        return {**planting.normalize(weather_fixture(),TODAY),'cache':{'stale':False}}

    def factor(self,result,key):
        return next(f for f in result['factors'] if f['key']==key)

    def test_full_evidence_can_be_favorable_without_claiming_absolute_aptitude(self):
        result=planting.evaluate(self.normalized(),favorable_inputs(),TODAY,NDVI)
        self.assertEqual(result['status'],'favorable')
        self.assertFalse(result['missing'])
        self.assertEqual(self.factor(result,'rain7')['value'],35)
        self.assertEqual(self.factor(result,'rain14')['value'],70)
        self.assertEqual(self.factor(result,'forecast7')['value'],35)
        self.assertEqual(self.factor(result,'balance')['value'],7)
        self.assertIn('parâmetros avaliados',result['title'])
        self.assertIn('não laudo',result['note'])

    def test_unverified_field_or_legal_conditions_prevent_favorable_verdict(self):
        result=planting.evaluate(self.normalized(),planting.field_inputs({}),TODAY,NDVI)
        self.assertEqual(result['status'],'incomplete')
        self.assertTrue({'soil_condition','drainage','fertility','calendar','zarc'}<=set(result['missing']))

    def test_each_field_problem_is_reported_even_in_good_weather(self):
        for key,value in [('soil_condition','dry'),('soil_condition','waterlogged'),('drainage','problem'),('fertility','needs_correction'),('calendar','outside'),('zarc','outside')]:
            inputs=favorable_inputs();inputs[key]=value
            result=planting.evaluate(self.normalized(),inputs,TODAY,NDVI)
            self.assertEqual(result['status'],'attention')
            self.assertIn(key,result['attention'])

    def test_thermal_soil_limits(self):
        for temperature,status in [(19,'attention'),(20,'favorable'),(30,'favorable'),(31,'attention')]:
            raw=weather_fixture();raw['hourly']['soil_temperature_6cm']=[temperature]*24
            result=planting.evaluate(planting.normalize(raw,TODAY),favorable_inputs(),TODAY,NDVI)
            self.assertEqual(self.factor(result,'soil_temperature')['status'],status)

    def test_missing_rain_and_soil_values_are_not_zero_or_favorable(self):
        raw=weather_fixture();raw['daily']['precipitation_sum'][13]=None
        raw['hourly']['soil_temperature_6cm']=[None]*24
        result=planting.evaluate(planting.normalize(raw,TODAY),favorable_inputs(),TODAY,NDVI)
        self.assertIsNone(self.factor(result,'rain7')['value'])
        self.assertEqual(self.factor(result,'soil_temperature')['status'],'missing')
        self.assertEqual(result['status'],'incomplete')

    def test_past_forecast_and_partial_today_are_separate(self):
        raw=weather_fixture();raw['daily']['precipitation_sum'][14]=1000
        result=planting.evaluate(planting.normalize(raw,TODAY),favorable_inputs(),TODAY,NDVI)
        self.assertEqual(self.factor(result,'rain7')['value'],35)
        self.assertEqual(self.factor(result,'forecast7')['value'],35)
        self.assertNotIn('heavy_rain',result['attention'])

    def test_rainfed_dry_spell_and_heavy_rain_flags(self):
        raw=weather_fixture();raw['daily']['precipitation_sum']=[0]*22
        climate=planting.normalize(raw,TODAY)
        result=planting.evaluate(climate,favorable_inputs(),TODAY,NDVI)
        self.assertIn('dry_spell',result['attention'])
        inputs=favorable_inputs();inputs['water_management']='irrigated'
        self.assertNotIn('dry_spell',planting.evaluate(climate,inputs,TODAY,NDVI)['attention'])
        raw['daily']['precipitation_sum'][-1]=50
        result=planting.evaluate(planting.normalize(raw,TODAY),inputs,TODAY,NDVI)
        self.assertIn('heavy_rain',result['attention'])

    def test_missing_or_stale_weather_and_old_ndvi_prevent_favorable(self):
        climate=self.normalized();climate['cache']['stale']=True
        self.assertEqual(planting.evaluate(climate,favorable_inputs(),TODAY,NDVI)['status'],'incomplete')
        result=planting.evaluate(None,favorable_inputs(),TODAY,None)
        self.assertEqual(result['status'],'incomplete')
        self.assertIn('freshness',result['missing'])
        old={**NDVI,'date':'2026-09-01'}
        self.assertIn('ndvi',planting.evaluate(self.normalized(),favorable_inputs(),TODAY,old)['missing'])

    def test_bad_units_duplicate_dates_bad_timezone_and_misaligned_arrays_rejected(self):
        cases=[]
        raw=weather_fixture();raw['hourly_units']['soil_temperature_6cm']='°F';cases.append(raw)
        raw=weather_fixture();raw['daily']['time'][0]=raw['daily']['time'][1];cases.append(raw)
        raw=weather_fixture();raw['daily']['precipitation_sum'].pop();cases.append(raw)
        raw=weather_fixture();raw['timezone']='UTC';cases.append(raw)
        for raw in cases:
            with self.assertRaises(ValueError):planting.normalize(raw,TODAY)

    def test_numeric_rejects_boolean_nan_negative_rain_and_impossible_moisture(self):
        raw=weather_fixture();raw['daily']['precipitation_sum'][0]=-1
        raw['hourly']['soil_moisture_3_to_9cm'][0]=True
        raw['hourly']['soil_temperature_6cm'][0]=float('nan')
        climate=planting.normalize(raw,TODAY)
        self.assertIsNone(climate['days'][0]['precipitation_sum'])
        self.assertIsNone(climate['soil_hours'][0]['soil_moisture_3_to_9cm'])
        self.assertIsNone(climate['soil_hours'][0]['soil_temperature_6cm'])

    def test_invalid_inputs_and_large_geometry_rejected(self):
        for value in [None,[],{'soil_condition':True},{'calendar':'invented'}]:
            with self.assertRaises(ValueError):planting.field_inputs(value)
        geometry=copy.deepcopy(GEOMETRY);geometry['coordinates'][0][1][0]=-50
        with self.assertRaises(ValueError):planting.point_for(geometry)

    def test_fetch_normalizes_and_offline_mode_never_calls_provider(self):
        with patch.object(planting.storage,'source_snapshot',return_value=None) as snapshot,patch.object(planting,'urlopen',return_value=io.BytesIO(json.dumps(weather_fixture()).encode())) as request:
            result=planting.fetch_weather(GEOMETRY,TODAY)
            self.assertEqual(len(result['days']),22)
            self.assertFalse(result['cache']['hit'])
            self.assertEqual(snapshot.call_count,2)
            self.assertNotIn('forecast_days',request.call_args.args[0].full_url)
        with patch.object(planting.storage,'source_snapshot',return_value=None),patch.object(planting,'urlopen') as request:
            self.assertIsNone(planting.fetch_weather(GEOMETRY,TODAY,allow_network=False))
            request.assert_not_called()

    def test_consult_does_not_substitute_contained_sample_for_full_area(self):
        sample={'scope':'contained_sample','points':[NDVI]}
        with patch.object(planting,'fetch_weather',return_value=self.normalized()),patch.object(planting.local_ndvi,'local_series',return_value=([sample],1,None)),patch.object(planting.inactive_soy,'today',return_value=TODAY):
            result=planting.consult(GEOMETRY,favorable_inputs())
            self.assertIsNone(result['satellite'])
            self.assertEqual(result['status'],'incomplete')


if __name__=='__main__':unittest.main()
