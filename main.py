from fastapi import FastAPI, HTTPException
import torch, subprocess, shutil
from pathlib import Path

app = FastAPI(title="GPU Worker", version="2.1.0")
WORKSPACE = Path("/workspace")
WORKSPACE.mkdir(exist_ok=True)

@app.get("/api/gpu/info")
def gpu_info():
    cuda_ok = torch.cuda.is_available()
    result = None
    if cuda_ok:
        result = (torch.tensor([1,2,3], device="cuda") + torch.tensor([10,10,10], device="cuda")).tolist()
    return {
        "status": "ok",
        "cuda_available": cuda_ok,
        "gpu_name": torch.cuda.get_device_name(0) if cuda_ok else None,
        "tensor_test": {"result": result, "expected": [11,12,13], "pass": result == [11,12,13]},
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda if cuda_ok else None
    }

@app.get("/api/install/status")
def install_status():
    return {
        "status": "ok",
        "tools": {
            "torch": {"version": torch.__version__, "cuda": torch.cuda.is_available()},
            "ffmpeg": {"installed": shutil.which("ffmpeg") is not None},
            "imagemagick": {"installed": shutil.which("convert") is not None},
            "gtts": {"installed": True}
        }
    }

@app.post("/api/demo/create")
def create_demo():
    try:
        out = WORKSPACE / "workbot_demo.mp4"
        tmp = WORKSPACE / "demo_tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(exist_ok=True)

        # 6 scenes: (title, subtitle, duration_sec)
        scenes = [
            ("You ask an AI to...", "Write a report  Fix a bug  Send an email", 7),
            ("It gives you instructions.", "You still do the work yourself.", 5),
            ("WorkBot AI", "Not just talk. Work.", 6),
            ("Reads your spreadsheet.", "Analyzes data. Saves the report.", 8),
            ("Writes code. Runs tests.", "Deploys the fix. From one chat.", 8),
            ("WorkBot AI", "First month free. Start working today.", 11),
        ]

        # Step 1: Generate slide images with DejaVu font
        bg_colors = ["#0a0e27", "#1a1a3e", "#0d3b1e", "#1a1a3e", "#0a0e27", "#0d3b1e"]
        for i, (title, sub, dur) in enumerate(scenes):
            img = tmp / f"slide_{i}.png"
            cmd = [
                "convert", "-size", "1920x1080", f"xc:{bg_colors[i % len(bg_colors)]}",
                "-gravity", "center",
                "-font", "DejaVu-Sans-Bold",
                "-fill", "white",
                "-pointsize", "80",
                "-annotate", "+0-60", title,
                "-pointsize", "40",
                "-fill", "#b0b8d0",
                "-annotate", "+0+40", sub,
                str(img)
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode != 0 or not img.exists():
                raise RuntimeError(f"ImageMagick failed on scene {i}: " + (r.stderr or "no stderr")[-500:])

        # Step 2: Write concat file
        concat = tmp / "concat.txt"
        with open(concat, "w", encoding="utf-8") as f:
            for i, (_, _, dur) in enumerate(scenes):
                f.write(f"file '{tmp / f'slide_{i}.png'}'\n")
                f.write(f"duration {dur}\n")
            f.write(f"file '{tmp / 'slide_5.png'}'\n")

        # Step 3: FFmpeg NVENC render
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("ffmpeg not found")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat),
            "-vf", "fps=30,format=yuv420p",
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            str(out)
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

        # Fallback to CPU if NVENC fails
        if r.returncode != 0 or not out.exists():
            cmd[cmd.index("h264_nvenc")] = "libx264"
            cmd[cmd.index("p4")] = "medium"
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        # Verify output file
        if r.returncode != 0:
            raise RuntimeError("FFmpeg failed: " + (r.stderr or "no stderr")[-800:])

        if not out.exists():
            raise RuntimeError("Output file was not created")

        file_size = out.stat().st_size
        if file_size == 0:
            raise RuntimeError("Output file is empty (0 bytes)")

        # Cleanup temp
        shutil.rmtree(tmp, ignore_errors=True)

        return {
            "status": "ok",
            "file": "workbot_demo.mp4",
            "path": str(out),
            "size_bytes": file_size,
            "size_mb": round(file_size / (1024 * 1024), 2),
            "duration_seconds": sum(s[2] for s in scenes)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
def health():
    return {"status": "ok"}


import sys
sys.path.insert(0, "/workspace/opera_engine")
from task_queue import add as _qa, get as _qg, list_recent as _ql, admin_queue as _qad
from cost_tracker import get_status as _gs, ensure_user as _eu
from pydantic import BaseModel
from fastapi import Request, Form
from fastapi.responses import HTMLResponse, PlainTextResponse
import json, os as _os

# Auth helpers
_ADMIN_TOKEN = ""
_env_file = "/workspace/opera_engine/.env"
if _os.path.exists(_env_file):
    for _l in open(_env_file):
        if _l.startswith("ADMIN_TOKEN="):
            _ADMIN_TOKEN = _l.strip().split("=", 1)[1]

def _verify_admin(req):
    auth = req.headers.get("Authorization", "")
    return auth == f"Bearer {_ADMIN_TOKEN}"

def _get_user_from_token(req):
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    if token == _ADMIN_TOKEN:
        return "__admin__"
    try:
        users = json.loads(open("/workspace/opera_engine/data/users.json").read())
        for uid, u in users.items():
            if u.get("user_token") == token:
                return uid
    except:
        pass
    return None

@app.post("/api/op/task")
async def op_create_task(req: Request, prompt: str = Form(""), task_type: str = Form("summary")):
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    valid_types = {"document","summary","analysis","email","marketing","report","research","plan"}
    if task_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"invalid type: {task_type}")
    user = _get_user_from_token(req)
    if not user or user == "__admin__":
        raise HTTPException(status_code=401, detail="user token required")
    _eu(user, "basic")
    tid = _qa(user, task_type, {"topic": prompt})
    return {"status":"ok","task_id":tid,"user":user}

@app.get("/api/op/task/{task_id}")
async def op_get_task(task_id: str, req: Request):
    t = _qg(task_id)
    if not t:
        return {"status":"error","detail":"not found"}
    user = _get_user_from_token(req)
    if not user:
        raise HTTPException(status_code=401, detail="auth required")
    if user != "__admin__" and user != t.get("user",""):
        raise HTTPException(status_code=403, detail="forbidden")
    return {"status":"ok","task":{"id":t["id"],"state":t["state"],"error":t.get("error","")}}

@app.get("/api/op/task/{task_id}/result")
async def op_get_task_result(task_id: str, req: Request):
    t = _qg(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="not found")
    user = _get_user_from_token(req)
    if not user:
        raise HTTPException(status_code=401, detail="auth required")
    if user != "__admin__" and user != t.get("user",""):
        raise HTTPException(status_code=403, detail="forbidden")
    rp = t.get("result","")
    if not rp:
        return PlainTextResponse("(no result)")
    try:
        return PlainTextResponse(open(rp).read())
    except:
        return PlainTextResponse("(unavailable)")

@app.get("/api/op/plan/{user}")
async def op_get_plan(user: str, req: Request):
    u = _get_user_from_token(req)
    if not u or (u != "__admin__" and u != user):
        raise HTTPException(status_code=403, detail="forbidden")
    s = _gs(user)
    if not s:
        _eu(user, "basic")
        s = _gs(user)
    return {"status":"ok","plan":s}

@app.get("/api/op/admin")
async def op_admin(req: Request):
    if not _verify_admin(req):
        raise HTTPException(status_code=401, detail="unauthorized")
    return {"status":"ok","queue":_qad(),"tasks":_ql(10)}

@app.get("/api/op/admin/dashboard")
async def op_admin_dashboard(req: Request):
    if not _verify_admin(req):
        raise HTTPException(status_code=401, detail="unauthorized")
    import sys as _sys
    _sys.path.insert(0, "/workspace/opera_engine")
    from admin_dashboard import admin_html
    return HTMLResponse(admin_html())


import os as _os
import subprocess as _sp
import atexit as _ae

_executor_proc = None

def _start_executor():
    global _executor_proc
    lock_file = "/workspace/opera_engine/.executor.lock"
    try: _os.remove(lock_file)
    except: pass
    env = _os.environ.copy()
    env_file = "/workspace/opera_engine/.env"
    if _os.path.exists(env_file):
        for line in open(env_file):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip()); _os.environ.setdefault(k.strip(), v.strip())
    # Cloudflared tunnel auto-recovery
    _cf_script = "/workspace/start_tunnel.sh"
    if not _os.path.exists(_cf_script):
        with open(_cf_script, "w") as f:
            f.write("#!/bin/sh\necho 'checking tunnel...'\npkill -f 'cloudflared tunnel' 2>/dev/null\nsleep 2\ncloudflared tunnel run opera-api > /tmp/tunnel.log 2>&1 &\necho 'tunnel started'\n")
        _os.chmod(_cf_script, 0o755)
    # Check tunnel every 60s via subprocess
    _sp.Popen(["sh", "-c", "while sleep 60; do pgrep -f 'cloudflared tunnel run' > /dev/null || (pkill -f cloudflared 2>/dev/null; sleep 2; cloudflared tunnel run opera-api > /tmp/tunnel.log 2>&1 &); done"], env=env, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
    
    try:
        _executor_proc = _sp.Popen(["python3", "/workspace/opera_engine/executor.py"], env=env, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        with open(lock_file, "w") as f: f.write(str(_executor_proc.pid))
        print(f"Executor auto-started (PID: {_executor_proc.pid})")
    except Exception as e:
        print(f"Executor start failed: {e}")

def _stop_executor():
    global _executor_proc
    if _executor_proc:
        _executor_proc.terminate()
        try: _executor_proc.wait(timeout=5)
        except: pass

_ae.register(_stop_executor)
_start_executor()


import secrets as _sec

@app.post("/api/op/user")
async def op_create_user(req: Request):
    """사용자 생성 + user_token 발급"""
    body = await req.json() if req.headers.get("content-type","").startswith("application/json") else {}
    plan = body.get("plan", "free")
    valid_plans = {"free", "basic", "pro", "ent1", "ent2"}
    if plan not in valid_plans:
        plan = "free"
    
    uid = "user_" + _sec.token_hex(8)
    token = "usr_" + _sec.token_hex(16)
    
    users = json.loads(open("/workspace/opera_engine/data/users.json").read())
    users[uid] = {
        "plan": plan, "tokens": 500 if plan == "basic" else 30,
        "cost_used": 0.0, "month_start": __import__("time").time(),
        "user_token": token, "tokens_purchased": 0, "annual": False
    }
    open("/workspace/opera_engine/data/users.json","w").write(json.dumps(users, indent=2))
    
    return {"status":"ok","user_id":uid,"user_token":token,"plan":plan}

@app.post("/api/paypal/create-order")
async def op_create_order(req: Request):
    """PayPal 결제 주문 생성"""
    body = await req.json()
    plan = body.get("plan", "")
    import sys as _sys; _sys.path.insert(0, "/workspace/opera_engine")
    from paypal_handler import PLANS, get_access_token
    tk = get_access_token()
    if not tk:
        return {"status":"error","detail":"paypal not configured"}
    if plan not in PLANS:
        return {"status":"error","detail":"invalid plan"}
    price = PLANS[plan]["price"]
    order = {"intent":"CAPTURE","purchase_units":[{"amount":{"currency_code":"USD","value":str(price)},"description":f"OPERA AI {plan} plan"}]}
    import urllib.request as _ur
    mode = __import__("os").environ.get("PAYPAL_MODE","sandbox")
    base = "https://api-m.sandbox.paypal.com" if mode == "sandbox" else "https://api-m.paypal.com"
    req2 = _ur.Request(f"{base}/v2/checkout/orders",
        data=json.dumps(order).encode(),
        headers={"Content-Type":"application/json","Authorization":f"Bearer {tk}"})
    r = json.loads(_ur.urlopen(req2,timeout=15).read())
    return {"status":"ok","order_id":r.get("id",""),"approval_url":next((l["href"] for l in r.get("links",[]) if l["rel"]=="approve"),"")}


@app.get("/api/op/test")
async def op_test():
    import sys as _s; _s.path.insert(0, "/workspace/opera_engine")
    import importlib as _il
    mod = _il.import_module("test_dashboard")
    from fastapi.responses import HTMLResponse
    return HTMLResponse(mod.get_queue_stats())


@app.get("/api/op/test")
async def op_test():
    import sys
    sys.path.insert(0, "/workspace/opera_engine")
    from test_dashboard import get_queue_stats
    from fastapi.responses import HTMLResponse
    return HTMLResponse(get_queue_stats())


@app.get("/api/paypal/plans")
async def op_plans():
    import sys as _s; _s.path.insert(0, "/workspace/opera_engine")
    from paypal_handler import PLANS, TOKEN_PACKS
    return {"status":"ok","plans":{k:{"price":v["price"],"tokens":v["tokens"]} for k,v in PLANS.items()},"token_packs":{k:{"price":v["price"],"tokens":v["tokens"]} for k,v in TOKEN_PACKS.items()}}


# --- PayPal capture + webhook 수신 ---

@app.post("/api/paypal/capture-order")
async def op_capture_order(req: Request):
    """PayPal order capture (Sandbox 직접 캡처)"""
    import sys as _s; _s.path.insert(0, "/workspace/opera_engine")
    from paypal_handler import PLANS, get_access_token
    import urllib.request as _ur, os as _os, json as _json, time as _time
    
    body = await req.json()
    order_id = body.get("order_id", "")
    user_id = body.get("user_id", "")
    user_token = body.get("user_token", "")
    
    if not order_id:
        return {"status":"error","detail":"order_id required"}
    
    tk = get_access_token()
    if not tk:
        return {"status":"error","detail":"paypal not configured"}
    
    mode = _os.environ.get("PAYPAL_MODE", "sandbox")
    base = "https://api-m.sandbox.paypal.com" if mode == "sandbox" else "https://api-m.paypal.com"
    
    # 1. Get order details first
    try:
        req_get = _ur.Request(f"{base}/v2/checkout/orders/{order_id}",
            headers={"Authorization": f"Bearer {tk}", "Content-Type": "application/json"})
        order_info = _json.loads(_ur.urlopen(req_get, timeout=10).read())
        order_status = order_info.get("status", "")
    except Exception as e:
        order_status = "UNKNOWN"
    
    amount = 29.00  # default BASIC
    plan_name = "basic"
    
    # 2. Try capture
    capture_success = False
    try:
        capture_req = _ur.Request(f"{base}/v2/checkout/orders/{order_id}/capture",
            data=b"{}",
            headers={"Authorization": f"Bearer {tk}", "Content-Type": "application/json"})
        capture_res = _json.loads(_ur.urlopen(capture_req, timeout=10).read())
        capture_id = capture_res.get("id", "") or capture_res.get("purchase_units", [{}])[0].get("payments", {}).get("captures", [{}])[0].get("id", f"sim_{_time.time()}")
        status = capture_res.get("status", "COMPLETED")
        if status in ("COMPLETED", "APPROVED"):
            capture_success = True
            transaction_id = capture_id
    except Exception as e:
        # Sandbox 모드: capture 실패 시에도 payments 기록 (시뮬레이션)
        if mode == "sandbox":
            capture_success = True
            transaction_id = f"sim_capture_{_time.time()}"
            status = "COMPLETED"
        else:
            return {"status":"error","detail":f"capture failed: {str(e)}"}
    
    if not capture_success:
        return {"status":"error","detail":"capture not completed"}
    
    # 3. payments.json 기록
    payments_file = "/workspace/opera_engine/data/payments.json"
    payments = []
    if _os.path.exists(payments_file):
        payments = _json.loads(open(payments_file).read())
    
    # 중복 체크 (transaction_id)
    for p in payments:
        if p.get("transaction_id") == transaction_id:
            return {"status":"ok","detail":"duplicate capture"}
    
    payment_entry = {
        "user_id": user_id or "sandbox_test",
        "plan": plan_name,
        "amount": amount,
        "tokens_added": PLANS[plan_name]["tokens"] if plan_name in PLANS else 500,
        "order_id": order_id,
        "transaction_id": transaction_id,
        "paypal_event_id": f"evt_capture_{transaction_id}",
        "status": status,
        "created_at": _time.time()
    }
    payments.append(payment_entry)
    open(payments_file, "w").write(_json.dumps(payments, indent=2))
    
    # 4. users.json plan 업그레이드
    tokens = PLANS[plan_name]["tokens"] if plan_name in PLANS else 500
    users_file = "/workspace/opera_engine/data/users.json"
    if _os.path.exists(users_file):
        users = _json.loads(open(users_file).read())
        matched = False
        # Try user_id first, then user_token
        for uid, u in users.items():
            if uid == user_id or u.get("user_token", "") == user_token:
                users[uid]["plan"] = plan_name
                users[uid]["tokens"] = users[uid].get("tokens", 0) + tokens
                users[uid]["tokens_purchased"] = users[uid].get("tokens_purchased", 0) + tokens
                users[uid]["month_start"] = _time.time()
                users[uid]["cost_used"] = 0.0
                matched = True
                break
        if matched:
            open(users_file, "w").write(_json.dumps(users, indent=2))
    
    return {
        "status":"ok",
        "order_id": order_id,
        "transaction_id": transaction_id,
        "plan": plan_name,
        "tokens_granted": tokens,
        "user": user_id or "sandbox_test",
        "payment_recorded": True
    }

@app.get("/app")
async def op_app():
    import sys as _s; _s.path.insert(0, "/workspace/opera_engine")
    import importlib as _il
    mod = _il.import_module("onboarding_page")
    from fastapi.responses import HTMLResponse
    return HTMLResponse(mod.get_onboarding_page())

@app.get("/landing")
async def op_landing():
    from fastapi.responses import HTMLResponse
    p = "/workspace/opera_engine/landing_page.html"
    return HTMLResponse(open(p).read())

@app.get("/")
async def op_root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/landing")


@app.post("/api/waitlist")
async def op_waitlist(req: Request):
    import json, time, os
    body = await req.json()
    email = body.get("email", "").strip()
    platform = body.get("os", "both")
    if not email or "@" not in email:
        return {"status":"error","detail":"invalid email"}
    wl_file = "/workspace/opera_engine/data/waitlist.json"
    entries = []
    if os.path.exists(wl_file):
        entries = json.loads(open(wl_file).read())
    for e in entries:
        if e.get("email") == email:
            return {"status":"ok","detail":"already on waitlist","status":e.get("status","pending")}
    entries.append({"email": email, "os": platform, "status": "pending", "created_at": time.time()})
    open(wl_file, "w").write(json.dumps(entries, indent=2))
    return {"status":"ok","detail":"added to waitlist","count":len(entries),"status":"pending"}


# --- Waitlist Admin ---
@app.get("/waitlist-admin")
async def op_waitlist_admin():
    import sys as _s; _s.path.insert(0, "/workspace/opera_engine")
    import importlib as _il
    mod = _il.import_module("waitlist_admin")
    from fastapi.responses import HTMLResponse
    return HTMLResponse(mod.get_waitlist_admin())

# --- Analytics: track visit ---
@app.post("/api/analytics/visit")
async def op_track_visit(req: Request):
    import json, time, os
    body = await req.json() if req.headers.get("content-type","").startswith("application/json") else {}
    page = body.get("page","/")
    ref = body.get("ref","")
    ua = body.get("ua","")
    ip = req.client.host if req.client else ""
    visit = {"ip":ip,"page":page,"ref":ref,"ua":ua[:80],"ts":time.time(),"date":time.strftime("%Y-%m-%d")}
    visits_file = "/workspace/opera_engine/data/visits.json"
    visits = json.loads(open(visits_file).read()) if os.path.exists(visits_file) else []
    visits.append(visit)
    open(visits_file,"w").write(json.dumps(visits, indent=2))
    return {"status":"ok"}

# --- Analytics: track click ---
@app.post("/api/analytics/click")
async def op_track_click(req: Request):
    import json, time, os
    body = await req.json() if req.headers.get("content-type","").startswith("application/json") else {}
    btn = body.get("button","")
    click = {"button":btn,"ts":time.time(),"date":time.strftime("%Y-%m-%d")}
    clicks_file = "/workspace/opera_engine/data/clicks.json"
    clicks = json.loads(open(clicks_file).read()) if os.path.exists(clicks_file) else []
    clicks.append(click)
    open(clicks_file,"w").write(json.dumps(clicks, indent=2))
    return {"status":"ok"}

@app.get("/api/waitlist/count")
async def op_waitlist_count():
    import json, os
    f = "/workspace/opera_engine/data/waitlist.json"
    entries = json.loads(open(f).read()) if os.path.exists(f) else []
    return {"count": len(entries)}


@app.get("/assets/{filename}")
async def op_asset(filename: str):
    from fastapi.responses import FileResponse
    import os
    p = f"/workspace/opera_engine/assets/{filename}"
    if os.path.exists(p):
        return FileResponse(p)
    return {"error":"not found"}


@app.post("/api/waitlist/approve")
async def op_wl_approve(req: Request):
    import json, os, time
    body = await req.json()
    email = body.get("email","")
    action = body.get("action","approved")
    f = "/workspace/opera_engine/data/waitlist.json"
    entries = json.loads(open(f).read()) if os.path.exists(f) else []
    for e in entries:
        if e.get("email") == email:
            e["status"] = action
            e["approved_at"] = time.time()
            open(f,"w").write(json.dumps(entries, indent=2))
            return {"status":"ok","email":email,"new_status":action}
    return {"status":"error","detail":"not found"}
