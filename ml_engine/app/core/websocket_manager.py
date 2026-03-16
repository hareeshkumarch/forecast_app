import json
import asyncio
from fastapi import WebSocket
from redis.asyncio import Redis
from app.core.config import settings
from app.core.logging import logger

class WebSocketManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}
        # Using decode_responses=False to be safer with pubsub if it sends bytes, but True is usually fine for text JSON
        self.redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.pubsub = self.redis.pubsub()

    async def connect(self, websocket: WebSocket, job_id: str):
        await websocket.accept()
        if job_id not in self.active_connections:
            self.active_connections[job_id] = []
            await self.pubsub.subscribe(f"job_updates:{job_id}")
        self.active_connections[job_id].append(websocket)

    def disconnect(self, websocket: WebSocket, job_id: str):
        if job_id in self.active_connections and websocket in self.active_connections[job_id]:
            self.active_connections[job_id].remove(websocket)
            if not self.active_connections[job_id]:
                del self.active_connections[job_id]
                # Unsubscribe from Redis to prevent connection/memory leak
                import asyncio
                try:
                    asyncio.get_event_loop().create_task(
                        self.pubsub.unsubscribe(f"job_updates:{job_id}")
                    )
                except Exception:
                    pass

    async def broadcast_from_redis(self):
        try:
            async for message in self.pubsub.listen():
                if message["type"] == "message":
                    channel = message["channel"]
                    job_id = channel.split(":")[1]
                    data = message["data"]
                    if job_id in self.active_connections:
                        dead_sockets = []
                        for connection in self.active_connections[job_id]:
                            try:
                                await connection.send_text(data)
                            except Exception:
                                dead_sockets.append(connection)
                        for dead in dead_sockets:
                            self.disconnect(dead, job_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Redis PubSub listener error: {e}")

manager = WebSocketManager()
