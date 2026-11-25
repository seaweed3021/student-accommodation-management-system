function getIdToken() {
  return new Promise((resolve, reject) => {
    const user = userPool.getCurrentUser();
    if (!user) return reject(new Error('Please sign in again'));
    user.getSession((err, session) => {
      if (err || !session.isValid()) return reject(new Error('Session expired, sign in again'));
      resolve(session.getIdToken().getJwtToken());
    });
  });
}

async function apiRequest(path, method = 'GET', body = null, needsToken = true) {
  const headers = {};
  if (body) headers['Content-Type'] = 'application/json';
  if (needsToken) headers['Authorization'] = 'Bearer ' + (await getIdToken());
  const response = await fetch(API_BASE_URL + path, {
    method: method,
    headers: headers,
    body: body ? JSON.stringify(body) : undefined
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || 'Request failed (' + response.status + ')');
  return data;
}

function makeEl(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function showMessage(text, type) {
  const box = document.getElementById('message');
  box.textContent = text;
  box.className = type || '';
}