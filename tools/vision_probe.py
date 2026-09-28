# Does a gateway model accept images? Sends the synthetic test image, asks what the buttons say.
import base64, io, os, re, sys
from PIL import Image, ImageDraw
from openai import OpenAI
key = os.environ.get("GATEWAY_KEY", "")
img = Image.new("RGB", (800, 400), (235, 235, 235)); d = ImageDraw.Draw(img)
d.rectangle([100, 100, 300, 150], fill="white", outline="black"); d.text((120, 115), "SAVE-42", fill="black")
b = io.BytesIO(); img.save(b, "PNG"); u = "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()
cli = OpenAI(base_url=os.environ.get("GATEWAY_URL", "http://127.0.0.1:4000/v1"), api_key=key)
for m in sys.argv[1:]:
    try:
        r = cli.chat.completions.create(model=m, messages=[{"role": "user", "content": [{"type": "image_url", "image_url": {"url": u}}, {"type": "text", "text": "What text is on the button? Answer with the text only."}]}])
        print(m, "->", r.choices[0].message.content.strip()[:80])
    except Exception as e:
        print(m, "ERR", str(e)[:200])
