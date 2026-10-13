"""Render a fictional coindex product story with real native UI captures.

Requires Pillow and numpy, macOS system fonts, and the companion Swift encoder.
No screen capture, model, network, SSH or nudge operation occurs in this script.
Motion graphics explain the workflow; simulated native receipts are labeled.
"""
import argparse
import functools
import json
import math
import pathlib
import subprocess
import wave

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
W, H, DURATION = 1920, 1080, 46
ACCENT, INK, MUTED = '#7770f5', '#17171d', '#777780'
SOURCES = [
    ('这台 Mac', '改善表单问答体验', '实现与测试通过', '体验完整问答流程并确认', '需要决定', '#5482e0'),
    ('dev-server', '为文档搜索增加全文检索', 'PR 已提交，尚未集成验证', '在测试环境验证完整搜索流程', '结果校对', '#7770f5'),
    ('build-server', '修复应用自动更新', '已定位错误，尚未改代码', '修改版本比较规则后验证升级', '继续推进', '#b18247'),
]
STILLS = [0.8, 3, 7.5, 11.7, 15.4, 19.2, 24.4, 28.5, 31.8, 34.6, 36.3, 39.7, 44.2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--captures', type=pathlib.Path, default=ROOT/'build/film-captures')
parser.add_argument('--assets', type=pathlib.Path, default=ROOT/'docs/assets')
parser.add_argument('--output', type=pathlib.Path, default=ROOT/'build/product-film')
parser.add_argument('--stills', action='store_true')
parser.add_argument('--gifs', action='store_true')
parser.add_argument('--video', action='store_true')
parser.add_argument('--fps', type=int, default=30)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
args.assets.mkdir(parents=True, exist_ok=True)
PINGFANG = next(pathlib.Path('/System/Library/AssetsV2/com_apple_MobileAsset_Font8').glob('*/AssetData/PingFang.ttc'))


@functools.lru_cache(maxsize=128)
def font(size, weight='regular'):
    return ImageFont.truetype(str(PINGFANG), size, index={'regular':3, 'medium':7, 'bold':11}[weight])


def ease(value):
    value = max(0, min(1, value))
    return 1 - (1 - value) ** 3


def smooth(value):
    value = max(0, min(1, value))
    return value * value * (3 - 2 * value)


def appear(time, start=0, length=.5):
    return ease((time - start) / length)


def text(image, value, xy, size, color=INK, weight='regular', anchor='la', alpha=1):
    layer = label(value, size, color, weight)
    x, y = xy
    if anchor.startswith('m'): x -= layer.width / 2
    if anchor.startswith('r'): x -= layer.width
    paste(image, layer, x, y, alpha)


@functools.lru_cache(maxsize=384)
def label(value, size, color, weight):
    f = font(size, weight)
    box = f.getbbox(value)
    image = Image.new('RGBA', (max(1,box[2]+6), size+20))
    ImageDraw.Draw(image).text((0,-box[1]+4), value, font=f, fill=color)
    return image


def paste(image, layer, x, y, alpha=1):
    if alpha <= 0: return
    if alpha < .999:
        layer = layer.copy()
        layer.putalpha(layer.getchannel('A').point(lambda v: round(v*alpha)))
    image.alpha_composite(layer, (round(x), round(y)))


def panel(width, height, fill='white', radius=24, border=None):
    # Draw geometry at 2x, then downsample for clean rounded edges.
    image = Image.new('RGBA', (width*2, height*2))
    ImageDraw.Draw(image).rounded_rectangle((1,1,width*2-2,height*2-2), radius=radius*2,
                                          fill=fill, outline=border, width=2)
    return image.resize((width,height), Image.Resampling.LANCZOS)


def shadow(layer, blur=25, opacity=32):
    margin = blur * 3
    image = Image.new('RGBA', (layer.width+margin*2,layer.height+margin*2))
    black = Image.new('RGBA',layer.size,(20,20,40,opacity))
    black.putalpha(layer.getchannel('A').point(lambda v: round(v*opacity/255)))
    image.alpha_composite(black,(margin,margin+15))
    image = image.filter(ImageFilter.GaussianBlur(blur))
    image.alpha_composite(layer,(margin,margin))
    return image, margin


def gradient(dark=False):
    y,x = np.mgrid[0:H,0:W].astype(np.float32)
    if dark:
        base = np.zeros((H,W,3), dtype=np.float32) + [8,9,14]
        glow = np.exp(-(((x-1140)/640)**2+((y-680)/430)**2))
        base += glow[:,:,None]*np.array([25,18,53])
    else:
        base = np.zeros((H,W,3), dtype=np.float32) + [248,248,250]
        glow = np.exp(-(((x-1130)/690)**2+((y-610)/450)**2))
        base -= glow[:,:,None]*np.array([14,16,1])
    return Image.fromarray(np.uint8(np.clip(base,0,255))).convert('RGBA')


LIGHT, DARK = gradient(), gradient(True)
ICON = Image.open(ROOT/'Resources/Brand/AppIcon.png').convert('RGBA')
OVERVIEW = Image.open(args.assets/'overview.png').convert('RGBA')
CONVERSATIONS = Image.open(args.assets/'conversations.png').convert('RGBA')


def capture(name):
    image = Image.open(args.captures/name).convert('RGB')
    bounds = ImageChops.difference(image,Image.new('RGB',image.size,'white')).getbbox()
    if image.size == (2400,1640) and bounds == (0,0,1200,828):
        image = image.crop((0,32,1200,820))
    elif image.size == (2400,1640) and bounds == (0,0,2400,1640):
        image = image.crop((0,64,2400,1640))
    else:
        raise ValueError('Review unexpected native UI capture: '+name)
    image.info.clear()
    return image.convert('RGBA')


CAPTURES = {state:capture('nudge-'+state+'.png') for state in ('ready','sending','sent')}
NATIVE_PANES = {state:im.crop((876,64,1180,530)) for state,im in CAPTURES.items()}
DETAIL = NATIVE_PANES['ready']


def framed(image, width, radius=18):
    height = round(image.height * width / image.width)
    out = image.resize((width,height),Image.Resampling.LANCZOS)
    mask = panel(width,height,radius=radius).getchannel('A')
    out.putalpha(mask)
    return shadow(out)


UI_HERO, UI_MARGIN = framed(OVERVIEW,1180)
UI_CONVERSATIONS, CONV_MARGIN = framed(CONVERSATIONS,650)
DETAIL_SHOT, DETAIL_MARGIN = framed(DETAIL,445)
NUDGE_SHOTS = {state:framed(pane,445) for state,pane in NATIVE_PANES.items()}


def chrome(image, dark=False):
    ink = '#b5b5c4' if dark else '#747480'
    paste(image,ICON.resize((28,28),Image.Resampling.LANCZOS),72,49)
    text(image,'coindex', (112,49),24,ink,'medium')
    text(image,'PRODUCT STORY', (1848,53),17,ink,anchor='ra')
    text(image,'虚构演示数据 · 催办流程示意', (72,1010),19,ink)
    text(image,'Agent 驱动的多机器目标与跟进清单', (1848,1010),19,ink,anchor='ra')


def source_card(index):
    host,goal,progress,action,status,color = SOURCES[index]
    image = panel(560,310, '#171720', radius=25,border='#323240')
    draw = ImageDraw.Draw(image)
    for j,c in enumerate(('#f07068','#e8bb57','#63bd80')):
        draw.ellipse((28+j*23,25,40+j*23,37),fill=c)
    text(image,host,(525,24),22,'#b5b5c4','medium',anchor='ra')
    text(image,'你交代的事', (32,76),20,'#89899d')
    text(image,goal,(32,115),32,'#fafafe','medium')
    draw.line((32,182,528,182),fill='#323240',width=1)
    text(image,'Agent 最新回复', (32,201),19,'#89899d')
    text(image,progress,(32,238),27,'#c9c7f2')
    return shadow(image,20,45)


SOURCE_CARDS = [source_card(i) for i in range(3)]


def goal_card(index):
    host,goal,progress,action,status,color = SOURCES[index]
    image = panel(1120,176,radius=22,border='#e4e3ec')
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0,24,5,152),radius=2,fill=color)
    text(image,goal,(31,19),33,INK,'medium')
    badge = panel(136,38,'#f0effb',radius=10)
    text(badge,status,(68,8),19,color,'medium',anchor='ma')
    paste(image,badge,948,22)
    text(image,'进度', (33,77),21,MUTED)
    text(image,progress,(119,77),24,'#555563')
    text(image,'下一步',(33,118),21,color,'medium')
    text(image,action,(119,118),24,INK,'medium')
    text(image,host,(1087,128),17,MUTED,anchor='ra')
    return shadow(image,14,24)


GOALS = [goal_card(i) for i in range(3)]


def packet():
    image = panel(970,480,radius=28,border='#dddbe9')
    text(image,'催办上下文',(38,28),23,MUTED,'medium')
    for y,key,value in [(95,'整体目标','为文档搜索增加全文检索'),
                        (210,'当前进度','PR 已提交；尚未做集成验证'),
                        (325,'下一步','在测试环境验证完整搜索流程')]:
        text(image,key,(40,y),20,ACCENT,'medium')
        text(image,value,(40,y+40),35,INK,'medium')
    return shadow(image)


PACKET, PACKET_MARGIN = packet()


def plane(image, xy, size=80, color=ACCENT, alpha=1):
    layer = Image.new('RGBA',(size,size))
    draw = ImageDraw.Draw(layer)
    draw.polygon([(5,size*.35),(size-7,7),(size*.68,size-5),(size*.48,size*.57)],fill=color)
    draw.line([(size*.48,size*.57),(size-7,7)],fill='#bdb8ff',width=max(2,size//35))
    paste(image,layer,*xy,alpha)


def pointer(image, xy, alpha=1):
    layer = Image.new('RGBA',(55,65))
    points=[(8,4),(9,51),(22,41),(31,61),(40,56),(29,37),(47,36)]
    ImageDraw.Draw(layer).polygon(points,fill='#17171d',outline='white',width=3)
    paste(image,layer,*xy,alpha)


def scene(index,t):
    dark = index in (0,1,5)
    image = (DARK if dark else LIGHT).copy()
    if index == 0:
        a = appear(t,0,.5)
        text(image,'AI 干完了。',(960,340+30*(1-a)),132,'#f6f5ff','bold','ma',a)
        a = appear(t,1.5,.5)
        text(image,'你却忘了，交代过什么。',(960,520+35*(1-a)),72,'#aea7ff','medium','ma',a)
        text(image,'多台机器。多个会话。越来越多的事。',(960,686),28,'#8d8d9f',anchor='ma',alpha=appear(t,2.5,.5))
    elif index == 1:
        text(image,'工作交出去了。目标散在各处。',(960,134),65,'#f7f7fd','medium','ma',appear(t))
        for i,(layer,margin) in enumerate(SOURCE_CARDS):
            a = appear(t,.5+i*.5,.5)
            x = [50,680,1310][i]
            y = [356,420,341][i] + 70*(1-a) + math.sin(t*.7+i)*7
            paste(image,layer,x-margin,y-margin,a)
        a = appear(t,2)
        text(image,'当初要做什么？做到哪了？还有谁在等你？',(960,836),37,'#aaa9bb',anchor='ma',alpha=a)
        text(image,'本机 + SSH 来源',(960,913),24,'#7b779e',anchor='ma',alpha=a)
    elif index == 2:
        text(image,'一个整理 Agent。把目标找回来。',(960,125),65,INK,'medium','ma',appear(t))
        text(image,'多机器 Codex 会话',(65,268),23,MUTED,alpha=appear(t,.2))
        text(image,'目标与跟进清单',(690,268),23,ACCENT,'medium',alpha=appear(t,.6))
        # The same source colors persist from machine labels into goal rows.
        for i in range(3):
            host,_,_,_,_,color = SOURCES[i]
            a = appear(t,.5+i*.5,.5)
            y = 324 + i*203
            pill=panel(226,86,'#ffffff',radius=18,border='#e1dfe9')
            text(pill,host,(113,16),24,color,'medium',anchor='ma')
            text(pill,'本机 Codex' if i==0 else 'SSH Codex',(113,53),17,MUTED,anchor='ma')
            paste(image,pill,65-35*(1-a),y+35,a)
            draw=ImageDraw.Draw(image)
            draw.line((316,y+78,382,y+78),fill='#bcb9d8',width=2)
            draw.line((538,y+78,661,y+78),fill='#bcb9d8',width=2)
            travel=smooth((t-.5-i*.5)/1)
            dotx=316+(661-316)*travel
            if travel < 1: draw.ellipse((dotx-5,y+73,dotx+5,y+83),fill=color)
            goal_a=appear(t,1.5+i*.5,.5)
            layer,margin=GOALS[i]
            paste(image,layer,690-margin+65*(1-goal_a),y-margin,goal_a)
        draw=ImageDraw.Draw(image)
        draw.rounded_rectangle((399,343,528,862),radius=28,fill='#efedf9')
        paste(image,ICON.resize((82,82),Image.Resampling.LANCZOS),422,516)
        text(image,'整理',(463,630),26,ACCENT,'medium','ma')
        text(image,'Agent',(463,675),22,ACCENT,anchor='ma')
        text(image,'逐个读取会话里的目标、进度与下一步',(960,928),27,MUTED,anchor='ma',alpha=appear(t,3))
    elif index == 3:
        text(image,'所有目标。一眼找回。',(960,126),72,INK,'medium','ma',appear(t))
        a=appear(t,0,.5)
        scale=.96+.04*a
        layer=UI_HERO.resize((round(UI_HERO.width*scale),round(UI_HERO.height*scale)),Image.Resampling.BICUBIC)
        paste(image,layer,960-layer.width/2,220-UI_MARGIN+32*(1-a),a)
        # Source and action labels remain outside the real app image.
        text(image,'本机与 SSH',(132,540),29,ACCENT,'medium',alpha=appear(t,1))
        text(image,'统一跟进',(132,585),26,MUTED,alpha=appear(t,1.5))
        text(image,'原始目标',(1790,445),29,ACCENT,'medium','ra',appear(t,1.5))
        text(image,'当前进度',(1790,500),29,ACCENT,'medium','ra',appear(t,2))
        text(image,'下一步',(1790,555),29,ACCENT,'medium','ra',appear(t,2.5))
    elif index == 4:
        text(image,'终于想起来。这件事还没收尾。',(960,123),65,INK,'medium','ma',appear(t))
        a=appear(t,0)
        paste(image,DETAIL_SHOT,270-DETAIL_MARGIN,250-DETAIL_MARGIN+35*(1-a),a)
        for i,(key,value) in enumerate([
            ('当初的目标','为文档搜索增加全文检索'),
            ('现在的进度','PR 已提交，还没有集成验证'),
            ('该跟进的下一步','在测试环境验证完整搜索流程')]):
            a=appear(t,.5+i*1,.5)
            y=300+i*190
            text(image,key,(870,y+25*(1-a)),27,ACCENT,'medium',alpha=a)
            text(image,value,(870,y+53+25*(1-a)),44,INK,'medium',alpha=a)
        text(image,'原机器、原对话、原文依据，都能追溯。',(870,900),27,MUTED,alpha=appear(t,3))
    elif index == 5:
        a=appear(t,0,.5)
        plane(image,(908,234+30*(1-a)),104,alpha=a)
        if t < .5:
            text(image,'一键。',(960-60*(1-a),424),145,'#f7f5ff','bold','ma',a)
        elif t < 1:
            b=appear(t,.5,.35)
            text(image,'催办。',(960+60*(1-b),424),145,'#f7f5ff','bold','ma',b)
        else:
            b=appear(t,1,.25)
            text(image,'一键催办。',(960,424+18*(1-b)),145,'#f7f5ff','bold','ma',b)
        text(image,'找回目标。让原 Agent 接着干。',(960,669),42,'#afa9ff','medium','ma',appear(t,1.5,.5))
        text(image,'目标 + 进度 + 下一步，随这一键一起送达。',(960,771),27,'#9290a5',anchor='ma',alpha=appear(t,2,.5))
    elif index == 6:
        text(image,'带着上下文。回到原对话。',(960,127),70,INK,'medium','ma',appear(t))
        state='ready' if t<2 else ('sending' if t<5 else 'sent')
        shot,margin=NUDGE_SHOTS[state]
        paste(image,shot,120-margin,238-margin,appear(t))
        text(image,'真实应用界面 · 隔离演示',(342,936),23,MUTED,anchor='ma')
        # Native pane crop transforms: button center (51,409) -> screen (195,837).
        if .5<t<2.25:
            move=smooth((t-.5)/1.5)
            pointer(image,(620+(180-620)*move,915+(816-915)*move),appear(t,.5,.25))
        if 2<=t<2.5:
            p=(t-2)/.5
            ring=Image.new('RGBA',(W,H))
            d=ImageDraw.Draw(ring)
            r=15+42*p
            d.ellipse((197-r,844-r,197+r,844+r),outline=(119,112,245,round(200*(1-p))),width=4)
            image.alpha_composite(ring)
        a=appear(t,2.5,.5)
        paste(image,PACKET,790-PACKET_MARGIN+55*(1-a),344-PACKET_MARGIN,a)
        if 3<t<4.5:
            p=smooth((t-3)/1.5)
            plane(image,(594+p*138,603-math.sin(p*math.pi)*85),46,alpha=math.sin(p*math.pi))
        text(image,'dev-server · 原 Codex 会话',(1275,871),27,ACCENT,'medium','ma',appear(t,3.5))
        text(image,'沿用原对话的模型与权限',(1275,930),25,MUTED,anchor='ma',alpha=appear(t,4.5))
        if t>=5:
            a=appear(t,5,.5)
            badge=panel(334,55,'#e9f3ef',radius=16)
            text(badge,'✓ 催办已送达 · 演示回执',(167,16),23,'#357b66','medium','ma')
            paste(image,badge,1108,260-18*(1-a),a)
    elif index == 7:
        text(image,'原 Agent 继续。上下文不用重讲。',(960,125),66,INK,'medium','ma',appear(t))
        window=panel(1440,690,'white',radius=28,border='#e2e0ea')
        text(window,'原 Codex 对话 · 流程示意',(47,28),24,MUTED,'medium')
        text(window,'dev-server / 文档检索功能',(1390,32),22,ACCENT,'medium','ra')
        d=ImageDraw.Draw(window)
        d.line((35,90,1405,90),fill='#e9e7f0',width=1)
        a=appear(t,.5)
        request=panel(1070,220,'#f0eefb',radius=20)
        text(request,'coindex 催办 · 虚构内容',(30,25),22,ACCENT,'medium')
        text(request,'请继续推进「为文档搜索增加全文检索」。',(30,74),36,INK,'medium')
        text(request,'此前：PR 已提交；尚未做集成验证。',(30,132),28,'#656471')
        text(request,'下一步：在测试环境验证完整搜索流程。',(30,174),28,'#656471')
        paste(window,request,321,124+25*(1-a),a)
        a=appear(t,1.5)
        response=panel(1070,168,'#f6f6f8',radius=20)
        text(response,'原 Agent · 虚构回复',(30,25),22,'#357b66','medium')
        text(response,'我会先核对最新代码与 PR 状态，',(30,72),35,INK,'medium')
        text(response,'再继续集成验证，并汇报结果。',(30,120),35,INK,'medium')
        paste(window,response,48,383+25*(1-a),a)
        text(window,'原对话  /  原工作目录  /  原模型与权限',(720,615),25,MUTED,anchor='ma',alpha=appear(t,2.3))
        layer,margin=shadow(window)
        paste(image,layer,240-margin,252-margin)
    else:
        a=appear(t,0)
        paste(image,ICON.resize((130,130),Image.Resampling.LANCZOS),665,224+25*(1-a),a)
        text(image,'coindex',(836,239+25*(1-a)),95,INK,'bold',alpha=a)
        text(image,'交代过的事。都有下一步。',(960,470),96,INK,'medium','ma',appear(t,.5))
        text(image,'Agent 驱动 · 多机器会话 · 目标与跟进清单',(960,647),34,MUTED,anchor='ma',alpha=appear(t,1))
        text(image,'开源 · macOS 14+ · Apple Silicon 与 Intel',(960,753),25,ACCENT,anchor='ma',alpha=appear(t,1.5))
        text(image,'github.com/Junming-Liang/coindex',(960,828),24,MUTED,anchor='ma',alpha=appear(t,2))
    chrome(image,dark)
    return image


TIMELINE = [(0,4.5),(1,6),(2,6),(3,5.5),(4,5),(5,3),(6,7),(7,5),(8,4)]
assert sum(length for _,length in TIMELINE) == DURATION


def frame(time):
    offset=0
    for index,length in TIMELINE:
        if time < offset+length or index==8:
            local=time-offset
            image=scene(index,local)
            # Dissolve at each chapter boundary; do not obstruct reading holds.
            if index and local<.25:
                previous_length=TIMELINE[index-1][1]
                previous=scene(index-1,previous_length)
                image=Image.blend(previous,image,smooth(local/.25))
            return image.convert('RGB')
        offset+=length


def score():
    """Original 120 BPM electronic cue, composed around the film's visual events."""
    rate=48000
    samples=rate*DURATION
    times=np.arange(samples)/rate
    drums=np.zeros((samples,2),dtype=np.float32)
    music=np.zeros_like(drums)
    rng=np.random.default_rng(19)
    beat=.5
    cuts=(0,4.5,10.5,16.5,22,27,30,37,42)
    cues={'tempo_bpm':120,'beat_seconds':beat,'chapter_accents':list(cuts),
          'goal_entries':[12,12.5,13],'nudge_title':[27,27.5,28],
          'button_click':32,'context_packet':32.5,'receipt':35,'agent_reply':38.5}
    for key in ('chapter_accents','goal_entries','nudge_title'):
        assert all(abs(value/beat-round(value/beat))<1e-8 for value in cues[key])
    (args.output/'beat-cues.json').write_text(json.dumps(cues,indent=2))

    def add(stem,signal,start,gain=1,pan=.5):
        left=round(start*rate)
        if left<0:
            signal=signal[-left:]; left=0
        count=min(len(signal),samples-left)
        if count<=0:return
        stem[left:left+count,0]+=signal[:count]*gain*math.sqrt(1-pan)
        stem[left:left+count,1]+=signal[:count]*gain*math.sqrt(pan)

    def local(seconds):return np.arange(round(rate*seconds))/rate

    def high_noise(length,window=12):
        noise=rng.normal(0,1,length)
        cumulative=np.cumsum(np.r_[np.zeros(window),noise])
        return noise-(cumulative[window:]-cumulative[:-window])/window

    def kick(start,gain=1):
        t=local(.36)
        # Fast pitch sweep + sub body + a short broadband attack.
        phase=2*np.pi*(48*t+75*.023*(1-np.exp(-t/.023)))
        body=np.sin(phase)*np.exp(-t*12)*np.minimum(1,t/.0015)
        attack=high_noise(len(t))*np.exp(-t*220)*.10
        add(drums,body+attack,start,.86*gain)

    def hat(start,gain=.1,opened=False):
        t=local(.16 if opened else .055)
        signal=high_noise(len(t),5)*np.exp(-t*(24 if opened else 92))
        add(drums,signal,start,gain,.32 if opened else .66)

    def clap(start,gain=1):
        t=local(.18)
        noise=high_noise(len(t),30)
        envelope=np.exp(-t*25)*.45
        for at in (0,.013,.026):
            pulse=np.maximum(0,t-at)
            envelope+=np.where(t>=at,np.exp(-pulse*160),0)*.30
        signal=noise*envelope + np.sin(2*np.pi*185*t)*np.exp(-t*32)*.18
        add(drums,signal,start,.28*gain)

    def synth(note,seconds,kind):
        t=local(seconds)
        frequency=440*2**((note-69)/12)
        if kind=='bass':
            wave=np.sin(2*np.pi*frequency*t)*.72
            for harmonic in range(2,7):
                wave+=np.sin(2*np.pi*frequency*harmonic*t)/harmonic**1.7*.48
            envelope=np.minimum(1,t/.007)*np.exp(-t*5)*np.minimum(1,(seconds-t)/.04)
        else:
            wave=np.zeros_like(t)
            for detune in (-.003,0,.003):
                for harmonic in range(1,7):
                    wave+=np.sin(2*np.pi*frequency*(1+detune)*harmonic*t+.15*harmonic)/harmonic**1.5/3
            envelope=np.minimum(1,t/.005)*np.exp(-t*(10 if kind=='lead' else 7))*np.minimum(1,(seconds-t)/.05)
        return wave*envelope

    # A clear groove is already present in the opening; intensity builds at the
    # organizing scene and peaks when one-click nudging is revealed.
    for i,start in enumerate(np.arange(0,DURATION-.5,beat)):
        energy=.64 if start<4.5 else (.85 if start<10.5 else 1)
        if 26<=start<27: energy=.4
        if 37<=start<42: energy=.75
        kick(float(start),energy)
        if i%2:clap(float(start),energy)
        hat(float(start),.052*energy)
        hat(float(start+.25),.11*energy,opened=True)
        if start>=10.5 and i%4 in (1,3):
            hat(float(start+.125),.040)
            hat(float(start+.375),.047)

    roots=[40,36,43,38]  # E minor / C / G / D.
    bass_pattern=[(0,0),(.75,0),(1.25,12),(1.75,7),(2.25,0),(2.75,0),(3.25,12),(3.75,7)]
    lead_pattern=[(0,12),(.25,15),(.75,19),(1,17),(1.5,15),(1.75,12),
                  (2.25,10),(2.5,12),(2.75,15),(3.25,19),(3.5,17)]
    for bar,start in enumerate(np.arange(0,DURATION,4)):
        root=roots[bar%4]
        for at,interval in bass_pattern:
            add(music,synth(root+interval,.32,'bass'),float(start+at+.25),.42)
        for at,interval in lead_pattern:
            gain=.055 if start<8 else (.115 if start<26 else .14)
            if 37<=start<42:gain=.065
            signal=synth(root+24+interval,.42,'lead')
            pan=.26 if (int(at*4)%2) else .74
            add(music,signal,float(start+at),gain,pan)
            add(music,signal,float(start+at+.25),gain*.24,1-pan)
            add(music,signal,float(start+at+.5),gain*.10,pan)
        for at in (.5,1.5,2.5,3.5):
            for interval in (12,15 if bar%4 in (0,3) else 16,19):
                add(music,synth(root+interval,.28,'chord'),float(start+at+.25),.06)

    # Precisely placed accents tie the chapter cuts and UI actions to the cue.
    for start in cuts[1:]:
        t=local(.75)
        riser=high_noise(len(t),9)*np.linspace(0,1,len(t))**2
        add(drums,riser,start-.75,.14)
        t=local(.6)
        crash=high_noise(len(t),4)*np.exp(-t*8)
        add(drums,crash,start,.18)
        t=local(.35)
        impact=np.sin(2*np.pi*(46*t+38*.035*(1-np.exp(-t/.035))))*np.exp(-t*13)
        add(drums,impact,start,.34)
    for start in (26,26.25,26.5,26.625,26.75,26.875):
        clap(start,.55)
    for start in (12,12.5,13,27,27.5,28):
        add(drums,synth(88,.12,'lead'),start,.075)
    t=local(.07)
    click=high_noise(len(t),5)*np.exp(-t*100)
    add(drums,click,32,.23)
    for i,note in enumerate((76,83,88)):
        add(music,synth(note,.48,'lead'),35+i*.125,.14)

    # Side-chain the musical stem against each kick; leave the transient sharp.
    phase=np.mod(times,beat)
    duck=.34+.66*(1-np.exp(-phase/.09))
    music*=duck[:,None]
    audio=drums+music
    audio=np.tanh(audio*1.5)
    fade=np.minimum(1,times/.025)*np.minimum(1,(DURATION-times)/.65)
    audio*=fade[:,None]
    audio*=.89/max(.001,float(np.max(np.abs(audio))))
    audio=np.int16(np.clip(audio,-1,1)*32767)
    path=args.output/'original-score.wav'
    with wave.open(str(path),'wb') as out:
        out.setnchannels(2); out.setsampwidth(2); out.setframerate(rate); out.writeframes(audio.tobytes())
    return path


def gif(path,start,end,fps=12,width=960):
    samples=[frame(time).resize((480,270),Image.Resampling.LANCZOS) for time in STILLS]
    montage=Image.new('RGB',(480,270*len(samples)))
    for i,image in enumerate(samples): montage.paste(image,(0,270*i))
    palette=montage.quantize(colors=256,method=Image.Quantize.MEDIANCUT)
    frames=[]
    for i,time in enumerate(np.arange(start,end,1/fps)):
        # A paused/loading preview must already communicate its opening idea.
        preview_time = max(float(time), 2 if start==0 else start+2)
        image=frame(preview_time).resize((width,round(width*H/W)),Image.Resampling.LANCZOS)
        frames.append(image.quantize(palette=palette,dither=Image.Dither.NONE))
    durations=[round((i+1)*1000/fps/10)*10-round(i*1000/fps/10)*10 for i in range(len(frames))]
    frames[0].save(path,save_all=True,append_images=frames[1:],duration=durations,loop=0,optimize=True,disposal=1)
    return len(frames)


if args.stills:
    tiles=[]
    for i,time in enumerate(STILLS):
        image=frame(time)
        image.save(args.output/f'shot-{i:02d}.png')
        tiles.append(image.resize((480,270),Image.Resampling.LANCZOS))
    sheet=Image.new('RGB',(480*3,300*math.ceil(len(tiles)/3)),'#e7e7ef')
    for i,image in enumerate(tiles):
        sheet.paste(image,((i%3)*480,(i//3)*300))
        ImageDraw.Draw(sheet).text(((i%3)*480+12,(i//3)*300+277),f'{STILLS[i]:04.1f}s',fill=INK,font=font(17))
    sheet.save(args.output/'contact-sheet.jpg',quality=92)
    poster=scene(2,5.4).convert('RGB')
    poster.save(args.assets/'workflow-poster.png',optimize=True)
    # Dedicated still keeps the one-click story readable without playback.
    scene(6,6.2).convert('RGB').save(args.assets/'nudge-story.png',optimize=True)
    print('Storyboard and posters rendered.',flush=True)

if args.gifs:
    count=gif(args.assets/'workflow-demo.gif',0,DURATION)
    nudge_count=gif(args.assets/'nudge-demo.gif',27,42,fps=15,width=960)
    print(json.dumps({'story_frames':count,'nudge_frames':nudge_count,'duration_seconds':DURATION}),flush=True)

if args.video:
    encoder=ROOT/'build/encode-product-film'
    if not encoder.exists():
        subprocess.run(['swiftc','-swift-version','5','-O','-module-cache-path',str(ROOT/'build/module-cache'),
                        str(ROOT/'scripts/encode-product-film.swift'),'-o',str(encoder)],check=True)
    soundtrack=score()
    process=subprocess.Popen([str(encoder),str(W),str(H),str(args.fps),str(DURATION*args.fps),
        str(args.output/'silent.mp4'),str(soundtrack),str(args.output/'coindex-1.9.0-product-film.mp4')],stdin=subprocess.PIPE)
    try:
        for i in range(DURATION*args.fps):
            process.stdin.write(frame(i/args.fps).convert('RGBA').tobytes('raw','BGRA'))
            if i% (args.fps*5)==0: print(f'Rendered {i/args.fps:.0f}/{DURATION}s',flush=True)
        process.stdin.close()
        if process.wait(): raise RuntimeError('Video encoder failed')
    finally:
        if process.poll() is None: process.terminate()
