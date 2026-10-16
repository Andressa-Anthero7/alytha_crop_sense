"""Recompute spatial progression using only the exact local raster cache."""
import hashlib
from . import research, storage, spatial_activity, spatial_raster


def analyze(history, cutoff, prior=None):
    if prior and prior.get('progression'):
        return prior
    try:
        periods = prior.get('periods') if prior else spatial_activity.select_periods(history['points'], cutoff)
        grid = spatial_raster.grid_for(history['parameters']['geometry'])
        paths = [spatial_raster.cache_path(history['parameters']['geometry'], grid, period) for period in periods]
        if not all(p.is_file() for p in paths): return prior
        images = [spatial_raster.read_raster(path, grid) for path in paths]
        inputs = [{'resource':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(), 'period':period}
                  for path,period in zip(paths,periods)]
        result = spatial_activity.analyze_pixels(images, grid)
        params = {'geometry':history['parameters']['geometry'], 'area_id':history['parameters']['area_key'],
                  'as_of':cutoff,'algorithm_version':3,'mode':'local_rasters_only','input_rasters':inputs}
        identifier = research.fingerprint(params)
        result.update(id=identifier,parameters=params,periods=periods,updated_at=storage.now(),source='Sentinel-2 · rasters locais')
        storage.source_snapshot('cv:job:' + identifier,result)
        return result
    except (ValueError, OSError, ImportError):
        # Unavailable cache never authorizes a replacement network call.
        return prior
