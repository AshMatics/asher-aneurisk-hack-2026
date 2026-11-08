"""Check event tables against their manifest and inspect paired NIfTI headers."""
import argparse
import hashlib
import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd

parser=argparse.ArgumentParser()
parser.add_argument('--data',type=Path,default=Path('data/practice'))
parser.add_argument('--output',type=Path,default=Path('outputs/data-inventory.json'))
args=parser.parse_args()
root=args.data
manifest=json.loads((root/'manifest.json').read_text())
errors=[]
for item in manifest['files']:
 path=root/item['path']
 if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
  errors.append(f'Manifest mismatch: {item["path"]}')
 if path.suffix=='.parquet' and path.exists() and len(pd.read_parquet(path))!=item['rows']:
  errors.append(f'Row count mismatch: {item["path"]}')
hospitals=[]
for hospital in sorted(root.glob('hospital_*')):
 labels=pd.read_parquet(hospital/'labels.parquet')
 checked=0
 for case in labels.case_id:
  ct=hospital/'images'/f'{case}.nii.gz'
  mask=hospital/'masks'/f'{case}_aorta.nii.gz'
  if not ct.exists() or not mask.exists():
   errors.append(f'Missing CT/mask pair: {hospital.name}/{case}')
   continue
  c,m=nib.load(ct),nib.load(mask)
  if len(c.shape)!=3 or c.shape!=m.shape or not np.allclose(c.affine,m.affine,atol=1e-4,rtol=0):
   errors.append(f'Grid mismatch: {hospital.name}/{case}')
   continue
  checked+=1
 hospitals.append({'hospital':hospital.name,'table_cases':len(labels),
                   'aaa_labeled_cases':int(labels.aaa.sum()),'aligned_pairs':checked})
report={'manifest_files_checked':len(manifest['files']),'hospitals':hospitals,'errors':errors,
        'note':'AAA status is the event table label; anatomy has not been independently adjudicated.'}
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
raise SystemExit(bool(errors))
