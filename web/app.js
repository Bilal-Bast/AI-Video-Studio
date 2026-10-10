const $ = (id) => document.getElementById(id);
const state = {
  scenes: [{id: makeId(), engine: 'local', prompt: 'A fluffy orange cat in a tiny business suit, sitting in a modern office.', duration: 4, motion: 'zoom_in', overlay: '', referenceFile: null}],
  busy: false,
  sceneProgress: [],
};

function makeId() {
  return globalThis.crypto?.randomUUID?.() || `scene-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
function escapeHtml(value) {
  return String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}
function showError(message) {
  $('error').textContent = message;
  $('error').classList.remove('hidden');
}
function clearError() {
  $('error').textContent = '';
  $('error').classList.add('hidden');
}
function selected(value, expected) { return String(value) === String(expected) ? 'selected' : ''; }

function renderScenes() {
  const progressById = new Map(state.sceneProgress.map((item) => [item.id, item]));
  $('sceneList').innerHTML = state.scenes.map((scene, index) => {
    const progress = progressById.get(scene.id);
    const durationOptions = Array.from({length: 12}, (_, i) => i + 1).map((seconds) => {
      const disabled = scene.engine === 'wan' && (seconds < 3 || seconds > 6) ? 'disabled' : '';
      return `<option value="${seconds}" ${selected(scene.duration, seconds)} ${disabled}>${seconds} second${seconds === 1 ? '' : 's'}</option>`;
    }).join('');
    const refName = scene.referenceFile ? scene.referenceFile.name : 'Choose a reference image';
    const progressText = progress?.error ? progress.error : (progress?.progress || 'Ready when you are');
    const status = progress?.status || 'ready';
    return `<article class="scene-card ${progress?.status === 'error' ? 'scene-error' : ''}" data-scene-id="${escapeHtml(scene.id)}">
      <div class="scene-card-header">
        <div class="scene-heading"><span class="scene-number">SCENE ${String(index + 1).padStart(2, '0')}</span><span class="scene-state state-${escapeHtml(status)}">${escapeHtml(status)}</span></div>
        <div class="scene-actions" aria-label="Scene actions">
          <button class="icon-button" type="button" data-action="up" aria-label="Move scene up" title="Move up" ${index === 0 || state.busy ? 'disabled' : ''}>↑</button>
          <button class="icon-button" type="button" data-action="down" aria-label="Move scene down" title="Move down" ${index === state.scenes.length - 1 || state.busy ? 'disabled' : ''}>↓</button>
          <button class="icon-button" type="button" data-action="duplicate" aria-label="Duplicate scene" title="Duplicate" ${state.scenes.length >= 20 || state.busy ? 'disabled' : ''}>▣</button>
          <button class="icon-button delete-button" type="button" data-action="delete" aria-label="Delete scene" title="Delete" ${state.scenes.length <= 1 || state.busy ? 'disabled' : ''}>×</button>
        </div>
      </div>
      <div class="scene-engine-row">
        <label class="field-label" for="engine-${escapeHtml(scene.id)}">SCENE ENGINE</label>
        <select id="engine-${escapeHtml(scene.id)}" data-field="engine" ${state.busy ? 'disabled' : ''}>
          <option value="local" ${selected(scene.engine, 'local')}>Local Motion · FFmpeg</option>
          <option value="wan" ${selected(scene.engine, 'wan')}>Wan 2.2 · ComfyUI</option>
        </select>
      </div>
      <label class="field-label" for="prompt-${escapeHtml(scene.id)}">PROMPT</label>
      <textarea id="prompt-${escapeHtml(scene.id)}" data-field="prompt" maxlength="1800" placeholder="Describe this scene…" ${state.busy ? 'disabled' : ''}>${escapeHtml(scene.prompt)}</textarea>
      <div class="scene-settings-row">
        <div class="field"><label class="field-label" for="duration-${escapeHtml(scene.id)}">DURATION</label><select id="duration-${escapeHtml(scene.id)}" data-field="duration" ${state.busy ? 'disabled' : ''}>${durationOptions}</select></div>
        <div class="field"><label class="field-label" for="motion-${escapeHtml(scene.id)}">ANIMATION</label><select id="motion-${escapeHtml(scene.id)}" data-field="motion" ${state.busy ? 'disabled' : ''}>
          <option value="zoom_in" ${selected(scene.motion, 'zoom_in')}>Zoom in</option><option value="zoom_out" ${selected(scene.motion, 'zoom_out')}>Zoom out</option><option value="pan_left" ${selected(scene.motion, 'pan_left')}>Pan left</option><option value="pan_right" ${selected(scene.motion, 'pan_right')}>Pan right</option>
        </select></div>
      </div>
      <label class="field-label reference-label" for="reference-${escapeHtml(scene.id)}">REFERENCE IMAGE <span class="optional">OPTIONAL · MAX 12 MB</span></label>
      <div class="reference-control"><label class="file-choose" for="reference-${escapeHtml(scene.id)}"><span>${escapeHtml(refName)}</span></label><input id="reference-${escapeHtml(scene.id)}" data-field="reference" type="file" accept="image/png,image/jpeg,image/webp" hidden ${state.busy ? 'disabled' : ''}/>${scene.referenceFile ? `<button class="text-button" type="button" data-action="remove-reference" ${state.busy ? 'disabled' : ''}>Remove</button>` : ''}</div>
      <label class="field-label overlay-label" for="overlay-${escapeHtml(scene.id)}">TEXT OVERLAY <span class="optional">OPTIONAL · 180 CHARACTERS</span></label>
      <textarea class="overlay-input" id="overlay-${escapeHtml(scene.id)}" data-field="overlay" maxlength="180" rows="2" placeholder="Add a caption to this scene…" ${state.busy ? 'disabled' : ''}>${escapeHtml(scene.overlay)}</textarea>
      <div class="scene-progress" aria-live="polite"><span class="progress-dot state-dot-${escapeHtml(status)}"></span><span>${escapeHtml(progressText)}</span></div>
    </article>`;
  }).join('');
  $('addScene').disabled = state.busy || state.scenes.length >= 20;
  $('generate').disabled = state.busy;
  updateSummary();
}

function updateSummary() {
  const total = state.scenes.reduce((sum, scene) => sum + Number(scene.duration), 0);
  $('sceneSummary').textContent = `${state.scenes.length} scene${state.scenes.length === 1 ? '' : 's'} · ${total} second${total === 1 ? '' : 's'}`;
  $('sceneSummary').classList.toggle('over-limit', total > 60);
}
function findScene(id) { return state.scenes.find((scene) => scene.id === id); }

$('sceneList').addEventListener('input', (event) => {
  const card = event.target.closest('[data-scene-id]');
  const field = event.target.dataset.field;
  if (!card || !field || field === 'reference') return;
  const scene = findScene(card.dataset.sceneId);
  if (!scene) return;
  scene[field] = field === 'duration' ? Number(event.target.value) : event.target.value;
  if (field === 'duration') updateSummary();
});

$('sceneList').addEventListener('change', (event) => {
  const card = event.target.closest('[data-scene-id]');
  const field = event.target.dataset.field;
  if (!card || !field) return;
  const scene = findScene(card.dataset.sceneId);
  if (!scene) return;
  if (field === 'reference') {
    const file = event.target.files[0];
    if (file && file.size > 12 * 1024 * 1024) {
      event.target.value = '';
      showError('Each reference image must be 12 MB or smaller.');
      return;
    }
    scene.referenceFile = file || null;
    renderScenes();
    return;
  }
  scene[field] = field === 'duration' ? Number(event.target.value) : event.target.value;
  if (field === 'engine') {
    if (scene.engine === 'wan' && scene.duration > 6) scene.duration = 4;
    if (scene.engine === 'wan' && scene.duration < 3) scene.duration = 3;
    renderScenes();
  } else if (field === 'duration') {
    updateSummary();
  }
});

$('sceneList').addEventListener('click', (event) => {
  const button = event.target.closest('[data-action]');
  if (!button || state.busy) return;
  const card = button.closest('[data-scene-id]');
  const index = state.scenes.findIndex((scene) => scene.id === card?.dataset.sceneId);
  if (index < 0) return;
  const action = button.dataset.action;
  if (action === 'remove-reference') {
    state.scenes[index].referenceFile = null;
  } else if (action === 'delete' && state.scenes.length > 1) {
    state.scenes.splice(index, 1);
  } else if (action === 'duplicate' && state.scenes.length < 20) {
    const copy = {...state.scenes[index], id: makeId()};
    state.scenes.splice(index + 1, 0, copy);
  } else if (action === 'up' && index > 0) {
    [state.scenes[index - 1], state.scenes[index]] = [state.scenes[index], state.scenes[index - 1]];
  } else if (action === 'down' && index < state.scenes.length - 1) {
    [state.scenes[index + 1], state.scenes[index]] = [state.scenes[index], state.scenes[index + 1]];
  }
  renderScenes();
});

$('addScene').addEventListener('click', () => {
  if (state.scenes.length >= 20) return;
  state.scenes.push({id: makeId(), engine: 'local', prompt: '', duration: 4, motion: 'zoom_in', overlay: '', referenceFile: null});
  clearError();
  renderScenes();
  $('sceneList').lastElementChild?.scrollIntoView({behavior: 'smooth', block: 'nearest'});
});

$('music').addEventListener('change', () => {
  const file = $('music').files[0];
  if (file && file.size > 16 * 1024 * 1024) {
    $('music').value = '';
    $('musicLabel').textContent = '＋ Add MP3, WAV, or M4A';
    showError('The soundtrack must be 16 MB or smaller.');
    return;
  }
  $('musicLabel').textContent = file?.name || '＋ Add MP3, WAV, or M4A';
});

function setBusy(busy) {
  state.busy = busy;
  $('orientation').disabled = busy;
  $('resolution').disabled = busy;
  $('fps').disabled = busy;
  $('music').disabled = busy;
  $('comfyUrl').disabled = busy;
  $('timeout').disabled = busy;
  $('testComfy').disabled = busy;
  $('saveComfy').disabled = busy;
  $('addScene').disabled = busy;
  $('generate').disabled = busy;
  $('generate').innerHTML = busy ? '<span class="spinner inline-spinner"></span> Rendering scenes…' : '<span>✦</span> Render video <span class="arrow">→</span>';
  renderScenes();
}
function setProgress(message, percent = 8) {
  $('progressBox').classList.remove('hidden');
  $('progressText').textContent = message;
  $('progressBar').style.width = `${Math.max(5, Math.min(100, percent))}%`;
  $('previewStatus').textContent = '● RENDERING';
}
function finish(job) {
  state.sceneProgress = job.scene_progress || [];
  clearTimeout(state.pollTimer);
  state.pollTimer = null;
  setBusy(false);
  $('progressBox').classList.add('hidden');
  renderScenes();
  if (job.status === 'error') {
    $('previewStatus').textContent = '● ERROR';
    $('outputSubtitle').textContent = 'One or more scenes could not be rendered.';
    showError(job.error || 'Rendering failed. See the scene status for details.');
    return;
  }
  const videoUrl = job.video_url;
  $('emptyPreview').classList.add('hidden');
  $('video').classList.remove('hidden');
  $('video').src = `${videoUrl}?v=${Date.now()}`;
  $('video').load();
  $('download').href = videoUrl;
  $('download').classList.remove('disabled');
  $('download').setAttribute('aria-disabled', 'false');
  $('previewStatus').textContent = '● COMPLETE';
  $('outputTitle').textContent = `${state.scenes.length} scene${state.scenes.length === 1 ? '' : 's'} rendered`;
  $('outputSubtitle').textContent = 'Your MP4 is ready to preview and download.';
}

async function poll(jobId) {
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {cache: 'no-store'});
    if (!response.ok) throw new Error('Could not fetch render progress.');
    const job = await response.json();
    state.sceneProgress = job.scene_progress || [];
    renderScenes();
    const done = state.sceneProgress.filter((item) => item.status === 'complete').length;
    const percent = Math.round((done / Math.max(1, state.scenes.length)) * 88);
    setProgress(job.progress || 'Rendering scenes…', job.progress?.startsWith('Combining') ? 95 : percent + 5);
    if (job.status === 'complete' || job.status === 'error') {
      finish(job);
    } else {
      state.pollTimer = setTimeout(() => poll(jobId), 1200);
    }
  } catch (err) {
    clearTimeout(state.pollTimer);
    state.pollTimer = null;
    setBusy(false);
    $('progressBox').classList.add('hidden');
    $('previewStatus').textContent = '● ERROR';
    showError(`Lost connection while checking progress: ${err.message}`);
  }
}

$('generate').addEventListener('click', async () => {
  if (state.busy) return;
  clearError();
  const total = state.scenes.reduce((sum, scene) => sum + Number(scene.duration), 0);
  if (total > 60) { showError('Keep the finished project at 60 seconds or less.'); return; }
  if (state.scenes.some((scene) => scene.engine === 'wan' && !scene.prompt.trim())) {
    showError('Add a prompt to every Wan 2.2 scene.'); return;
  }
  setBusy(true);
  state.sceneProgress = state.scenes.map((scene) => ({id: scene.id, status: 'queued', progress: 'Waiting', error: null}));
  renderScenes();
  setProgress('Submitting your storyboard…');
  $('outputTitle').textContent = 'Rendering your scenes…';
  $('outputSubtitle').textContent = 'Keep this page open to follow each scene.';
  $('download').classList.add('disabled');
  $('download').setAttribute('aria-disabled', 'true');
  const references = [];
  const scenes = state.scenes.map((scene) => {
    let image_index = null;
    if (scene.referenceFile) {
      image_index = references.push(scene.referenceFile) - 1;
    }
    return {id: scene.id, engine: scene.engine, prompt: scene.prompt, duration: Number(scene.duration), motion: scene.motion, overlay: scene.overlay, image_index};
  });
  const form = new FormData();
  form.append('project', JSON.stringify({scenes, orientation: $('orientation').value, resolution: Number($('resolution').value), fps: Number($('fps').value)}));
  for (const file of references) form.append('reference_images', file, 'reference.jpg');
  const music = $('music').files[0];
  if (music) {
    const ext = music.name.split('.').pop().toLowerCase();
    form.append('music', music, ['mp3', 'wav', 'm4a'].includes(ext) ? `music.${ext}` : 'music.mp3');
  }
  try {
    const response = await fetch('/api/render', {method: 'POST', body: form});
    const result = await response.json();
    if (!response.ok) {
      const reason = typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail);
      throw new Error(reason || 'The render request failed.');
    }
    await poll(result.id);
  } catch (err) {
    setBusy(false);
    $('progressBox').classList.add('hidden');
    $('previewStatus').textContent = '● ERROR';
    showError(err.message || 'Could not start rendering.');
  }
});

async function loadSettings() {
  try {
    const response = await fetch('/api/settings');
    const settings = await response.json();
    if (!response.ok) throw new Error('Could not load ComfyUI settings.');
    $('comfyUrl').value = settings.comfyui_url;
    if (![...$('timeout').options].some((option) => Number(option.value) === settings.timeout_seconds)) {
      $('timeout').add(new Option(`${settings.timeout_seconds} seconds (custom)`, String(settings.timeout_seconds)));
    }
    $('timeout').value = String(settings.timeout_seconds);
    if (!settings.workflow_valid) $('comfyStatus').textContent = `Workflow validation failed: ${settings.workflow_error}`;
  } catch (err) {
    $('comfyStatus').textContent = err.message;
  }
}

async function checkHealth() {
  try {
    const response = await fetch('/api/health');
    if (!response.ok) throw new Error('Unavailable');
    const health = await response.json();
    $('serverDot').classList.add('ready');
    $('serverStatus').textContent = health.comfyui_connected ? 'Local engine ready · ComfyUI responds' : 'Local engine ready · ComfyUI not detected';
  } catch {
    $('serverStatus').textContent = 'Local server offline';
  }
}

$('testComfy').addEventListener('click', async () => {
  $('testComfy').disabled = true;
  $('comfyStatus').textContent = 'Checking ComfyUI and validating the workflow…';
  try {
    const response = await fetch('/api/health');
    const health = await response.json();
    if (!response.ok) throw new Error('Health check failed.');
    if (!health.comfyui_connected) $('comfyStatus').textContent = 'ComfyUI did not respond at the saved URL. Check the server and firewall.';
    else if (!health.workflow_valid) $('comfyStatus').textContent = 'ComfyUI responds, but the workflow file is invalid.';
    else $('comfyStatus').textContent = 'ComfyUI responded and the workflow file is valid. GPU inference has not been tested.';
  } catch (err) {
    $('comfyStatus').textContent = err.message;
  } finally {
    $('testComfy').disabled = false;
  }
});

$('saveComfy').addEventListener('click', async () => {
  $('saveComfy').disabled = true;
  $('comfyStatus').textContent = 'Saving local settings…';
  try {
    const response = await fetch('/api/settings', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: $('comfyUrl').value.trim(), timeout_seconds: Number($('timeout').value)}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not save settings.');
    $('comfyUrl').value = result.comfyui_url;
    $('timeout').value = String(result.timeout_seconds);
    $('comfyStatus').textContent = 'Settings saved to .env. Test the connection to confirm ComfyUI responds.';
    checkHealth();
  } catch (err) {
    $('comfyStatus').textContent = err.message;
  } finally {
    $('saveComfy').disabled = false;
  }
});

renderScenes();
loadSettings();
checkHealth();
