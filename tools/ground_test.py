# Grounding sanity check on a synthetic 2560x1440 image (no real screen leaves the PC).
# Draws buttons at known places, asks the grounder for coordinates, prints error in px
# for two interpretations: 0-1000 normalized and absolute pixels.
import base64, io, os, re, sys, time
from PIL import Image, ImageDraw, ImageFont
from openai import OpenAI
key = os.environ.get("GATEWAY_KEY", "")
model = sys.argv[1] if len(sys.argv) > 1 else "cloud-qwen3-vl-plus"
W, H = 2560, 1440
img = Image.new("RGB", (W, H), (235, 235, 235))
d = ImageDraw.Draw(img)
try: font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 22)
except Exception: font = ImageFont.load_default()
targets = {"Сохранить": (300, 200), "Отмена": (2200, 1300), "HTTP-сервисы": (1280, 720), "api_test": (180, 1250)}
for label, (x, y) in targets.items():
    d.rectangle([x-70, y-18, x+70, y+18], fill=(255, 255, 255), outline=(90, 90, 90))
    d.text((x-60, y-12), label, fill=(0, 0, 0), font=font)
buf = io.BytesIO(); img.save(buf, "PNG"); b64 = base64.b64encode(buf.getvalue()).decode()
cli = OpenAI(base_url=os.environ.get("GATEWAY_URL", "http://127.0.0.1:4000/v1"), api_key=key)
for label, (x, y) in targets.items():
    q = f"Query:the button labeled '{label}'\nOutput only the coordinate of one point in your response.\n"
    t0 = time.time()
    try:
        r = cli.chat.completions.create(model=model, temperature=0, messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}, {"type": "text", "text": q}]}])
        txt = r.choices[0].message.content
    except Exception as e:
        print(label, "ERR", e); continue
    n = [int(v) for v in re.findall(r"\d+", txt)][:2]
    dt = time.time() - t0
    if len(n) < 2: print(label, "no coords:", txt); continue
    nx, ny = n[0] * W / 1000, n[1] * H / 1000
    print(f"{label:14s} true=({x},{y}) raw={txt.strip()[:60]!r} | as 0-1000 -> ({nx:.0f},{ny:.0f}) err={((nx-x)**2+(ny-y)**2)**.5:.0f}px | as px err={((n[0]-x)**2+(n[1]-y)**2)**.5:.0f}px | {dt:.1f}s")
