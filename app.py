import os, re, json, math, shutil, subprocess, tempfile
from pathlib import Path
from collections import Counter
import streamlit as st

APP = "LMPD AI"
ROOT = Path(__file__).parent
OUT = ROOT / "outputs"
WORK = ROOT / "work"
OUT.mkdir(exist_ok=True); WORK.mkdir(exist_ok=True)

st.set_page_config(page_title=APP, page_icon="🎬", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap');
html, body, [class*="css"] {font-family:'Space Grotesk',sans-serif;}
.stApp {background: radial-gradient(ellipse at 15% 0%, #22204b 0%, #10111a 42%, #090a10 100%); color:#f5f5fb;}
section[data-testid="stSidebar"] {background:#11121c;border-right:1px solid #292a3a;}
.hero {padding:28px 30px;border:1px solid #34344a;border-radius:22px;background:linear-gradient(120deg,#191a2b,#242044 60%,#171827);margin-bottom:22px;}
.brand {font-size:34px;font-weight:700;letter-spacing:-1.5px;color:#fff;}
.brand span {color:#a78bfa;}
.sub {color:#b7b8ca;font-size:14px;margin-top:5px;}
.pill {display:inline-block;padding:5px 10px;border-radius:99px;background:#30275a;color:#d9ccff;font-size:11px;margin-right:5px;}
.metric {padding:16px;border:1px solid #303044;border-radius:16px;background:#171824;}
.metric b {font-size:26px;color:#c4b5fd;}
.panel {padding:18px;border:1px solid #303044;border-radius:18px;background:#151622;margin:8px 0;}
.smallmuted {color:#a4a5b8;font-size:12px;}
div.stButton>button {border-radius:12px;border:1px solid #7864ce;background:linear-gradient(90deg,#6d4bd1,#8b5cf6);color:white;font-weight:700;min-height:42px;}
div.stButton>button:hover {border-color:#c4b5fd;color:white;}
</style>
""", unsafe_allow_html=True)

def has_bin(name):
    return shutil.which(name) is not None

def ffmpeg_path():
    if has_bin("ffmpeg"): return "ffmpeg"
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception: return None

def run_cmd(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout)[-3500:])
    return p.stdout

def get_video(source, uploaded):
    if uploaded is not None:
        target = WORK / uploaded.name
        target.write_bytes(uploaded.getbuffer())
        return target
    if source.strip():
        try:
            import yt_dlp
        except ImportError:
            raise RuntimeError("yt-dlp is not installed. Run run.bat again.")
        target = WORK / "source_video.%(ext)s"
        opts = {"outtmpl": str(target), "format":"bestvideo[height<=1080]+bestaudio/best[height<=1080]/best", "merge_output_format":"mp4", "noplaylist":True}
        with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([source.strip()])
        found = list(WORK.glob("source_video.*"))
        found = [p for p in found if p.suffix.lower() in [".mp4",".mkv",".webm",".mov"]]
        if not found: raise RuntimeError("Download did not produce a supported video file.")
        return max(found, key=lambda p:p.stat().st_mtime)
    raise RuntimeError("Upload a video or enter a video URL.")

def probe(path):
    fp=ffmpeg_path()
    if not fp: raise RuntimeError("FFmpeg not found. Re-run setup or install FFmpeg.")
    data=json.loads(run_cmd([fp.replace("ffmpeg","ffprobe") if fp=="ffmpeg" else fp, "-v","quiet","-print_format","json","-show_format","-show_streams",str(path)])) if fp=="ffmpeg" else None
    if data is None:
        # imageio-ffmpeg bundles ffmpeg but not ffprobe; use OpenCV for metadata fallback
        import cv2
        cap=cv2.VideoCapture(str(path)); fps=cap.get(cv2.CAP_PROP_FPS) or 25
        frames=cap.get(cv2.CAP_PROP_FRAME_COUNT); w=cap.get(cv2.CAP_PROP_FRAME_WIDTH); h=cap.get(cv2.CAP_PROP_FRAME_HEIGHT); cap.release()
        return {"duration":frames/fps if fps else 0,"width":int(w),"height":int(h),"fps":fps}
    v=next((s for s in data["streams"] if s.get("codec_type")=="video"),{})
    return {"duration":float(data.get("format",{}).get("duration",0)),"width":v.get("width",0),"height":v.get("height",0),"fps":eval(v.get("avg_frame_rate","25/1"))}

def transcribe(path, model_name):
    try:
        from faster_whisper import WhisperModel
    except ImportError: raise RuntimeError("faster-whisper is missing. Run run.bat again.")
    model=WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info=model.transcribe(str(path), word_timestamps=True, vad_filter=True, beam_size=5)
    result=[]
    for seg in segments:
        words=[]
        if seg.words:
            for w in seg.words:
                words.append({"start":float(w.start),"end":float(w.end),"text":w.word.strip()})
        result.append({"start":float(seg.start),"end":float(seg.end),"text":seg.text.strip(),"words":words})
    return result

HOOKS = ["wait","listen","secret","mistake","truth","never","always","why","how","crazy","imagine","remember","actually","problem","because","finally","first","best","worst","nobody","everyone","money","love","fail","win","important"]
def score_segment(text, duration):
    words=re.findall(r"\b[\w']+\b",text.lower())
    if not words: return 0, []
    unique=len(set(words))/max(1,len(words))
    hook=[w for w in HOOKS if w in words]
    emph=sum(1 for w in words if w.isupper() and len(w)>2)
    questions=text.count("?")
    density=min(1,len(words)/max(1,duration*2.0))
    # Transparent heuristic, not a measured prediction of virality.
    score=34 + min(20,len(hook)*6) + unique*12 + min(12,questions*4) + density*12 + min(8,emph*2)
    score=max(0,min(100,score))
    reasons=[]
    if hook: reasons.append("hook words: "+", ".join(hook[:3]))
    if questions: reasons.append("question / curiosity cue")
    if unique>.72: reasons.append("varied wording")
    if density>.65: reasons.append("strong speech density")
    return round(score), reasons

def choose_clips(segments, duration, count, clip_len):
    # Generate overlapping candidate windows at transcript boundaries.
    candidates=[]
    for i,s in enumerate(segments):
        start=max(0,s["start"]-1.5); end=min(duration,start+clip_len)
        if end-start < min(12,clip_len*.55): continue
        txt=" ".join(x["text"] for x in segments if x["start"] < end and x["end"] > start)
        score,reasons=score_segment(txt,end-start)
        # Prefer a strong opening line and a clean sentence boundary.
        if txt.strip().endswith((".", "!", "?")): score=min(100,score+4); reasons.append("sentence-ending boundary")
        candidates.append({"start":start,"end":end,"score":score,"text":txt,"reasons":reasons})
    candidates.sort(key=lambda x:x["score"],reverse=True)
    picked=[]
    for c in candidates:
        if all(abs(c["start"]-p["start"])>clip_len*.55 for p in picked):
            picked.append(c)
        if len(picked)>=count: break
    if not picked and segments:
        s=segments[0]; picked=[{"start":s["start"],"end":min(duration,s["start"]+clip_len),"score":50,"text":s["text"],"reasons":["fallback transcript segment"]}]
    return sorted(picked,key=lambda x:x["start"])

def make_ass(words, start, end, out_path, style="Karaoke"):
    # ASS karaoke timing uses centiseconds and is burned by FFmpeg subtitles.
    lines=[]
    for w in words:
        if w["end"] < start or w["start"] > end: continue
        a=max(0,w["start"]-start); b=max(a+.04,min(end-start,w["end"]-start))
        cs=max(1,int((b-a)*100))
        text=w["text"].replace("{","").replace("}","").replace("\\","")
        lines.append((a, f"{{\\k{cs}}}{text}"))
    def ts(t):
        h=int(t//3600); m=int((t%3600)//60); s=t%60
        return f"{h}:{m:02d}:{s:05.2f}"
    chunks=[]
    for i in range(0,len(lines),7):
        part=lines[i:i+7]
        if not part: continue
        start_t=part[0][0]; end_t=part[-1][0]+.6
        phrase=" ".join(x[1] for x in part)
        chunks.append(f"Dialogue: 0,{ts(start_t)},{ts(min(end-start,end_t))},Default,,0,0,0,,{phrase}")
    header="""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Arial,76,&H00FFFFFF,&H0000D8FF,&H00101010,&H90000000,-1,0,1,5,2,2,70,70,220,1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    out_path.write_text(header+"\n".join(chunks),encoding="utf-8")

def crop_filter(path, out, clip, meta, face_track):
    fp=ffmpeg_path()
    start=clip["start"]; dur=clip["end"]-start
    # Dynamic face-aware center crop uses sampled Haar detections; fallback is center crop.
    if face_track:
        try:
            import cv2
            cap=cv2.VideoCapture(str(path))
            cascade=cv2.CascadeClassifier(cv2.data.haarcascades+"haarcascade_frontalface_default.xml")
            xs=[]; n=max(1,int(dur*1.5))
            for i in range(n):
                cap.set(cv2.CAP_PROP_POS_MSEC,(start+dur*i/n)*1000)
                ok,frame=cap.read()
                if not ok: continue
                gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
                faces=cascade.detectMultiScale(gray,1.1,4,minSize=(50,50))
                if len(faces):
                    f=max(faces,key=lambda z:z[2]*z[3]); xs.append((f[0]+f[2]/2)/frame.shape[1])
            cap.release()
            center=sum(xs)/len(xs) if xs else .5
        except Exception: center=.5
    else: center=.5
    # Crop 9:16 around estimated subject position; scale to 1080x1920.
    w,h=meta["width"],meta["height"]
    crop_h=h; crop_w=int(h*9/16)
    if crop_w>w: crop_w=w; crop_h=int(w*16/9)
    x=max(0,min(w-crop_w,int(center*w-crop_w/2)))
    vf=f"crop={crop_w}:{crop_h}:{x}:0,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
    ass=clip.get("ass")
    if ass:
        ass_path = str(ass).replace("\\", "/").replace(":", r"\:")
        vf += f",subtitles='{ass_path}'"
    cmd=[fp,"-y","-ss",str(start),"-i",str(path),"-t",str(dur),"-vf",vf,"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-b:a","160k","-movflags","+faststart",str(out)]
    run_cmd(cmd)

def gen_metadata(transcript, cliptext, style):
    words=re.findall(r"[A-Za-z0-9']+",cliptext)
    freq=Counter(w.lower() for w in words if len(w)>3)
    terms=[w for w,n in freq.most_common(8)]
    first=re.sub(r"\s+"," ",cliptext).strip()
    first=first[:110]
    if not first: first="The moment you need to see"
    titles=[
        first[:75].strip().rstrip(".,!?") + " 👀",
        "Wait Until You Hear This…",
        "The Moment Everything Clicks 🔥"
    ]
    hashtags = ["#shorts", "#viral", "#clips"] + ["#" + re.sub(r"[^A-Za-z0-9]", "", w.title()) for w in terms[:4]]
    hashtags=list(dict.fromkeys(hashtags))
    return titles,hashtags

st.markdown("""<div class="hero"><div class="brand">LMPD <span>AI</span></div>
<div class="sub">Turn long videos into short-form moments. Local-first creator studio.</div>
<div style="margin-top:14px"><span class="pill">AUTO CLIPPING</span><span class="pill">SMART RANKING</span><span class="pill">FACE-AWARE CROP</span><span class="pill">WORD CAPTIONS</span></div></div>""",unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## 🎛️ Studio settings")
    model=st.selectbox("Speech model",["base","tiny","small"],index=0,help="base is a practical starting point for 16 GB RAM. small is slower but may transcribe more accurately.")
    clip_count=st.slider("Clips to create",1,10,5)
    clip_len=st.slider("Clip length (seconds)",15,60,35,5)
    face=st.toggle("Face-aware vertical framing",value=True)
    karaoke=st.toggle("Animated word-by-word captions",value=True)
    st.caption("Runs on your PC using CPU processing. AMD GPU acceleration is not configured in this build.")
    st.markdown("---")
    st.caption("Viral scores are heuristic estimates, not predictions or guarantees.")

c1,c2=st.columns([1.35,.85],gap="large")
with c1:
    st.markdown("### 01 / Import your video")
    url=st.text_input("YouTube URL (only content you own or are authorized to edit)",placeholder="https://www.youtube.com/watch?v=…")
    uploaded=st.file_uploader("Or upload a video",type=["mp4","mov","mkv","webm"])
    st.caption("For YouTube links, follow the platform's terms and only download content you have permission to use.")
    go=st.button("✦  ANALYZE & CREATE CLIPS",use_container_width=True)
with c2:
    st.markdown("### 02 / Workflow")
    for a,b in [("01","Transcribe speech"),("02","Find candidate moments"),("03","Rank and score"),("04","Vertical crop + captions"),("05","Export MP4 + metadata")]:
        st.markdown(f"<div class='panel'><b style='color:#c4b5fd'>{a}</b>　{b}</div>",unsafe_allow_html=True)

if go:
    try:
        with st.status("Preparing your video…",expanded=True) as status:
            video=get_video(url,uploaded); st.write(f"Loaded: {video.name}")
            meta=probe(video); st.write(f"Duration: {meta['duration']:.1f}s · {meta['width']}×{meta['height']}")
            if meta["duration"]<=0: raise RuntimeError("Could not read video duration.")
            st.write("Transcribing speech with faster-whisper…")
            segs=transcribe(video,model)
            if not segs: raise RuntimeError("No speech detected. This version needs spoken audio to identify moments.")
            words=[w for s in segs for w in s["words"]]
            st.write("Ranking candidate moments…")
            clips=choose_clips(segs,meta["duration"],clip_count,clip_len)
            if not clips: raise RuntimeError("No suitable clip windows found.")
            st.write("Rendering vertical clips and animated captions…")
            progress=st.progress(0)
            for i,cl in enumerate(clips):
                name=f"clutch_clip_{i+1:02d}.mp4"; target=OUT/name
                if karaoke and words:
                    ass=WORK/f"clip_{i+1:02d}.ass"; make_ass(words,cl["start"],cl["end"],ass); cl["ass"]=ass
                crop_filter(video,target,cl,meta,face)
                cl["file"]=target
                progress.progress((i+1)/len(clips))
            metadata=[]
            for i,cl in enumerate(clips):
                titles,tags=gen_metadata(" ".join(s["text"] for s in segs),cl["text"],"")
                metadata.append({"clip":cl["file"].name,"score":cl["score"],"titles":titles,"hashtags":tags,"start":cl["start"],"end":cl["end"],"reasons":cl["reasons"]})
            (OUT/"clip_metadata.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8")
            (OUT/"transcript.txt").write_text("\n".join(s["text"] for s in segs),encoding="utf-8")
            status.update(label="Your clips are ready!",state="complete",expanded=False)
        st.success(f"Created {len(clips)} clips in the outputs folder.")
        st.markdown("### ✦ Your generated clips")
        for i,cl in enumerate(clips):
            with st.container(border=True):
                left,right=st.columns([1,1.5])
                with left:
                    st.video(str(cl["file"]))
                with right:
                    st.markdown(f"**Clip {i+1}** · {cl['start']:.1f}s–{cl['end']:.1f}s")
                    st.metric("Estimated moment score",f"{cl['score']}/100")
                    st.caption("Why it ranked: "+(", ".join(cl["reasons"]) if cl["reasons"] else "general transcript signals"))
                    titles,tags=gen_metadata("",cl["text"],"")
                    st.markdown("**Title ideas**")
                    for t in titles: st.write("• "+t)
                    st.markdown("**Hashtags**")
                    st.write(" ".join(tags))
                    st.download_button("⬇ Download MP4",data=cl["file"].read_bytes(),file_name=cl["file"].name,mime="video/mp4",key=f"dl{i}")
        st.info(f"All files are also saved in: {OUT}")
    except Exception as e:
        st.error(f"Could not finish processing: {e}")
        st.caption("If this is an installation error, close the app and run run.bat again. For help, copy the full error message.")

st.markdown("---")
st.markdown("<div class='smallmuted'>LMPD AI · Local creator workstation · V1–V6 integrated starter build</div>",unsafe_allow_html=True)
