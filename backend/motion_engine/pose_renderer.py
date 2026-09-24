from __future__ import annotations
from io import BytesIO
from PIL import Image, ImageDraw
from .schema import CanonicalPose, JointName

LIMBS=[(JointName.HEAD,JointName.NECK),(JointName.NECK,JointName.LEFT_SHOULDER),(JointName.NECK,JointName.RIGHT_SHOULDER),
(JointName.LEFT_SHOULDER,JointName.LEFT_ELBOW),(JointName.LEFT_ELBOW,JointName.LEFT_WRIST),(JointName.RIGHT_SHOULDER,JointName.RIGHT_ELBOW),
(JointName.RIGHT_ELBOW,JointName.RIGHT_WRIST),(JointName.NECK,JointName.PELVIS),(JointName.PELVIS,JointName.LEFT_HIP),(JointName.PELVIS,JointName.RIGHT_HIP),
(JointName.LEFT_HIP,JointName.LEFT_KNEE),(JointName.LEFT_KNEE,JointName.LEFT_ANKLE),(JointName.RIGHT_HIP,JointName.RIGHT_KNEE),(JointName.RIGHT_KNEE,JointName.RIGHT_ANKLE)]

def render_pose_png(pose:CanonicalPose,size:tuple[int,int]=(512,512),padding=.08)->bytes:
    w,h=size; visible=list(pose.joints.values())
    if not visible: raise ValueError("Pose has no joints")
    xs=[j.x for j in visible]; ys=[j.y for j in visible]; sx=max(max(xs)-min(xs),1e-6); sy=max(max(ys)-min(ys),1e-6)
    scale=min((w*(1-2*padding))/sx,(h*(1-2*padding))/sy)
    cx=(min(xs)+max(xs))/2; cy=(min(ys)+max(ys))/2
    def pt(j): return (int(w/2+(j.x-cx)*scale),int(h/2+(j.y-cy)*scale))
    im=Image.new("RGB",(w,h),"black"); d=ImageDraw.Draw(im)
    for a,b in LIMBS:
        ja,jb=pose.joint(a),pose.joint(b)
        if ja is not None and jb is not None: d.line([pt(ja),pt(jb)],fill="white",width=max(2,w//128))
    for j in visible:
        x,y=pt(j); r=max(3,w//96); d.ellipse((x-r,y-r,x+r,y+r),fill="white")
    out=BytesIO(); im.save(out,format="PNG"); return out.getvalue()
