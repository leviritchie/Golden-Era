import json,sys,os
from PIL import Image,ImageDraw
blend,rdir,out=sys.argv[1:4]
fj=json.load(open(blend+".frames.json"));src=fj['sources'];segs=fj['segments']
C=(95,110,335,300);cw,ch=C[2]-C[0],C[3]-C[1];Z=2;cell=(cw*Z,ch*Z)
frames=[]
for t,sp in enumerate(src):
    a=Image.open(sp).convert('RGBA').crop(C).resize(cell,Image.NEAREST)
    b=Image.open(f"{rdir}/sprite_{t+1:03d}.png").convert('RGBA').crop(C).resize(cell,Image.LANCZOS)
    c=Image.open(f"{rdir}/side_{t+1:03d}.png").convert('RGBA').resize((cell[1],cell[1]))
    im=Image.new('RGB',(cell[0]*2+cell[1],cell[1]),(45,45,45))
    for x,p in [(0,a),(cell[0],b),(2*cell[0],c)]: im.paste(p,(x,0),p)
    dr=ImageDraw.Draw(im);seg=[s for s in segs if s[1]<=t<s[2]][0]
    dr.text((6,6),f"DEF {t:02d} {seg[0]}",fill=(255,255,0));dr.text((cell[0]+6,6),"mesh, sprite camera",fill=(220,220,220));dr.text((2*cell[0]+6,6),"mesh, side",fill=(220,220,220))
    frames.append(im);im.save(f"{rdir}/cmp_{t:03d}.png")
frames[0].save(out,save_all=True,append_images=frames[1:],duration=125,loop=0)
