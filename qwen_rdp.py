# Open harness: Qwen (planner + grounder + verifier) drives 1C Configurator over agent-rdp.
# Brain = any OpenAI-compatible model on the local LiteLLM gateway (no Claude).
# Loop per subgoal: screenshot -> planner picks ONE action -> grounder gives point (0-1000 grid) -> execute
#                   -> fresh screenshot -> verifier answers yes/no "is the subgoal achieved?".
import base64, datetime, io, json, os, re, subprocess, sys, time
from PIL import Image
from openai import OpenAI

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(os.environ["APPDATA"], "npm", "agent-rdp.cmd")
KEY = os.environ.get("GATEWAY_KEY", "")
URL = os.environ.get("GATEWAY_URL", "http://127.0.0.1:4000/v1")
cli = OpenAI(base_url=URL, api_key=KEY, timeout=180)

task = json.load(open(sys.argv[1], encoding="utf-8"))
PLANNER = task.get("planner", "cloud-qwen3-vl-plus")
GROUNDER = task.get("grounder", "cloud-qwen3-vl-plus")
VERIFIER = task.get("verifier", PLANNER)
ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
RUN = os.path.join(HERE, "runs_rdp", ts + "_" + task.get("name", "task")); os.makedirs(RUN, exist_ok=True)
LOG = open(os.path.join(RUN, "run.log"), "a", encoding="utf-8")
def L(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s + "\n"); LOG.flush()

def rdp(*args, timeout=60):
    r = subprocess.run([EXE, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return (r.stdout + r.stderr).strip()

N = [0]
def shot(tag):
    N[0] += 1
    p = os.path.join(RUN, f"{N[0]:03d}_{tag}.png")
    rdp("screenshot", "--output", p)
    im = Image.open(p).convert("RGB"); return p, im

def b64(im, maxw=1920):
    if im.width > maxw: im = im.resize((maxw, int(im.height * maxw / im.width)))
    b = io.BytesIO(); im.save(b, "PNG"); return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()

def ask(model, im, text, max_tokens=800):
    t0 = time.time()
    r = cli.chat.completions.create(model=model, temperature=0, max_tokens=max_tokens, messages=[{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": b64(im)}}, {"type": "text", "text": text}]}])
    return (r.choices[0].message.content or "").strip(), time.time() - t0

GCROP = None
def ground(im, target):
    ox = oy = 0; src = im
    if GCROP:
        ox, oy = GCROP[0], GCROP[1]; src = im.crop(tuple(GCROP))
    txt, dt = ask(GROUNDER, src, f"Query:{target}\nOutput only the coordinate of one point in your response.\n", 60)
    n = [int(v) for v in re.findall(r"\d+", txt)][:2]
    if len(n) < 2: return None, txt, dt
    return (ox + round(n[0] * src.width / 1000), oy + round(n[1] * src.height / 1000)), txt, dt

# Context menu of a 1C field, offsets from the right-click point in px.
# Measured at 1920x1080, Windows scale 100%. Other resolution/DPI -> override in the task JSON ("menu_offsets").
MENU_OFFSETS = {"select_all": [55, 111], "paste": [55, 59]}
# After pasting, 1C applies the value only when the field loses focus: click a neutral label nearby.
CONFIRM_TARGET = "the grey label text 'Комментарий' on the left side of the properties window"
ALWAYS_BLOCKED = {"ctrl+s", "f7", "ctrl+f7", "delete", "alt+f4", "win+r", "ctrl+shift+s", "f5", "ctrl+f5"}

PLAN_PROMPT = """You operate 1C:Enterprise Configurator (Russian UI) on a remote Windows server, through screenshots.
Overall task: {task}
CURRENT SUBGOAL: {sub}
Rules: {rules}
Previous actions for this subgoal (most recent last): {hist}
Look at the screenshot. Choose exactly ONE next action to progress the CURRENT SUBGOAL.
Answer ONLY with a JSON object, no prose:
{{"thought": "<short>", "action": "click|double_click|right_click|set_field|paste_text|type|press|scroll_down|scroll_up|done",
  "target": "<precise visual description of the element to act on, e.g. 'the tree node labelled HTTP-сервисы in the right window'>",
  "text": "<text for type>", "keys": "<keys for press, e.g. enter, right, insert, down>"}}
"set_field" = put "text" into the input/value cell described in "target" (replaces its content and confirms) — all in one action. Prefer set_field whenever you need to put a value into a field. "paste_text" = insert multi-line "text" at the place described in "target" (e.g. an empty line inside a procedure in a code module).
Use "done" only if the subgoal is ALREADY visibly achieved on this screenshot."""

VERIFY_PROMPT = """Screenshot of 1C:Enterprise Configurator (Russian UI).
Question: is this condition TRUE on the screenshot right now? Condition: {check}
Answer with one word YES or NO, then a short reason."""

VCROP = None
def verify(im, check):
    if VCROP:
        im = im.crop(tuple(VCROP)); im = im.resize((im.width * 2, im.height * 2))
    txt, dt = ask(VERIFIER, im, VERIFY_PROMPT.format(check=check), 120)
    return txt.upper().startswith("YES") or txt.upper().startswith("ДА"), txt, dt

def parse_json(txt):
    m = re.search(r"\{.*\}", txt, re.S)
    if not m: return None
    try: return json.loads(m.group(0))
    except Exception:
        try: return json.loads(m.group(0).replace("'", '"'))
        except Exception: return None

L("RUN", ts, "planner", PLANNER, "grounder", GROUNDER, "verifier", VERIFIER)
rdp("automate", "window", "focus", "Конфигуратор")
MENU_OFFSETS.update(task.get("menu_offsets", {}))
CONFIRM_TARGET = task.get("confirm_target", CONFIRM_TARGET)
T0 = time.time(); budget = int(task.get("max_total_s", 1200))
results = []
for si, sg in enumerate(task["subgoals"], 1):
    sub, check = sg["goal"], sg["check"]
    VCROP = sg.get("verify_crop", task.get("verify_crop"))
    GCROP = sg.get("ground_crop", task.get("ground_crop"))
    allowed_keys = set(k.lower() for k in sg.get("allowed_keys", []))
    allow_type = sg.get("allow_type", False)
    rules = task.get("rules", "") + (" Typing text is allowed for this subgoal." if allow_type else " Do NOT type any text.")
    L(f"\n##### SUBGOAL {si}: {sub}\n      check: {check}")
    hist = []; ok = False
    p, im = shot(f"s{si}_start")
    ok, vtxt, vdt = verify(im, check); L(f"pre-check ({vdt:.1f}s): {vtxt[:160]}")
    for step in range(1, int(sg.get("max_steps", 8)) + 1):
        if ok or time.time() - T0 > budget: break
        if os.path.exists(os.path.join(HERE, "STOP")): L("STOP file"); break
        txt, pdt = ask(PLANNER, im, PLAN_PROMPT.format(task=task["task"], sub=sub, rules=rules, hist=json.dumps(hist[-6:], ensure_ascii=False)))
        a = parse_json(txt)
        L(f"-- step {si}.{step} plan ({pdt:.1f}s): {txt[:400]}")
        if not a: hist.append({"error": "unparseable"}); continue
        act = str(a.get("action", "")).lower()
        if act == "done":
            p, im = shot(f"s{si}_{step}_claimdone"); ok, vtxt, vdt = verify(im, check)
            L(f"   claims done; verifier ({vdt:.1f}s): {vtxt[:160]}"); hist.append({"action": "done", "verifier": vtxt[:80]})
            continue
        res = ""
        if act in ("click", "double_click", "right_click"):
            pt, gtxt, gdt = ground(im, a.get("target", ""))
            if not pt: L(f"   grounding failed: {gtxt}"); hist.append({"action": act, "error": "no point"}); continue
            cmd = {"click": "click", "double_click": "double-click", "right_click": "right-click"}[act]
            res = rdp("mouse", cmd, str(pt[0]), str(pt[1])); L(f"   {act} {pt} ({gdt:.1f}s ground raw={gtxt}) -> {res}")
        elif act == "set_field":
            # 1C Configurator ignores keyboard coming from agent-rdp, so: RDP clipboard + mouse only.
            if not allow_type: L("   BLOCKED: typing not allowed"); hist.append({"action": act, "error": "blocked"}); continue
            pt, gtxt, gdt = ground(im, a.get("target", ""))
            if not pt: L(f"   grounding failed: {gtxt}"); hist.append({"action": act, "error": "no point"}); continue
            rdp("clipboard", "set", str(a.get("text", "")))
            rdp("mouse", "click", str(pt[0]), str(pt[1])); time.sleep(0.6)
            rdp("mouse", "right-click", str(pt[0]), str(pt[1])); time.sleep(1.0)
            sx, sy = MENU_OFFSETS["select_all"]
            rdp("mouse", "click", str(pt[0] + sx), str(pt[1] + sy)); time.sleep(0.6)   # 'Выделить все'
            rdp("mouse", "right-click", str(pt[0]), str(pt[1])); time.sleep(1.2)
            # 1C field context menu: Вырезать / Копировать / Вставить ... -> 'Вставить' is the 3rd item, offset from MENU_OFFSETS
            mp = (pt[0] + MENU_OFFSETS["paste"][0], pt[1] + MENU_OFFSETS["paste"][1])
            _, im2 = shot(f"s{si}_{step}_menu")
            rdp("mouse", "click", str(mp[0]), str(mp[1])); time.sleep(0.8)
            _, im3 = shot(f"s{si}_{step}_pasted")
            cp, ctxt, cdt = ground(im3, CONFIRM_TARGET)
            if cp: rdp("mouse", "click", str(cp[0]), str(cp[1]))
            L(f"   set_field field={pt} paste={mp} confirm={cp} text={a.get('text')!r}")
        elif act == "paste_text":
            if not allow_type: L("   BLOCKED: typing not allowed"); hist.append({"action": act, "error": "blocked"}); continue
            pt, gtxt, gdt = ground(im, a.get("target", ""))
            if not pt: L(f"   grounding failed: {gtxt}"); hist.append({"action": act, "error": "no point"}); continue
            rdp("clipboard", "set", str(a.get("text", "")))
            rdp("mouse", "click", str(pt[0]), str(pt[1])); time.sleep(0.5)
            rdp("mouse", "right-click", str(pt[0]), str(pt[1])); time.sleep(1.2)
            _, im2 = shot(f"s{si}_{step}_ctx")
            x0, y0 = max(0, pt[0] - 50), max(0, pt[1] - 50)
            crop = im2.crop((x0, y0, min(im2.width, x0 + 450), min(im2.height, y0 + 600)))
            mp, mtxt, mdt = ground(crop, "the context menu item 'Вставить' (Paste)")
            if not mp: L(f"   paste item not found: {mtxt}"); hist.append({"action": act, "error": "no paste item"}); continue
            mp = (x0 + mp[0], y0 + mp[1])
            rdp("mouse", "click", str(mp[0]), str(mp[1]))
            L(f"   paste_text at {pt} menu item {mp} ({len(str(a.get('text','')))} chars)")
        elif act == "type":
            if not allow_type: L("   BLOCKED: typing not allowed"); hist.append({"action": "type", "error": "blocked"}); continue
            res = rdp("keyboard", "type", str(a.get("text", ""))); L(f"   type {a.get('text')!r} -> {res}")
        elif act == "press":
            k = str(a.get("keys", "")).lower().strip()
            if k in ALWAYS_BLOCKED and k not in allowed_keys: L(f"   BLOCKED key {k}"); hist.append({"action": "press", "keys": k, "error": "blocked"}); continue
            res = rdp("keyboard", "press", k); L(f"   press {k} -> {res}")
        elif act in ("scroll_down", "scroll_up"):
            pt, gtxt, gdt = ground(im, a.get("target", "") or "the tree in the right window")
            if pt: rdp("mouse", "move", str(pt[0]), str(pt[1]))
            res = rdp("scroll", "down" if act == "scroll_down" else "up"); L(f"   {act} at {pt} -> {res}")
        else:
            L("   unknown action"); hist.append({"error": "unknown action " + act}); continue
        time.sleep(float(sg.get("settle_s", 1.5)))
        p, im = shot(f"s{si}_{step}")
        ok, vtxt, vdt = verify(im, check)
        L(f"   verifier ({vdt:.1f}s): {vtxt[:160]}")
        hist.append({"action": act, "target": a.get("target"), "text": a.get("text"), "keys": a.get("keys"), "achieved": ok})
    L(f"SUBGOAL {si} -> {'OK' if ok else 'NOT ACHIEVED'}")
    results.append(ok)
    if not ok: break
L(f"\nRESULT {results}  total {time.time()-T0:.0f}s")
