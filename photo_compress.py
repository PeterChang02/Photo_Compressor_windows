#!/usr/bin/env python3
"""Photo Compressor: the complete source of the standalone Windows app.

Started by "Photo Compressor.exe", which embeds the bundled Python (runtime\\) and
runs this file. It starts a small local server bound to 127.0.0.1 and opens a
native window using Microsoft Edge WebView2 (via pywebview).

The same file also runs on macOS (system WebKit, RAW via sips).
"""
from __future__ import annotations
import importlib.util
import io
import os
import shutil
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
APP_DIR = Path(__file__).resolve().parent


def data_dir() -> Path:
    """Per-user folder for settings and logs."""
    if IS_WIN:
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "PhotoCompress"
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "PhotoCompress"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "PhotoCompress"


if sys.stderr is None:
    # GUI process without a console: send stray output to a log file instead of nowhere
    try:
        data_dir().mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(data_dir() / "PhotoCompress.log", "w", encoding="utf-8", buffering=1)
    except OSError:
        pass

from PIL import Image, ImageOps  # noqa: E402

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_OK = True
except ImportError:
    HEIC_OK = False

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".avif", ".jp2", ".j2k"}
if HEIC_OK:
    EXTS |= {".heic", ".heif"}

# Camera RAW (input only): LibRaw via rawpy on Windows, macOS's built-in sips (ImageIO) on a Mac
RAW_EXTS = {".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".dng", ".raf",
            ".orf", ".rw2", ".pef", ".srw", ".x3f", ".3fr", ".iiq", ".mos", ".mrw", ".erf",
            ".rwl", ".kdc", ".dcr", ".raw"}
SIPS_OK = IS_MAC and shutil.which("sips") is not None
RAWPY_OK = not SIPS_OK and importlib.util.find_spec("rawpy") is not None  # imported lazily (numpy is slow to load)
RAW_OK = SIPS_OK or RAWPY_OK
if RAW_OK:
    EXTS |= RAW_EXTS


def _open_raw_rawpy(src: Path, data_in: bytes | None) -> Image.Image:
    import rawpy
    try:
        with rawpy.imread(io.BytesIO(data_in) if data_in is not None else str(src)) as raw:
            rgb = raw.postprocess(use_camera_wb=True, output_bps=8)  # also applies the camera's rotation
    except Exception as e:
        msg = e.args[0] if e.args else e
        if isinstance(msg, bytes):  # LibRaw reports its messages as bytes
            msg = msg.decode("utf-8", "replace")
        raise RuntimeError("RAW 解码失败: " + str(msg)[:200])
    return Image.fromarray(rgb)


def open_image(src: Path, data_in: bytes | None = None) -> Image.Image:
    """Open an image and load it fully into memory. RAW files are decoded with rawpy or sips first."""
    if src.suffix.lower() not in RAW_EXTS:
        im = Image.open(io.BytesIO(data_in) if data_in is not None else src)
        im.load()
        return im
    if not RAW_OK:
        raise RuntimeError("RAW 解码不可用")
    if RAWPY_OK:
        return _open_raw_rawpy(src, data_in)
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        raw = src
        if data_in is not None:
            raw = Path(td) / ("in" + src.suffix)
            raw.write_bytes(data_in)
        tif = Path(td) / "out.tif"
        r = subprocess.run(["sips", "-s", "format", "tiff", str(raw), "--out", str(tif)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0 or not tif.exists():
            raise RuntimeError("RAW 解码失败: " + (r.stderr or r.stdout).strip()[:200])
        im = Image.open(tif)
        im.load()
        return im

FMT_EXT = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "AVIF": ".avif", "HEIF": ".heic",
           "TIFF": ".tif", "GIF": ".gif", "JPEG2000": ".jp2", "BMP": ".bmp"}
# Format names used by the UI -> Pillow format names
FMT_CHOICES = {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "avif": "AVIF", "heic": "HEIF",
               "tiff": "TIFF", "gif": "GIF", "jp2": "JPEG2000", "bmp": "BMP"}
EXT_FMT = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP", ".avif": "AVIF",
           ".heic": "HEIF", ".heif": "HEIF", ".tif": "TIFF", ".tiff": "TIFF", ".gif": "GIF",
           ".jp2": "JPEG2000", ".j2k": "JPEG2000", ".bmp": "BMP"}


@dataclass
class Options:
    mode: str = "quality"      # "quality" | "target"
    quality: int = 80          # 1-95
    target_kb: float = 500
    fmt: str = "keep"          # "keep" or a key of FMT_CHOICES
    max_side: int = 0          # 0 = no resizing
    keep_exif: bool = False


# ---------------- Core ----------------
def pick_format(src: Path, fmt: str) -> str:
    if fmt != "keep":
        out = FMT_CHOICES[fmt]
    else:
        out = EXT_FMT.get(src.suffix.lower(), "JPEG")
    if out == "HEIF" and not HEIC_OK:
        raise RuntimeError("HEIC 输出需要 pillow-heif")
    return out


def _flatten(img: Image.Image) -> Image.Image:
    """Remove transparency by compositing onto a white background."""
    if img.mode in ("RGBA", "LA", "P", "PA"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB") if img.mode != "RGB" else img


def prepare(img: Image.Image, out_fmt: str, max_side: int) -> Image.Image:
    img = ImageOps.exif_transpose(img)  # rotate upright according to the EXIF orientation
    if max_side and max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    has_alpha = "A" in img.mode or (img.mode == "P" and "transparency" in img.info)
    if out_fmt == "JPEG":
        img = _flatten(img)
    elif out_fmt in ("WEBP", "AVIF", "HEIF", "JPEG2000", "TIFF", "BMP", "PNG"):
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if has_alpha else "RGB")
    return img


def _palette(img: Image.Image, quality: int, max_colors: int = 256) -> Image.Image:
    colors = min(max_colors, max(16, int(256 * quality / 95)))
    method = Image.Quantize.FASTOCTREE if img.mode == "RGBA" else Image.Quantize.MEDIANCUT
    return img.quantize(colors=colors, method=method)


def encode(img: Image.Image, out_fmt: str, quality: int, exif: bytes | None) -> bytes:
    """Encode with quality 10-95. BMP has no compression setting and can only shrink by resizing."""
    buf = io.BytesIO()
    kw = {"exif": exif} if exif else {}
    if out_fmt == "JPEG":
        img.save(buf, "JPEG", quality=quality, optimize=True, progressive=True, **kw)
    elif out_fmt == "WEBP":
        img.save(buf, "WEBP", quality=quality, method=6, **kw)
    elif out_fmt == "AVIF":
        img.save(buf, "AVIF", quality=quality, speed=6, **kw)
    elif out_fmt == "HEIF":
        img.save(buf, "HEIF", quality=quality, **kw)
    elif out_fmt == "JPEG2000":
        ratio = 200 * (5 / 200) ** ((quality - 10) / 85)  # quality 10 -> 200:1 compression ratio, 95 -> 5:1
        img.save(buf, "JPEG2000", quality_mode="rates", quality_layers=[ratio], irreversible=True)
    elif out_fmt == "TIFF":
        if quality >= 95 or img.mode == "RGBA":  # lossless
            img.save(buf, "TIFF", compression="tiff_adobe_deflate", **kw)
        else:
            img.save(buf, "TIFF", compression="jpeg", quality=quality, **kw)
    elif out_fmt == "GIF":
        _palette(img.convert("RGBA") if "A" in img.mode else img.convert("RGB"), quality).save(
            buf, "GIF", optimize=True)
    elif out_fmt == "BMP":
        img.save(buf, "BMP")
    else:  # PNG: quality < 95 quantizes to a palette (lossy); otherwise lossless optimization
        im = _palette(img, quality) if quality < 95 else img
        im.save(buf, "PNG", optimize=True, **kw)
    return buf.getvalue()


def encode_to_target(img, out_fmt, target_bytes, exif):
    """Binary-search the quality; if even the lowest quality is too large, scale the image down step by step.
    Returns (bytes, quality, scale)."""
    scale = 1.0
    base = img
    best = None
    for _ in range(12):
        lo, hi, found = 10, 95, None
        while lo <= hi:
            mid = (lo + hi) // 2
            data = encode(img, out_fmt, mid, exif)
            if len(data) <= target_bytes:
                found = (data, mid)
                lo = mid + 1
            else:
                hi = mid - 1
            if best is None or len(data) < len(best[0]):
                best = (data, mid, scale)
        if found:
            return found[0], found[1], scale
        scale *= 0.85
        w, h = base.size
        img = base.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    return best  # target unreachable: return the smallest result


def compress_one(src, dst: Path, opt: Options, data_in: bytes | None = None):
    """Compress one image. src is the source path; if data_in is given, src only supplies the name/extension."""
    src = Path(src)
    orig = len(data_in) if data_in is not None else src.stat().st_size
    with open_image(src, data_in) as im:
        exif = None
        if opt.keep_exif:
            exif = im.info.get("exif")
            if not exif and len(im.getexif()):
                exif = im.getexif().tobytes()
        out_fmt = pick_format(src, opt.fmt)
        img = prepare(im, out_fmt, opt.max_side)
    if exif:  # pixels are already upright; drop the orientation tag so viewers don't rotate again
        e = Image.Exif()
        e.load(exif)
        e.pop(0x0112, None)
        exif = e.tobytes()
    dst = Path(dst).with_suffix(FMT_EXT[out_fmt])
    dst.parent.mkdir(parents=True, exist_ok=True)

    if opt.mode == "target":
        data, q, scale = encode_to_target(img, out_fmt, int(opt.target_kb * 1024), exif)
        note = f"q={q}" + (f" 缩放{scale:.0%}" if scale < 1 else "")
        if len(data) > int(opt.target_kb * 1024):
            note += " ⚠未达目标"
    else:
        data = encode(img, out_fmt, opt.quality, exif)
        note = f"q={opt.quality}"

    same_fmt = EXT_FMT.get(src.suffix.lower()) == out_fmt
    if len(data) >= orig and same_fmt and not opt.max_side:
        if data_in is not None:
            dst.write_bytes(data_in)
        else:
            shutil.copy2(src, dst)
        return src, dst, orig, orig, "原图已最优, 直接复制"
    dst.write_bytes(data)
    return src, dst, orig, len(data), note


# ---------------- UI ----------------
WEB_HTML = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>照片压缩</title>
<style>
:root{--bg:#f5f5f7;--card:#fff;--fg:#1d1d1f;--mut:#6e6e73;--line:#d2d2d7;--acc:#0071e3;--ok:#1a7f37;--bad:#c9372c;--drop:#eef5ff}
@media (prefers-color-scheme:dark){:root{--bg:#1c1c1e;--card:#2c2c2e;--fg:#f5f5f7;--mut:#a1a1a6;--line:#3a3a3c;--acc:#0a84ff;--ok:#30d158;--bad:#ff6961;--drop:#1f2a3a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei UI","Microsoft YaHei",sans-serif}
main{max-width:760px;margin:0 auto;padding:24px 16px 40px}
h1{font-size:22px;margin:0 0 16px;display:flex;justify-content:space-between;align-items:center;gap:12px}
.hd{display:flex;gap:8px;align-items:center}.hd>button{font-size:13px;font-weight:400;padding:5px 12px}
.lang{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:8px;overflow:hidden;font-size:13px;font-weight:500}
.lang button{border:0;border-radius:0;padding:5px 10px;background:var(--card);color:var(--mut)}
.lang i{color:var(--line);font-style:normal}
.lang button.sel{color:#fff;background:var(--acc)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:12px}
#drop{border:2px dashed var(--line);border-radius:12px;padding:28px;text-align:center;color:var(--mut);cursor:pointer;transition:.15s}
#drop.on{border-color:var(--acc);background:var(--drop);color:var(--fg)}
#drop b{color:var(--fg);font-size:15px}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:8px 0}
.row>label:first-child{min-width:96px;color:var(--mut)}
input[type=text],input[type=number],select{background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:6px 8px;font:inherit}
input[type=text]{flex:1;min-width:200px}input[type=number]{width:90px}
input[type=range]{flex:1;min-width:160px}
button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;padding:6px 12px;cursor:pointer}
button.pri{background:var(--acc);border-color:var(--acc);color:#fff;padding:8px 20px;font-weight:600}
button:disabled{opacity:.5;cursor:default}
.row.off{opacity:.4}.row.off input,.row.off select{cursor:not-allowed}
#unit{width:auto}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.seg button{border:0;border-radius:0}.seg button.sel{background:var(--acc);color:#fff}
#bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden;margin:10px 0}#bar i{display:block;height:100%;width:0;background:var(--acc);transition:width .2s}
#log{max-height:280px;overflow:auto;font:12px ui-monospace,Menlo,Consolas,"Microsoft YaHei UI",monospace;line-height:1.6}
#log .e{color:var(--bad)}#sum{font-weight:600;color:var(--ok);margin-top:6px}
.mut{color:var(--mut);font-size:12px}
body.loading main{visibility:hidden}
</style></head><body class="loading"><main>
<h1><span data-t="title"></span><span class="hd">
  <span class="lang"><button data-l="zh">中</button><i>/</i><button data-l="en">ENG</button></span>
</span></h1>
<div class="card">
  <div id="drop"><b data-t="drop"></b><br><span data-t="dropSub"></span></div>
  <input type="file" id="fi" multiple accept="image/*,__ACCEPT__" hidden>
  <div class="row" style="justify-content:center"><button id="pickIn" data-t="pickIn"></button></div>
  <div id="src" class="mut" style="text-align:center"></div>
</div>
<div class="card">
  <div class="row"><label data-t="mode"></label>
    <span class="seg"><button data-m="quality" class="sel" data-t="mQuality"></button><button data-m="target" data-t="mTarget"></button></span></div>
  <div class="row" id="qRow"><label data-t="quality"></label><input type="range" id="q" min="10" max="95" value="80"><span id="qv">80</span></div>
  <div class="row off" id="tRow"><label data-t="maxEach"></label><input type="number" id="kb" value="500" min="0" step="any" disabled><select id="unit" disabled><option value="B">B</option><option value="KB" selected>KB</option><option value="MB">MB</option><option value="GB">GB</option><option value="TB">TB</option></select></div>
  <div class="row"><label data-t="format"></label><select id="fmt"><option value="keep" data-t="fKeep"></option><option value="jpeg">JPEG</option><option value="png">PNG</option><option value="webp">WebP</option><option value="avif">AVIF</option><option value="heic" id="optHeic">HEIC</option><option value="tiff">TIFF</option><option value="gif">GIF</option><option value="jp2">JPEG 2000</option><option value="bmp" data-t="fBmp"></option></select>
    <label style="margin-left:12px;color:var(--mut)" data-t="side"></label><input type="number" id="side" value="0" min="0" step="160"> px <span class="mut" data-t="sideHint"></span></div>
  <div class="row"><label></label><label style="color:var(--fg)"><input type="checkbox" id="exif"> <span data-t="exif"></span></label></div>
  <div class="row"><label data-t="saveTo"></label><input type="text" id="out"><button id="pickOut" data-t="change"></button></div>
</div>
<div class="card">
  <div class="row"><button class="pri" id="go" data-t="go"></button><button id="stop" disabled data-t="stop"></button><button id="open" disabled data-t="open"></button></div>
  <div id="bar"><i></i></div><div id="log"></div><div id="sum"></div>
</div>
<p class="mut" id="foot"></p>
</main><script>
const T="__TOKEN__", $=s=>document.querySelector(s), EXT=__EXTS__;
const I18N={
 zh:{title:"照片压缩",drop:"把照片或文件夹拖到这里",dropSub:"或点击选择照片",pickIn:"选择文件夹…",
  mode:"压缩方式",mQuality:"指定质量",mTarget:"目标大小",quality:"质量",maxEach:"每张不超过",format:"输出格式",
  fKeep:"保持原格式",fBmp:"BMP（不压缩）",side:"最长边",sideHint:"(0 = 不缩放)",exif:"保留 EXIF（拍摄信息 / GPS）",
  saveTo:"保存到",change:"更改…",go:"开始压缩",stop:"停止",open:"打开输出文件夹",
  nFiles:n=>`已选 ${n} 张照片`, nDir:(d,n)=>`${d} · ${n} 张照片`, pickInP:"选择要压缩的文件夹", pickOutP:"选择保存位置",
  needSrc:"先拖入照片或选择文件夹", needOut:"请填写保存位置", minSize:"目标大小至少 1 KB",
  sum:(stopped,n,a,b,save,fail)=>`${stopped?"已停止，":"完成 "}${n} 张：${a} → ${b}`+(save!==null?`（节省 ${save}%）`:"")+(fail?`，失败 ${fail} 张`:""),
  heicOn:"已支持 HEIC", heicOff:"HEIC 未启用", raw:" · 已支持相机 RAW（CR2/CR3/NEF/ARW/DNG/RAF 等，仅作为输入）",
  outName:"压缩_"},
 en:{title:"Photo Compressor",drop:"Drop photos or folders here",dropSub:"or click to choose photos",pickIn:"Choose Folder…",
  mode:"Mode",mQuality:"Quality",mTarget:"Target Size",quality:"Quality",maxEach:"Max per photo",format:"Output Format",
  fKeep:"Keep Original",fBmp:"BMP (uncompressed)",side:"Longest Side",sideHint:"(0 = no resize)",exif:"Keep EXIF (camera info / GPS)",
  saveTo:"Save To",change:"Change…",go:"Compress",stop:"Stop",open:"Open Output Folder",
  nFiles:n=>`${n} photo${n===1?"":"s"} selected`, nDir:(d,n)=>`${d} · ${n} photo${n===1?"":"s"}`, pickInP:"Choose a folder to compress", pickOutP:"Choose where to save",
  needSrc:"Drop photos or choose a folder first", needOut:"Please set an output folder", minSize:"Target size must be at least 1 KB",
  sum:(stopped,n,a,b,save,fail)=>`${stopped?"Stopped. ":"Done: "}${n} photo${n===1?"":"s"}, ${a} → ${b}`+(save!==null?` (saved ${save}%)`:"")+(fail?`, ${fail} failed`:""),
  heicOn:"HEIC supported", heicOff:"HEIC unavailable", raw:" · Camera RAW supported (CR2/CR3/NEF/ARW/DNG/RAF…, input only)",
  outName:"Compressed_"}};
let L="zh", info={}, srcDesc=null, lastSum=null;
const t=k=>I18N[L][k];
const pj=(a,b)=>a.replace(/[\\/]+$/,"")+(info.sep||"/")+b;  // join paths with the OS separator
function applyLang(){
  document.documentElement.lang=L==="zh"?"zh":"en"; document.title=t("title");
  document.querySelectorAll("[data-t]").forEach(el=>el.textContent=t(el.dataset.t));
  document.querySelectorAll(".lang button").forEach(b=>b.classList.toggle("sel",b.dataset.l===L));
  if(info.stamp!==undefined){ $("#foot").textContent=(info.heic?t("heicOn"):t("heicOff"))+(info.raw?t("raw"):"");
    const other=I18N[L==="zh"?"en":"zh"].outName; const o=$("#out").value;
    if(o===pj(info.dl,other+info.stamp)) $("#out").value=pj(info.dl,t("outName")+info.stamp); }
  if(srcDesc) $("#src").textContent=srcDesc();
  if(lastSum) $("#sum").textContent=lastSum();
}
document.querySelectorAll(".lang button").forEach(b=>b.onclick=()=>{ if(L===b.dataset.l)return; L=b.dataset.l; applyLang(); api("lang",{set:L}).catch(()=>{}); });
["dragover","drop"].forEach(ev=>document.addEventListener(ev,e=>e.preventDefault()));
const api=(p,q={},body)=>fetch(`/api/${p}?`+new URLSearchParams({t:T,...q}),{method:body!==undefined||p!=="info"&&p!=="list"?"POST":"GET",body}).then(r=>r.json());
let mode="quality", src=null, stopping=false, running=false;
applyLang();
api("info").then(i=>{ info=i; L=i.lang||"zh"; $("#out").value=pj(i.dl,I18N[L].outName+i.stamp); if(!i.heic) $("#optHeic").disabled=true; applyLang(); })
  .finally(()=>document.body.classList.remove("loading"));
document.querySelectorAll(".seg button").forEach(b=>b.onclick=()=>{mode=b.dataset.m;document.querySelectorAll(".seg button").forEach(x=>x.classList.toggle("sel",x===b));applyMode();});
function applyMode(){ const q=mode==="quality";
  $("#qRow").classList.toggle("off",!q); $("#tRow").classList.toggle("off",q);
  $("#q").disabled=!q; $("#kb").disabled=q; $("#unit").disabled=q; }
applyMode();
// Unit conversion (base 1024): after input, switch to the best-fitting unit, e.g. 1024 KB -> 1 MB, 0.5 MB -> 512 KB.
// Changing the unit manually keeps the number unchanged.
const UNITS=["B","KB","MB","GB","TB"], r2=v=>Math.round(v*100)/100;
function sizeKB(){ const v=parseFloat($("#kb").value)||0; return v*Math.pow(1024,UNITS.indexOf($("#unit").value))/1024; }
function normalize(){ let v=parseFloat($("#kb").value); if(!(v>0)) return;
  let i=UNITS.indexOf($("#unit").value);
  while(v>=1024 && i<UNITS.length-1){ v/=1024; i++; }
  while(v<1 && i>0){ v*=1024; i--; }
  $("#unit").value=UNITS[i]; $("#kb").value = i===0 ? Math.round(v) : r2(v); }
$("#kb").addEventListener("change",normalize);
$("#kb").addEventListener("keydown",e=>{ if(e.key==="Enter") normalize(); });
$("#q").oninput=e=>$("#qv").textContent=e.target.value;
const okExt=n=>EXT.includes(n.slice(n.lastIndexOf(".")).toLowerCase());
function setFiles(list){ list=list.filter(x=>okExt(x.rel)); src={type:"files",files:list}; srcDesc=()=>t("nFiles")(list.length); $("#src").textContent=srcDesc(); }
$("#drop").onclick=()=>$("#fi").click();
$("#fi").onchange=e=>setFiles([...e.target.files].map(f=>({file:f,rel:f.name})));
["dragenter","dragover"].forEach(ev=>$("#drop").addEventListener(ev,e=>{e.preventDefault();$("#drop").classList.add("on")}));
["dragleave","drop"].forEach(ev=>$("#drop").addEventListener(ev,e=>{e.preventDefault();$("#drop").classList.remove("on")}));
async function walk(entry,prefix,out){
  if(entry.isFile){ await new Promise(r=>entry.file(f=>{out.push({file:f,rel:prefix+f.name});r()},r)); }
  else if(entry.isDirectory){ const rd=entry.createReader(); let batch;
    do{ batch=await new Promise(r=>rd.readEntries(r,()=>r([]))); for(const e of batch) await walk(e,prefix+entry.name+"/",out);}while(batch.length); }
}
$("#drop").addEventListener("drop",async e=>{ const out=[]; const ents=[...e.dataTransfer.items].map(i=>i.webkitGetAsEntry&&i.webkitGetAsEntry()).filter(Boolean);
  if(ents.length){ for(const en of ents) await walk(en,"",out); } else [...e.dataTransfer.files].forEach(f=>out.push({file:f,rel:f.name}));
  setFiles(out); });
$("#pickIn").onclick=async()=>{ const r=await api("pick",{prompt:t("pickInP")}); if(!r.path)return;
  const l=await api("list",{dir:r.path}); src={type:"dir",dir:r.path,files:l.files}; $("#out").value=l.out;
  srcDesc=()=>t("nDir")(r.path,l.files.length); $("#src").textContent=srcDesc(); };
$("#pickOut").onclick=async()=>{ const r=await api("pick",{prompt:t("pickOutP")}); if(r.path)$("#out").value=r.path; };
$("#open").onclick=()=>api("open",{path:$("#out").value});
$("#stop").onclick=()=>{stopping=true};
const kb=b=>(b/1024).toFixed(0)+"KB", mb=b=>(b/1048576).toFixed(1)+"MB";
function log(s,err){const d=document.createElement("div");d.textContent=s;if(err)d.className="e";$("#log").appendChild(d);$("#log").scrollTop=1e9;}
$("#go").onclick=async()=>{
  if(!src||!src.files.length) return alert(t("needSrc"));
  const out=$("#out").value.trim(); if(!out) return alert(t("needOut"));
  normalize(); if(mode==="target" && sizeKB()<1) return alert(t("minSize"));
  const o=JSON.stringify({mode,quality:+$("#q").value,target_kb:sizeKB(),fmt:$("#fmt").value,max_side:+$("#side").value,keep_exif:$("#exif").checked});
  running=true;stopping=false;$("#go").disabled=true;$("#stop").disabled=false;$("#log").innerHTML="";$("#sum").textContent="";lastSum=null;
  const items=src.files.slice(), n=items.length; let done=0,a=0,b=0,fail=0;
  const one=async it=>{
    const r= src.type==="dir" ? await api("path",{src:pj(src.dir,it),rel:it,out,o,lang:L})
                              : await api("upload",{rel:it.rel,out,o,lang:L},it.file);
    done++; $("#bar i").style.width=(done/n*100)+"%";
    if(r.error){fail++;log(`✗ ${r.name}: ${r.error}`,1);}
    else{a+=r.orig;b+=r.new;log(`${r.name}: ${kb(r.orig)} → ${kb(r.new)} (${Math.round((1-r.new/r.orig)*100)}%↓) ${r.note}`);}
  };
  const worker=async()=>{ while(items.length&&!stopping){ try{await one(items.shift());}catch(e){fail++;log("✗ "+e,1);} } };
  await Promise.all(Array.from({length:__WORKERS__},worker));
  const st=stopping, ok=done-fail, A=a, B=b, F=fail;
  lastSum=()=>t("sum")(st,ok,mb(A),mb(B),A?Math.round((1-B/A)*100):null,F); $("#sum").textContent=lastSum();
  running=false;$("#go").disabled=false;$("#stop").disabled=true;$("#open").disabled=false;
};
</script></body></html>"""


SETTINGS_F = data_dir() / "settings.json"


def load_settings() -> dict:
    try:
        import json
        return json.loads(SETTINGS_F.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(d: dict):
    try:
        import json
        SETTINGS_F.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_F.write_text(json.dumps(d), encoding="utf-8")
    except OSError:
        pass


def downloads_dir() -> Path:
    """The user's Downloads folder (on Windows it can be moved, so ask the shell)."""
    if IS_WIN:
        try:
            import ctypes
            import uuid
            guid = uuid.UUID("{374DE290-123F-4565-9164-39C4925E467B}")  # FOLDERID_Downloads
            buf = (ctypes.c_ubyte * 16).from_buffer_copy(guid.bytes_le)
            p = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(buf), 0, None, ctypes.byref(p)) == 0:
                path = p.value
                ctypes.windll.ole32.CoTaskMemFree(p)
                if path:
                    return Path(path)
        except Exception:
            pass
    return Path.home() / "Downloads"


def open_folder(p: Path):
    if IS_WIN:
        os.startfile(str(p))
    else:
        import subprocess
        subprocess.run(["open" if IS_MAC else "xdg-open", str(p)])


def show_error(msg: str):
    """Last-resort error report for a GUI process that has no console."""
    try:
        data_dir().mkdir(parents=True, exist_ok=True)
        (data_dir() / "error.log").write_text(msg, encoding="utf-8")
    except OSError:
        pass
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg[-1500:], "Photo Compressor", 0x10)
        except Exception:
            pass
    else:
        print(msg, file=sys.stderr)


def run_app_window(url, srv, win):
    """Open a native window (Edge WebView2 on Windows, WebKit on macOS); no browser involved."""
    icon = None
    if IS_WIN:
        import ctypes
        try:  # own taskbar group and icon instead of Python's
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PeterChang02.PhotoCompressor")
        except Exception:
            pass
        ico = APP_DIR / "AppIcon.ico"
        icon = str(ico) if ico.exists() else None
        # pythonnet must use the Python DLL this process already runs on
        if getattr(sys, "dllhandle", 0) and "PYTHONNET_PYDLL" not in os.environ:
            buf = ctypes.create_unicode_buffer(32768)
            if ctypes.windll.kernel32.GetModuleFileNameW(ctypes.c_void_p(sys.dllhandle), buf, 32768):
                os.environ["PYTHONNET_PYDLL"] = buf.value
    elif IS_MAC:
        try:  # menu bar name and Dock icon
            from AppKit import NSApplication, NSImage
            from Foundation import NSBundle
            info = NSBundle.mainBundle().infoDictionary()
            info["CFBundleName"] = info["CFBundleDisplayName"] = "照片压缩"
            icns = APP_DIR / "AppIcon.icns"
            if icns.exists():
                NSApplication.sharedApplication().setApplicationIconImage_(
                    NSImage.alloc().initWithContentsOfFile_(str(icns)))
        except Exception:
            pass
    import webview
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    lang = load_settings().get("lang", "zh")
    title = "Photo Compressor" if lang == "en" else "照片压缩"
    win[0] = webview.create_window(title, url, width=820, height=920, min_size=(640, 600))
    try:
        if IS_WIN:
            # WebView2 only: the legacy IE engine cannot run this page
            webview.start(gui="edgechromium", icon=icon, private_mode=True,
                          storage_path=str(data_dir() / "webview"))
        else:
            webview.start()
    finally:
        srv.shutdown()


def main():
    import json
    import secrets
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, urlparse

    token = secrets.token_urlsafe(16)
    workers = max(1, min(4, (os.cpu_count() or 2) - 1))
    page = (WEB_HTML.replace("__TOKEN__", token)
            .replace("__EXTS__", json.dumps(sorted(EXTS)))
            .replace("__ACCEPT__", ",".join(sorted(EXTS)))
            .replace("__WORKERS__", str(workers))).encode()
    win = [None]
    stamp = time.strftime("%Y%m%d-%H%M")
    EN = {"缩放": "scaled ", "⚠未达目标": "⚠ target not reached", "原图已最优, 直接复制": "already optimal, copied original",
          "非法路径": "invalid path", "RAW 解码失败": "RAW decode failed", "RAW 解码不可用": "RAW decoding unavailable",
          "HEIC 输出需要 pillow-heif": "HEIC output requires pillow-heif"}

    def tr(text: str, lang: str) -> str:
        if lang == "en":
            for k, v in EN.items():
                text = text.replace(k, v)
        return text

    def safe_join(base: str, rel: str) -> Path:
        base_p = Path(base).expanduser().resolve()
        p = (base_p / rel).resolve()
        if base_p != p and base_p not in p.parents:
            raise ValueError("非法路径")
        return p

    def pick_folder() -> str:
        import webview
        r = win[0].create_file_dialog(webview.FileDialog.FOLDER)
        p = (r[0] if r else "") if isinstance(r, (list, tuple)) else (r or "")
        return p.rstrip("/\\") if len(p.rstrip("/\\")) > 2 else p  # keep "C:\\" and "/"

    def to_opts(o: str) -> Options:
        d = json.loads(o)
        return Options(mode=d["mode"], quality=int(d["quality"]), target_kb=float(d["target_kb"]),
                       fmt=d["fmt"], max_side=int(d["max_side"]), keep_exif=bool(d["keep_exif"]))

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, obj, ctype="application/json", code=200):
            body = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def handle_any(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/":
                return self.send(page, "text/html; charset=utf-8")
            if not u.path.startswith("/api/") or q.get("t") != token:
                return self.send({"error": "forbidden"}, code=403)
            ep = u.path[5:]
            body = b""
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                body = self.rfile.read(n)
            try:
                if ep == "info":
                    return self.send({"dl": str(downloads_dir()), "sep": os.sep, "stamp": stamp, "heic": HEIC_OK, "raw": RAW_OK,
                                      "lang": load_settings().get("lang", "zh")})
                if ep == "lang":
                    lang = "en" if q.get("set") == "en" else "zh"
                    st = load_settings(); st["lang"] = lang; save_settings(st)
                    if win[0] is not None:
                        try:
                            win[0].set_title("Photo Compressor" if lang == "en" else "照片压缩")
                        except Exception:
                            pass
                    return self.send({"ok": 1})
                if ep == "pick":
                    return self.send({"path": pick_folder()})
                if ep == "list":
                    d = Path(q["dir"])
                    files = sorted(f.relative_to(d).as_posix() for f in d.rglob("*")
                                   if f.is_file() and f.suffix.lower() in EXTS)
                    return self.send({"files": files, "out": str(d.parent / (d.name + "_compressed"))})
                if ep == "open":
                    p = Path(q["path"]).expanduser()
                    p.mkdir(parents=True, exist_ok=True)
                    open_folder(p)
                    return self.send({"ok": 1})
                if ep in ("path", "upload"):
                    rel = q["rel"]
                    dst = safe_join(q["out"], rel)
                    opt = to_opts(q["o"])
                    try:
                        if ep == "path":
                            s, _, a, b, note = compress_one(Path(q["src"]), dst, opt)
                        else:
                            s, _, a, b, note = compress_one(Path(rel), dst, opt, data_in=body)
                        return self.send({"name": rel, "orig": a, "new": b, "note": tr(note, q.get("lang", "zh"))})
                    except Exception as e:
                        return self.send({"name": rel, "error": tr(str(e), q.get("lang", "zh"))})
                return self.send({"error": "unknown"}, code=404)
            except Exception as e:
                return self.send({"error": str(e)}, code=500)

        do_GET = do_POST = handle_any

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    run_app_window(url, srv, win)


if __name__ == "__main__":
    try:
        main()
        if IS_WIN:
            os._exit(0)  # don't wait on .NET / WebView2 threads once the window is closed
    except Exception:
        import traceback
        err = traceback.format_exc()
        hint = ""
        if IS_WIN and ("WebView2" in err or "edgechromium" in err.lower() or "clr" in err.lower()):
            hint = ("Photo Compressor needs the Microsoft Edge WebView2 Runtime and .NET Framework 4.7.2+.\n"
                    "Install WebView2: https://go.microsoft.com/fwlink/p/?LinkId=2124703\n\n")
        show_error(hint + err)
        os._exit(1)
