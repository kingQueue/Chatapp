'use strict';
document.getElementById('login-form').addEventListener('submit', async e => {
  e.preventDefault();
  const button = e.submitter, status = document.getElementById('login-status');
  button.disabled = true; status.textContent = 'Connecting…';
  try {
    const code = document.getElementById('access-code').value.trim().toUpperCase();
    const response = await fetch('/api/login', {method:'POST',headers:{'Content-Type':'application/json','X-Character-Room':'1'},body:JSON.stringify({code})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
    location.replace('/');
  } catch(e) { status.textContent = e.message; }
  finally { button.disabled = false; }
});
