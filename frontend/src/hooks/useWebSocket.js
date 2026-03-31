import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Custom hook for WebSocket communication with the writing agent.
 *
 * @param {string|null} url  – WebSocket URL (pass null to defer connecting)
 * @returns {{ messages, status, connect, disconnect }}
 */
export default function useWebSocket(url) {
  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState("idle"); // idle | connecting | connected | closed | error
  const wsRef = useRef(null);

  const connect = useCallback(() => {
    if (!url) return;
    if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) return;

    setStatus("connecting");
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => setStatus("connected");

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        setMessages((prev) => [...prev, msg]);
      } catch {
        // ignore non-JSON frames
      }
    };

    ws.onerror = () => setStatus("error");

    ws.onclose = () => {
      setStatus("closed");
      wsRef.current = null;
    };
  }, [url]);

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => () => disconnect(), [disconnect]);

  return { messages, status, connect, disconnect };
}
