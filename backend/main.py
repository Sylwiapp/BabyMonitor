# backend/main.py
from __future__ import annotations
import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# --- Konfiguracja ---
APP_SECRET = os.getenv("APP_SECRET", "dev-secret-change-me")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app = FastAPI(title="BabyMonitor Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Prosty model pomiaru ---
class Telemetry(BaseModel):
    device_id: str
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    respiration_rate: float | None = None   # oddechy/min (z mmWave)
    heart_rate: float | None = None         # tętno (opcjonalnie)
    skin_temp_c: float | None = None        # MLX90614
    ambient_temp_c: float | None = None
    h2s_level: float | None = None          # surowy lub znormalizowany
    noise_db: float | None = None
    presence: bool | None = None
    event: str | None = None                # np. "poop", "no-breath-15s"

# --- PubSub per device ---
class Hub:
    def __init__(self):
        self._subscribers: Dict[str, Set[WebSocket]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    async def subscribe(self, device_id: str, ws: WebSocket):
        await ws.accept()
        if device_id not in self._subscribers:
            self._subscribers[device_id] = set()
            self._locks[device_id] = asyncio.Lock()
        self._subscribers[device_id].add(ws)

    async def unsubscribe(self, device_id: str, ws: WebSocket):
        try:
            self._subscribers.get(device_id, set()).discard(ws)
        except Exception:
            pass

    async def publish(self, payload: dict):
        device_id = payload.get("device_id")
        if not device_id:
            return
        subs = self._subscribers.get(device_id)
        if not subs:
            return
        message = json.dumps(payload, default=str)
        stale: List[WebSocket] = []
        for ws in list(subs):
            try:
                await ws.send_text(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            subs.discard(ws)

hub = Hub()

# --- Prosta autoryzacja tokenem w query/header ---
def check_token(request: Request):
    token = request.headers.get("X-Token") or request.query_params.get("token")
    if token != APP_SECRET:
        raise HTTPException(status_code=401, detail="Invalid token")


# --- HTTP ingest dla Pico (jeśli wolisz POST zamiast WebSocket po stronie urządzenia) ---
@app.post("/api/ingest")
async def ingest(t: Telemetry, _: None = Depends(check_token)):
    await hub.publish(t.model_dump())
    return {"ok": True}


# --- WebSocket: aplikacja odbiera live dane ---
@app.websocket("/ws/app/{device_id}")
async def ws_app(websocket: WebSocket, device_id: str):
    # token w query: /ws/app/abc?token=...
    token = websocket.query_params.get("token")
    if token != APP_SECRET:
        await websocket.close(code=4401)
        return
    await hub.subscribe(device_id, websocket)
    try:
        while True:
            # app nic nie musi wysyłać; ale czytamy pingi żeby utrzymać połączenie
            await websocket.receive_text()
    except WebSocketDisconnect:
        await hub.unsubscribe(device_id, websocket)


# --- WebSocket: urządzenie może wysyłać telemetrię bezpośrednio ---
@app.websocket("/ws/device/{device_id}")
async def ws_device(websocket: WebSocket, device_id: str):
    token = websocket.query_params.get("token")
    if token != APP_SECRET:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
                data.setdefault("device_id", device_id)
                data.setdefault("ts", datetime.now(timezone.utc).isoformat())
                await hub.publish(data)
            except Exception:
                pass
    except WebSocketDisconnect:
        return


# --- Strona testowa (opcjonalnie) ---
@app.get("/")
def root():
    return HTMLResponse("<h1>BabyMonitor backend OK</h1>")


# --- Prosty generator danych do testów (uruchamiany oddzielnie) ---
async def simulator(device_id: str = "demo-1"):
    import math, random
    t = 0.0
    while True:
        payload = Telemetry(
            device_id=device_id,
            respiration_rate=24 + 2 * math.sin(t/10),
            heart_rate=120 + 5 * math.sin(t/7),
            skin_temp_c=35.4 + 0.2 * math.sin(t/19),
            ambient_temp_c=22.5,
            h2s_level=max(0.0, random.gauss(0.1, 0.02)),
            noise_db=max(30.0, random.gauss(38, 3)),
            presence=True,
            event=None,
        ).model_dump()
        await hub.publish(payload)
        if int(t) % 30 == 0 and int(t) != 0:
            await hub.publish({
                "device_id": device_id,
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": "poop",
            })
        t += 1
        await asyncio.sleep(1)


if __name__ == "__main__":
    import uvicorn
    # loop = asyncio.get_event_loop()
    # loop.create_task(simulator("demo-1"))
    uvicorn.run(app, host="0.0.0.0", port=8000)
