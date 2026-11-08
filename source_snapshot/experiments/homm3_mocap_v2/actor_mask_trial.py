"""Exact complementary actor masks from explicit, versioned sprite polygons."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from pin import sha256_file

KEYS = ("g02_idle", "g00_move", "g12_attack_front")

def partition(raw, mask):
    if raw.ndim != 3 or raw.shape[2] != 4 or mask.shape != raw.shape[:2] or mask.dtype != bool:
        raise ValueError('RGBA and boolean ownership dimensions disagree')
    rider=raw.copy();mount=raw.copy()
    rider[:,:,3]=np.where(mask,raw[:,:,3],0);mount[:,:,3]=np.where(mask,0,raw[:,:,3])
    if not np.array_equal(rider[:,:,3].astype(int)+mount[:,:,3].astype(int),raw[:,:,3]):
        raise ValueError('mask partition failed')
    return mount,rider

def selected(manifest):
    clips = [c for c in manifest["clips"] if c["key"] in KEYS]
    paths = list(dict.fromkeys(Path(f) for c in clips for f in c["contextBefore"]+c["frames"]+c["contextAfter"]))
    return clips, paths

def plate_sheet(manifest_path, output):
    manifest=json.loads(manifest_path.read_text()); clips,paths=selected(manifest)
    paths=sorted(paths,key=lambda p:(p.parent.name,p.name))
    sheet=Image.new("RGB",(350*5,320*((len(paths)+4)//5)),(38,38,38)); draw=ImageDraw.Draw(sheet)
    for i,path in enumerate(paths):
        x=(i%5)*350;y=(i//5)*320
        im=Image.open(path).convert("RGBA");im.thumbnail((350,290))
        sheet.paste(im,(x,y+20),im)
        draw.text((x+4,y+3),path.parent.name+"/"+path.stem,fill="white")
        for xx in (50,100,150,200,250,300):
            draw.line((x+xx,y+20,x+xx,y+310),fill=(55,55,55));draw.text((x+xx,y+308),str(xx),fill="white")
        for yy in (50,100,150,200,250): draw.text((x,y+20+yy),str(yy),fill="white")
    sheet.save(output)

def build(manifest_path,recipe_path,output):
    if output.exists(): raise FileExistsError(output)
    source=json.loads(manifest_path.read_text());clips,paths=selected(source)
    recipe=json.loads(recipe_path.read_text())
    if recipe['coordinateCanvas'] != [350,290]: raise ValueError('unsupported authored coordinate canvas')
    if recipe["sourceManifestSha256"]!=sha256_file(manifest_path): raise ValueError("source manifest changed")
    output.mkdir(parents=True)
    remap={actor:{} for actor in ("mount","rider")};reports=[]
    for path in paths:
        key=path.parent.name+"/"+path.stem
        row=recipe["frames"][key]
        if sha256_file(path)!=row["sha256"]: raise ValueError("authored source frame changed")
        im=Image.open(path).convert("RGBA");raw=np.array(im)
        ownership=Image.new("L",im.size,0);draw=ImageDraw.Draw(ownership)
        sx,sy=im.width/350,im.height/290
        for polygon in row["riderPolygons"]:
            draw.polygon([(x*sx,y*sy) for x,y in polygon],fill=255)
        mask=np.asarray(ownership)>0
        mount,rider=partition(raw,mask)
        for actor,rgba in (("mount",mount),("rider",rider)):
            if not np.any(rgba[:,:,3]): raise ValueError("empty actor mask")
            dest=output/actor/path.parent.name/path.name;dest.parent.mkdir(parents=True,exist_ok=True)
            Image.fromarray(rgba).save(dest);remap[actor][str(path)]=str(dest.resolve())
        reports.append({"key":key,"source":str(path),"sourceSha256":sha256_file(path),"riderPixels":int(np.count_nonzero(rider[:,:,3])),"mountPixels":int(np.count_nonzero(mount[:,:,3]))})
    for actor in ("mount","rider","control"):
        payload=dict(source);payload["clips"]=[];payload["allGroupsIncluded"]=False;payload["frameCount"]=sum(len(c["frames"]) for c in clips)
        mapping=remap[actor] if actor!="control" else {str(p):str(p) for p in paths}
        payload["idle"]=mapping[source["idle"]]
        for clip in clips:
            c=dict(clip)
            for field in ("frames","contextBefore","contextAfter"): c[field]=[mapping[f] for f in c[field]]
            payload["clips"].append(c)
        payload["maskPolicy"]="unchanged RGB and canvas; complementary visible-pixel partition; no hidden anatomy fill" if actor!="control" else "unchanged source control"
        payload['sourceManifestSha256']=sha256_file(manifest_path)
        payload['maskRecipe']=str(recipe_path.resolve());payload['maskRecipeSha256']=sha256_file(recipe_path)
        (output/f"{actor}_manifest.json").write_text(json.dumps(payload,indent=2))
    report={"sourceManifest":str(manifest_path.resolve()),"recipe":str(recipe_path.resolve()),"recipeSha256":sha256_file(recipe_path),"frames":reports,"authoredTargetFrames":sum(len(c["frames"]) for c in clips),"uniqueFramesIncludingContext":len(paths),"visualAcceptance":"unreviewed"}
    (output/"mask_report.json").write_text(json.dumps(report,indent=2))
    # Inspection image uses exactly the generated masks, not a separate drawing.
    frames=[]
    for path in paths:
        row=Image.new("RGB",(1050,290),(38,38,38))
        for j,p in enumerate((path,Path(remap['mount'][str(path)]),Path(remap['rider'][str(path)]))):
            im=Image.open(p).convert("RGBA").resize((350,290),Image.Resampling.NEAREST);row.paste(im,(350*j,0),im)
        ImageDraw.Draw(row).text((4,4),path.parent.name+'/'+path.stem,fill='white');frames.append(row)
    frames[0].save(output/"mask_review.gif",save_all=True,append_images=frames[1:],duration=350,loop=0)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--recipe',type=Path)
    a=p.parse_args()
    if a.recipe: print(json.dumps(build(a.manifest,a.recipe,a.output)))
    else: plate_sheet(a.manifest,a.output)
