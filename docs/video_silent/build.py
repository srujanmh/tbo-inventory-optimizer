import json, subprocess, os, sys
sys.path.insert(0, '.')
from script import SCENES, durs, chunk_dur
D = durs(); LEAD, TAIL = 0.4, 0.8; FPS = 30
ENC = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-r', str(FPS), '-g', '60']
STILL = {'slide:cover': 'stills/cover.jpg', 'slide:problem': 'stills/problem.jpg', 'slide:pipeline': 'stills/pipeline.jpg', 'slide:end': 'stills/end.jpg'}
os.makedirs('scenes', exist_ok=True)
def ts(t): return f"{int(t//3600)}:{int(t%3600//60):02d}:{t%60:05.2f}"
HEAD = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Plus Jakarta Sans,40,&H00FFFFFF,&H00FFFFFF,&H1A181818,&H00000000,1,0,0,0,100,100,0,0,3,18,0,2,200,200,52,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode: print(r.stderr[-2000:]); raise SystemExit(1)
for sid, cap, vis in SCENES:
    T = round(D[sid] + LEAD + TAIL, 3); t = LEAD; ev = []
    for c in [c.strip() for c in cap.split('|')]:
        d = chunk_dur(c); ev.append(f"Dialogue: 0,{ts(t)},{ts(min(t + d - 0.08, T - 0.05))},Cap,,0,0,0,,{c}"); t += d
    open(f'scenes/{sid}.ass', 'w').write(HEAD + '\n'.join(ev) + '\n')
    if vis.startswith('slide:'):
        inp = ['-framerate', str(FPS), '-i', STILL[vis]]; vf = ['format=yuv420p', 'loop=-1:1', f'trim=duration={T}']
    else:
        fr = json.load(open(f'frames/{sid}.json')); lines = []
        for i, (tt, path) in enumerate(fr):
            nxt = fr[i + 1][0] if i + 1 < len(fr) else T
            start = 0 if i == 0 else tt
            lines.append(f"file '{os.path.abspath(path)}'\nduration {max(nxt - start, 0.001):.4f}")
        lines.append(f"file '{os.path.abspath(fr[-1][1])}'")
        open(f'scenes/{sid}.txt', 'w').write('\n'.join(lines) + '\n')
        inp = ['-f', 'concat', '-safe', '0', '-i', f'scenes/{sid}.txt']; vf = [f'fps={FPS}', 'scale=1920:1080:flags=lanczos', 'format=yuv420p', 'tpad=stop_mode=clone:stop_duration=30', f'trim=duration={T}']
    vf += ['fade=t=in:st=0:d=0.3', f'fade=t=out:st={T - 0.3}:d=0.3', f"ass=scenes/{sid}.ass"]
    run(['ffmpeg', '-y', '-v', 'error', *inp, '-vf', ','.join(vf), '-t', str(T), *ENC, '-an', f'scenes/{sid}.tmp.mp4'])
    os.replace(f'scenes/{sid}.tmp.mp4', f'scenes/{sid}.mp4'); print(sid, T, flush=True)
open('scenes/v.txt', 'w').write(''.join(f"file '{os.path.abspath('scenes/'+s[0]+'.mp4')}'\n" for s in SCENES))
run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', 'scenes/v.txt', '-c', 'copy', 'scenes/video_only.mp4'])
run(['ffmpeg', '-y', '-v', 'error', '-i', 'scenes/video_only.mp4', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '64k', '-shortest', '-movflags', '+faststart', 'final.tmp.mp4'])
os.replace('final.tmp.mp4', 'TBO_Inventory_Intelligence_pitch_silent.mp4'); print('done')
