"""Screened harmonic skin weights on exact-weld surface topology.

This is an explicit candidate preparation method, not a repair fallback. It
changes only weights. Original labels remain evidence, not hard discontinuous
support barriers. The original rigid weapon owner is a Dirichlet constraint.
"""
from pathlib import Path
import argparse
import json
import time
import numpy as np
from scipy.sparse import coo_matrix, diags
from scipy.sparse.linalg import splu
from scipy.sparse.csgraph import connected_components
from pin import sha256_file
from ownership_candidate_validation import validate_invariants


def solve(vertices, triangles, original, rigid_rows, prior_strength):
    if not np.isfinite(prior_strength) or prior_strength <= 0:
        raise ValueError('prior strength must be positive and finite')
    unique, inverse = np.unique(vertices, axis=0, return_inverse=True)
    count = len(unique)
    welded_faces = inverse[triangles]
    edges = np.concatenate([welded_faces[:,[0,1]], welded_faces[:,[1,2]], welded_faces[:,[2,0]]])
    edges = np.unique(np.sort(edges,axis=1),axis=0)
    edges = edges[edges[:,0]!=edges[:,1]]
    length = np.linalg.norm(unique[edges[:,0]]-unique[edges[:,1]],axis=1)
    if not len(length) or np.any(length <= 0): raise ValueError('invalid welded edges')
    # Symmetric inverse-length conductance penalizes abrupt weights most strongly
    # across short edges, where small motion differences cause the worst strain.
    conductance = 1/length
    rows=np.concatenate([edges[:,0],edges[:,1]]);cols=np.concatenate([edges[:,1],edges[:,0]])
    adjacency=coo_matrix((np.tile(conductance,2),(rows,cols)),shape=(count,count)).tocsr()
    degree=np.asarray(adjacency.sum(axis=1)).ravel()
    if np.any(degree<=0):raise ValueError('isolated surface vertices need authored ownership')
    prior=np.zeros((count,original.shape[1]))
    np.add.at(prior,inverse,original)
    prior/=np.bincount(inverse)[:,None]
    fixed_nodes=np.unique(inverse[np.asarray(rigid_rows,dtype=int)])
    fixed=np.zeros_like(prior)
    for node in fixed_nodes:
        source=original[np.asarray(rigid_rows)[inverse[rigid_rows]==node]]
        if not np.allclose(source,source[0],atol=1e-12) or np.count_nonzero(source[0])!=1:
            raise ValueError('conflicting rigid ownership at coincident surface position')
        fixed[node]=source[0]
    free=np.setdiff1d(np.arange(count),fixed_nodes)
    matrix=diags(degree*(1+prior_strength))-adjacency
    rhs=prior_strength*degree[:,None]*prior
    rhs_free=rhs[free]-matrix.tocsr()[free][:,fixed_nodes]@fixed[fixed_nodes]
    result=fixed.copy()
    result[free]=splu(matrix.tocsc()[free][:,free]).solve(rhs_free)
    if np.any(result < -1e-10) or not np.isfinite(result).all():raise ValueError('harmonic solve violated positive weights')
    result=np.maximum(result,0)
    result/=result.sum(axis=1,keepdims=True)
    # Export support is an explicit measured projection, never silent truncation.
    order=np.argsort(-result,axis=1)[:,:8]
    sparse=np.zeros_like(result);np.put_along_axis(sparse,order,np.take_along_axis(result,order,axis=1),axis=1)
    dropped=1-sparse.sum(axis=1)
    sparse/=sparse.sum(axis=1,keepdims=True)
    return sparse[inverse],{'uniqueSurfacePositions':count,'originalVertices':len(vertices),
        'surfaceComponents':int(connected_components(adjacency,directed=False,return_labels=False)),
        'edgeCount':len(edges),'rigidSurfacePositions':len(fixed_nodes),'priorStrength':prior_strength,
        'supportProjectionMaxDroppedMass':float(dropped.max()),'supportProjectionMeanDroppedMass':float(dropped.mean())}


def run(source,output,strength):
    if output.exists():raise FileExistsError(output)
    started=time.perf_counter()
    with np.load(source,allow_pickle=False) as raw:skin={k:raw[k].copy() for k in raw.files}
    candidate=dict(skin)
    rigid=np.flatnonzero(skin['regions'].astype(str)=='weapon')
    candidate['weights'],report=solve(skin['vertices'],skin['triangles'],skin['weights'],rigid,strength)
    report['invariants']=validate_invariants(skin,candidate,weapon_regions=('weapon',))
    output.mkdir(parents=True)
    dest=output/'research_skin.npz';np.savez(dest,**candidate)
    report.update(source=str(source.resolve()),sourceSha256=sha256_file(source),candidate=str(dest.resolve()),
        candidateSha256=sha256_file(dest),method='exact_weld_screened_harmonic_weights',proof='generated_candidate',
        originalRegionsArePriorLabels=True,profileSupportContract='not compatible with old per-region hard support; not promoted',
        elapsedSeconds=time.perf_counter()-started)
    (output/'preparation_report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--prior-strength',type=float,default=.05)
    a=p.parse_args();run(a.source,a.output,a.prior_strength)
