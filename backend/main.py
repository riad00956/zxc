import os
import asyncio
import requests
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()

# CORS Setup
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- Cloudflare D1 Config ---
CF_ACC_ID = "57bdaf73b4ceb569b6de021f12d0ea3d"
CF_DB_ID = "7b646686-5b58-4c36-8a75-6eb62a190150"
CF_TOKEN = "MEWIAo2AAFe6nYf79WsLP0pysthOczmf2iC1HZWq"

# Temporary store for login
pending_clients = {}

# --- Pydantic Models ---
class LoginData(BaseModel):
    api_id: str; api_hash: str; phone: str

class VerifyData(BaseModel):
    phone: str; otp: str; password: str = None

# --- Helpers ---
def query_d1(sql, params):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACC_ID}/d1/database/{CF_DB_ID}/query"
    headers = {"Authorization": f"Bearer {CF_TOKEN}", "Content-Type": "application/json"}
    res = requests.post(url, headers=headers, json={"sql": sql, "params": params})
    return res.json()

# --- Phantom Bot Logic (The Core) ---
async def start_phantom_bot(session_str, api_id, api_hash):
    """এটি ব্যাকগ্রাউন্ডে ইউজারের টেলিগ্রাম একাউন্ট চালু রাখবে"""
    try:
        client = TelegramClient(StringSession(session_str), int(api_id), api_hash)
        await client.connect()
        
        @client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
        async def handler(event):
            # এখানে তোমার কাস্টম রিপ্লাই মেসেজ
            await event.reply("**[Auto Reply]** I am currently offline. Will get back to you soon!")
        
        print(f"Bot started for a user!")
        await client.run_until_disconnected()
    except Exception as e:
        print(f"Bot Error: {e}")

# --- API Endpoints ---
@app.post("/send_otp")
async def send_otp(data: LoginData):
    try:
        client = TelegramClient(StringSession(), int(data.api_id), data.api_hash)
        await client.connect()
        sent_code = await client.send_code_request(data.phone)
        pending_clients[data.phone] = {"client": client, "hash": sent_code.phone_code_hash, "api_id": data.api_id, "api_hash": data.api_hash}
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/verify")
async def verify(data: VerifyData, background_tasks: BackgroundTasks):
    if data.phone not in pending_clients:
        raise HTTPException(status_code=400, detail="Session Expired")
    
    info = pending_clients[data.phone]
    try:
        await info["client"].sign_in(data.phone, data.otp, password=data.password)
        session_str = info["client"].session.save()
        
        # Save to Cloudflare D1
        query_d1("INSERT INTO users (phone, api_id, api_hash, session_string) VALUES (?, ?, ?, ?) ON CONFLICT(phone) DO UPDATE SET session_string=?", 
                 [data.phone, info["api_id"], info["api_hash"], session_str, session_str])
        
        # ব্যাকগ্রাউন্ডে বট চালু করা
        background_tasks.add_task(start_phantom_bot, session_str, info["api_id"], info["api_hash"])
        
        del pending_clients[data.phone]
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# সার্ভার স্টার্ট হওয়ার সময় ডাটাবেস থেকে সব একটিভ বট চালু করা
@app.on_event("startup")
async def startup_event():
    # এখানে D1 থেকে সব সেশন ফেচ করে লুপ চালিয়ে বট স্টার্ট করার কোড লিখা যাবে
    print("System Started: Ready to sync bots from D1")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
