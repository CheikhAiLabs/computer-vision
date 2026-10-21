'use strict';
const notice = document.querySelector('#notice');
const notes = document.querySelector('#incident-notes');
let notesDirty = false;
if (notes) notes.addEventListener('input', () => { notesDirty = true; });
function announce(text, failed = false) {
  notice.textContent = text;
  notice.className = failed ? 'notice error' : 'notice success';
  notice.hidden = false;
  notice.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
async function send(url, method, body) {
  const response = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Request rejected. Check the entered values.');
  return result;
}
for (const button of document.querySelectorAll('[data-action]')) {
  button.addEventListener('click', async () => {
    const panel = button.closest('[data-incident]');
    const note = document.querySelector('#action-note').value;
    // Capture edits before disabling controls; disabled fields are omitted by FormData.
    const pendingNotes = notes && notesDirty ? Object.fromEntries(new FormData(notes)) : null;
    const controls = document.querySelectorAll('button, input, textarea');
    for (const item of controls) item.disabled = true;
    try {
      if (pendingNotes) {
        await send(`/api/incidents/${panel.dataset.incident}`, 'PATCH', pendingNotes);
        notesDirty = false;
      }
      await send(`/api/incidents/${panel.dataset.incident}/${button.dataset.action}`, 'POST', { note });
      window.location.reload();
    } catch (error) {
      announce(error.message, true);
      for (const item of controls) item.disabled = false;
    }
  });
}
if (notes) notes.addEventListener('submit', async event => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(notes));
  const controls = notes.querySelectorAll('button, textarea');
  for (const control of controls) control.disabled = true;
  try {
    await send(`/api/incidents/${notes.dataset.incident}`, 'PATCH', body);
    notesDirty = false;
    announce('Investigation notes saved to the incident timeline.');
  } catch (error) { announce(error.message, true); }
  finally { for (const control of controls) control.disabled = false; }
});
// Empty filters should be omitted rather than submitted as invalid enum/date values.
for (const form of document.querySelectorAll('form.filters')) form.addEventListener('submit', () => {
  for (const input of form.querySelectorAll('input, select')) if (!input.value) input.disabled = true;
});
window.addEventListener('pageshow', () => {
  for (const input of document.querySelectorAll('form.filters input, form.filters select')) input.disabled = false;
});
