import type { Express } from "express";
import type { Server } from "http";
import multer from "multer";
import { WebSocket, WebSocketServer } from "ws";


const ML_ENGINE = process.env.ML_ENGINE_URL || "http://localhost:8001";

const upload = multer({
  storage: multer.memoryStorage(),           // keep in memory, not disk — ML engine is the single writer
  limits: { fileSize: 50 * 1024 * 1024 },   // 50MB
});

const ML_REQUEST_TIMEOUT_MS = parseInt(process.env.ML_REQUEST_TIMEOUT_MS || "60000", 10);

async function proxyToML(endpoint: string, options: RequestInit = {}): Promise<any> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), ML_REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(`${ML_ENGINE}/api/v1${endpoint}`, {
      ...options,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...options.headers },
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`ML Engine error (${res.status}): ${text}`);
    }
    return res.json();
  } finally {
    clearTimeout(timeout);
  }
}

export function registerRoutes(server: Server, app: Express) {
  // Liveness: app is up (ML engine may be down)
  app.get("/api/health", async (_req, res) => {
    try {
      const ml = await proxyToML("/health");
      res.json({ status: "ok", ml_engine: ml });
    } catch (e: any) {
      res.json({ status: "ok", ml_engine: { status: "unavailable", error: e.message } });
    }
  });

  // Readiness: app can serve traffic (ML engine must be reachable)
  app.get("/api/ready", async (_req, res) => {
    try {
      await proxyToML("/health");
      res.json({ status: "ready" });
    } catch (e: any) {
      res.status(503).json({ status: "not_ready", error: e.message });
    }
  });

  // Upload file — stream buffer directly to ML engine (single write, no temp disk file)
  app.post("/api/upload", upload.single("file"), async (req, res) => {
    try {
      if (!req.file) return res.status(400).json({ error: "No file uploaded" });

      const formData = new FormData();
      const blob = new Blob([new Uint8Array(req.file.buffer)], { type: "application/octet-stream" });
      formData.append("file", blob, req.file.originalname);


      const response = await fetch(`${ML_ENGINE}/api/v1/upload`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const text = await response.text();
        return res.status(response.status).json({ error: text });
      }

      const data = await response.json();
      res.json(data);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });


  // Demo datasets
  app.get("/api/demos", async (_req, res) => {
    try {
      const data = await proxyToML("/demos/");
      res.json(data);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  app.get("/api/demo/:id", async (req, res) => {
    try {
      const data = await proxyToML(`/demos/${req.params.id}`);
      res.json(data);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // Start forecast job
  app.post("/api/forecast", async (req, res) => {
    try {
      const data = await proxyToML("/forecast", {
        method: "POST",
        body: JSON.stringify(req.body),
      });
      res.json(data);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // Get all jobs (history)
  app.get("/api/jobs", async (_req, res) => {
    try {
      const data = await proxyToML("/jobs");
      res.json(data);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // Get job detail
  app.get("/api/jobs/:id", async (req, res) => {
    try {
      const data = await proxyToML(`/jobs/${req.params.id}`);
      res.json(data);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // Get results
  app.get("/api/results/:id", async (req, res) => {
    try {
      const data = await proxyToML(`/jobs/results/${req.params.id}`);
      res.json(data);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // Delete job
  app.delete("/api/jobs/:id", async (req, res) => {
    try {
      const data = await proxyToML(`/jobs/${req.params.id}`, { method: "DELETE" });
      res.json(data);
    } catch (e: any) {
      res.status(500).json({ error: e.message });
    }
  });

  // WebSocket proxy to ML engine
  const wss = new WebSocketServer({ noServer: true });

  server.on("upgrade", (request, socket, head) => {
    const url = request.url || "";
    if (url.startsWith("/ws/")) {
      wss.handleUpgrade(request, socket, head, (ws) => {
        wss.emit("connection", ws, request);
      });
    }
  });

  wss.on("connection", (clientWs, request) => {
    const jobId = (request.url || "").replace("/ws/", "");
    const mlHostname = new URL(ML_ENGINE).host;
    const mlWsUrl = `ws://${mlHostname}/ws/${jobId}`;

    const mlWs = new WebSocket(mlWsUrl);

    // FIX Bug 36: Add a max connection lifetime so orphaned WS connections don't linger forever
    const WS_MAX_LIFETIME_MS = 24 * 60 * 60 * 1000; // 24 hours
    const lifetimeTimer = setTimeout(() => {
      console.log(`[WS] Closing long-lived connection for job ${jobId} after ${WS_MAX_LIFETIME_MS / 3600000}h`);
      if (clientWs.readyState === WebSocket.OPEN) clientWs.close();
      if (mlWs.readyState === WebSocket.OPEN) mlWs.close();
    }, WS_MAX_LIFETIME_MS);

    mlWs.on("open", () => {
      console.log(`[WS] Connected to ML engine for job ${jobId}`);
    });

    mlWs.on("message", (data) => {
      if (clientWs.readyState === WebSocket.OPEN) {
        clientWs.send(data.toString());
      }
    });

    mlWs.on("error", (err) => {
      console.error(`[WS] ML engine error for ${jobId}:`, err.message);
    });

    mlWs.on("close", () => {
      clearTimeout(lifetimeTimer);
      if (clientWs.readyState === WebSocket.OPEN) {
        clientWs.close();
      }
    });

    clientWs.on("close", () => {
      clearTimeout(lifetimeTimer);
      if (mlWs.readyState === WebSocket.OPEN) {
        mlWs.close();
      }
    });

    clientWs.on("message", (data) => {
      if (mlWs.readyState === WebSocket.OPEN) {
        mlWs.send(data.toString());
      }
    });
  });
}
