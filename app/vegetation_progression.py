"""Experimental spatial ordering of vegetation transitions, never machinery motion."""
import math


def analyze(cube, common, grid):
    import cv2
    import numpy as np
    from rasterio.warp import transform_geom
    result={'status':'not_detected','method':'ordered_ndvi_transitions_v1','experimental':True,
            'fronts':[],'geojson':{'type':'FeatureCollection','features':[]},
            'note':'Direção da sequência de mudanças entre janelas, não trajetória de máquinas nem linhas de plantio. Limiares experimentais; hipóteses de manejo precisam de validação de campo.'}
    # Both cohorts start in the same state and end in the same new state.
    # Changes must persist; temporary greening/loss cannot produce an arrow.
    a,b,c=cube
    signals=[('vegetation_gain',common & (a<=.25)&(b>=.35)&(c>=.35)&(c>=b-.05),
              common & (a<=.25)&(b<=.25)&(c>=.35)&(a<=b+.05)&(c-a>=.15)),
             ('vegetation_loss',common & (a>=.35)&(b<=.25)&(c<=.25)&(c<=b+.05),
              common & (a>=.35)&(b>=.35)&(c<=.25)&(a>=b-.05)&(a-c>=.15))]
    directions=['N','NE','L','SE','S','SO','O','NO']
    labels={'N':'norte','NE':'nordeste','L':'leste','SE':'sudeste','S':'sul','SO':'sudoeste','O':'oeste','NO':'noroeste'}
    def xy(rows,cols):
        t=grid['transform']
        return np.column_stack((t.a*(cols+.5)+t.b*(rows+.5)+t.c,t.d*(cols+.5)+t.e*(rows+.5)+t.f))
    for signal,early,late in signals:
        # Every transition needs a material net difference, including the early cohort.
        early &= (c-a>=.15) if signal=='vegetation_gain' else (a-c>=.15)
        count,components,stats,_=cv2.connectedComponentsWithStats((early|late).astype(np.uint8),connectivity=8)
        for index in range(1,count):
            if stats[index,cv2.CC_STAT_AREA]<200:continue
            region=components==index
            first=region & early;last=region & late
            if first.sum()<100 or last.sum()<100:continue
            first_xy=xy(*np.nonzero(first));last_xy=xy(*np.nonzero(last))
            start=first_xy.mean(axis=0);end=last_xy.mean(axis=0)
            vector=end-start;distance=float(np.linalg.norm(vector))
            if distance<30:continue
            positions=np.vstack((first_xy,last_xy));order=np.concatenate((np.zeros(len(first_xy)),np.ones(len(last_xy))))
            # Bound the fit's memory/time while retaining both chronological cohorts.
            sample=np.linspace(0,len(order)-1,min(10000,len(order)),dtype=int)
            x=positions[sample]-positions.mean(axis=0);y=order[sample]
            design=np.column_stack((np.ones(len(x)),x))
            coefficients=np.linalg.lstsq(design,y,rcond=None)[0]
            total=float(np.sum((y-y.mean())**2))
            r2=1-float(np.sum((y-design@coefficients)**2))/total if total else 0
            gradient=coefficients[1:]
            agreement=float(gradient@vector/(np.linalg.norm(gradient)*distance)) if np.linalg.norm(gradient) else 0
            if r2<.35 or agreement<.8:continue
            geographic=transform_geom(grid['crs'],'EPSG:4326',{'type':'LineString','coordinates':[start.tolist(),end.tolist()]})
            (lon1,lat1),(lon2,lat2)=geographic['coordinates']
            bearing=math.degrees(math.atan2((lon2-lon1)*math.cos(math.radians((lat1+lat2)/2)),lat2-lat1))%360
            cardinal=directions[int((bearing+22.5)//45)%8]
            reading=('Ganho de vegetação em sequência, compatível com estabelecimento ou desenvolvimento vegetal; pode acompanhar plantio em setores, rebrota ou diferenças de umidade.' if signal=='vegetation_gain' else 'Perda de vegetação em sequência, compatível com colheita, dessecação, senescência ou outro evento de redução vegetal.')
            front={'signal':signal,'direction':cardinal,'direction_label':labels[cardinal],'bearing_degrees':round(bearing,1),
                   'centroid_distance_m':round(distance,1),'affected_area_ha':int(region.sum())*.01,
                   'earlier_area_ha':int(first.sum())*.01,'later_area_ha':int(last.sum())*.01,
                   'spatial_order_r2':round(r2,3),'reading':reading,
                   'note':'R² descreve a organização espacial dos tempos de mudança; não é probabilidade de plantio ou colheita. Distância entre centros não mede deslocamento real nem velocidade de operação.'}
            result['fronts'].append(front)
            # An arrowhead uses the same metric grid as the direction segment.
            unit=vector/distance;normal=np.array([-unit[1],unit[0]])
            size=min(35,distance*.25)
            head=[(end-unit*size+normal*size*.5).tolist(),end.tolist(),(end-unit*size-normal*size*.5).tolist()]
            geometry=transform_geom(grid['crs'],'EPSG:4326',{'type':'MultiLineString','coordinates':[[start.tolist(),end.tolist()],head]})
            result['geojson']['features'].append({'type':'Feature','geometry':geometry,'properties':{**front,'progression':True}})
    if result['fronts']:result['status']='detected'
    return result
