import { useCallback, useEffect, useRef, useState } from "react";
import { ApiRequestError } from "../lib/api";
import { formatDate as formatDateValue } from "../lib/formatters";

export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

export function useApi<T>(request: () => Promise<T>, refreshKey?: unknown) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const requestRef = useRef(request);
  requestRef.current = request;
  const requestIdRef = useRef(0);

  const reload = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError(null);
    setErrorCode(null);
    try {
      const result = await requestRef.current();
      if (requestId === requestIdRef.current) {
        setData(result);
      }
    } catch (caught) {
      if (requestId === requestIdRef.current) {
        setError(caught instanceof Error ? caught.message : "Unable to reach the API");
        setErrorCode(caught instanceof ApiRequestError ? caught.code : "upstream_down");
      }
    } finally {
      if (requestId === requestIdRef.current) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void refreshKey;
    void reload();
    return () => {
      requestIdRef.current += 1;
    };
  }, [refreshKey, reload]);
  return { data, error, errorCode, loading, reload };
}

export function formatDate(value: string) {
  return formatDateValue(value);
}
