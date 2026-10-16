"""Reproducible, unpromoted vegetation clustering candidates from local history."""
import argparse
import csv
import json
from pathlib import Path
from . import research, storage

ROOT = Path(__file__).resolve().parents[1] / 'data/outputs/experiments/ml'
FEATURES = ['mean_ndvi','latest_ndvi','amplitude','slope_day','mean_observed_fraction']


def evaluate(history, output_root=None):
    import numpy as np
    import sklearn
    import joblib
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score, adjusted_rand_score
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_limits
    from .historical_comparison import training_rows
    rows = training_rows(history)
    if len(rows) < 30:
        raise ValueError('O experimento precisa de pelo menos 30 janelas históricas aproveitáveis.')
    matrix = np.array([[row[key] for key in FEATURES] for row in rows], dtype=float)
    split = max(20, int(len(rows)*.7))
    if len(rows)-split < 5: raise ValueError('Janelas insuficientes para reservar um período posterior.')
    scaler = StandardScaler().fit(matrix[:split])
    train = scaler.transform(matrix[:split]); test = scaler.transform(matrix[split:])
    version = research.fingerprint([history['id'],rows,FEATURES,sklearn.__version__,np.__version__,1])
    folder = Path(output_root or ROOT) / version
    folder.mkdir(parents=True, exist_ok=True)
    candidates = []
    unique = len(np.unique(train.round(8), axis=0))
    with threadpool_limits(limits=1):
        for k in (2,3,4):
            if unique < k: continue
            model = KMeans(n_clusters=k, random_state=42, n_init=10).fit(train)
            alternate = KMeans(n_clusters=k, random_state=7, n_init=10).fit(train)
            predicted = model.predict(test)
            def silhouette(values, labels):
                return float(silhouette_score(values, labels)) if 1 < len(set(labels)) < len(labels) else None
            file = folder / f'candidate-k{k}.joblib'
            joblib.dump({'scaler':scaler,'model':model,'features':FEATURES,'version':version},file)
            candidates.append({'clusters':k,'train_silhouette':silhouette(train,model.labels_),
                'later_period_silhouette':silhouette(test,predicted),
                'seed_stability_adjusted_rand':float(adjusted_rand_score(model.labels_,alternate.labels_)),
                'later_period_mean_distance':float(model.transform(test).min(axis=1).mean()),
                'later_group_counts':{str(i):int((predicted==i).sum()) for i in range(k)},
                'model_artifact':file.name,'promoted':False})
    report = {'version':1,'experiment_id':version,'dataset_id':history['id'],
        'area_key':history['parameters']['area_key'],'created_at':storage.now(),
        'input_sha256':research.fingerprint(history),'libraries':{'numpy':np.__version__,'sklearn':sklearn.__version__},
        'features':FEATURES,'seeds':[42,7],'n_init':10,'windows':len(rows),
        'split':{'method':'chronological_70_30','train_windows':split,'later_windows':len(rows)-split,
                 'train_through':rows[split-1]['as_of'],'later_from':rows[split]['as_of'],
                 'scaler_fit':'training_only','overlapping_windows':True},
        'candidates':candidates,'field_labels_used':False,'active_model_changed':False,
        'note':'Avaliação exploratória interna do mesmo recorte. Janelas vizinhas se sobrepõem; métricas não medem previsão independente, cultura, manejo ou acurácia agronômica. Hipóteses não são rótulos.'}
    with (folder/'windows.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (folder/'evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return {**report,'folder':str(folder)}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--dataset-id',required=True)
    parser.add_argument('--output',type=Path);args=parser.parse_args()
    result=evaluate(research.dataset(args.dataset_id),args.output)
    print(json.dumps({'folder':result['folder'],'windows':result['windows'],'candidates':len(result['candidates'])}))


if __name__=='__main__':main()
