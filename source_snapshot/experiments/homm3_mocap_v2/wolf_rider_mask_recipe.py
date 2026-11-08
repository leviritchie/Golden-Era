"""Eye-authored visible actor outlines on the 350x290 inspection canvas.

No occluded pixels are synthesized. Polygons include transparent margins;
the actual segmentation is intersected with the original source alpha.
"""
import json
from pathlib import Path
from actor_mask_trial import selected
from pin import sha256_file

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'artifacts/homm3_mocap_v2/skin_mesh_pilot/wolf_rider/corpus_v1/manifest.json'
IDLE=[(122,85),(181,82),(198,126),(182,145),(171,155),(163,169),(161,187),(155,199),(165,208),(166,216),(154,215),(145,205),(142,192),(141,177),(136,168),(128,167),(125,153),(119,134)]
MOVE=[(100,94),(176,84),(195,125),(184,144),(169,153),(164,171),(160,189),(154,200),(165,211),(159,217),(149,208),(144,195),(143,181),(144,172),(134,167),(124,168),(120,145),(100,127)]
ATTACK={
 0:IDLE,
 1:[(96,47),(112,55),(120,96),(171,88),(180,116),(190,147),(169,147),(158,164),(157,188),(149,201),(160,210),(154,217),(144,207),(140,188),(139,174),(132,162),(133,145),(104,148),(97,131)],
 2:[(53,28),(127,68),(138,86),(179,77),(194,109),(210,138),(185,143),(190,156),(188,176),(183,184),(185,199),(193,202),(191,212),(177,209),(171,196),(171,181),(172,166),(162,153),(154,145),(147,139),(137,122),(110,119),(100,100),(89,72)],
 3:[(155,88),(244,82),(321,61),(322,83),(270,120),(250,131),(247,156),(231,158),(222,169),(222,188),(216,202),(226,209),(222,218),(209,208),(205,192),(201,178),(188,163),(186,152),(171,150),(174,132),(156,125)],
 4:[(180,93),(247,92),(251,126),(271,143),(339,145),(339,164),(272,168),(258,158),(241,156),(228,159),(221,183),(218,205),(225,211),(222,220),(211,213),(207,199),(207,184),(201,173),(194,156),(182,146),(180,127)],
 5:[(168,91),(224,87),(230,126),(237,144),(216,152),(211,167),(259,185),(267,195),(251,193),(213,181),(200,184),(197,194),(201,203),(191,209),(181,200),(179,186),(176,176),(178,162),(169,155),(168,138)],
 6:[(133,91),(184,85),(194,123),(196,151),(227,155),(228,164),(181,165),(176,175),(170,193),(162,196),(166,205),(156,209),(149,199),(151,181),(149,169),(142,163),(135,161),(131,140)],
}

def build(output):
    if output.exists(): raise FileExistsError(output)
    source=json.loads(SOURCE.read_text());_,paths=selected(source);rows={}
    for p in paths:
        group=p.parent.name;frame=int(p.stem)
        if group=='g12_attack_front': polygon=ATTACK[frame]
        elif group=='g00_move':
            dx,dy=((0,0),(1,1),(2,3),(0,4),(1,2),(0,-1))[frame]
            polygon=[(x+dx,y+dy) for x,y in MOVE]
        elif group in ('g02_idle','g20_move_start','g21_move_end'): polygon=IDLE
        else: raise ValueError('unauthored group '+group)
        rows[group+'/'+p.stem]={'sha256':sha256_file(p),'riderPolygons':[polygon]}
    payload={'method':'eye_authored_visible_actor_polygons','coordinateCanvas':[350,290],
      'sourceManifestSha256':sha256_file(SOURCE),'authoringCodeSha256':sha256_file(Path(__file__)),
      'frames':rows,'temporalPolicy':'shared idle contour; authored movement offsets and strike-specific outlines'}
    output.write_text(json.dumps(payload,indent=2))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);build(p.parse_args().output)
