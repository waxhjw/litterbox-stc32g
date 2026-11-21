"""按生产CAM还原主板接口图；不虚构长条小板内部电路或小板插座针序。"""
from pathlib import Path
import json
import sys
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'.tools/pdf-python-4'))
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import landscape,A4
from reportlab.lib.colors import HexColor
import fitz

data=json.loads((root/'build/cam-review/connectivity.json').read_text(encoding='utf-8'))
rx=data['components']['CN3']; tx=data['components']['CN7']
assert [rx[str(i)]['mcu_pins'] for i in (2,3,4)]==[['3'],['5'],['6']]
assert [tx[str(i)]['mcu_pins'] for i in (2,3,4)]==[['47'],['48'],['1']]
assert rx['1']['net']==tx['1']['net'] and rx['5']['net']==tx['5']['net']
out=root/'output/pdf'; out.mkdir(parents=True,exist_ok=True)
pdf=out/'IR-array-mainboard-interface-20261111.pdf'
png=out/'IR-array-mainboard-interface-20261111.png'
pdfmetrics.registerFont(TTFont('CN','C:/Windows/Fonts/simhei.ttf'))
c=canvas.Canvas(str(pdf),pagesize=landscape(A4))
c.setTitle('三路对射：生产主板端接口连线图')
W,H=landscape(A4)
ink=HexColor('#152b3d'); blue=HexColor('#2468a0'); red=HexColor('#b42932'); gray=HexColor('#52616e')
def text(x,y,s,size=11,color=ink,center=False):
    c.setFillColor(color); c.setFont('CN',size)
    (c.drawCentredString if center else c.drawString)(x,y,s)
def line(x1,y1,x2,y2,color=ink,width=1.3):
    c.setStrokeColor(color); c.setLineWidth(width); c.line(x1,y1,x2,y2)
def arrow(x1,y1,x2,y2):
    line(x1,y1,x2,y2,blue)
    direction=1 if x2>x1 else -1
    line(x2,y2,x2-6*direction,y2+3,blue); line(x2,y2,x2-6*direction,y2-3,blue)
def node(x,y,color=ink):
    c.setFillColor(color); c.circle(x,y,2.4,fill=1,stroke=0)

text(32,H-39,'三路红外对射 · 主板端接口连线图',22)
text(32,H-59,'依据 2026-09-19 生产CAM与焊盘编号还原  |  2026-11-11',10,gray)
c.setFillColor(HexColor('#fff1ef')); c.roundRect(30,H-104,W-60,31,5,fill=1,stroke=0)
text(43,H-93,'出现发热时：先断开12V与USB，冷却后核对线束两端；不要带电换接。',12,red)

text(130,427,'CN3 · 接收接口',16,center=True)
text(130,410,'本组黑色探头、带三颗8脚芯片的长条',9,gray,True)
text(708,427,'CN7 · 发射控制接口',16,center=True)
text(708,410,'本组透明白色探头长条',9,gray,True)

c.setFillColor(HexColor('#eef5f9')); c.setStrokeColor(blue)
c.roundRect(300,220,240,181,7,fill=1,stroke=1)
text(420,382,'主控 U4',15,center=True)
text(420,365,'STC32G8K64 · LQFP48',11,gray,True)

for x in (65,730):
    c.setFillColor(HexColor('#f7f9fb')); c.setStrokeColor(gray)
    c.roundRect(x,233,45,166,4,fill=1,stroke=1)
ys=[385,350,315,280,245]
for number,y in enumerate(ys,1):
    text(83,y-4,str(number),12,center=True)
    text(754,y-4,str(number),12,center=True)
    node(110,y,red if number==1 else ink if number==5 else blue)
    node(730,y,red if number==1 else ink if number==5 else blue)

# 两个接口第一脚同供电网；不把这个网连接为尚未核对的主控供电脚。
line(110,385,255,385,red); line(255,385,255,452,red)
line(255,452,585,452,red); line(585,452,585,385,red); line(585,385,730,385,red)
text(420,460,'同一供电网72：电压未实测，不接12V入口',11,red,True)
text(124,391,'VDD',11,red); text(686,391,'ITR+',11,red)

receive=[('REV1','P0.6 / 脚3','ADC14'),('REV2','P1.0 / 脚5','ADC0'),('REV3','P1.1 / 脚6','ADC1')]
transmit=[('ITR1-','脚47 / P0.4'),('ITR2-','脚48 / P5.2'),('ITR3-','脚1 / P5.3')]
for y,(label,pin,adc),(txlabel,txpin) in zip(ys[1:4],receive,transmit):
    arrow(110,y,300,y); text(180,y+6,label,11,blue,True)
    text(310,y-5,pin,11); text(310,y-17,adc,8,gray)
    arrow(540,y,730,y); text(640,y+6,txlabel,11,blue,True)
    c.setFont('CN',11); c.setFillColor(ink); c.drawRightString(530,y-5,txpin)

# 地网和主控17脚连通。
line(110,245,240,245); line(240,245,240,190)
line(240,190,600,190); line(600,190,600,245); line(600,245,730,245)
line(420,220,420,183); node(420,190)
for width,y in ((24,183),(16,178),(8,173)):
    line(420-width/2,y,420+width/2,y)
text(124,252,'GND',11); text(685,252,'GND',11)
text(420,204,'脚17 · GND',10,center=True)
text(420,155,'接口5脚同地网13',11,gray,True)

c.setFillColor(HexColor('#fff7e6')); c.roundRect(30,74,W-60,64,5,fill=1,stroke=0)
text(43,118,'图中按逻辑针号排列，不表示插座实际的左右、上下方向。',12,red)
text(43,99,'小板内部原理图和小板插座针序尚未取得；此图只确认主板端。',11)
text(43,82,'接线按两端功能丝印/走线核对，不能只按线色，也不能把插错收发口等同电源反接。',10)
text(32,48,'来源：生产CAM连通分析 + 2026-09-21贴片图；GPIO由匹配STC32G手册引脚表交叉核对。',9,gray)
text(32,32,'文件：IR-array-mainboard-interface-20261111.pdf  |  长条小板线路不在现有主板原理图中。',9,gray)
c.showPage(); c.save()
doc=fitz.open(pdf)
assert len(doc)==1
page_text=doc[0].get_text()
assert all(s in page_text for s in ('CN3','CN7','REV1','ITR1-','P0.6','P5.2','P5.3'))
doc[0].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False).save(png)
print(pdf); print(png)
