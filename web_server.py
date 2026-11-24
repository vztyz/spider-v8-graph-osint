import os
import json
import urllib.parse
import uvicorn
import asyncio
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import shutil

# 🛡️ Отрубаем влияние системных прокси Windows на Requests и системные вызовы Python (Защита от утечки DNS)
for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'all_proxy', 'ALL_PROXY']:
    os.environ.pop(key, None)

try:
    import google.generativeai as genai
    from google.generativeai.types import GenerationConfig
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

from database import DatabaseManager

app = FastAPI(title="Spider V8 Web API")
db = DatabaseManager()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

base_dir = os.path.dirname(os.path.abspath(__file__))
web_dir = os.path.join(base_dir, "web")

if not os.path.exists(web_dir):
    os.makedirs(web_dir)

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

active_spiders = {}

async def db_poller():
    last_hash = None
    while True:
        try:
            def fetch_db():
                return db._execute("SELECT COUNT(*), SUM(LENGTH(ai_tags)) FROM channels WHERE status IN ('approved', 'enriching')", fetch=True)
            res = await asyncio.to_thread(fetch_db)
            current_hash = f"{res[0]}_{res[1]}" if res else "0_0"
            
            if last_hash is not None and current_hash != last_hash:
                await manager.broadcast({"action": "update_graph"})
                
            last_hash = current_hash
        except Exception:
            pass
        
        await asyncio.sleep(2)  

@app.on_event("startup")
async def startup_event():
    import sys
    loop = asyncio.get_running_loop()
    
    def custom_exception_handler(loop, context):
        exc = context.get('exception')
        if isinstance(exc, ConnectionResetError) and getattr(exc, 'winerror', None) == 10054:
            return 
        loop.default_exception_handler(context)
    
    loop.set_exception_handler(custom_exception_handler)

    db._execute("UPDATE profiles SET status = 'idle' WHERE status = 'running'")
    asyncio.create_task(db_poller())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/api/graph/micro")
def get_micro_graph():
    nodes_data, edges_data = db.get_graph_render_data()
    
    nodes = []
    valid_ids = set()
    for n in nodes_data:
        nodes.append({
            "id": n[0],
            "username": n[1] or "",
            "title": n[2] or n[1] or "Unknown",
            "subs": n[3] or 0,
            "tags": n[6] or "",
            "posts": n[7] or "Контент не собран или скрыт.",
            "category": n[9] or "Uncategorized"
        })
        valid_ids.add(n[0])
        
    links = []
    for e in edges_data:
        if e[0] in valid_ids and e[1] in valid_ids:
            links.append({
                "source": e[0],
                "target": e[1],
                "type": e[2]
            })
            
    return {"nodes": nodes, "links": links}

@app.get("/api/graph/macro")
def get_macro_graph():
    folders = db.get_graph_folders()
    edges = db.get_folder_edges()
    
    nodes = []
    valid_ids = set()
    for f in folders:
        nodes.append({
            "id": f[0], 
            "title": f[0].capitalize(),
            "ch_count": f[1],
            "subs": f[2],
            "tags": f[0] 
        })
        valid_ids.add(f[0])
        
    links = []
    for e in edges:
        if e[0] in valid_ids and e[1] in valid_ids:
            links.append({
                "source": e[0],
                "target": e[1],
                "weight": e[2],
                "type": "macro_link"
            })
        
    return {"nodes": nodes, "links": links}

import threading
from spider_core import SpiderWorker

def run_spider_in_thread(p_name, api_id, api_hash, proxy):
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    def log_cb(msg):
        if hasattr(app, 'loop') and app.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({"type": "log", "profile": p_name, "message": msg}), 
                app.loop
            )
        
    def status_cb(stat, err):
        db.update_profile_status(p_name, stat, err)
        if hasattr(app, 'loop') and app.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({"type": "status", "profile": p_name, "status": stat, "error": err}), 
                app.loop
            )

    worker = SpiderWorker(p_name, int(api_id), api_hash, db, proxy, log_cb, status_cb, False)
    active_spiders[p_name] = worker
    
    worker._loop = loop
    
    try:
        worker._main_task = loop.create_task(worker.start())
        loop.run_until_complete(worker._main_task)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        status_cb("error", str(e))
    finally:
        try:
            if worker.client.is_connected():
                loop.run_until_complete(worker.client.disconnect())
        except: pass
        status_cb("idle", "")
        try:
            del active_spiders[p_name]
        except KeyError:
            pass
        try:
            loop.close()
        except: pass

class SpiderTaskRequest(BaseModel):
    profile: str
    task_mode: str
    skip_setup: bool = False
    target_channel: str = ""
    main_channel: str = ""
    first_name: str = "User"
    last_name: str = ""
    channel_title: str = "My Blog"
    w_count: int = 3
    w_min: int = 5
    w_max: int = 15
    leadgen_delay_min: int = 5
    leadgen_delay_max: int = 15
    leadgen_daily_limit: int = 15
    is_private_request: bool = False

@app.post("/api/spider/start_task")
async def start_spider_task(req: SpiderTaskRequest):
    data = db.get_profile(req.profile)
    if not data or not data['api_id'] or not data['api_hash']:
        return {"status": "error", "message": "Invalid API ID/Hash"}
        
    if req.profile in active_spiders:
        return {"status": "error", "message": "Already running"}
        
    # 💾 Сохраняем настройки профиля в БД навсегда, чтобы не терять их при перезапуске
    db._execute("""
        UPDATE profiles 
        SET warmup_count=?, warmup_min=?, warmup_max=?, daily_limit=?, delay_min=?, delay_max=?, first_name=?, last_name=?, channel_title=?
        WHERE name=?
    """, (req.w_count, req.w_min, req.w_max, req.leadgen_daily_limit, req.leadgen_delay_min, req.leadgen_delay_max, req.first_name, req.last_name, req.channel_title, req.profile))
        
    active_spiders[req.profile] = "starting"
    app.loop = asyncio.get_running_loop()
    
    proxy = None
    if data['proxy_type'] != 'None' and data['proxy_addr']:
        addr_parts = data['proxy_addr'].split(':')
        if len(addr_parts) == 2:
            p_type = 'socks5' if 'socks5' in data['proxy_type'].lower() else 'http'
            proxy = {
                "proxy_type": p_type,
                "addr": addr_parts[0],
                "port": int(addr_parts[1]),
                "rdns": True
            }
            if data.get('proxy_user') and data.get('proxy_pass'):
                proxy["username"] = data['proxy_user']
                proxy["password"] = data['proxy_pass']
            
    t = threading.Thread(target=run_spider_task_in_thread, args=(
        req.profile, data['api_id'], data['api_hash'], proxy, req.task_mode, 
        req.skip_setup, req.target_channel, req.main_channel, 
        req.first_name, req.last_name, req.channel_title, 
        req.w_count, req.w_min, req.w_max, 
        req.leadgen_delay_min, req.leadgen_delay_max, req.leadgen_daily_limit,
        req.is_private_request
    ), daemon=True)
    t.start()
    return {"status": "ok"}

@app.post("/api/spider/stop_task/{profile_name}")
async def stop_spider_task(profile_name: str):
    if profile_name in active_spiders:
        worker = active_spiders[profile_name]
        if hasattr(worker, 'is_running'):
            worker.is_running = False
            if hasattr(worker, '_loop') and worker._loop.is_running():
                async def graceful_shutdown():
                    if hasattr(worker, 'client') and worker.client.is_connected():
                        await worker.client.disconnect()
                    for t in asyncio.all_tasks():
                        if t is not asyncio.current_task():
                            t.cancel()
                asyncio.run_coroutine_threadsafe(graceful_shutdown(), worker._loop)
        try:
            del active_spiders[profile_name]
        except KeyError:
            pass
    
    # Принудительно сбрасываем статус в БД, чтобы UI отреагировал мгновенно
    db.update_profile_status(profile_name, "idle", "")
    return {"status": "ok"}

def run_spider_task_in_thread(p_name, api_id, api_hash, proxy, task_mode, skip_setup=False, target_channel="", main_channel="", first_name="User", last_name="", channel_title="My Blog", w_count=3, w_min=5, w_max=15, leadgen_delay_min=5, leadgen_delay_max=15, leadgen_daily_limit=15, is_private_request=False):
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    def log_cb(msg):
        if hasattr(app, 'loop') and app.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({"type": "log", "profile": p_name, "message": msg}), 
                app.loop
            )
        
    def status_cb(stat, err):
        db.update_profile_status(p_name, stat, err)
        if hasattr(app, 'loop') and app.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({"type": "status", "profile": p_name, "status": stat, "error": err}), 
                app.loop
            )

    worker = SpiderWorker(p_name, int(api_id), api_hash, db, proxy, log_cb, status_cb, False)
    active_spiders[p_name] = worker
    
    worker._loop = loop

    async def run_wrapper():
        if task_mode in ["leadgen", "auto_leadgen"]:
            log_cb(f"⚙️ ЗАПУСК: Лимит {leadgen_daily_limit} шт/день | Пауза {leadgen_delay_min}-{leadgen_delay_max} мин | Прогрев {w_count} кан.")
            
        if task_mode == "scout":
            await worker.client.connect()
            if await worker.client.is_user_authorized():
                status_cb("running", "")
                profile_data = db.get_profile(p_name)
                seed = profile_data.get('seed_channel', '@ege_math_100')
                await worker.run_scout(seed)
            else:
                log_cb("❌ Ошибка авторизации!")
                status_cb("error", "Сессия мертва (Unauthorized)")
        elif task_mode == "warmup":
            await worker.client.connect()
            if await worker.client.is_user_authorized():
                status_cb("running", "")
                log_cb("☕ Запущен режим 'Только Прогрев' (Нагуливаем Trust Score).")
                await worker.warmup_account(w_count, w_min, w_max)
                log_cb("✅ Прогрев успешно завершен. Аккаунт переведен в спящий режим.")
                status_cb("idle", "")
            else:
                log_cb("❌ Ошибка авторизации (сессия мертва)!")
                status_cb("error", "Сессия мертва (Unauthorized)")
        elif task_mode == "funnel":
            settings = db.get_global_settings()
            bio_text = settings.get("funnel_bio", "Learn more about me:")
            offer_text = settings.get("funnel_post", "🚀 Join my exclusive private channel to get the best signals and insights! Subscribe now!")
            await worker.client.connect()
            if await worker.client.is_user_authorized():
                status_cb("running", "")
                await worker.setup_profile_funnel(bio_text, offer_text)
            else:
                log_cb("❌ Ошибка авторизации (сессия мертва)!")
                status_cb("error", "Сессия мертва (Unauthorized)")
        elif task_mode == "leadgen":
            await worker.client.connect()
            if await worker.client.is_user_authorized():
                status_cb("running", "")
                await worker.run_leadgen(leadgen_delay_min, leadgen_delay_max, leadgen_daily_limit)
            else:
                log_cb("❌ Ошибка авторизации!")
                status_cb("error", "Сессия мертва (Unauthorized)")
        elif task_mode == "auto_leadgen":
            await asyncio.sleep(1.5) # Даем UI время отрисовать терминал
            await worker.client.connect()
            if await worker.client.is_user_authorized():
                status_cb("running", "")
                await asyncio.sleep(1.0)
                if not skip_setup:
                    settings = db.get_global_settings()
                    bio_text = settings.get("funnel_bio", "Learn more about me:")
                    offer_text = settings.get("funnel_post", "🚀 Join my exclusive private channel to get the best signals and insights! Subscribe now!")
                    log_cb("🔄 [WIZARD] Фаза 1: Авто-оформление воронки (Setup)...")
                    await worker.setup_profile_funnel(bio_text, offer_text, target_channel, main_channel, channel_title, first_name, last_name, is_private_request)
                else:
                    log_cb("⏩ [WIZARD] Аккаунт УЖЕ оформлен. Пропускаем настройку био.")
                log_cb("🔄 [WIZARD] Фаза 2: Имитация человеческой активности (Прогрев)...")
                await worker.warmup_account(w_count, w_min, w_max)
                log_cb("🔄 [WIZARD] Фаза 3: Запуск нейро-комментинга (LeadGen)...")
                await worker.run_leadgen(leadgen_delay_min, leadgen_delay_max, leadgen_daily_limit)
            else:
                log_cb("❌ Ошибка авторизации!")
                status_cb("error", "Сессия мертва (Unauthorized)")
        elif task_mode == "setup_and_warmup":
            await asyncio.sleep(1.5) # Даем UI время отрисовать терминал
            await worker.client.connect()
            if await worker.client.is_user_authorized():
                status_cb("running", "")
                await asyncio.sleep(1.0)
                if not skip_setup:
                    settings = db.get_global_settings()
                    bio_text = settings.get("funnel_bio", "Learn more about me:")
                    offer_text = settings.get("funnel_post", "🚀 Join my exclusive private channel to get the best signals and insights! Subscribe now!")
                    log_cb("🔄 [WIZARD] Фаза 1: Авто-оформление воронки (Setup)...")
                    await worker.setup_profile_funnel(bio_text, offer_text, target_channel, main_channel, channel_title, first_name, last_name, is_private_request)
                else:
                    log_cb("⏩ [WIZARD] Оформление пропущено (галочка 'Уже оформлен').")
                log_cb("🔄 [WIZARD] Фаза 2: Имитация человеческого чтения (Прогрев)...")
                await worker.warmup_account(w_count, w_min, w_max)
                log_cb("✅ [WIZARD] Подготовка завершена! Аккаунт переведен в режим ожидания (IDLE).")
                status_cb("idle", "")
            else:
                log_cb("❌ Ошибка авторизации!")
                status_cb("error", "Сессия мертва (Unauthorized)")
        else:
            await worker.start()

    try:
        worker._main_task = loop.create_task(run_wrapper())
        loop.run_until_complete(worker._main_task)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        status_cb("error", str(e))
    finally:
        try:
            if worker.client.is_connected():
                loop.run_until_complete(worker.client.disconnect())
        except: pass
        status_cb("idle", "")
        try:
            del active_spiders[p_name]
        except KeyError:
            pass
        try:
            loop.close()
        except: pass

@app.post("/api/spider/start")
async def start_all_spiders():
    profiles = db.get_all_profiles()
    started = 0
    app.loop = asyncio.get_running_loop()
    
    for (p_name, status, _) in profiles:
        if p_name in active_spiders or status == 'running':
            continue
        data = db.get_profile(p_name)
        if not data or not data['api_id'] or not data['api_hash']:
            continue
            
        proxy = None
        if data['proxy_type'] != 'None' and data['proxy_addr']:
            addr_parts = data['proxy_addr'].split(':')
            if len(addr_parts) == 2:
                p_type = 'socks5' if 'socks5' in data['proxy_type'].lower() else 'http'
                proxy = {
                    "proxy_type": p_type,
                    "addr": addr_parts[0],
                    "port": int(addr_parts[1]),
                    "rdns": True
                }
                if data.get('proxy_user') and data.get('proxy_pass'):
                    proxy["username"] = data['proxy_user']
                    proxy["password"] = data['proxy_pass']
        
        t = threading.Thread(target=run_spider_in_thread, args=(p_name, data['api_id'], data['api_hash'], proxy), daemon=True)
        t.start()
        started += 1
        
    return {"status": "ok", "started": started}

@app.post("/api/spider/stop")
async def stop_all_spiders():
    for name, worker in list(active_spiders.items()):
        if hasattr(worker, 'is_running'):
            worker.is_running = False
            if hasattr(worker, '_loop') and worker._loop.is_running():
                # Прокидываем worker аргументом (w), чтобы защититься от замыканий цикла
                async def graceful_shutdown_all(w):
                    if hasattr(w, 'client') and w.client.is_connected():
                        await w.client.disconnect()
                    for t in asyncio.all_tasks():
                        if t is not asyncio.current_task():
                            t.cancel()
                asyncio.run_coroutine_threadsafe(graceful_shutdown_all(worker), worker._loop)
    active_spiders.clear()
    return {"status": "ok"}
    

@app.get("/api/proxies")
def get_unique_proxies():
    query = "SELECT DISTINCT proxy_type, proxy_addr, proxy_user, proxy_pass FROM profiles WHERE proxy_type != 'None' AND proxy_addr != ''"
    rows = db._execute(query, fetchall=True)
    return [{"type": r[0], "addr": r[1], "user": r[2], "pass": r[3]} for r in (rows or [])]


@app.get("/api/wizard_defaults")
def get_wizard_defaults():
    api_row = db._execute("SELECT api_id, api_hash FROM profiles WHERE api_id IS NOT NULL AND api_id != '' LIMIT 1", fetch=True)
    api_id = api_row[0] if api_row else ""
    api_hash = api_row[1] if api_row else ""
    
    proxy_rows = db._execute("SELECT DISTINCT proxy_type, proxy_addr, proxy_user, proxy_pass FROM profiles WHERE proxy_addr IS NOT NULL AND proxy_addr != '' AND proxy_addr != 'None'", fetchall=True)
    proxies = [{"type": r[0], "addr": r[1], "user": r[2], "pass": r[3]} for r in (proxy_rows or [])]
    
    return {"api_id": api_id, "api_hash": api_hash, "proxies": proxies}

@app.get("/api/profiles")
def get_profiles():
    return [{"name": p[0], "status": p[1], "error": p[2], "target": p[3], "bridge": p[4]} for p in db.get_all_profiles()]

@app.get("/api/profiles/{name}")
def get_profile_details(name: str):
    data = db.get_profile(name)
    if not data:
        raise HTTPException(status_code=404, detail="Profile not found")
    return data

@app.delete("/api/profiles/{name}")
def delete_profile(name: str):
    db.delete_profile(name)
    session_file = os.path.join(base_dir, f"{name}.session")
    if os.path.exists(session_file):
        try: os.remove(session_file)
        except: pass
    return {"status": "ok"}

@app.post("/api/profiles/{name}/avatars")
async def upload_avatars(name: str, request: Request):
    form = await request.form()
    acc_file = form.get("account_avatar")
    chan_file = form.get("channel_avatar")
    
    avatars_dir = os.path.join(base_dir, "avatars")
    os.makedirs(avatars_dir, exist_ok=True)
    
    if acc_file and hasattr(acc_file, 'filename') and acc_file.filename:
        with open(os.path.join(avatars_dir, f"{name}_acc.jpg"), "wb") as f:
            f.write(await acc_file.read())
            
    if chan_file and hasattr(chan_file, 'filename') and chan_file.filename:
        with open(os.path.join(avatars_dir, f"{name}_chan.jpg"), "wb") as f:
            f.write(await chan_file.read())
            
    return {"status": "ok"}

@app.post("/api/profiles/import")
async def import_profile(request: Request):
    try:
        form = await request.form()
        
        name = str(form.get("name", "")).strip()
        api_id = str(form.get("api_id", "")).strip()
        api_hash = str(form.get("api_hash", "")).strip()
        proxy_type = str(form.get("proxy_type", "None")).strip()
        proxy_addr = str(form.get("proxy_addr", "")).strip()
        proxy_user = str(form.get("proxy_user", "")).strip()
        proxy_pass = str(form.get("proxy_pass", "")).strip()
        session_file = form.get("session_file")

        if not name or not api_id or not api_hash:
            return {"status": "error", "detail": "Заполните все обязательные поля (Имя, API ID, API Hash)"}

        if not session_file or not hasattr(session_file, 'filename') or not session_file.filename:
            return {"status": "error", "detail": "Файл не выбран или поврежден"}

        if session_file.filename.endswith('.rar') or session_file.filename.endswith('.7z'):
            return {"status": "error", "detail": "RAR и 7Z архивы не поддерживаются! Кликните по папке tdata ПКМ -> 'Сжать в ZIP файл' (или 'Отправить' -> 'Сжатая ZIP папка')."}
            
        if not (session_file.filename.endswith('.session') or session_file.filename.endswith('.zip')):
            return {"status": "error", "detail": "Поддерживаются только .session и .zip (архив с папкой tdata)"}

        dest_path = os.path.join(base_dir, f"{name}.session")
        file_bytes = await session_file.read()
        
        if session_file.filename.endswith('.zip'):
            try:
                from opentele.td import TDesktop
                from opentele.api import UseCurrentSession
            except ImportError:
                return {"status": "error", "detail": "Для загрузки tdata(ZIP) установите библиотеку в консоли: pip install opentele"}
                
            import tempfile, zipfile, shutil
            temp_dir = tempfile.mkdtemp()
            zip_path = os.path.join(temp_dir, "temp.zip")
            with open(zip_path, "wb") as f:
                f.write(file_bytes)
                
            try:
                with zipfile.ZipFile(zip_path, 'r') as z:
                    z.extractall(temp_dir)
                    
                tdata_path = None
                for root, dirs, files in os.walk(temp_dir):
                    # Ищем строго файл ключей, чтобы не перепутать папку
                    if any(f.startswith("key_data") for f in files):
                        tdata_path = root
                        break
                        
                if not tdata_path:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return {"status": "error", "detail": "В ZIP архиве не найдена папка tdata (отсутствует файл key_data)."}
                    
                try:
                    tdas = TDesktop(tdata_path)
                except BaseException as tdata_err:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return {"status": "error", "detail": "Аккаунт не найден! Закройте Telegram перед копированием tdata. Если не помогает — конвертируйте tdata в .session сторонней программой."}
                    
                if not tdas.isLoaded():
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return {"status": "error", "detail": "tdata повреждена или заблокирована облачным паролем (2FA)."}
                    
                client = await tdas.ToTelethon(session=dest_path, flag=UseCurrentSession)
                await client.connect()
                await client.disconnect()
            except Exception as e:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return {"status": "error", "detail": f"Ошибка конвертации tdata: {str(e)}"}
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
        else:
            with open(dest_path, "wb") as buffer:
                buffer.write(file_bytes)
            
        if db.create_profile(name):
            db.update_profile(name, {
                "api_id": api_id, "api_hash": api_hash, "proxy_type": proxy_type,
                "proxy_addr": proxy_addr, "proxy_user": proxy_user, "proxy_pass": proxy_pass,
                "seed_channel": "@ege_math_100"
            })
        else:
            db.update_profile(name, {
                "api_id": api_id, "api_hash": api_hash, "proxy_type": proxy_type,
                "proxy_addr": proxy_addr, "proxy_user": proxy_user, "proxy_pass": proxy_pass
            })
            
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": f"Сбой на сервере: {str(e)}"}

@app.post("/api/profiles/{name}")
def save_profile(name: str, data: dict):
    if not db.get_profile(name):
        db.create_profile(name)
    db.update_profile(name, data)
    return {"status": "ok"}

class AIPreviewRequest(BaseModel):
    prompt: str

@app.post("/api/wizard/preview_comment")
async def preview_ai_comment(req: AIPreviewRequest):
    settings = db.get_global_settings()
    api_key = settings.get('gemini_api_key', '')
    if not api_key: return {"error": "Нет API ключа Gemini. Добавьте во вкладке Graph AI."}
    
    ip = str(settings.get('gemini_proxy_ip', '')).strip()
    port = str(settings.get('gemini_proxy_port', '')).strip()
    user = str(settings.get('gemini_proxy_user', '')).strip()
    pwd = str(settings.get('gemini_proxy_pass', '')).strip()
    
    proxy_url = ""
    if ip and port:
        if user and pwd:
            u = urllib.parse.quote(user, safe='')
            p = urllib.parse.quote(pwd, safe='')
            proxy_url = f"http://{u}:{p}@{ip}:{port}"
        else:
            proxy_url = f"http://{ip}:{port}"
            
    if proxy_url:
        os.environ['HTTP_PROXY'] = proxy_url
        os.environ['HTTPS_PROXY'] = proxy_url
    else:
        for k in ['HTTP_PROXY', 'HTTPS_PROXY']:
            os.environ.pop(k, None)

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-3.1-flash-lite-preview")
        dummy_post = "Ребята, биток пробил 70к, что думаете, куда дальше полетим? Закупаться или ждать коррекции? Пишите в комменты!"
        prompt = req.prompt.replace("{text}", dummy_post)
        system_instruction = "Ты оставляешь комментарий от лица пользователя. Выдай ТОЛЬКО текст одного финального комментария. Строго следуй правилам из промпта. Без вариантов, без приветствий, без пояснений."
        response = model.generate_content([system_instruction, prompt])
        return {"status": "ok", "comment": response.text.strip().replace('"', '')}
    except Exception as e:
        return {"error": str(e)}

class ValidateAccountRequest(BaseModel):
    name: str

class ProxyTestRequest(BaseModel):
    proxy_type: str
    proxy_addr: str
    proxy_user: str
    proxy_pass: str

@app.post("/api/wizard/test_proxy")
def test_proxy_only(req: ProxyTestRequest):
    import requests
    if not req.proxy_addr or req.proxy_type == 'None':
        return {"status": "error", "message": "Прокси не указан"}
    
    # Используем socks5h для жесткой проверки DNS и протокола
    p_type = 'socks5h' if 'socks5' in req.proxy_type.lower() else 'http'
    
    # ФИКС: Убираем urllib.parse.quote. Дешевые прокси ломаются от URL-кодировки.
    # Передаем пароли "как есть", точно так же, как это делает validate_account.
    auth_str = ""
    if req.proxy_user and req.proxy_pass:
        auth_str = f"{req.proxy_user}:{req.proxy_pass}@"
        
    req_proxy_url = f"{p_type}://{auth_str}{req.proxy_addr}"
    proxies = {"http": req_proxy_url, "https": req_proxy_url}
    
    try:
        # ФИКС: Увеличиваем таймаут до 10 секунд (некоторые IPv4 прокси тупят при первом коннекте)
        res = requests.get("http://ip-api.com/json", proxies=proxies, timeout=10)
        if res.status_code == 407:
            return {"status": "error", "message": "❌ Ошибка 407: Неверный логин/пароль от прокси."}
        res.raise_for_status()
        data = res.json()
        return {"status": "ok", "message": f"✅ Прокси работает! IP: {data.get('query')} ({data.get('country')})"}
    except requests.exceptions.ProxyError:
        return {"status": "error", "message": "❌ Ошибка авторизации. Проверьте пароль!"}
    except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout):
        # ФИКС: Главная подсказка для юзера
        return {"status": "error", "message": "❌ Таймаут. Если прокси рабочий, смените тип (SOCKS5 ↔ HTTP Proxy) в списке!"}
    except requests.exceptions.InvalidSchema:
         return {"status": "error", "message": "❌ Ошибка: Серверу не хватает модуля PySocks (pip install requests[socks])."}
    except Exception as e:
        return {"status": "error", "message": f"❌ Прокси мертв: {type(e).__name__}"}

@app.post("/api/wizard/check_spambot")
async def check_spambot_endpoint(req: ValidateAccountRequest):
    data = db.get_profile(req.name)
    if not data: return {"status": "error", "message": "Профиль не найден"}
    
    if req.name in active_spiders:
        return {"status": "error", "message": "❌ Ошибка: Сначала остановите аккаунт в Dashboard! База сессии заблокирована."}
        
    try:
        api_id_int = int(data['api_id'])
    except (ValueError, TypeError):
        return {"status": "error", "message": "❌ Ошибка: API ID не указан или имеет неверный формат."}

    telethon_proxy = None
    if data.get('proxy_type') and data['proxy_type'] != 'None' and data.get('proxy_addr'):
        p_type = 'socks5' if 'socks5' in data['proxy_type'].lower() else 'http'
        addr_parts = data['proxy_addr'].split(':')
        if len(addr_parts) == 2:
            telethon_proxy = {
                "proxy_type": p_type,
                "addr": addr_parts[0],
                "port": int(addr_parts[1]),
                "rdns": True
            }
            if data.get('proxy_user') and data.get('proxy_pass'):
                telethon_proxy["username"] = data['proxy_user']
                telethon_proxy["password"] = data['proxy_pass']
            
    import telethon
    import traceback
    session_path = os.path.join(base_dir, f"{req.name}.session")
    
    if not os.path.exists(session_path):
        return {"status": "error", "message": "❌ Файл .session не найден на сервере!"}
        
    client = telethon.TelegramClient(session_path, api_id_int, data['api_hash'], proxy=telethon_proxy)
    try:
        await asyncio.wait_for(client.connect(), timeout=10.0)
        
        if not await client.is_user_authorized():
            return {"status": "error", "message": "❌ Сессия мертва (Unauthorized). Загрузите новый .session файл."}
        
        await client.send_message('spambot', '/start')
        await asyncio.sleep(2)
        messages = await client.get_messages('spambot', limit=1)
        
        if messages and messages[0].text:
            text = messages[0].text
            clean_words = ["good news", "no limits", "свободен", "нет ограничений"]
            if any(w in text.lower() for w in clean_words):
                return {"status": "ok", "message": f"Чисто: {text}"}
            else:
                return {"status": "error", "message": f"Ограничения: {text}"}
        else:
            return {"status": "error", "message": "❌ SpamBot ничего не ответил."}
            
    except asyncio.TimeoutError:
        return {"status": "error", "message": "❌ Ошибка: Таймаут подключения к Telegram (прокси не пускает трафик)."}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": f"❌ Ошибка Telethon: {type(e).__name__} - {str(e)}"}
    finally:
        if client.is_connected():
            await client.disconnect()

@app.post("/api/wizard/validate_account")
async def validate_account(req: ValidateAccountRequest):
    data = db.get_profile(req.name)
    if not data: return {"status": "error", "message": "Профиль не найден"}
    
    if req.name in active_spiders:
        return {"status": "error", "message": "❌ Ошибка: Сначала остановите аккаунт в Dashboard! База сессии заблокирована."}
        
    try:
        api_id_int = int(data['api_id'])
    except (ValueError, TypeError):
        return {"status": "error", "message": "❌ Ошибка: API ID не указан или имеет неверный формат (должны быть только цифры)."}

    telethon_proxy = None
    if data.get('proxy_type') and data['proxy_type'] != 'None' and data.get('proxy_addr'):
        p_type = 'socks5' if 'socks5' in data['proxy_type'].lower() else 'http'
        addr_parts = data['proxy_addr'].split(':')
        if len(addr_parts) == 2:
            telethon_proxy = {
                "proxy_type": p_type,
                "addr": addr_parts[0],
                "port": int(addr_parts[1]),
                "rdns": True
            }
            if data.get('proxy_user') and data.get('proxy_pass'):
                telethon_proxy["username"] = data['proxy_user']
                telethon_proxy["password"] = data['proxy_pass']
            
            import requests
            try:
                auth_str = f"{data['proxy_user']}:{data['proxy_pass']}@" if data.get('proxy_user') and data.get('proxy_pass') else ""
                req_proxy_url = f"{p_type}://{auth_str}{data['proxy_addr']}"
                proxies = {"http": req_proxy_url, "https": req_proxy_url}
                
                res = requests.get("http://ip-api.com/json", proxies=proxies, timeout=5)
                if res.status_code == 407:
                    return {"status": "error", "message": "❌ Ошибка 407: Неверный логин или пароль от прокси."}
                res.raise_for_status()
            except requests.exceptions.ProxyError:
                return {"status": "error", "message": "❌ Ошибка авторизации прокси. Проверьте логин/пароль."}
            except requests.exceptions.ConnectTimeout:
                return {"status": "error", "message": "❌ Прокси мертв (Таймаут). Замените IP."}
            except Exception as e:
                return {"status": "error", "message": f"❌ Ошибка соединения с прокси: {type(e).__name__} - {str(e)}"}
    
    import telethon
    import traceback
    session_path = os.path.join(base_dir, f"{req.name}.session")
    if not os.path.exists(session_path):
        return {"status": "error", "message": "❌ Файл .session не найден на сервере!"}
        
    client = telethon.TelegramClient(session_path, api_id_int, data['api_hash'], proxy=telethon_proxy)
    try:
        await asyncio.wait_for(client.connect(), timeout=10.0)
        is_auth = await client.is_user_authorized()
        
        if is_auth:
            return {"status": "ok", "message": "✅ Связка проверена! Прокси работает, сессия жива."}
        else:
            return {"status": "error", "message": "❌ Сессия мертва (Unauthorized). Загрузите новый .session файл."}
    except asyncio.TimeoutError:
        return {"status": "error", "message": "❌ Ошибка: Таймаут подключения к Telegram (прокси не пускает трафик)."}
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": f"❌ Ошибка Telethon: {type(e).__name__} - {str(e)}"}
    finally:
        if client.is_connected():
            await client.disconnect()

@app.get("/api/settings/global")
def get_global_settings_api():
    return db.get_global_settings()

@app.post("/api/settings/global")
def save_global_settings_api(data: dict):
    db.update_global_settings(data)
    return {"status": "ok"}

@app.get("/api/keywords")
def get_keywords():
    return [{"word": w, "type": t} for w, t in db.get_all_keywords()]

class KeywordAddRequest(BaseModel):
    words: str
    kw_type: str

@app.post("/api/keywords")
def add_keywords(req: KeywordAddRequest):
    words_list = [w.strip().lower() for w in req.words.split(',') if w.strip()]
    if words_list:
        db.add_keywords_bulk(words_list, req.kw_type)
    return {"status": "ok"}

@app.delete("/api/keywords/{word}")
def delete_keyword(word: str):
    db._execute("DELETE FROM keywords WHERE word=?", (word,))
    return {"status": "ok"}

from gogle import ScraperWorker, CheckerWorker, link_queue

active_scraper = None
active_checkers = []

def run_scraper_in_thread(queries):
    global active_scraper
    
    def on_status(msg):
        if hasattr(app, 'loop') and app.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({"type": "log", "profile": "Google", "message": msg}), 
                app.loop
            )
            
    active_scraper = ScraperWorker(queries, pages_count=5)
    active_scraper.on_status = on_status
    active_scraper.run()

def run_checker_in_thread():
    def on_found(chat_data):
        lead = {
            'username': chat_data['username'],
            'title': chat_data['type'],
            'description': f"[Google Lead] {chat_data['desc']}",
            'subscribers': chat_data['subs'],
            'tags': '', 
            'last_posts': chat_data['last_posts'],
            'has_comments': True if chat_data['is_open'] == 1 else False
        }
        db.import_external_leads([lead])
        if hasattr(app, 'loop') and app.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({
                    "type": "log", "profile": "Checker", 
                    "message": f"🎯 Найден лид: {chat_data['username']} ({chat_data['subs']} subs)"
                }), app.loop
            )

    checker = CheckerWorker()
    checker.on_found = on_found
    active_checkers.append(checker)
    checker.run()

class SniperStartRequest(BaseModel):
    queries: list[str]

@app.post("/api/sniper/start")
async def start_sniper(req: SniperStartRequest):
    global active_scraper, active_checkers
    if active_scraper and active_scraper.is_running:
        return {"status": "error", "message": "Already running"}
        
    app.loop = asyncio.get_running_loop()
    
    # Если запуск ручной (есть дорки) - чистим очередь. 
    # Если фоновый из Scout - оставляем спаршенные ссылки в очереди.
    if req.queries:
        while not link_queue.empty():
            try: link_queue.get_nowait()
            except: pass
        
    active_checkers = []
    for _ in range(5):
        t = threading.Thread(target=run_checker_in_thread, daemon=True)
        t.start()
        
    if req.queries:
        t = threading.Thread(target=run_scraper_in_thread, args=(req.queries,), daemon=True)
        t.start()
    
    return {"status": "started", "message": "Started checkers/scrapers"}

@app.post("/api/sniper/stop")
async def stop_sniper():
    global active_scraper, active_checkers
    if active_scraper: active_scraper.stop()
    for w in active_checkers: w.stop()
    active_checkers.clear()
    return {"status": "stopped"}


@app.get("/api/dashboard/stats")
def get_dashboard_stats():
    health = db.get_global_db_health()
    stats = db.get_statistics()
    profiles = db.get_all_profiles()
    return {
        "health": health,
        "stats": stats,
        "profiles": [{"name": p[0], "status": p[1], "error": p[2]} for p in profiles],
        "incomplete": db.get_incomplete_channels_stats(),
        "proxy_stats": db.get_statistics_by_proxy()
    }

tagger_running = False

def run_ai_tagger_in_thread():
    global tagger_running
    if not tagger_running: return
    
    def send_log(msg):
        if hasattr(app, 'loop') and app.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({"type": "log", "profile": "AI Tagger", "message": msg}), app.loop
            )

    try:
        settings = db.get_global_settings()
        api_key = settings.get('gemini_api_key', '')
        if not api_key:
            send_log("❌ Ошибка: Вставь ключ Gemini во вкладке 'Graph AI View'.")
            tagger_running = False
            return

        ip = str(settings.get('gemini_proxy_ip', '')).strip()
        port = str(settings.get('gemini_proxy_port', '')).strip()
        user = str(settings.get('gemini_proxy_user', '')).strip()
        pwd = str(settings.get('gemini_proxy_pass', '')).strip()
        
        proxy_url = ""
        if ip and port:
            if user and pwd:
                u = urllib.parse.quote(user, safe='')
                p = urllib.parse.quote(pwd, safe='')
                proxy_url = f"http://{u}:{p}@{ip}:{port}"
            else:
                proxy_url = f"http://{ip}:{port}"
                
        if proxy_url:
            os.environ['HTTP_PROXY'] = proxy_url
            os.environ['HTTPS_PROXY'] = proxy_url
        else:
            for k in ['HTTP_PROXY', 'HTTPS_PROXY']:
                os.environ.pop(k, None)

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-3.1-flash-lite-preview")

        system_prompt = "Ты - OSINT-аналитик. Твоя задача - категоризировать Telegram каналы.\nОпредели для каждого канала из переданного списка 1 глобальную нишу (category) на английском (например: Crypto, Business, Adult, Entertainment, IT, Education, etc.) и 3-5 хештегов (tags).\nОтвет СТРОГО в JSON формате:\n{\n  \"results\": [\n    { \"id\": 123456, \"category\": \"Crypto\", \"tags\": \"#trading, #bitcoin\" }\n  ]\n}"

        while tagger_running:
            untagged = db.get_untagged_channels(limit=10)
            if not untagged:
                send_log("✅ Все доступные каналы размечены!")
                tagger_running = False
                break

            send_log(f"🧠 Отправляю пачку ({len(untagged)} шт.) на анализ ИИ...")

            user_prompt = "Проанализируй эти каналы:\n\n"
            for ch in untagged:
                tid, uname, title, desc, posts = ch
                clean_desc = desc.replace('\n', ' ')[:100] if desc else ""
                clean_posts = posts.replace('\n', ' ')[:300] if posts else ""
                user_prompt += f"ID: {tid}\nTitle: {title}\nDesc: {clean_desc}\nPosts: {clean_posts}\n---\n"

            try:
                response = model.generate_content(
                    contents=[
                        {"role": "user", "parts": [system_prompt]},
                        {"role": "user", "parts": [user_prompt]}
                    ],
                    generation_config=genai.types.GenerationConfig(temperature=0.1, response_mime_type="application/json")
                )
                
                clean_text = response.text.replace('```json', '').replace('```', '').strip()
                data = json.loads(clean_text)
                results = data.get("results", [])
                
                tagged_count = 0
                for res in results:
                    tid = res.get("id")
                    cat = res.get("category", "Uncategorized").capitalize()
                    tags = res.get("tags", "")
                    
                    if tid and tags:
                        db._execute("UPDATE channels SET ai_tags = ?, category = ? WHERE telegram_id = ?", (tags, cat, tid))
                        tagged_count += 1
                
                send_log(f"✅ Пачка успешно размечена ({tagged_count} каналов).")
                
                db.generate_semantic_links()
                
                if hasattr(app, 'loop') and app.loop.is_running():
                    asyncio.run_coroutine_threadsafe(manager.broadcast({"action": "update_graph"}), app.loop)

                if tagger_running:
                    import time
                    time.sleep(5) 

            except Exception as e:
                send_log(f"⚠️ Ошибка генерации (возможно Rate Limit). Ждем 10 сек... ({str(e)})")
                import time
                time.sleep(10)

    except Exception as e:
        send_log(f"❌ Критическая ошибка теггера: {str(e)}")
    finally:
        tagger_running = False

@app.post("/api/tagger/start")
async def start_tagger():
    global tagger_running
    if tagger_running: return {"status": "error", "message": "Already running"}
    tagger_running = True
    app.loop = asyncio.get_running_loop()
    import threading
    threading.Thread(target=run_ai_tagger_in_thread, daemon=True).start()
    return {"status": "started"}

@app.post("/api/tagger/stop")
async def stop_tagger():
    global tagger_running
    tagger_running = False
    return {"status": "stopped"}

class AISettingsRequest(BaseModel):
    prompt: str

@app.get("/api/ai_settings")
def get_ai_settings():
    settings = db.get_global_settings()
    default_prompt = """Роль: Ты — гениальный OSINT-маркетолог и эксперт по латеральному маркетингу в Telegram.
Твоя суперсила — находить платежеспособную аудиторию через КОСВЕННЫЕ интересы, а не только "в лоб".

ЗАДАЧА:
1. Анализ ниши и Латеральное мышление: Кто покупает этот продукт/услугу? Где сидят эти люди, когда НЕ думают о продукте? (Например: покупатели OFM/AI-моделей — это часто крипто-инвесторы, экспаты в Дубае, лудоманы, IT-предприниматели).
2. Google Dorks (30 шт): Напиши дорки для поиска чатов. 
   - 10 дорков на ПРЯМОЙ запрос (где обсуждают услугу напрямую).
   - 20 дорков на КОСВЕННЫЕ ниши (где просто сидит целевая ЦА с деньгами: крипта, релокация, дорогие хобби, недвижка, мужские клубы, бизнес).
ПРАВИЛО ФОРМАТА: Каждый дорк строго с новой строки. Начинается ТОЛЬКО с site:t.me. Без нумерации и тире. Комбинируй языки (RU/EN/Arabic) в зависимости от контекста запроса!
3. Выборка из БД: Я передам тебе список "Доступные теги БД". Выбери из них от 1 до 8 тегов.
   КРИТИЧЕСКИ ВАЖНО: Мысли шире! Если ищут клиентов на специфичные услуги, смело бери смежные теги платежеспособной аудитории (#crypto, #dubai, #investments, #business, #trading, #it). НЕ ограничивайся только буквальными совпадениями! Если ищут B2B, цепляй теги маркетинга и стартапов.

ФОРМАТ ОТВЕТА (СТРОГИЙ JSON без маркдауна и вступлений):
{
  "analysis": "Краткий анализ (кто ЦА и в каких косвенных нишах они сидят)",
  "dorks": ["site:t.me \"keyword\"", "site:t.me \"keyword2\""],
  "db_tags_selected": ["#dubai", "#crypto", "#modeling", "Бизнес"]
}"""
    prompt = settings.get('ai_helper_prompt', default_prompt)
    if not prompt.strip():
        prompt = default_prompt
    return {"prompt": prompt}

@app.post("/api/ai_settings")
def save_ai_settings(req: AISettingsRequest):
    db.update_global_settings({'ai_helper_prompt': req.prompt})
    return {"status": "ok"}

class AIGenerateNamesRequest(BaseModel):
    niche: str
    language: str = "RU"
    gender: str = "Женский"
    age_min: str = "20"
    age_max: str = "25"
    country: str = ""
    profession: str = ""
    interests: str = ""

@app.post("/api/wizard/generate_names")
async def generate_names_endpoint(req: AIGenerateNamesRequest):
    settings = db.get_global_settings()
    api_key = settings.get('gemini_api_key', '')
    if not api_key: return {"error": "Нет API ключа Gemini. Добавьте во вкладке Graph AI."}
    
    ip = str(settings.get('gemini_proxy_ip', '')).strip()
    port = str(settings.get('gemini_proxy_port', '')).strip()
    user = str(settings.get('gemini_proxy_user', '')).strip()
    pwd = str(settings.get('gemini_proxy_pass', '')).strip()
    
    proxy_url = ""
    if ip and port:
        if user and pwd:
            u = urllib.parse.quote(user, safe='')
            p = urllib.parse.quote(pwd, safe='')
            proxy_url = f"http://{u}:{p}@{ip}:{port}"
        else:
            proxy_url = f"http://{ip}:{port}"
            
    if proxy_url:
        os.environ['HTTP_PROXY'] = proxy_url
        os.environ['HTTPS_PROXY'] = proxy_url
    else:
        for k in ['HTTP_PROXY', 'HTTPS_PROXY']:
            os.environ.pop(k, None)

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-3.1-flash-lite-preview")
        
        prompt = f"""
        Создай Легенду (персонажа) для Telegram-аккаунта (Лидогенератора/Стримера/Эксперта).
        Базовая ниша: {req.niche}
        Требуемый язык: {req.language}
        Пол: {req.gender}
        Возраст: от {req.age_min} до {req.age_max}
        Локация: {req.country if req.country else "Не указана"}
        Профессия/Роль: {req.profession if req.profession else "Подбери под нишу"}
        Интересы: {req.interests if req.interests else "Подбери под нишу"}

        ВАЖНОЕ ПРАВИЛО: Все значения (Имя, Фамилия, Название, Био, Пост) должны быть СТРОГО на языке: {req.language}.
        Если язык RU - используй ТОЛЬКО русский язык и кириллицу (например: "Алексей", а не "Alexey"; "Инвест", а не "Invest").
        Если язык EN - используй английский алфавит.

        Сгенерируй:
        1. Имя (first_name) - реалистичное под локацию.
        2. Фамилия или приставка (last_name) - (например для RU: Инвест, Блог, Приват; для EN: Private, Crypto).
        3. Название канала-прокладки (channel_title).
        4. БИО профиля (bio) - СТРОГО до 50 символов! Короткий хук.
        5. Первый рекламный пост в канал-прокладку (post). Это оффер, призывающий перейти в основной VIP канал. Обязательно вставь маркер {{link}} туда, где должна быть ссылка на основной канал.

        Верни СТРОГО JSON без markdown-разметки:
        {{
            "first_name": "...",
            "last_name": "...",
            "channel_title": "...",
            "bio": "...",
            "post": "..."
        }}
        """
        res = model.generate_content(prompt)
        text = res.text.replace('```json', '').replace('```', '').strip()
        return json.loads(text)
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/wizard/upload_assets/{profile_name}")
async def upload_wizard_assets(profile_name: str, request: Request):
    try:
        form = await request.form()
        avatars_dir = os.path.join(base_dir, "avatars")
        os.makedirs(avatars_dir, exist_ok=True)
        
        for key, suffix in [("acc_avatar", "_acc.jpg"), ("chan_avatar", "_chan.jpg"), ("post_image", "_post.jpg")]:
            file = form.get(key)
            if file and hasattr(file, 'filename') and file.filename:
                with open(os.path.join(avatars_dir, f"{profile_name}{suffix}"), "wb") as f:
                    f.write(await file.read())
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

class AIHelperRequest(BaseModel):
    query: str
    min_subs: int = 0
    max_subs: int = 999999999
# Мы переименовываем сломанный дубликат эндпоинта, чтобы он перестал перекрывать рабочий
@app.post("/api/wizard/check_spambot_BROKEN_OLD")
async def check_spambot_broken(req: Request):
    data = await req.json()
    profile_name = data.get("name")
    
    if not profile_name:
        return {"status": "error", "message": "Профиль не указан."}
        
    session_path = os.path.join(SESSIONS_DIR, f"{profile_name}.session")
    if not os.path.exists(session_path):
        return {"status": "error", "message": "Файл сессии не найден."}

    # Грузим прокси если есть
    from spider_core import load_profiles
    profiles = load_profiles()
    p_data = profiles.get(profile_name, {})
    
    proxy_dict = None
    if p_data.get('proxy_type') and p_data.get('proxy_type') != 'None' and p_data.get('proxy_addr'):
        import socks
        p_type = socks.SOCKS5 if 'socks5' in p_data['proxy_type'].lower() else socks.HTTP
        addr_parts = p_data['proxy_addr'].split(':')
        if len(addr_parts) >= 2:
            proxy_dict = {
                "proxy_type": p_type,
                "addr": addr_parts[0],
                "port": int(addr_parts[1]),
                "rdns": True,
                "username": p_data.get('proxy_user'),
                "password": p_data.get('proxy_pass')
            }

    from telethon import TelegramClient
    import asyncio
    
    client = TelegramClient(session_path, int(p_data.get('api_id', 2040)), p_data.get('api_hash', 'b18441a1ff607e10a989891a5462e627'), proxy=proxy_dict)
    
    try:
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return {"status": "error", "message": "Сессия мертва (вылет)."}
            
        # Отправляем /start спамботу
        await client.send_message('spambot', '/start')
        await asyncio.sleep(2) # Ждем ответ
        
        # Получаем последнее сообщение от спамбота
        messages = await client.get_messages('spambot', limit=1)
        if messages and messages[0].text:
            text = messages[0].text
            if "Good news" in text or "Свободен" in text or "Нет ограничений" in text or "нет ограничений" in text.lower():
                await client.disconnect()
                return {"status": "ok", "message": "Ограничений нет! Аккаунт чист."}
            else:
                await client.disconnect()
                return {"status": "error", "message": text[:150] + "..."} # Показываем кусок ответа
        else:
            await client.disconnect()
            return {"status": "error", "message": "Спамбот не ответил. Возможно, сильный флуд."}
            
    except Exception as e:
        await client.disconnect()
        return {"status": "error", "message": f"Ошибка: {str(e)}"}

@app.post("/api/ai_helper")
async def ai_helper_endpoint(req: AIHelperRequest):
    if not HAS_GENAI:
        return {"error": "Библиотека google-generativeai не установлена. Настройте ИИ в Desktop приложении."}
        
    settings = db.get_global_settings()
    api_key = settings.get('gemini_api_key', '')
    
    if not api_key:
        return {"error": "API ключ Gemini не найден. Укажите его во вкладке 'Graph AI View'."}
        
    ip = str(settings.get('gemini_proxy_ip', '')).strip()
    port = str(settings.get('gemini_proxy_port', '')).strip()
    user = str(settings.get('gemini_proxy_user', '')).strip()
    pwd = str(settings.get('gemini_proxy_pass', '')).strip()
    
    proxy_url = ""
    if ip and port:
        if user and pwd:
            u = urllib.parse.quote(user, safe='')
            p = urllib.parse.quote(pwd, safe='')
            proxy_url = f"http://{u}:{p}@{ip}:{port}"
        else:
            proxy_url = f"http://{ip}:{port}"
            
    if proxy_url:
        os.environ['HTTP_PROXY'] = proxy_url
        os.environ['HTTPS_PROXY'] = proxy_url
    else:
        for k in ['HTTP_PROXY', 'HTTPS_PROXY']:
            os.environ.pop(k, None)

    try:
        categories, tags = db.get_available_tags_for_ai()
        context_tags = list(set(categories + tags))
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-3.1-flash-lite-preview")
        
        system_prompt = get_ai_settings()["prompt"]
        
        user_prompt = f"""
        ЗАПРОС КЛИЕНТА: {req.query}
        
        ДОСТУПНЫЕ ТЕГИ БД (выбирай смело косвенные ниши, где сидит эта ЦА):
        {', '.join(context_tags) if context_tags else 'База пуста'}
        """

        response = model.generate_content(
            contents=[{"role": "user", "parts": [system_prompt + "\n\n" + user_prompt]}],
            generation_config=GenerationConfig(
                temperature=0.3,
                response_mime_type="application/json"
            )
        )
        
        clean_text = response.text.replace('```json', '').replace('```', '').strip()
        ai_result = json.loads(clean_text)
        
        selected_tags = ai_result.get("db_tags_selected", [])
        channels_data = db.get_channels_by_tags_for_ai(selected_tags, req.min_subs, req.max_subs)
        
        channels = []
        for c in channels_data:
            tid, uname, title, subs, cat, tags_str, posts = c
            match_score = "🔥 High" if subs > 5000 else "⭐ Med"
            channels.append({
                "id": tid, "username": uname, "title": title, "subs": subs,
                "category": cat, "tags": tags_str, "match_score": match_score,
                "recent_posts": posts[:300] + "..." if len(posts) > 300 else posts
            })
            
        return {
            "analysis": ai_result.get("analysis", ""),
            "dorks": ai_result.get("dorks", []),
            "selected_tags": selected_tags,
            "channels": channels
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": f"Ошибка ИИ: {str(e)}"}

app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8050, log_level="error")

if __name__ == "__main__":
    run_server()