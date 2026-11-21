"""生产Gerber离线连通分析；结果是图纸证据，不代替实物通断测量。"""
import sys
from pathlib import Path
import math
import json
import warnings
from collections import Counter
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'.tools/cam-python'))
sys.stdout.reconfigure(encoding='utf-8')
from gerbonara.rs274x import GerberFile
from gerbonara.utils import MM
from shapely.geometry import Point, LineString, Polygon, box
from shapely.ops import unary_union
from shapely import affinity
from shapely import to_wkb, from_wkb
from PIL import Image, ImageDraw
CAM = ROOT/'build/cam-review/cam-LQ-WIFI-加大螺丝孔20260919'
OUT = ROOT/'build/cam-review'

def arc_points(x1,y1,x2,y2,cx,cy,clockwise):
    r=math.hypot(x1-cx,y1-cy)
    start=math.atan2(y1-cy,x1-cx)
    end=math.atan2(y2-cy,x2-cx)
    angle=(start-end)%(2*math.pi) if clockwise else (end-start)%(2*math.pi)
    if math.isclose(angle,0,abs_tol=1e-8): angle=2*math.pi
    count=max(8,math.ceil(angle*r/0.025))
    delta=-angle if clockwise else angle
    return [(cx+r*math.cos(start+delta*i/count),cy+r*math.sin(start+delta*i/count)) for i in range(count+1)]

def primitive_shape(p):
    kind=type(p).__name__
    if kind=='Circle': return Point(p.x,p.y).buffer(p.r,resolution=24)
    if kind=='Line': return LineString([(p.x1,p.y1),(p.x2,p.y2)]).buffer(p.width/2,resolution=16)
    if kind=='Rectangle':
        return affinity.rotate(box(p.x-p.w/2,p.y-p.h/2,p.x+p.w/2,p.y+p.h/2),p.rotation,use_radians=True,origin=(p.x,p.y))
    if kind=='ArcPoly':
        points=[]
        for (x1,y1),(x2,y2),arc in p.segments:
            if arc:
                clockwise,(cx,cy)=arc
                points.extend(arc_points(x1,y1,x2,y2,cx,cy,clockwise)[:-1])
            else: points.append((x1,y1))
        return Polygon(points).buffer(0)
    raise ValueError('Unhandled primitive '+kind)

layers=[]
files=[]
for number in (1,2):
    # PADS采用模态D操作码，解析器能读但会逐行警告；记录数量与样例，避免刷屏。
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        file=GerberFile.open(CAM/('art%03d.pho'%number))
    print('LAYER',number,'parser_warnings',len(caught),'sample',str(caught[0].message)[:140] if caught else None,flush=True)
    files.append(file)
    cache=OUT/('copper-%d.wkb'%number)
    if cache.exists():
        geom=from_wkb(cache.read_bytes())
    else:
        groups=[]
        result=Polygon()
        polarity=True
        for obj in file.objects:
            conv=obj.converted(MM)
            if obj.polarity_dark != polarity:
                area=unary_union(groups)
                result=result.union(area) if polarity else result.difference(area)
                groups=[]
                polarity=obj.polarity_dark
            if type(obj).__name__=='Arc':
                # graphic_objects的弧心相对起点；此版本的primitive转换没有加起点。
                pts=arc_points(conv.x1,conv.y1,conv.x2,conv.y2,
                               conv.x1+conv.cx,conv.y1+conv.cy,conv.clockwise)
                shape=LineString(pts).buffer(conv.aperture.equivalent_width(MM)/2,resolution=16)
                groups.append(shape)
            else:
                for p in obj.to_primitives(MM):
                    shape=primitive_shape(p)
                    # 开孔flash使用相反极性的primitive；按当前对象内部顺序处理。
                    if p.polarity_dark==obj.polarity_dark: groups.append(shape)
                    else:
                        area=unary_union(groups).difference(shape)
                        groups=[area]
        area=unary_union(groups)
        result=result.union(area) if polarity else result.difference(area)
        # 亚微米级接触误差只作绘图数值容差，不跨越常规0.2mm以上间距。
        geom=result.buffer(0.0005).buffer(-0.0005)
        cache.write_bytes(to_wkb(geom))
    polygons=list(geom.geoms) if geom.geom_type=='MultiPolygon' else [geom]
    print('CONNECTED_COPPER',number,len(polygons),flush=True)
    layers.append(polygons)

nodes=[(side,i) for side,polys in enumerate(layers) for i in range(len(polys))]
parents={p:p for p in nodes}
def find(p):
    while parents[p]!=p:
        parents[p]=parents[parents[p]]
        p=parents[p]
    return p
def join(a,b): parents[find(a)]=find(b)
def locate(side,x,y):
    p=Point(x,y)
    return [(side,i) for i,g in enumerate(layers[side]) if g.distance(p)<0.003]

# 本包钻孔为inch、2.4位、尾零省略，先用明确格式读取；钻孔连接仅在双面均有铜时成立。
x=y=None
holes=[]
import re
for line in (CAM/'drl001.drl').read_text().splitlines():
    if line.startswith('X') or line.startswith('Y'):
        xx=re.search(r'X([+-]?\d+)',line); yy=re.search(r'Y([+-]?\d+)',line)
        if xx: x=float(xx[1].ljust(6,'0'))/10000*25.4
        if yy: y=float(yy[1].ljust(6,'0'))/10000*25.4
        if x is not None and y is not None:
            holes.append((x,y))
            near=locate(0,x,y)+locate(1,x,y)
            for n in near[1:]: join(near[0],n)

def net(side,x,y): return sorted(set(find(n) for n in locate(side,x,y)))

# 48个LQFP焊盘直接来自生产层尺寸0.25x1mm；按贴片图1脚标记建立编号。
flashes=[o.converted(MM) for o in files[1].objects if type(o).__name__=='Flash']
mcu=[o for o in flashes if o.aperture.original_number in (91,92)]
assert len(mcu)==48
left=min(o.x for o in mcu); right=max(o.x for o in mcu)
bottom=min(o.y for o in mcu); top=max(o.y for o in mcu)
ordered=(sorted([o for o in mcu if abs(o.y-bottom)<0.01],key=lambda o:-o.x)+
         sorted([o for o in mcu if abs(o.x-left)<0.01],key=lambda o:o.y)+
         sorted([o for o in mcu if abs(o.y-top)<0.01],key=lambda o:o.x)+
         sorted([o for o in mcu if abs(o.x-right)<0.01],key=lambda o:-o.y))
pins={str(i+1):{'x':o.x,'y':o.y,'net':net(1,o.x,o.y)} for i,o in enumerate(ordered)}
switches=[o.converted(MM) for o in files[0].objects if type(o).__name__=='Flash' and o.aperture.original_number==237]
result={'mcu_pins':pins,'switch_pads':[],'driver_pads':[],'warning':'production CAM inferred connectivity; verify against board'}
for o in switches:
    n=net(0,o.x,o.y)
    shared=[pin for pin,data in pins.items() if set(map(tuple,data['net'])) & set(n)]
    row={'x':round(o.x,4),'y':round(o.y,4),'net':n,'mcu_pins':shared}
    result['switch_pads'].append(row)
    print('SW_PAD',row,flush=True)
for o in flashes:
    if 27<o.x<40 and 51<o.y<61:
        n=net(1,o.x,o.y)
        shared=[pin for pin,data in pins.items() if set(map(tuple,data['net'])) & set(n)]
        row={'x':round(o.x,4),'y':round(o.y,4),'aperture':o.aperture.original_number,'net':n,'mcu_pins':shared}
        result['driver_pads'].append(row)
        print('DRIVER_AREA',row,flush=True)
(OUT/'connectivity.json').write_text(json.dumps(result,indent=2),encoding='utf-8')

# 用贴片图隐藏的逐焊盘标签交叉定位元件。背面图为镜像，不能直接按屏幕左右编号。
import fitz
pdf=fitz.open(ROOT/'docs/reference/贴片图-LQ-WiFi_红外20260921更新贴片图.pdf')
components={}
scale_pdf=0.5/(328.57537841796875-325.56494140625)
for word in pdf[1].get_text('words'):
    match=re.fullmatch(r'([A-Z]+\d+)x(\d+)',word[4])
    if match:
        name,pin=match.groups()
        x=131.806-scale_pdf*(word[0]+word[2])/2
        y=100.723-scale_pdf*(word[1]+word[3])/2
        nearest=min(flashes,key=lambda o:math.hypot(o.x-x,o.y-y))
        error=math.hypot(nearest.x-x,nearest.y-y)
        if error<0.15:
            nn=net(1,nearest.x,nearest.y)
            shared=[p for p,d in pins.items() if set(map(tuple,d['net'])) & set(nn)]
            components.setdefault(name,{})[pin]={'x':nearest.x,'y':nearest.y,'net':nn,'mcu_pins':shared,'position_error_mm':error}
for name in ('R9','R15','U5','SP2'):
    print('COMPONENT',name,components.get(name),flush=True)
for pin in ('1','2'):
    target=set(components['U5'][pin]['net'])
    for name,pads in components.items():
        if name.startswith('R') and any(target & set(p['net']) for p in pads.values()):
            print('DRIVER_INPUT_SERIES',pin,name,pads,flush=True)
result['components']=components
# 电源地及串口与既有实测作交叉核对，防止镜像/编号错误被误用为GPIO结果。
assert all('17' in p['mcu_pins'] for p in result['switch_pads'] if p['y']<31)
for pin in ('19','20'):
    assert any(set(map(tuple,pins[pin]['net'])) & set(p['net']) for p in components['SP2'].values())
(OUT/'connectivity.json').write_text(json.dumps(result,indent=2),encoding='utf-8')

# 画生产铜层与引脚标记，供独立目视检查映射及连通算法。
for side,polys in enumerate(layers):
    scale=25
    image=Image.new('RGB',(2600,1350),'white'); draw=ImageDraw.Draw(image)
    xy=lambda pt:((pt[0]-24)*scale,(77-pt[1])*scale)
    for p in polys:
        draw.polygon([xy(c) for c in p.exterior.coords],fill='#49746a')
        for ring in p.interiors: draw.polygon([xy(c) for c in ring.coords],fill='white')
    for pin,d in pins.items():
        if side==1:
            px,py=xy((d['x'],d['y'])); draw.ellipse((px-2,py-2,px+2,py+2),fill='red'); draw.text((px+3,py-7),pin,fill='black')
    image.save(OUT/('copper-layer-%s.png'%side))
print('SAVED',OUT/'connectivity.json',flush=True)
