import { useCallback, useEffect, useRef, useState } from 'react';
import type { SessionUpdate } from '../types';

const WS_URL = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/sessions/ws`;

export function useSessionsSocket() {
  const [connected, setConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<SessionUpdate | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const retriesRef = useRef(0);

  const connect = useCallback(() => {
    const ws = new WebSocket(WS_URL);
    ws.onopen = () => { setConnected(true); retriesRef.current = 0; };
    ws.onmessage = (e) => {
      try { setLastUpdate(JSON.parse(e.data) as SessionUpdate); } catch { /* ignore */ }
    };
    ws.onclose = () => {
      setConnected(false); wsRef.current = null;
      if (retriesRef.current < 10) {
        const delay = Math.min(1000 * 2 ** retriesRef.current, 30000);
        retriesRef.current++; setTimeout(connect, delay);
      }
    };
    ws.onerror = () => ws.close();
    wsRef.current = ws;
  }, []);

  useEffect(() => { connect(); return () => wsRef.current?.close(); }, [connect]);
  return { connected, lastUpdate };
}
