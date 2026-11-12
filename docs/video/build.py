import json, subprocess, os, sys
sys.path.insert(0, '.')
from script import SCENES
D = json.load(open('durs.json')); LEAD, TAIL = 0.35, 0.65; FPS = 30
ENC = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-r', str(FPS), '-g', '60']
STILL = {'slide:cover': 'stills/cover.jpg', 'slide:problem': 'stills/problem.jpg', 'slide:pipeline': 'stills/pipeline.jpg', 'slide:impact': 'stills/impact.jpg'}
FADE_IN = {'s1', 's2', 's3', 's4', 's9'}; FADE_OUT = {'s1', 's2', 's3', 's8', 's9'}

def ts(t):
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"

def ass(sid, cap, d, T):
    chunks = [c.strip() for c in cap.split('|')]
    w = [len(c) for c in chunks]; tot = sum(w); t = LEAD; ev = []
    for c, n in zip(chunks, w):
        dur = d * n / tot
        ev.append(f"Dialogue: 0,{ts(t)},{ts(min(t + dur, T - 0.05))},Cap,,0,0,0,,{c}")
        t += dur
    head = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Plus Jakarta Sans,36,&H00FFFFFF,&H00FFFFFF,&H28181818,&H00000000,1,0,0,0,100,100,0,0,3,16,0,2,220,220,46,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    open(f'scenes/{sid}.ass', 'w').write(head + '\n'.join(ev) + '\n')

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode: print(r.stderr[-2000:]); raise SystemExit(1)

for sid, spoken, cap, vis in SCENES:
    T = round(D[sid] + LEAD + TAIL, 3); ass(sid, cap, D[sid], T)
    vf = []
    if vis.startswith('slide:'):
        inp = ['-framerate', str(FPS), '-i', STILL[vis]]; vf = ['format=yuv420p', 'loop=-1:1', f'trim=duration={T}']
    else:
        fr = json.load(open(f'frames/{sid}.json')); lines = []
        for i, (t, path) in enumerate(fr):
            nxt = fr[i + 1][0] if i + 1 < len(fr) else T
            start = 0 if i == 0 else t
            lines.append(f"file '{os.path.abspath(path)}'\nduration {max(nxt - start, 0.001):.4f}")
        lines.append(f"file '{os.path.abspath(fr[-1][1])}'")
        open(f'scenes/{sid}.txt', 'w').write('\n'.join(lines) + '\n')
        inp = ['-f', 'concat', '-safe', '0', '-i', f'scenes/{sid}.txt']; vf = [f'fps={FPS}', 'scale=1920:1080:flags=lanczos', 'format=yuv420p', f'trim=duration={T}']
    if sid in FADE_IN: vf.append('fade=t=in:st=0:d=0.35')
    if sid in FADE_OUT: vf.append(f'fade=t=out:st={T - 0.35}:d=0.35')
    vf.append(f"ass=scenes/{sid}.ass")
    tmp = f'scenes/{sid}.tmp.mp4'
    run(['ffmpeg', '-y', '-v', 'error', *inp, '-vf', ','.join(vf), '-t', str(T), *ENC, '-an', tmp])
    os.replace(tmp, f'scenes/{sid}.mp4')
    # matching audio: lead silence + voice + tail, exactly T long
    run(['ffmpeg', '-y', '-v', 'error', '-i', f'audio/{sid}.wav', '-af', f'adelay={int(LEAD*1000)},apad,atrim=duration={T},aresample=48000,aformat=channel_layouts=stereo', '-c:a', 'pcm_s16le', f'scenes/{sid}.wav'])
    print(sid, 'ok', T)

open('scenes/v.txt', 'w').write(''.join(f"file '{os.path.abspath('scenes/'+s[0]+'.mp4')}'\n" for s in SCENES))
open('scenes/a.txt', 'w').write(''.join(f"file '{os.path.abspath('scenes/'+s[0]+'.wav')}'\n" for s in SCENES))
run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', 'scenes/v.txt', '-c', 'copy', 'scenes/video_only.mp4'])
run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', 'scenes/a.txt', '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11', '-ar', '48000', '-c:a', 'pcm_s16le', 'scenes/voice.wav'])
run(['ffmpeg', '-y', '-v', 'error', '-i', 'scenes/video_only.mp4', '-i', 'scenes/voice.wav', '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k', '-shortest', '-movflags', '+faststart', 'final.tmp.mp4'])
os.replace('final.tmp.mp4', 'TBO_Inventory_Intelligence_pitch.mp4')
print('done')
