import hashlib
import json
from pathlib import Path
import pandas as pd

models_dir = Path('data/models')
evidence_dir = Path('evidence')
pkl_files = sorted(list(models_dir.glob('*.pkl')))

rows = []
pilot_count = 0
for pkl in pkl_files:
    parts = pkl.stem.split('_')
    st, se, tg, ld = parts[0], parts[1], parts[2], parts[3]
    h = hashlib.sha256(pkl.read_bytes()).hexdigest()
    
    # Identify pilot station 18h TMAX
    is_pilot_18h_tmax = (st in ['KORD', 'KMIA', 'KSFO']) and (tg == 'Max') and (ld == 'lead18h')
    if is_pilot_18h_tmax:
        status = 'VALIDATED'
    else:
        status = 'FITTED'
        
    rows.append({
        'station': st,
        'target_type': tg,
        'lead_hour': ld,
        'season': se,
        'model_filename': f'data/models/{pkl.name}',
        'training_window': '2000-2018',
        'fitting_script_version': 'scripts/train_emos_matrix.py (commit 67d668b7)',
        'file_sha256': h,
        'status': status,
    })

# Add the 2 Active 10 JSON parameter assets
f1 = evidence_dir / 'active10_training_variance_factors.json'
f2 = evidence_dir / 'active10_climate_calibration.json'

rows.append({
    'station': 'ACTIVE_10_UNIVERSE',
    'target_type': 'Max',
    'lead_hour': 'lead18h',
    'season': 'ALL_4_SEASONS',
    'model_filename': 'evidence/active10_training_variance_factors.json',
    'training_window': '2000-2018',
    'fitting_script_version': 'scripts/fit_training_variance_factors.py',
    'file_sha256': hashlib.sha256(f1.read_bytes()).hexdigest(),
    'status': 'FITTED',
})

rows.append({
    'station': 'ACTIVE_10_UNIVERSE',
    'target_type': 'Max',
    'lead_hour': 'lead18h',
    'season': 'ALL_4_SEASONS',
    'model_filename': 'evidence/active10_climate_calibration.json',
    'training_window': '2000-2018',
    'fitting_script_version': 'scripts/fit_active10_climate_calibration.py',
    'file_sha256': hashlib.sha256(f2.read_bytes()).hexdigest(),
    'status': 'FITTED',
})

df = pd.DataFrame(rows)
out_csv = evidence_dir / 'model_inventory_audit.csv'
df.to_csv(out_csv, index=False)
print(f'Saved {out_csv} with {len(df)} entries.')
print(df['status'].value_counts())
