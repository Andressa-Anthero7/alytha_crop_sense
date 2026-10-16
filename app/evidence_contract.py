"""Versioned evidence envelope for computed and retrieved analytical results."""
from . import local_inventory


def computed(identifier, kind, history, period, method, version, quality, data, resource=None,
             source='Alytha · análise local'):
    result = local_inventory.evidence(identifier, kind, history['parameters'].get('area_key'),
        period, resource or 'sqlite:history:' + history['id'], quality, data, source)
    result['provenance'].update(method=method, version=version, dataset_id=history['id'])
    result['scope'] = 'mesmo recorte; não representa todo o município'
    result['municipality_code'] = history['parameters'].get('municipality_code')
    return result


def annotate_context(grounded, data, history=None):
    """Extend legacy context projections without claiming unknown source quality."""
    area_ids={'satellite_history','temporal_analysis','historical_comparison','crop_monitoring',
              'field_observations','learning_cycle','visual_learning'}
    for item in grounded.get('evidence',[]):
        if item.get('contract_version'):continue
        local=bool(history and item['id'] in area_ids)
        value=item.get('data',{})
        if not isinstance(value,dict):value={}
        period=item.get('period') or value.get('period')
        if not period:
            cutoff=item.get('as_of') or value.get('as_of') or value.get('date')
            if cutoff:period={'from':None,'to':cutoff}
        quality=value.get('quality') or item.get('quality') or {
            'status':item.get('status') or value.get('status') or 'not_reported',
            'pixel_quality':'not_evaluated_by_context_projection'}
        resource=('sqlite:history:'+str(history.get('id') or data.get('dataset_id'))) if local else item.get('url') or 'local-context:'+item['id']
        item.update(contract_version=1,kind=item['id'],area_key=history['parameters'].get('area_key') if local else None,
                    period=period,quality=quality,
                    provenance={'resource':resource,'method':'server_context_projection',
                                'version':1,'upstream_method':value.get('method'),'upstream_version':value.get('version'),
                                'source_method_version_known':value.get('version') is not None})
        item.setdefault('source','Alytha · análise local')
        item.setdefault('scope','mesmo recorte' if local else 'escala da fonte; sem vínculo de talhão confirmado')
    return grounded
