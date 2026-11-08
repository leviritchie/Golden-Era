"""Fresh Eagle reference-package capture comparison (diagnostic only)."""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
import numpy as np
from capture_candidates import require_frozen_package
from intermediate_capture import run_capture
from model_runner import load_model
from paths import REPO
from run_mocap_baseline import _gpu_lock_waiting
from vendor_reference import load_complete_package

CLIPS=('g00_move','g02_idle','g11_attack_up')
REFS=('Eagle#Eagle-Landing/y15','Eagle#Eagle-Landing/y0','Eagle#Eagle-Landing/y90')

def _sha(path):
 import hashlib
 h=hashlib.sha256(); h.update(Path(path).read_bytes()); return h.hexdigest()

def _rows(corpus):
 rows={row['key']:row for row in corpus.get('captures',[])}
 if len(rows)!=len(corpus['captures']) or not set(CLIPS).issubset(rows): raise ValueError('corpus requires unique clips including move, idle, and upward attack')
 return {key:rows[key] for key in CLIPS}

def _verify_package(package, baseline):
 if list(package['jointNames'])!=list(baseline['jointNames']) or not np.array_equal(package['parents'],baseline['parents']): raise ValueError('reference package skeleton differs from baseline')

def verify_source_identity(corpus,row):
 manifest_path=Path(corpus['manifest'])
 if _sha(manifest_path)!=corpus['manifestSha256']: raise ValueError('source manifest hash drift')
 manifest=json.loads(manifest_path.read_text())
 matches=[clip for clip in manifest['clips'] if clip['key']==row['key']]
 if len(matches)!=1: raise ValueError('source manifest clip is not unique')
 clip=matches[0]
 expected=clip['contextBefore']+clip['frames']+clip['contextAfter']
 indices=list(range(len(clip['contextBefore']),len(clip['contextBefore'])+len(clip['frames'])))
 if row['frames']!=clip['frames'] or row['sourceIndices']!=indices: raise ValueError('authored source order differs from manifest')
 folder=Path(row['capture']).parent.parent/'frames'
 numbered=sorted(folder.glob('*.png'))
 if len(numbered)!=len(expected) or any(not p.stem.isdigit() for p in numbered): raise ValueError('context frame inventory differs')
 hashes=[]
 for frame,number in zip(expected,numbered):
  digest=corpus['sourceFrames'][frame]['sha256']
  if _sha(frame)!=digest or _sha(number)!=digest: raise ValueError('source/context frame hash drift')
  hashes.append(digest)
 return {'contextSha256':hashes,'authoredSha256':[hashes[i] for i in indices]}

def run(corpus_paths, output):
 started=time.perf_counter()
 if len(corpus_paths)!=2: raise ValueError('exactly two --corpus inputs are required')
 if output.exists(): raise FileExistsError('output must be absent')
 old=[json.loads(Path(p).read_text()) for p in corpus_paths]
 units={c['unit'] for c in old}
 if len(units)!=2: raise ValueError('corpus units must be distinct')
 rows=[_rows(c) for c in old]
 for corpus,rowset in zip(old,rows):
  if corpus.get('package',{}).get('refSeq')!='Eagle#Eagle-Landing/y15': raise ValueError('old corpus must be y15 baseline')
  for row in rowset.values():
   verify_source_identity(corpus,row)
   raw=Path(row['capture']); frames=raw.parent.parent/'frames'; numbered=sorted(frames.glob('*.png'))
   with np.load(raw,allow_pickle=False) as data:
    if _sha(raw)!=row['captureSha256'] or len(numbered)!=len(data['image_embed']): raise ValueError('stale raw capture or frame/embed mismatch')
  
 import torch
 output.mkdir(parents=True)
 results=[]
 with _gpu_lock_waiting(REPO):
  model=load_model(torch.device('cuda'))[0]
  for corpus,rowset in zip(old,rows):
   unit=corpus['unit']; unit_dir=output/unit; unit_dir.mkdir()
   baseline_pkg=require_frozen_package(unit,role='primary')
   for ref in REFS:
    package=load_complete_package('zoo',ref)
    _verify_package(package,baseline_pkg)
    ref_dir=unit_dir/ref.replace('#','_').replace('/','_'); ref_dir.mkdir()
    new_rows=[]
    for key in CLIPS:
     oldrow=rowset[key]; oldraw=Path(oldrow['capture']); clip_dir=ref_dir/key; frames=oldraw.parent.parent/'frames'
     with np.load(oldraw,allow_pickle=False) as data:
      embed=np.asarray(data['image_embed'],dtype=np.float32).copy(); old_pred=np.asarray(data['pred_position']).copy(); old_ref=np.asarray(data['ref_image_embed']).copy()
     report=run_capture(package=package,frames_dir=frames,out_dir=clip_dir/'capture',image_embed=embed,preprocess_meta=corpus['preprocess'],model=model,source_kind='authored_source_frame',title=key,compare_gt=False)
     fresh=clip_dir/'capture'/'raw_capture.npz'
     with np.load(fresh,allow_pickle=False) as data:
      if not np.array_equal(data['image_embed'],embed): raise ValueError('fresh capture image embedding changed')
      if not np.array_equal(data['ref_image_embed'],package['refImageEmbed']): raise ValueError('reference image embedding differs from selected package')
      if ref==REFS[0] and not np.array_equal(data['ref_image_embed'],old_ref): raise ValueError('baseline reference image embedding changed')
      if ref==REFS[0] and not np.array_equal(data['pred_position'],old_pred): raise ValueError('fresh y15 baseline differs from old capture')
      baseline_error=float(np.max(np.abs(data['pred_position']-old_pred))) if ref==REFS[0] else None
     new_rows.append({'key':key,'frames':oldrow['frames'],'sourceIndices':oldrow['sourceIndices'],'referenceIndex':oldrow['referenceIndex'],'contextBeforeCount':oldrow['contextBeforeCount'],'contextAfterCount':oldrow['contextAfterCount'],'capture':str(fresh.resolve()),'captureSha256':_sha(fresh),'report':report,'baselineMaxError':baseline_error,'oldCapture':str(oldraw.resolve()),'oldCaptureSha256':_sha(oldraw)})
     print(f'{unit} {ref} {key}: baseline error {baseline_error}',flush=True)
    out_corpus={'schema':'homm3.skin-corpus.v1','unit':unit,'package':{'kind':package['kind'],'refSeq':ref},'preprocess':corpus['preprocess'],'captures':new_rows,'provenance':{'oldCorpus':str(Path(corpus_paths[old.index(corpus)]).resolve()),'oldCorpusSha256':_sha(corpus_paths[old.index(corpus)]),'reference':ref}}
    (ref_dir/'corpus.json').write_text(json.dumps(out_corpus,indent=2))
    results.append(str(ref_dir/'corpus.json'))
 result={'outputs':results,'elapsedSeconds':time.perf_counter()-started}
 (output/'report.json').write_text(json.dumps(result,indent=2))
 return result

if __name__=='__main__':
 p=argparse.ArgumentParser(); p.add_argument('--corpus',type=Path,action='append',required=True); p.add_argument('--output',type=Path,required=True); a=p.parse_args(); print(json.dumps(run(a.corpus,a.output.resolve()),indent=2))
