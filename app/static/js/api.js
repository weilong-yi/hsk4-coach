async function call(method, path, body) {
  const r = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `${method} ${path} failed (${r.status})`);
  return data;
}

export const get = path => call('GET', path);
export const post = (path, body = {}) => call('POST', path, body);
export const logEvent = (session_id, activity, item, result, ms) =>
  post('/api/event', { session_id, activity, item, result, ms });
