"""Replay existing fixed motion with two skins; no capture or fitting."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
import torch
from corpus_motion import load_motion
from asset_profiles import get_profile
from ownership_candidate_validation import validate_invariants
from run_skin_mesh_pilot import comparison, deform, digest, expand_camera_to_full_canvas
from run_skin_weight_pilot import cascade_batch_lock,ROOT,source_images
from skin_image_objective import SkinImageRenderer
from skin_surface_constraints import SurfaceConstraints
from pin import sha256_file

def _motion_retention(before, after, regions):
    ranges=[np.linalg.norm(np.ptp(x.detach().cpu().numpy(),axis=0),axis=1) for x in (before,after)]
    result={}
    for region in np.unique(regions):
        mask=np.asarray(regions)==region
        a,b=[float(np.median(x[mask])) for x in ranges]
        result[str(region)]={'baselineMedianTemporalRange':a,'candidateMedianTemporalRange':b,
                             'ratio':b/a if a>1e-8 else None}
    return result

def run(original,candidate,corpus_path,camera_path,output,registration=None,all_clips=False,fit_seconds=0):
    started=time.perf_counter()
    if not np.isfinite(fit_seconds) or fit_seconds < 0:
        raise ValueError('fit seconds must be finite and nonnegative')
    if output.exists():raise FileExistsError(output)
    with np.load(original) as z:base={k:z[k].copy() for k in z.files}
    with np.load(candidate) as z:trial={k:z[k].copy() for k in z.files}
    base['names']=list(base['names'].astype(str));trial['names']=list(trial['names'].astype(str))
    validate_invariants(base,trial,weapon_regions=('weapon',))
    corpus=json.loads(corpus_path.read_text())
    registration_path = Path(registration) if registration else None
    if registration_path is not None:
        previous=json.loads((registration_path/'pilot_report.json').read_text())
        if previous.get('asset') != corpus.get('unit') or previous.get('kind') != 'idle_registration_only':
            raise ValueError('registration asset or kind does not match corpus')
        inputs=previous.get('inputs', {})
        if inputs.get('researchSkin') != sha256_file(original):
            raise ValueError('registration research skin differs from original')
        calibration_path=Path(inputs.get('calibrationPath',''))
        if not calibration_path.is_file() or sha256_file(calibration_path) != inputs.get('calibration'):
            raise ValueError('registration calibration is missing or changed')
        calibration=json.loads(calibration_path.read_text())
        reference=np.asarray(calibration['referencePositions'],dtype=np.float64)
        hubs=tuple(get_profile(corpus['unit'])['wholeBodyHubs'])
        if camera_path.resolve() != (registration_path/'camera.json').resolve():
            raise ValueError('explicit camera must be owned by the supplied registration')
        camera=expand_camera_to_full_canvas(json.loads(camera_path.read_text()),224)
    elif corpus.get('motionRepresentation') != 'fixed_composed_fk_v1':
        raise ValueError('position corpus comparison requires --registration')
    else:
        camera=json.loads(camera_path.read_text())
    data={};report={'motionOwner':'identical calibrated motion across compared skins; no new capture or pose fit','candidateSha256':sha256_file(candidate),'originalSha256':sha256_file(original),'corpusSha256':sha256_file(corpus_path),'cameraSha256':sha256_file(camera_path),'cases':{}}
    selected={e['key'] for e in corpus['captures']} if all_clips else {'g00_move','g02_idle','g12_attack_front'}
    if not selected:
        raise ValueError('empty comparison inventory')
    for e in corpus['captures']:
        if e['key'] not in selected:continue
        if e['key'] in data:
            raise ValueError('duplicate comparison clip')
        for path in e['frames']:
            if sha256_file(Path(path)) != corpus['sourceFrames'][path]['sha256']:
                raise ValueError('source frame changed')
        if sha256_file(Path(e['capture']))!=e['captureSha256']:raise ValueError('fixed motion changed')
        with np.load(e['capture']) as raw:
            if registration_path is not None:
                motion=load_motion(raw,e,corpus,base,reference,hubs)
            elif corpus.get('motionRepresentation') == 'fixed_composed_fk_v1':
                motion=load_motion(raw,e,corpus,base,raw['pred_position'][0],())
            else:
                raise ValueError('position corpus comparison requires --registration')
        data[e['key']]=(e,motion)
        report['cases'][e['key']]={'fixedMotionSha256':digest(motion['jointWorld'])}
    if set(data) != selected:
        raise ValueError('comparison clip inventory is incomplete')
    output.mkdir(parents=True)
    with cascade_batch_lock(ROOT):
        renderer=SkinImageRenderer(base['triangles'],base['uvs'],base['albedo'],camera,224)
        vertices=torch.as_tensor(base['vertices'],device='cuda',dtype=torch.float32)
        surface=SurfaceConstraints(base['vertices'],base['triangles'],device='cuda')
        weights=[torch.as_tensor(s['weights'],device='cuda',dtype=torch.float32) for s in (base,trial)]
        if fit_seconds:
            from topology_weight_field import TopologyWeightField
            from motion_retention_floor import RegionMotionFloor
            from skin_mesh_field import MeshField
            from run_skin_mesh_pilot import optimize
            field=TopologyWeightField(base['vertices'],base['triangles'],trial['weights'],
                np.flatnonzero(np.asarray(base['regions'])=='weapon'),device='cuda')
            mesh_field=MeshField(base['vertices'],base['regions'],set(base['regions']),device='cuda')
            packed=[];target_batches=[];clip_slices={};cursor=0
            for key,(entry,motion) in data.items():
                packed.append(motion['jointWorld']@base['inverseBind'][None])
                target_batches.append(source_images([Path(p) for p in entry['frames']],camera['sourceCrop'],224))
                count=len(entry['frames']);clip_slices[key]=(cursor,cursor+count);cursor+=count
            transforms=torch.as_tensor(np.concatenate(packed)[:,:,:3],device='cuda',dtype=torch.float32)
            targets=tuple(torch.cat([batch[i] for batch in target_batches]) for i in range(3))
            baseline=deform(transforms,weights[0],vertices).detach()
            floor=RegionMotionFloor(baseline,base['regions'],clip_slices,fraction=.9,
                min_range=float(np.linalg.norm(np.ptp(base['vertices'],axis=0)))*.005)
            before_fit=time.perf_counter()
            history=optimize(field,mesh_field,transforms,surface,renderer,torch.arange(cursor,device='cuda'),targets,
                renderer.render(vertices[None]),tuple(x[:1] for x in targets),iterations=200,
                deadline=before_fit+fit_seconds,allow_mesh=False,motion_floor=floor)
            learned=field.weights().detach()
            fitted=dict(trial);fitted['weights']=learned.cpu().numpy()
            validate_invariants(base,fitted,weapon_regions=('weapon',))
            np.savez_compressed(output/'fitted_skin.npz',**fitted)
            report['fit']={'method':'fixed-support topology weight optimization','history':history,
                'trainingScope':'all selected frames; not heldout','elapsedSeconds':time.perf_counter()-before_fit,
                'fittedSkinSha256':sha256_file(output/'fitted_skin.npz'),
                'motionFloor':floor.report(deform(transforms,learned,vertices))}
            weights.append(learned)
        for key,(entry,motion) in data.items():
            transforms=torch.as_tensor((motion['jointWorld']@base['inverseBind'][None])[:,:,:3],device='cuda',dtype=torch.float32)
            meshes=[deform(transforms,w,vertices) for w in weights]
            report['cases'][key]['surfaceBeforeAfter'] = [surface.metrics(x) for x in meshes]
            report['cases'][key]['motionRetention'] = _motion_retention(meshes[0],meshes[-1],base['regions'])
            source=source_images([Path(p) for p in entry['frames']],camera['sourceCrop'],224)[0]
            titles=['Source','Previous owned skin','Topology weights']+(['Fitted topology weights'] if fit_seconds else [])
            comparison(output/(key+'.gif'),[source]+[renderer.render(mesh)[0] for mesh in meshes],titles,key+'; identical motion')
            print(str(output/(key+'.gif')),flush=True)
    report['elapsedSecondsIncludingPreview']=time.perf_counter()-started
    (output/'comparison.json').write_text(json.dumps(report,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('original','candidate','corpus','camera','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--registration',type=Path)
    p.add_argument('--all-clips',action='store_true')
    p.add_argument('--fit-seconds',type=float,default=0)
    a=p.parse_args();run(a.original,a.candidate,a.corpus,a.camera,a.output,a.registration,a.all_clips,a.fit_seconds)
