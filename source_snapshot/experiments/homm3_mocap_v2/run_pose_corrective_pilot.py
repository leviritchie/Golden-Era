"""Fixed-mocap, pose-conditioned mesh diagnostic; no delivery or all-frame refit."""
from __future__ import annotations
import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from corpus_motion import load_motion
from pose_corrective_field import PoseCorrectiveField
from run_skin_mesh_pilot import expand_camera_to_full_canvas, comparison, _training_regions, validate_capture_indices
from run_skin_weight_pilot import (ROOT, HERE, _load_frozen_prep, get_profile,
    sha256_file, digest, source_images, SkinImageRenderer, image_loss, image_metrics, cascade_batch_lock)
from skin_surface_constraints import SurfaceConstraints
from run_eagle_reference_capture_comparison import verify_source_identity
from fitted_corrective_base import load_fitted_base


def split_frames(lengths):
    if 'g11_attack_up' not in lengths or 'g02_idle' not in lengths:
        raise ValueError('pilot requires upward attack and idle groups')
    train, held, slices, cursor = [], [], {}, 0
    for key,n in lengths.items():
        if type(n) is not int or n < 1:
            raise ValueError('clip length must be a positive integer')
        slices[key] = slice(cursor,cursor+n)
        for i in range(n):
            (held if key == 'g11_attack_up' or i % 3 == 1 else train).append(cursor+i)
        cursor += n
    if not train or not held:
        raise ValueError('empty training or heldout split')
    return train,held,slices


def checkpoint_improves(metrics, best_image, initial):
    if not all(np.isfinite(value) for value in (*metrics.values(), best_image, *initial.values())):
        raise ValueError('checkpoint metrics must be finite')
    return (metrics['image'] < best_image - 1e-6
        and metrics['surface'] <= initial['surface'] + 1e-6
        and metrics['idle'] <= initial['idle'] + 1e-6)


def run(asset,baseline_dir,corpus_path,output,seconds=300,iterations=150,*,base_fit=None,
        residual_energy=None,warm_start=None):
    started = time.perf_counter()
    if output.exists():
        raise FileExistsError('output must be absent')
    if not 0 < seconds <= 300 or iterations < 1:
        raise ValueError('requires positive budget at most 300 seconds and positive iterations')
    if residual_energy is not None and warm_start is None:
        raise ValueError('residual comparison requires explicit four-mode warm start')
    if warm_start is not None and base_fit is None:
        raise ValueError('warm start requires explicit fitted base')
    profile = get_profile(asset)
    freeze,skin = _load_frozen_prep(asset)
    previous = json.loads((baseline_dir/'pilot_report.json').read_text())
    if sha256_file(Path(freeze['researchSkin'])) != previous['inputs']['researchSkin']:
        raise ValueError('preparation differs from camera registration')
    calibration_path = Path(previous['inputs']['calibrationPath'])
    if sha256_file(calibration_path) != previous['inputs']['calibration']:
        raise ValueError('calibration drift')
    reference = np.asarray(json.loads(calibration_path.read_text())['referencePositions'])
    corpus = json.loads(corpus_path.read_text())
    if corpus['unit'] != asset:
        raise ValueError('corpus unit differs')
    camera = expand_camera_to_full_canvas(json.loads((baseline_dir/'camera.json').read_text()),224)
    motions,paths = {},{}
    inputs = {str(p.resolve()):sha256_file(p) for p in
        (corpus_path,calibration_path,baseline_dir/'camera.json',baseline_dir/'pilot_report.json',Path(freeze['researchSkin']))}
    for row in corpus['captures']:
        key = row['key']
        if key in motions:
            raise ValueError('duplicate clip')
        verify_source_identity(corpus,row)
        p = Path(row['capture']); inputs[str(p.resolve())] = sha256_file(p)
        if inputs[str(p.resolve())] != row['captureSha256']:
            raise ValueError('capture drift')
        with np.load(p,allow_pickle=False) as raw:
            validate_capture_indices(row,len(raw['pred_position']))
            if list(raw['joint_names'].astype(str)) != list(skin['names']) or not np.array_equal(raw['parents'],skin['parents']):
                raise ValueError('capture skeleton differs from preparation')
            motions[key] = load_motion(raw,row,corpus,skin,reference,profile['wholeBodyHubs'])
        if not np.array_equal(motions[key]['captureRest'],reference):
            raise ValueError('motion did not preserve single reference')
        paths[key] = list(map(Path,row['frames']))
    train,held,slices = split_frames({k:len(v) for k,v in paths.items()})
    motion_hashes = {k:digest(m['jointWorld']) for k,m in motions.items()}
    base_provenance = None
    if base_fit is not None:
        skin,base_provenance = load_fitted_base(base_fit,asset,skin,motion_hashes,
            sha256_file(corpus_path),sha256_file(Path(freeze['researchSkin'])))
        for name in ('report.json','diagnostic_candidate.npz'):
            p=base_fit/name; inputs[str(p.resolve())]=sha256_file(p)
    local_np = np.concatenate([m['localRotation'] for m in motions.values()])
    neutral = np.repeat(np.eye(3)[None],len(skin['names']),axis=0)
    frozen = tuple(sorted(set(skin['regions'])-set(_training_regions(asset,skin))))
    output.mkdir(parents=True)
    report = dict(asset=asset,accepted=False,proof='diagnostic mesh sequences; no exported animation',
        inputs=inputs,trainIndices=train,heldoutIndices=held,wholeHeldoutClip='g11_attack_up',
        fixedMotionHashes=motion_hashes,baseFit=base_provenance,
        evaluationScope=('images withheld from incremental corrective fit only; base was fitted on all frames'
            if base_fit is not None else 'images withheld from corrective fit; prepared baseline'),
        baseWeightsHash=digest(skin['weights']),baseVerticesHash=digest(skin['vertices']),
        secondsBudget=seconds,modeCount=4,frozenRegions=list(frozen),camera=camera,history=[],cases={})
    with cascade_batch_lock(ROOT):
        field_type = PoseCorrectiveField
        extra_options = {}
        if residual_energy is not None:
            from residual_pose_corrective_field import ResidualPoseCorrectiveField
            field_type = ResidualPoseCorrectiveField
            extra_options['target_energy'] = residual_energy
            report['residualFeatureEnergy'] = residual_energy
        field = field_type(skin['vertices'],skin['regions'],local_np[train],neutral,
            frozen_regions=frozen,max_displacement_fraction=.10,grid_resolution=4,device='cuda',**extra_options)
        report['modeCount'] = len(field.modes)
        warm_saved = None
        if warm_start is not None:
            warm_paths = {name:warm_start/name for name in ('report.json','corrective_field.pt','candidate_meshes.npz')}
            previous_corrective = json.loads(warm_paths['report.json'].read_text())
            if (previous_corrective['asset'] != asset or previous_corrective['modeCount'] != 4
                or previous_corrective['baseFit'] != base_provenance
                or previous_corrective['fixedMotionHashes'] != motion_hashes
                or previous_corrective['trainIndices'] != train or previous_corrective['heldoutIndices'] != held):
                raise ValueError('warm start must be the exact four-mode fitted-base comparison')
            state = torch.load(warm_paths['corrective_field.pt'],map_location='cuda',weights_only=True)
            if residual_energy is not None:
                field.load_four_mode_state(state)
            else:
                for key,value in field.state_dict().items():
                    if not key.endswith('.control') and not torch.equal(value,state[key]):
                        raise ValueError(f'warm start static field differs: {key}')
                field.load_state_dict(state,strict=True)
            with np.load(warm_paths['candidate_meshes.npz'],allow_pickle=False) as saved:
                warm_saved = saved['candidate'].copy()
            report['warmStart'] = dict(reportPath=str(warm_paths['report.json'].resolve()),
                reportSha256=sha256_file(warm_paths['report.json']),
                statePath=str(warm_paths['corrective_field.pt'].resolve()),
                stateSha256=sha256_file(warm_paths['corrective_field.pt']),
                meshesPath=str(warm_paths['candidate_meshes.npz'].resolve()),
                meshesSha256=sha256_file(warm_paths['candidate_meshes.npz']),candidateSha256=digest(warm_saved))
            for path in warm_paths.values():
                inputs[str(path.resolve())] = sha256_file(path)
            report['checkpointPolicy'] = 'image_best_without_surface_or_idle_regression'
        local = torch.as_tensor(local_np,device='cuda',dtype=torch.float32)
        neutral_t = torch.as_tensor(neutral[None],device='cuda',dtype=torch.float32)
        rest = torch.as_tensor(skin['vertices'],device='cuda',dtype=torch.float32)
        weights = torch.as_tensor(skin['weights'],device='cuda',dtype=torch.float32)
        transforms = torch.as_tensor(np.concatenate([(m['jointWorld']@skin['inverseBind'][None])[:,:,:3]
            for m in motions.values()]),device='cuda',dtype=torch.float32)
        f,j = transforms.shape[:2]
        blended = (<email>(1,0,2,3).reshape(j,-1)).reshape(len(rest),f,3,4).permute(1,0,2,3).detach()
        baseline = torch.einsum('fvkl,vl->fvk',blended,torch.cat((rest,torch.ones_like(rest[:,:1])),1)).detach()
        def animated():
            return baseline + torch.einsum('fvkl,fvl->fvk',blended[:,:,:,:3],field.displacement(local))
        renderer = SkinImageRenderer(skin['triangles'],skin['uvs'],skin['albedo'],camera,224)
        surface = SurfaceConstraints(skin['vertices'],skin['triangles'],device='cuda')
        targets = {k:source_images(v,camera['sourceCrop'],224) for k,v in paths.items()}
        all_targets = tuple(torch.cat([t[c] for t in targets.values()]) for c in range(3))
        train_targets = tuple(t[train] for t in all_targets)
        with torch.no_grad():
            idle_before = renderer.render(baseline[slices['g02_idle']])
            baseline_surface = surface.metrics(baseline)
            warm_candidate = animated().detach().clone()
            if warm_saved is not None and (warm_saved.shape != tuple(warm_candidate.shape)
                or not np.allclose(warm_candidate.cpu().numpy(),warm_saved,rtol=0,atol=1e-6)):
                raise ValueError('warm start candidate does not reproduce saved four-mode mesh')
            if warm_start is not None:
                warm_idle = renderer.render(warm_candidate[slices['g02_idle']])
                report['warmStartMetrics'] = dict(
                    image=float(image_loss(*renderer.render(warm_candidate[train]),*train_targets)['total']),
                    surface=float(surface.loss(warm_candidate)),
                    idle=float(sum((a-b).abs().mean() for a,b in zip(warm_idle,idle_before))))
        optimizer = torch.optim.Adam(field.parameters(),lr=.035)
        best,best_state = float('inf'),None
        if warm_start is not None:
            best = report['warmStartMetrics']['image']
            best_state = {k:v.detach().clone() for k,v in field.state_dict().items()}
            report['selectedMetrics'] = dict(report['warmStartMetrics'])
        completed_steps = 0
        deadline = time.perf_counter()+seconds
        fit_started = time.perf_counter()
        for step in range(iterations):
            if time.perf_counter() >= deadline:
                break
            optimizer.zero_grad(set_to_none=True)
            candidate = animated()
            photo = image_loss(*renderer.render(candidate[train]),*train_targets)['total']
            geometry = surface.loss(candidate)
            idle_now = renderer.render(candidate[slices['g02_idle']])
            idle = sum((a-b).abs().mean() for a,b in zip(idle_now,idle_before))
            objective = 10*photo+3*geometry+40*idle+2*field.penalty()
            if not torch.isfinite(objective):
                raise ValueError('nonfinite fitting objective')
            score = float(objective.detach())
            eligible = score < best
            selection_score = score
            if warm_start is not None:
                selection_score = float(photo.detach())
                limits = report['warmStartMetrics']
                eligible = checkpoint_improves(dict(image=selection_score,
                    surface=float(geometry.detach()),idle=float(idle.detach())),best,limits)
            if eligible:
                best = selection_score
                best_state = {k:v.detach().clone() for k,v in field.state_dict().items()}
                if warm_start is not None:
                    report['selectedMetrics'] = dict(image=selection_score,
                        surface=float(geometry.detach()),idle=float(idle.detach()))
            objective.backward()
            torch.nn.utils.clip_grad_norm_(field.parameters(),2)
            optimizer.step()
            completed_steps += 1
            if step%20 == 0:
                row = dict(step=step,objective=score,image=float(photo.detach()),surface=float(geometry.detach()),idleDifference=float(idle.detach()))
                report['history'].append(row); print(json.dumps(row),flush=True)
        if best_state is None:
            raise TimeoutError('no optimization step completed')
        field.load_state_dict(best_state)
        if warm_start is not None:
            report['feasibleImprovement'] = report['selectedMetrics']['image'] < report['warmStartMetrics']['image'] - 1e-6
        report['fitSeconds'] = time.perf_counter()-fit_started
        report['steps'] = completed_steps
        with torch.no_grad():
            candidate = animated().detach()
            delta = field.displacement(local)
            neutral_delta = field.displacement(neutral_t)
            if not torch.isfinite(candidate).all() or not torch.isfinite(delta).all():
                raise ValueError('nonfinite corrective mesh')
            if float(torch.linalg.vector_norm(delta,dim=-1).max()) > field.max_displacement+1e-6:
                raise ValueError('corrective displacement bound exceeded')
            coefficients=field.coefficients(local)
            if float(coefficients.abs().sum(-1).max()) > 1+1e-6:
                raise ValueError('corrective coefficient bound exceeded')
            frozen_mask=field.modes[0].frozen_mask
            if bool(frozen_mask.any()) and torch.count_nonzero(delta[:,frozen_mask]):
                raise ValueError('frozen geometry received a correction')
            if torch.count_nonzero(neutral_delta):
                raise ValueError('neutral correction must be exactly zero')
            after_surface = surface.metrics(candidate)
            idle_after = renderer.render(candidate[slices['g02_idle']])
            report['idleDifference'] = dict(rgbMeanAbs=float((idle_after[0]-idle_before[0]).abs().mean()),
                alphaMeanAbs=float((idle_after[1]-idle_before[1]).abs().mean()))
            report['neutralMaxDisplacement'] = float(neutral_delta.abs().max())
            report['maxCorrectiveDisplacement'] = float(torch.linalg.vector_norm(delta,dim=-1).max())
            report['maxCoefficientSumAbs'] = float(coefficients.abs().sum(-1).max())
            report['surface'] = dict(baseline=baseline_surface,candidate=after_surface)
            held_scores = []
            for key,selected in slices.items():
                before = renderer.render(baseline[selected]); after = renderer.render(candidate[selected])
                scores = {name:image_metrics(*values,*targets[key][:2]) for name,values in (('baseline',before),('candidate',after))}
                held_local = [i-selected.start for i in held if selected.start<=i<selected.stop]
                report['cases'][key] = dict(scores=scores,heldoutLocalIndices=held_local)
                for i in held_local:
                    held_scores.append((scores['baseline'][i],scores['candidate'][i]))
                columns = [targets[key][0],before[0],after[0]]
                labels = ('Source','Existing fit' if base_fit is not None else 'Fixed baseline','Pose corrective')
                if warm_start is not None:
                    columns = [targets[key][0],renderer.render(warm_candidate[selected])[0],after[0]]
                    labels = ('Source','Previous four-mode','Residual modes' if residual_energy is not None else 'Four-mode continuation')
                comparison(output/(key+'_comparison.gif'),columns,labels,key)
                print(json.dumps({'completedGif':str(output/(key+'_comparison.gif'))}),flush=True)
            report['heldoutMean'] = {name:{metric:float(np.mean([row[index][metric] for row in held_scores]))
                for metric in ('iou','color')} for index,name in enumerate(('baseline','candidate'))}
        torch.save(field.state_dict(),output/'corrective_field.pt')
        np.savez_compressed(output/'candidate_meshes.npz',candidate=candidate.cpu().numpy(),baseline=baseline.cpu().numpy(),localRotation=local_np)
        report['peakCudaAllocatedBytes'] = torch.cuda.max_memory_allocated()
    report['elapsedSecondsCached'] = time.perf_counter()-started
    report['implementationHashes'] = {name:sha256_file(HERE/name) for name in
        ('run_pose_corrective_pilot.py','fitted_corrective_base.py','pose_corrective_field.py','skin_mesh_field.py','skin_surface_constraints.py',
         'skin_image_objective.py','corpus_motion.py','run_skin_mesh_pilot.py','run_skin_weight_pilot.py')}
    if residual_energy is not None:
        report['implementationHashes']['residual_pose_corrective_field.py'] = sha256_file(HERE/'residual_pose_corrective_field.py')
    report['disposition'] = 'unreviewed diagnostic; heldout/surface/idle and delivery remain separate gates'
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--asset',required=True)
    parser.add_argument('--baseline-dir',type=Path,required=True)
    parser.add_argument('--corpus',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seconds',type=float,default=300)
    parser.add_argument('--iterations',type=int,default=150)
    parser.add_argument('--base-fit',type=Path,help='Explicit prior fixed-motion fit; no fallback to prepared baseline')
    parser.add_argument('--residual-energy',type=float,help='Explicit nested residual feature energy target')
    parser.add_argument('--warm-start',type=Path,help='Explicit matching saved four-mode corrective directory')
    args = parser.parse_args()
    r=run(args.asset,args.baseline_dir,args.corpus,args.output,args.seconds,args.iterations,base_fit=args.base_fit,
        residual_energy=args.residual_energy,warm_start=args.warm_start)
    print(json.dumps(dict(heldout=r['heldoutMean'],elapsed=r['elapsedSecondsCached'],fit=r['fitSeconds']),indent=2))
