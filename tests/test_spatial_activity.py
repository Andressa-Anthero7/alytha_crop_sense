import json
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import shape
from app import spatial_activity as spatial, spatial_raster, storage


class SpatialTests(unittest.TestCase):
    def test_growth_sequence_maps_regular_blocks_before_and_after(self):
        cube=np.full((3,30,30),.2,dtype=np.float32)
        cube[1,:,:15]=.6;cube[2,:,:]=.7
        result=spatial.analyze_pixels([(a,np.ones((30,30),dtype=bool)) for a in cube],self.grid)
        stages=result['growth_sequence']['stages']
        self.assertEqual([s['area_ha'] for s in stages],[4.5,4.5])
        self.assertEqual([s['features'][0]['properties']['growth_stage'] for s in stages],['early','late'])
        for stage in stages:
            self.assertEqual(stage['features'][0]['properties']['shape_pattern'],'bloco regular')
            self.assertEqual(stage['features'][0]['properties']['rectangularity'],1)
        self.assertTrue(shape(stages[0]['features'][0]['geometry']).intersection(shape(stages[1]['features'][0]['geometry'])).area<1e-14)

    def test_reversed_or_cloudy_gain_is_not_early_growth(self):
        cube=np.full((3,30,30),.2,dtype=np.float32);cube[1,:,:]=.6
        result=spatial.analyze_pixels([(a,np.ones((30,30),dtype=bool)) for a in cube],self.grid)
        self.assertFalse(result['growth_sequence']['geojson']['features'])
        cube[2,:,:]=.7
        masks=[np.ones((30,30),dtype=bool) for _ in range(3)];masks[1][:,:10]=False
        result=spatial.analyze_pixels(list(zip(cube,masks)),self.grid)
        self.assertAlmostEqual(result['growth_sequence']['stages'][0]['area_ha'],6)

    def setUp(self):
        self.grid={'mask':np.ones((30,30),dtype=bool),'crs':'EPSG:32721','transform':from_origin(500000,8600000,10,10),'width':30,'height':30}
    def images(self):
        images=[]
        for _ in range(3):
            ndvi=np.full((30,30),.7,dtype=np.float32);ndvi[5:25,5:25]=.2
            images.append((ndvi,np.ones((30,30),dtype=bool)))
        return images
    def test_persistent_pixels_preserve_holes_and_metric_area(self):
        images=self.images()
        for ndvi,_ in images:ndvi[10:15,10:15]=.7
        result=spatial.analyze_pixels(images,self.grid)
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['patches'],1)
        self.assertAlmostEqual(result['persistent_low_ha'],3.75)
        geometry=shape(result['geojson']['features'][0]['geometry'])
        self.assertTrue(geometry.is_valid)
        self.assertEqual(len(geometry.interiors),1)
        self.assertEqual(result['ml_features']['persistent_low_fraction'],375/900)
    def test_cloud_gaps_never_become_low_vegetation(self):
        images=self.images()
        images[1][1][:,:16]=False
        result=spatial.analyze_pixels(images,self.grid)
        self.assertEqual(result['status'],'inconclusive')
        self.assertIsNone(result['ml_features'])
        self.assertFalse(result['geojson']['features'])
    def test_only_same_observed_pixels_count_and_small_regions_are_excluded(self):
        images=self.images()
        images[1][1][5:15,5:15]=False
        for ndvi,_ in images:ndvi[0:2,0:2]=.1
        result=spatial.analyze_pixels(images,self.grid)
        self.assertAlmostEqual(result['persistent_low_ha'],3)
        self.assertAlmostEqual(result['small_low_regions_ha'],.04)
        self.assertEqual(result['patches'],1)
        self.assertAlmostEqual(result['observed_area_ha'],8)
    def test_one_high_reading_breaks_persistence(self):
        images=self.images();images[1][0][:]=.7
        result=spatial.analyze_pixels(images,self.grid)
        self.assertEqual(result['patches'],0)
        self.assertEqual(result['persistent_low_ha'],0)
    def test_gain_loss_and_low_patches_are_disjoint_and_exclude_cloud_gaps(self):
        images=[(np.full((30,30),.5,dtype=np.float32),np.ones((30,30),dtype=bool)) for _ in range(3)]
        for index,(ndvi,_) in enumerate(images):
            ndvi[:10]=.2
            ndvi[10:20]=[.1,.3,.6][index]
            ndvi[20:]=[.8,.5,.2][index]
        images[1][1][:,:5]=False
        result=spatial.analyze_pixels(images,self.grid)
        self.assertAlmostEqual(result['vegetation_gain_ha'],2.5)
        self.assertAlmostEqual(result['vegetation_loss_ha'],2.5)
        self.assertAlmostEqual(result['persistent_low_ha'],2.5)
        self.assertEqual({f['properties']['signal'] for f in result['change_geojson']['features']},
                         {'vegetation_gain','vegetation_loss','persistent_low_vegetation'})
        self.assertAlmostEqual(sum(f['properties']['area_ha'] for f in result['change_geojson']['features']),result['observed_area_ha'])
    def test_small_change_patches_are_not_promoted_to_mapped_hectares(self):
        images=[(np.full((30,30),.5,dtype=np.float32),np.ones((30,30),dtype=bool)) for _ in range(3)]
        images[-1][0][:5,:5]=.9
        result=spatial.analyze_pixels(images,self.grid)
        self.assertEqual(result['vegetation_gain_ha'],0)
        self.assertEqual(result['change_geojson']['features'],[])
    def test_nan_and_invalid_ndvi_are_not_valid_even_with_quality_flag(self):
        images=self.images()
        images[0][0][:16,:]=np.nan
        self.assertEqual(spatial.analyze_pixels(images,self.grid)['status'],'inconclusive')
    def test_periods_cannot_overlap_or_use_future_images(self):
        points=[{'date':d,'valid_pixels':100,'valid_fraction':1} for d in ['2026-09-18','2026-09-23','2026-10-03','2026-10-05','2026-10-15']]
        periods=spatial.select_periods(points,'2026-10-09')
        self.assertEqual([p['from'] for p in periods],['2026-09-18','2026-09-23','2026-10-05'])
        self.assertTrue(all(a['to']<b['from'] for a,b in zip(periods,periods[1:])))
        with self.assertRaises(ValueError):spatial.select_periods(points[-2:],'2026-10-09')
    def test_raster_reader_rejects_shifted_grid(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'image.tif'
            with rasterio.open(path,'w',driver='GTiff',width=30,height=30,count=2,dtype='float32',crs=self.grid['crs'],transform=self.grid['transform']) as dataset:
                dataset.write(np.stack([np.full((30,30),.2),np.ones((30,30))]).astype(np.float32))
            ndvi,valid=spatial_raster.read_raster(path,self.grid)
            self.assertTrue(valid.all())
            shifted={**self.grid,'transform':from_origin(500010,8600000,10,10)}
            with self.assertRaises(ValueError):spatial_raster.read_raster(path,shifted)
    def test_large_recorte_is_rejected_without_downsampling(self):
        geometry={'type':'Polygon','coordinates':[[[-56,-12],[-55,-12],[-55,-11],[-56,-11],[-56,-12]]]}
        with self.assertRaises(ValueError):spatial_raster.grid_for(geometry)
    def test_area_mismatch_is_rejected_before_downloading(self):
        geometry={'type':'Polygon','coordinates':[[[-55,-12],[-54.99,-12],[-54.99,-11.99],[-55,-11.99],[-55,-12]]]}
        other={'type':'Polygon','coordinates':[[[-54,-12],[-53.99,-12],[-53.99,-11.99],[-54,-11.99],[-54,-12]]]}
        with patch.object(spatial.research,'dataset',return_value={'parameters':{'geometry':other}}),patch.object(spatial_raster,'fetch') as provider:
            with self.assertRaisesRegex(ValueError,'outro recorte'):
                spatial.start({'geojson':geometry,'dataset_id':'a'*64})
            provider.assert_not_called()
    def test_provider_requests_numeric_data_and_reuses_validated_cache(self):
        from app import web_app
        from rasterio.io import MemoryFile
        with MemoryFile() as memory:
            with memory.open(driver='GTiff',width=30,height=30,count=2,dtype='float32',crs=self.grid['crs'],transform=self.grid['transform']) as dataset:
                dataset.write(np.stack([np.full((30,30),.2),np.ones((30,30))]).astype(np.float32))
            binary=memory.read()
        geometry={'type':'Polygon','coordinates':[[[-55,-12],[-54.999,-12],[-54.999,-11.999],[-55,-11.999],[-55,-12]]]}
        grid={**self.grid,'bounds':[500000,8599700,500300,8600000]}
        with tempfile.TemporaryDirectory() as temp,patch.object(spatial_raster,'ROOT',Path(temp)),patch.object(web_app,'get_cdse_access_token',return_value='fixture-token'),patch.object(spatial_raster,'urlopen',return_value=io.BytesIO(binary)) as provider:
            period={'from':'2026-10-03','to':'2026-10-07'}
            first=spatial_raster.fetch(geometry,grid,period)
            second=spatial_raster.fetch(geometry,grid,period)
            self.assertTrue(np.array_equal(first[0],second[0]))
            self.assertEqual(provider.call_count,1)
            payload=json.loads(provider.call_args.args[0].data)
            self.assertEqual(payload['output']['responses'][0]['format']['type'],'image/tiff')
            self.assertIn('FLOAT32',payload['evalscript'])
            self.assertEqual(payload['input']['bounds']['bbox'],grid['bounds'])
            self.assertTrue(first[1].all())
    def test_failed_job_retry_returns_loading_and_preserves_geometry(self):
        geometry={'type':'Polygon','coordinates':[[[-55,-12],[-54.999,-12],[-54.999,-11.999],[-55,-11.999],[-55,-12]]]}
        with tempfile.TemporaryDirectory() as temp, patch.object(storage,'DB_PATH',Path(temp)/'db.sqlite3'),patch.object(spatial.POOL,'submit'):
            first=spatial.start({'geojson':geometry})
            spatial.RUNNING.discard(first['id'])
            storage.source_snapshot('cv:job:'+first['id'],{**first,'status':'error'})
            retry=spatial.start({'geojson':geometry})
            self.assertEqual(retry['status'],'loading')
            self.assertEqual(retry['parameters']['geometry'],geometry)
            spatial.RUNNING.discard(first['id'])
    def test_worker_exports_features_without_management_labels(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(storage,'DB_PATH',Path(temp)/'db.sqlite3'),patch.object(spatial,'OUTPUT_ROOT',Path(temp)/'outputs'),patch.object(spatial,'recent_points',return_value=[{'date':d,'valid_pixels':100,'valid_fraction':1} for d in ['2026-09-23','2026-09-28','2026-10-03']]),patch.object(spatial_raster,'grid_for',return_value=self.grid),patch.object(spatial_raster,'fetch',side_effect=self.images()):
            params={'area_id':'fixture','geometry':{},'as_of':'2026-10-09','scope':'test','algorithm_version':1}
            spatial.build('a'*64,params)
            job=spatial.get('a'*64)
            self.assertEqual(job['status'],'ready')
            csv=(Path(job['output_folder'])/'caracteristicas_ml.csv').read_text(encoding='utf-8-sig')
            self.assertNotIn('target_stage',csv)
            self.assertIn('persistent_low_fraction',csv)
            self.assertTrue((Path(job['output_folder'])/'manchas.geojson').is_file())


if __name__=='__main__':unittest.main()
