import { useEffect, useRef, useCallback, useState } from "react";
import { getWebSocketUrl } from "@/lib/queryClient";

const MAX_RECONNECT_ATTEMPTS = 5;
const BASE_RECONNECT_DELAY_MS = 1000;

export function useWebSocket(jobId: string | null, options?: { onConnect?: () => void }) {
  const wsRef = useRef<WebSocket | null>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const isMountedRef = useRef(true);
  const onConnectRef = useRef(options?.onConnect);
  onConnectRef.current = options?.onConnect;

  const connect = useCallback(() => {
    if (!jobId || !isMountedRef.current) return;

    // Clean up any existing connection
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.onmessage = null;
      wsRef.current.onopen = null;
      if (
        wsRef.current.readyState === WebSocket.OPEN ||
        wsRef.current.readyState === WebSocket.CONNECTING
      ) {
        wsRef.current.close();
      }
    }

    const wsUrl = getWebSocketUrl(jobId);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!isMountedRef.current) return;
      setIsConnected(true);
      reconnectAttemptRef.current = 0; // Reset on successful connection
      onConnectRef.current?.(); // Sync backend state immediately after connect/reconnect
    };

    ws.onmessage = (event) => {
      if (!isMountedRef.current) return;
      try {
        const data = JSON.parse(event.data);
        setMessages((prev) => [...prev, data]);

        // If job completed or errored, no need to reconnect on close
        if (data.type === "completed" || data.type === "error") {
          reconnectAttemptRef.current = MAX_RECONNECT_ATTEMPTS; // Prevent reconnection
        }
      } catch {}
    };

    ws.onclose = () => {
      if (!isMountedRef.current) return;
      setIsConnected(false);

      // Attempt reconnection with exponential backoff
      if (reconnectAttemptRef.current < MAX_RECONNECT_ATTEMPTS) {
        const delay =
          BASE_RECONNECT_DELAY_MS * Math.pow(2, reconnectAttemptRef.current);
        reconnectAttemptRef.current++;
        reconnectTimeoutRef.current = setTimeout(() => {
          if (isMountedRef.current) {
            connect();
          }
        }, delay);
      }
    };

    ws.onerror = () => {
      if (!isMountedRef.current) return;
      setIsConnected(false);
    };

    return ws;
  }, [jobId]);

  useEffect(() => {
    isMountedRef.current = true;
    reconnectAttemptRef.current = 0;
    connect();

    // Ping keepalive
    const interval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send("ping");
      }
    }, 15000);

    return () => {
      isMountedRef.current = false;
      clearInterval(interval);
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.onclose = null; // Prevent reconnect on intentional close
        wsRef.current.close();
      }
    };
  }, [connect]);

  const clearMessages = useCallback(() => setMessages([]), []);

  return { messages, isConnected, clearMessages };
}
