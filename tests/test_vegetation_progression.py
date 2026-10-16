import unittest
import numpy as np
from rasterio.transform import from_origin
from app import spatial_activity


class ProgressionTests(unittest.TestCase):
    def setUp(self):
        self.grid={'mask':np.ones((30,30),dtype=bool),'crs':'EPSG:32721','transform':from_origin(500000,8600000,10,10),'width':30,'height':30}

    def sequence(self,loss=False,south=False):
        cube=np.full((3,30,30),.7 if loss else .2,dtype=np.float32)
        first=np.indices((30,30))[0 if south else 1]<15
        cube[1][first]=.2 if loss else .6
        cube[2][:]=.15 if loss else .7
        return [(image,np.ones((30,30),dtype=bool)) for image in cube]

    def analyze(self,images):return spatial_activity.analyze_pixels(images,self.grid)['progression']

    def test_eastward_greening_has_dated_cohorts_not_management_label(self):
        result=self.analyze(self.sequence())
        self.assertEqual(result['status'],'detected')
        front=result['fronts'][0]
        self.assertEqual(front['direction'],'L');self.assertEqual(front['signal'],'vegetation_gain')
        self.assertEqual(front['affected_area_ha'],9)
        self.assertGreater(front['spatial_order_r2'],.35)
        self.assertNotIn('stage',front);self.assertNotIn('probability',front)
        self.assertEqual(result['geojson']['features'][0]['geometry']['type'],'MultiLineString')

    def test_southward_loss_is_not_reported_as_confirmed_harvest(self):
        front=self.analyze(self.sequence(loss=True,south=True))['fronts'][0]
        self.assertEqual(front['direction'],'S');self.assertEqual(front['signal'],'vegetation_loss')
        self.assertIn('dessecação',front['reading'])

    def test_simultaneous_greening_has_no_direction(self):
        images=self.sequence();images[1][0][:]=.2
        self.assertEqual(self.analyze(images)['status'],'not_detected')

    def test_temporary_greening_does_not_become_planting_front(self):
        images=self.sequence();images[-1][0][:]=.2
        self.assertFalse(self.analyze(images)['fronts'])

    def test_clouds_cannot_create_front(self):
        images=self.sequence();images[1][1][:,15:]=False
        self.assertFalse(self.analyze(images)['fronts'])

    def test_disconnected_changes_are_not_linked_by_arrow(self):
        images=self.sequence()
        for ndvi,_ in images:ndvi[:,13:17]=.5
        self.assertFalse(self.analyze(images)['fronts'])

    def test_scattered_changes_have_no_direction(self):
        images=self.sequence();first=np.indices((30,30)).sum(axis=0)%2==0
        images[1][0][:]=.2;images[1][0][first]=.6
        self.assertFalse(self.analyze(images)['fronts'])

    def test_unobserved_pixels_produce_no_arrow_or_hypothesis(self):
        images=self.sequence();images[0][1][:,:20]=False
        result=spatial_activity.analyze_pixels(images,self.grid)
        self.assertEqual(result['progression']['status'],'inconclusive')
        self.assertFalse(result['progression']['geojson']['features'])


if __name__=='__main__':unittest.main()
