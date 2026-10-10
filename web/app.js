const $ = (id) => document.getElementById(id);
const state = {mode: 'local', busy: false, poll: null};
const escapeHtml = (s) => String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
function error(message) { $('error').textContent = message; $('error').classList.remove('hidden'); }
function clearError() { $('error').textContent = ''; $('error').classList.add('hidden'); }
function setMode(mode) {
  if (state.busy) return;
  state.mode = mode;
  $('localButton').classList.toggle('active', mode === 'local');
  $('wanButton').classList.toggle('active', mode === 'wan');
  $('wanNote').classList.toggle('hidden', mode !== 'wan');
  $('localOptions').classList.toggle('hidden', mode !== 'local');
  $('promptHelp').textContent = mode === 'local'
    ? 'For local motion, your text becomes an animated title card unless you upload an image.'
    : 'Describe exactly what you want Wan 2.2 to generate on your ComfyUI GPU.';
  for (const option of $('duration').options) option.disabled = (mode === 'wan' && Number(option.value) > 6);
  if (mode === 'wan' && Number($('duration').value) > 6) $('duration').value = '4';
  clearError();
}
$('localButton').addEventListener('click', () => setMode('local'));
$('wanButton').addEventListener('click', () => setMode('wan'));
$('prompt').addEventListener('input', () => $('promptCount').textContent = `${$('prompt').value.length} / 1800`);
$('prompt').dispatchEvent(new Event('input'));
$('image').addEventListener('change', () => { $('imageLabel').textContent = $('image').files[0]?.name || 'Click to upload an image'; });
$('audio').addEventListener('change', () => { $('audioLabel').textContent = $('audio').files[0]?.name || '＋ Add audio'; });
async function checkHealth() {
  try {
    const response = await fetch('/api/health');
    if (!response.ok) throw new Error('Unavailable');
    const health = await response.json();
    $('serverDot').classList.add('ready');
    $('serverStatus').textContent = health.comfyui_connected ? 'Local + GPU connected' : 'Local engine ready';
  } catch { $('serverStatus').textContent = 'Server offline'; }
}
function setBusy(value) {
  state.busy = value;
  $('generate').disabled = value;
  $('generate').innerHTML = value ? '◌ &nbsp; Creating video…' : '<span>✦</span> Generate video <span class="arrow">→</span>';
}
function setProgress(message) {
  $('progressBox').classList.remove('hidden');
  $('progressText').textContent = message;
  $('previewStatus').textContent = '◉ PROCESSING';
}
function finish(job) {
  clearInterval(state.poll);
  state.poll = null;
  setBusy(false);
  $('progressBox').classList.add('hidden');
  if (job.status === 'error') {
    $('previewStatus').textContent = '● ERROR';
    $('outputSubtitle').textContent = 'Your job could not be completed.';
    error(job.error || 'Unknown error');
    return;
  }
  const videoUrl = job.video_url;
  $('emptyPreview').classList.add('hidden');
  $('video').classList.remove('hidden');
  $('video').src = videoUrl;
  $('video').load();
  $('download').href = videoUrl;
  $('download').classList.remove('disabled');
  $('download').setAttribute('aria-disabled','false');
  $('previewStatus').textContent = '● COMPLETE';
  $('outputTitle').textContent = state.mode === 'wan' ? 'Wan 2.2 video generated' : 'Local motion video ready';
  $('outputSubtitle').textContent = 'Your MP4 is ready to play or download.';
}
async function poll(jobId) {
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {cache:'no-store'});
    if (!response.ok) throw new Error('Could not fetch job status');
    const job = await response.json();
    if (job.status === 'complete' || job.status === 'error') finish(job);
    else setProgress(job.progress || 'Creating video…');
  } catch (err) {
    clearInterval(state.poll); state.poll = null;
    setBusy(false); $('progressBox').classList.add('hidden');
    error(`Lost connection while checking progress: ${err.message}`);
  }
}
$('generate').addEventListener('click', async () => {
  if (state.busy) return;
  clearError();
  if (state.mode === 'wan' && !$('prompt').value.trim()) { error('Write a prompt for Wan 2.2.'); return; }
  setBusy(true);
  setProgress('Submitting new video job…');
  $('outputTitle').textContent = 'Building your video…';
  $('outputSubtitle').textContent = 'Please keep this page open to see the result.';
  $('download').classList.add('disabled'); $('download').setAttribute('aria-disabled','true');
  const data = new FormData();
  for (const name of ['prompt','orientation','duration','motion']) data.append(name, $(name).value);
  data.append('mode', state.mode);
  if ($('image').files[0]) data.append('image', $('image').files[0]);
  if (state.mode === 'local' && $('audio').files[0]) data.append('audio', $('audio').files[0]);
  try {
    const response = await fetch('/api/generate', {method:'POST',body:data});
    const result = await response.json();
    if (!response.ok) {
      const reason = typeof result.detail === 'string' ? result.detail : JSON.stringify(result.detail);
      throw new Error(reason || 'Request failed');
    }
    await poll(result.id);
    if (state.busy) state.poll = setInterval(() => poll(result.id), 1500);
  } catch (err) {
    setBusy(false); $('progressBox').classList.add('hidden');
    $('previewStatus').textContent = '● ERROR';
    error(err.message || 'Could not start job');
  }
});
checkHealth();
