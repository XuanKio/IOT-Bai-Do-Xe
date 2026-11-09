import { createApi, esc as e, icon, ROLE, LIFE, TRANSITIONS, COMMAND, dateTime, localInput, timeRange, query, commandKey, ApiError } from './core.js?v=20261106-lot-map1';
import * as V from './views.js?v=20261106-lot-map1';

const root = document.querySelector('#app');
const modal = document.querySelector('#modal');
const regionContent = new WeakMap();
const SESSION_KEY = 'parkflow.session';
const readToken = () => { try { return sessionStorage.getItem(SESSION_KEY) || ''; } catch { return ''; } };
const state = {
  token: readToken(), me: null, parking: null, viewerSlot: '', route: { page: 'overview', deviceId: null }, apiConnected: true,
  devices: [], users: [], slots: [], alerts: [], events: [], audit: [], health: null, selectedDeviceId: '',
  permissions: null, config: null, rules: null, commands: [], gates: [], gateBusy: {}, stats: null, latest: null,
  history: [], historyEvents: [], historyHasMore: false, eventsHasMore: false, historyLoading: false,
  historyInputs: { from: localInput(Date.now() - 86400000), to: '' }, historyRange: {},
  historyTab: 'samples', historyFrozen: false, eventsFrozen: false, deviceSearch: '', deviceStatus: '', userSearch: '',
  alertFilter: 'active', alertBusy: {}, selectionLoading: false, loadError: '', lastSync: null,
};
let pollTimer, ageTimer, refreshPromise, routeEpoch = 0, selectionEpoch = 0, historyEpoch = 0, pollRunning = false;
let lastStatsFetch = 0, lastAdminFetch = 0, lastMeFetch = 0;
let commandAttempt = null, modalGrants = [], modalEpoch = 0;
const api = createApi(() => state.token, () => endSession('Phiên đăng nhập đã hết hạn hoặc quyền tài khoản đã thay đổi. Vui lòng đăng nhập lại.'));

function toast(message, error = false) {
  const node = document.createElement('div'); node.className = 'toast' + (error ? ' error' : '');
  node.setAttribute('role', error ? 'alert' : 'status');
  node.innerHTML = icon(error ? 'info' : 'check') + '<span>' + e(message) + '</span>';
  document.querySelector('#toasts').append(node);
  setTimeout(() => node.remove(), error ? 9000 : 5500);
}
function parseRoute() {
  const [page, id] = location.hash.replace(/^#\/?/, '').split('/');
  return { page: Object.hasOwn(V.TITLES, page) ? page : 'overview', deviceId: page === 'devices' && /^\d+$/.test(id || '') ? Number(id) : null };
}
function saveToken(token) {
  state.token = token;
  try { if (token) sessionStorage.setItem(SESSION_KEY, token); else sessionStorage.removeItem(SESSION_KEY); } catch { /* The current tab can still operate without storage. */ }
}
function clearSelection() {
  selectionEpoch++; historyEpoch++;
  state.permissions = null; state.config = null; state.rules = null; state.commands = [];
  state.stats = null; state.latest = null; state.history = []; state.historyEvents = [];
  state.historyHasMore = false; state.eventsHasMore = false; state.historyFrozen = false; state.eventsFrozen = false;
  state.selectionLoading = false; commandAttempt = null; lastStatsFetch = 0;
}
function endSession(message = '') {
  clearInterval(pollTimer); clearInterval(ageTimer);
  routeEpoch++; selectionEpoch++; refreshPromise = null;
  saveToken(''); state.me = null; state.parking = null; state.viewerSlot = ''; state.devices = []; state.users = []; state.slots = [];
  state.gates = []; state.gateBusy = {}; state.alerts = []; state.alertBusy = {}; state.events = []; state.audit = []; state.selectedDeviceId = ''; state.loadError = '';
  clearSelection(); closeModal(true); setMenu(false);
  root.innerHTML = V.loginView(message);
  document.title = 'Đăng nhập — ParkFlow';
}
function mountShell() {
  root.innerHTML = V.shellView(state);
  renderMain(); renderLive();
}
function renderMain() {
  const host = document.querySelector('#page-content');
  if (!host || !state.me) return;
  host.innerHTML = V.renderPage(state);
  document.title = (state.me.role === 'viewer' && state.route.page === 'overview' ? 'Tìm chỗ đỗ' : V.TITLES[state.route.page]) + ' — ParkFlow';
  const crumb = document.querySelector('#breadcrumb-current');
  if (crumb) crumb.textContent = V.TITLES[state.route.page];
  document.querySelectorAll('[data-nav]').forEach(a => {
    const active = a.dataset.nav === state.route.page;
    a.classList.toggle('active', active);
    if (active) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
}
function region(name, html) {
  document.querySelectorAll('[data-region="' + name + '"]').forEach(node => {
    if (regionContent.get(node) === html) return;
    const active = document.activeElement;
    const focused = node.contains(active) && active.matches('a, button') ? active : null;
    const identity = ['href', 'data-action', 'data-id', 'data-user', 'data-tab', 'data-slot'];
    node.innerHTML = html; regionContent.set(node, html);
    if (focused) {
      const replacement = [...node.querySelectorAll('a, button')].find(el =>
        el.tagName === focused.tagName && identity.every(attr => el.getAttribute(attr) === focused.getAttribute(attr)));
      if (replacement && !replacement.disabled) replacement.focus({ preventScroll: true });
    }
  });
}
function renderLive() {
  if (!state.me) return;
  if (state.me.role === 'viewer') { region('driver-live', V.viewerContent(state)); return; }
  region('header-health', V.healthMarkup(state));
  region('network-banner', V.networkBanner(state));
  region('alert-count', V.activeAlerts(state).length ? String(V.activeAlerts(state).length) : '');
  const page = state.route.page;
  if (page === 'overview') {
    region('overview-stats', V.overviewStats(state)); region('parking', V.parking(state));
    region('overview-alerts', V.overviewAlerts(state));
  } else if (page === 'devices') {
    if (state.route.deviceId) region('device-detail', V.detailLive(state)); else region('device-rows', V.deviceRows(state));
  } else if (page === 'telemetry') {
    region('chart', V.chart(state)); region('stats-breakdown', V.statsBreakdown(state));
  } else if (page === 'alerts') region('alert-rows', V.alertRows(state));
  else if (page === 'commands') {
    region('command-live', V.commandLive(state)); region('command-rows', V.commandRows(state));
    const d = V.selected(state), p = state.permissions;
    const ready = state.apiConnected && d?.connectivity === 'online' && ['active', 'provisioned'].includes(d?.status);
    for (const button of document.querySelectorAll('[data-command]')) {
      if (!button.closest('form')?.dataset.busy) button.disabled = !(ready && (button.dataset.command === 'ping' ? p?.can_control : p?.can_configure));
    }
    const rulesButton = document.querySelector('[data-rule-submit]');
    if (rulesButton && !rulesButton.closest('form')?.dataset.busy) rulesButton.disabled = !(state.apiConnected && p?.can_configure);
    region('rule-effective', 'Ngưỡng thực tế: ' + (state.rules?.effective_offline_timeout_s ?? d?.effective_offline_timeout_s ?? '—') + ' giây, tối thiểu bằng 3 chu kỳ gửi.');
  } else if (page === 'users') region('user-rows', V.userRows(state));
  else if (page === 'audit') region('audit-rows', V.auditRows(state));
  if (modal.open && modal.dataset.commandId) {
    const command = state.commands.find(c => c.id === modal.dataset.commandId);
    if (command) region('command-detail', commandDetails(command));
  }
}
async function refreshCore({ full = false, render = true } = {}) {
  if (!state.token) return;
  if (refreshPromise) {
    await refreshPromise;
    if (!full || !state.token) return;
  }
  const token = state.token;
  const request = (async () => {
    const adminRefresh = state.me?.role === 'admin' && (full || Date.now() - lastAdminFetch > 30000);
    const meRefresh = full || Date.now() - lastMeFetch > 30000;
    try {
      if (state.me?.role === 'viewer') {
        const [parking, me] = await Promise.all([api('/parking/overview'), meRefresh ? api('/auth/me') : state.me]);
        if (token !== state.token || !state.me) return;
        state.parking = parking; state.me = me; state.apiConnected = true;
        state.loadError = ''; state.lastSync = Date.now();
        if (meRefresh) lastMeFetch = Date.now();
        return;
      }
      const [health, devices, slots, alerts, users, me] = await Promise.all([
        api('/health'), api('/devices'), api('/parking/slots'),
        api('/alerts?limit=200'), adminRefresh ? api('/users') : state.users,
        meRefresh ? api('/auth/me') : state.me,
      ]);
      if (token !== state.token || !state.me) return;
      const oldSelection = state.selectedDeviceId;
      state.health = health; state.devices = devices; state.slots = slots;
      state.alerts = alerts; state.users = users; state.me = me;
      if (adminRefresh) lastAdminFetch = Date.now(); if (meRefresh) lastMeFetch = Date.now();
      if (!devices.some(d => String(d.id) === String(state.selectedDeviceId))) {
        state.selectedDeviceId = devices[0] ? String(devices[0].id) : ''; clearSelection();
      }
      state.apiConnected = true; state.loadError = ''; state.lastSync = Date.now();
      if (state.route.page === 'overview') {
        const gateResults = await Promise.allSettled(devices.filter(d => ['active', 'provisioned'].includes(d.status)).map(async d => ({ ...await api('/devices/' + d.id + '/gates'), name: d.name, connectivity: d.connectivity })));
        if (token !== state.token || !state.me) return;
        state.gates = gateResults.filter(r => r.status === 'fulfilled').map(r => r.value);
      }
      if (oldSelection !== state.selectedDeviceId && document.querySelector('#page-content')) {
        renderMain();
      }
    } catch (error) {
      if (token === state.token && state.me) { state.apiConnected = false; state.loadError = error.message; }
      if (full) throw error;
    } finally {
      if (refreshPromise === request) refreshPromise = null;
      if (render) renderLive();
    }
  })();
  refreshPromise = request;
  return request;
}
async function loadSelection({ force = false } = {}) {
  const d = V.selected(state);
  if (!d || !state.token || state.me?.role === 'viewer') return;
  const token = state.token, epoch = selectionEpoch, id = d.id;
  const needsStats = state.route.page === 'telemetry' && (force || Date.now() - lastStatsFetch > 15000);
  state.selectionLoading = true;
  const paths = {
    permissions: '/devices/' + id + '/permissions',
    config: '/devices/' + id + '/configuration', rules: '/devices/' + id + '/rules',
    commands: '/devices/' + id + '/commands?limit=50',
    latest: '/telemetry/latest' + query({ device_id: d.code }),
    ...(needsStats ? { stats: '/parking/utilization' + query({ device_id: d.code, ...(state.route.page === 'telemetry' ? state.historyRange : { from_at: new Date(Date.now() - 86400000).toISOString() }) }) } : {}),
  };
  const results = await Promise.allSettled(Object.values(paths).map(path => api(path)));
  if (token !== state.token || epoch !== selectionEpoch || String(id) !== String(state.selectedDeviceId)) return;
  state.selectionLoading = false;
  let inaccessible = false;
  Object.keys(paths).forEach((key, i) => {
    const result = results[i];
    if (result.status === 'fulfilled') state[key] = result.value;
    else {
      if (result.reason?.status === 404) inaccessible = true;
      state.loadError = result.reason?.message || 'Không tải được dữ liệu thiết bị.';
      if (key === 'permissions') state.permissions = null;
    }
  });
  if (inaccessible) {
    clearSelection(); state.loadError = 'Thiết bị không còn trong phạm vi truy cập. Danh sách sẽ được cập nhật.';
  } else if (needsStats) lastStatsFetch = Date.now();
}
async function loadHistory({ reset = false, mode = 'both', more = false } = {}) {
  const d = V.selected(state); if (!d || !state.token) return;
  if (reset || more) historyEpoch++;
  const token = state.token, epoch = selectionEpoch, requestEpoch = historyEpoch, historyRange = JSON.stringify(state.historyRange);
  if (reset) { state.history = []; state.historyEvents = []; state.historyFrozen = false; state.eventsFrozen = false; }
  state.historyLoading = more || reset;
  region('history-content', V.historyContent(state));
  try {
    const tasks = [];
    if ((mode === 'both' || mode === 'samples') && (!state.historyFrozen || more || reset)) {
      tasks.push(api('/telemetry' + query({ device_id: d.code, ...state.historyRange, limit: 50, before_id: more && mode === 'samples' ? state.history.at(-1)?.id : undefined }))
        .then(rows => ['samples', rows]));
    }
    if ((mode === 'both' || mode === 'events') && (!state.eventsFrozen || more || reset)) {
      tasks.push(api('/parking/events' + query({ device_id: d.id, ...state.historyRange, limit: 50, before_id: more && mode === 'events' ? state.historyEvents.at(-1)?.id : undefined }))
        .then(rows => ['events', rows]));
    }
    const results = await Promise.all(tasks);
    if (token !== state.token || epoch !== selectionEpoch || requestEpoch !== historyEpoch || historyRange !== JSON.stringify(state.historyRange)) return;
    for (const [kind, rows] of results) {
      if (kind === 'samples') {
        if (!more && !reset && state.historyFrozen) continue;
        state.history = more ? [...state.history, ...rows] : rows; state.historyHasMore = rows.length === 50; if (more) state.historyFrozen = true;
      } else {
        if (!more && !reset && state.eventsFrozen) continue;
        state.historyEvents = more ? [...state.historyEvents, ...rows] : rows; state.eventsHasMore = rows.length === 50; if (more) state.eventsFrozen = true;
      }
    }
  } finally {
    if (epoch === selectionEpoch && token === state.token && requestEpoch === historyEpoch) {
      state.historyLoading = false; region('history-content', V.historyContent(state));
    }
  }
}
async function loadView(force = false) {
  if (state.me?.role === 'viewer') return;
  if (['devices', 'telemetry', 'commands'].includes(state.route.page)) await loadSelection({ force });
  if (state.route.page === 'telemetry') await loadHistory({ reset: force });
  if (state.route.page === 'audit' && state.me?.role === 'admin') {
    const token = state.token, rows = await api('/audit-logs?limit=200');
    if (token === state.token) state.audit = rows;
  }
}
async function activateRoute() {
  if (!state.me) return;
  const epoch = ++routeEpoch;
  state.route = parseRoute();
  if (state.me.role === 'viewer' && !['overview', 'account'].includes(state.route.page)) { location.hash = '#/overview'; return; }
  if (['users', 'audit'].includes(state.route.page) && state.me.role !== 'admin') {
    location.hash = '#/overview'; toast('Trang này chỉ dành cho quản trị viên.', true); return;
  }
  if (state.route.page === 'devices' && state.route.deviceId && state.devices.some(d => d.id === state.route.deviceId)) {
    if (String(state.route.deviceId) !== String(state.selectedDeviceId)) { state.selectedDeviceId = String(state.route.deviceId); clearSelection(); }
  }
  setMenu(false);
  const host = document.querySelector('#page-content'); if (host) host.innerHTML = V.loading();
  try {
    await refreshCore({ full: true, render: false });
    await loadView(true);
  } catch (error) { if (state.me) toast(error.message, true); }
  if (epoch === routeEpoch && state.me) { renderMain(); renderLive(); }
}
async function startSession() {
  state.me = await api('/auth/me'); lastMeFetch = Date.now();
  state.route = parseRoute();
  if ((state.me.role === 'viewer' && !['overview', 'account'].includes(state.route.page)) || (state.me.role !== 'admin' && ['users', 'audit'].includes(state.route.page))) {
    state.route = { page: 'overview', deviceId: null };
    history.replaceState(null, '', '#/overview');
  }
  state.historyRange = timeRange(state.historyInputs.from, state.historyInputs.to);
  try { await refreshCore({ full: true, render: false }); } catch { /* Display the connection state, with no fabricated live values. */ }
  if (!state.me) return;
  mountShell(); await activateRoute();
  clearInterval(pollTimer); clearInterval(ageTimer);
  pollTimer = setInterval(async () => {
    if (!state.me || document.hidden || refreshPromise || pollRunning) return;
    pollRunning = true;
    try {
      await refreshCore();
      if (state.apiConnected) await loadView(false);
      renderLive();
    } catch (error) { if (state.me) { state.loadError = error.message; renderLive(); } }
    finally { pollRunning = false; }
  }, 3000);
  ageTimer = setInterval(() => {
    if (state.me?.role === 'viewer' && !document.hidden) { region('driver-live', V.viewerContent(state)); return; }
    if (state.me && state.route.page === 'overview' && !document.hidden) {
      region('overview-stats', V.overviewStats(state)); region('parking', V.parking(state));
      region('overview-alerts', V.overviewAlerts(state)); region('gate-controls', V.gateControls(state));
    }
    if (state.me && state.me.role !== 'viewer' && !document.hidden) region('alert-count', V.activeAlerts(state).length ? String(V.activeAlerts(state).length) : '');
  }, 1000);
}
function openModal(title, content, { wide = false } = {}) {
  modalEpoch++;
  if (modal.open) modal.close();
  delete modal.dataset.commandId; modal.dataset.busy = '';
  modal.className = wide ? 'wide' : '';
  modal.innerHTML = `<header class="modal-header"><h2 id="modal-title">${e(title)}</h2><button class="btn-icon" data-action="close-modal" aria-label="Đóng hộp thoại">${icon('close')}</button></header><div class="modal-body">${content}</div>`;
  modal.showModal();
}
function closeModal(force = false) {
  if (modal.dataset.busy && !force) return;
  modalEpoch++;
  if (modal.open) modal.close();
  modal.replaceChildren(); delete modal.dataset.commandId; delete modal.dataset.busy;
}
function buttons(label = 'Lưu thay đổi', danger = false) {
  return `<p class="form-error" role="alert"></p><div class="modal-actions"><button class="btn" type="button" data-action="close-modal">Hủy</button><button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" type="submit">${e(label)}</button></div>`;
}
function field(label, name, value = '', { type = 'text', required = false, max = 100, min, hint = '', autocomplete = 'off', pattern = '' } = {}) {
  return `<label class="field">${e(label)}<input type="${e(type)}" name="${e(name)}" value="${e(value)}" maxlength="${max}"${required ? ' required' : ''}${min ? ' minlength="' + min + '"' : ''} autocomplete="${e(autocomplete)}"${pattern ? ' pattern="' + e(pattern) + '"' : ''}>${hint ? '<small>' + e(hint) + '</small>' : ''}</label>`;
}
const getDevice = id => state.devices.find(d => d.id === Number(id));
function deviceContext(id) {
  const d = getDevice(id); if (!d) throw new Error('Thiết bị không còn trong phạm vi truy cập.'); return d;
}
function createDeviceModal() {
  openModal('Đăng ký thiết bị', `<form data-form="create-device">${field('Tên thiết bị', 'name', '', { required: true, max: 100, hint: 'Tên dễ nhận biết trong danh sách giám sát.' })}${field('Mã định danh duy nhất', 'code', '', { required: true, max: 64, pattern: '[a-zA-Z0-9_][a-zA-Z0-9_\\-]*', hint: 'Chữ, số, dấu gạch dưới hoặc gạch ngang. Sau khi tạo, cấp kết nối MQTT trong chi tiết thiết bị.' })}${buttons('Đăng ký thiết bị')}</form>`);
}
function metadataModal(id) {
  const d = deviceContext(id);
  openModal('Thông tin thiết bị', `<form data-form="metadata" data-id="${d.id}"><p class="muted small">${e(d.name)} · ${e(d.code)}</p><br>${field('Vị trí / khu vực', 'location', d.location || '', { max: 100 })}<label class="field">Ghi nhận lỗi / bảo trì<textarea name="fault" maxlength="200" rows="3" placeholder="Để trống nếu chưa ghi nhận lỗi">${e(d.fault || '')}</textarea></label>${buttons()}</form>`);
}
function lifecycleModal(id) {
  const d = deviceContext(id);
  const options = TRANSITIONS[d.status].filter(status => status !== 'provisioned' || d.broker_provisioned);
  if (!options.length) { toast('Thiết bị cần được cấp kết nối MQTT trước khi chuyển trạng thái.', true); return; }
  openModal('Chuyển trạng thái thiết bị', `<form data-form="lifecycle" data-id="${d.id}"><p class="muted small">${e(d.name)} · Hiện tại: ${e(LIFE[d.status])}</p><br>
    <label class="field">Trạng thái mới<select name="status">${options.map(v => `<option value="${v}">${LIFE[v]}</option>`).join('')}</select></label>
    <div class="banner">${icon('info')}Thu hồi sẽ ngắt và chặn kết nối MQTT. Ngừng sử dụng là trạng thái kết thúc, không thể kích hoạt lại. Các lệnh đang chờ sẽ bị hủy khi chuyển sang bảo trì, thu hồi hoặc ngừng sử dụng.</div>${buttons('Xác nhận chuyển trạng thái')}</form>`);
}
function provisionModal(id, rotate = false) {
  const d = deviceContext(id);
  openModal(rotate ? 'Đổi mật khẩu MQTT' : 'Cấp kết nối MQTT', `<form data-form="${rotate ? 'rotate' : 'provision'}" data-id="${d.id}"><p class="small">Thiết bị <strong>${e(d.name)}</strong> · <code>${e(d.code)}</code></p><br>
    <div class="banner">${icon('key')}Mật khẩu mới chỉ hiển thị một lần. Bạn cần lưu lại và cập nhật vào cấu hình MQTT trên ESP32.${rotate ? ' Thông tin kết nối cũ sẽ không còn sử dụng được.' : ''}</div>${buttons(rotate ? 'Đổi mật khẩu' : 'Cấp thông tin kết nối', rotate)}</form>`);
}
function credentialsModal(result, id) {
  const d = getDevice(id);
  openModal('Thông tin MQTT · Chỉ hiển thị một lần', `<div class="banner success">${icon('check')}Broker đã xác nhận. Lưu mật khẩu trước khi đóng hộp thoại và cập nhật cấu hình trên thiết bị.</div>
    <dl class="detail-list"><dt>Tên đăng nhập</dt><dd><code>${e(result.mqtt_username)}</code></dd>${result.telemetry_topic ? '<dt>Topic telemetry</dt><dd><code>' + e(result.telemetry_topic) + '</code></dd><dt>Topic lệnh</dt><dd><code>' + e(result.command_topic) + '</code></dd><dt>Topic ACK</dt><dd><code>' + e(result.ack_topic) + '</code></dd>' : ''}</dl>
    <p class="small muted">Mật khẩu MQTT mới</p><div class="secret" id="mqtt-secret">${e(result.mqtt_password)}</div>
    <p class="form-hint command-hint">${d?.status === 'provisioned' ? 'Sau khi cấu hình kết nối thiết bị, chuyển vòng đời sang Đang hoạt động để theo dõi ô đỗ.' : 'Cập nhật mật khẩu mới vào thiết bị. Hệ thống không thể hiển thị lại mật khẩu này.'}</p>
    <div class="modal-actions"><button class="btn" data-action="copy-secret">Sao chép mật khẩu</button><button class="btn btn-primary" data-action="close-modal">Đã lưu, đóng</button></div>`);
}
async function grantsModal(id) {
  const d = deviceContext(id), token = state.token;
  openModal('Quyền truy cập · ' + d.name, V.loading(), { wide: true });
  const epoch = modalEpoch;
  let grants;
  try { grants = await api('/devices/' + d.id + '/grants'); }
  catch (error) {
    if (modal.open && token === state.token && epoch === modalEpoch) {
      modal.querySelector('.modal-body').innerHTML = V.empty('Không tải được quyền truy cập', error.message);
    }
    throw error;
  }
  if (!modal.open || token !== state.token || epoch !== modalEpoch) return;
  modalGrants = grants;
  const candidates = state.users.filter(u => u.active && u.role !== 'admin');
  const rows = grants.map(g => { const user = state.users.find(u => u.id === g.user_id); return `<tr><td><strong>${e(user?.username || '#' + g.user_id)}</strong><small>${e(ROLE[user?.role] || '')}</small></td><td>${V.badge('Xem', 'green')}</td><td>${V.badge(g.can_control && user?.role === 'operator' ? 'Có' : 'Không', g.can_control && user?.role === 'operator' ? 'green' : 'neutral')}</td><td>${V.badge(g.can_configure && user?.role === 'operator' ? 'Có' : 'Không', g.can_configure && user?.role === 'operator' ? 'green' : 'neutral')}</td><td><button class="btn btn-small btn-danger" data-action="remove-grant" data-id="${d.id}" data-user="${g.user_id}">Thu hồi</button></td></tr>`; }).join('');
  modal.querySelector('.modal-body').innerHTML = `<p class="muted small">Quản trị viên mặc định có toàn quyền. Các quyền dưới đây áp dụng cho operator và viewer.</p><br><div class="table-wrap"><table><thead><tr><th>NGƯỜI DÙNG</th><th>XEM</th><th>PING</th><th>CẤU HÌNH</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="5" class="table-empty">Chưa cấp quyền cho tài khoản nào.</td></tr>'}</tbody></table></div><br>
    ${candidates.length ? `<form data-form="grant" data-id="${d.id}"><h3>Cấp mới hoặc cập nhật quyền</h3><br><label class="field">Tài khoản<select name="user_id" data-grant-user>${candidates.map(u => `<option value="${u.id}">${e(u.username)} · ${e(ROLE[u.role])}</option>`).join('')}</select></label>
    <div class="row"><label class="checkbox"><input type="checkbox" name="can_control">Cho phép ping</label><label class="checkbox"><input type="checkbox" name="can_configure">Cho phép cấu hình</label></div><p class="form-hint">Chỉ operator được nhận quyền ping/cấu hình. Viewer luôn chỉ có quyền xem.</p>${buttons('Lưu quyền truy cập')}</form>`
      : '<p class="muted small">Tạo tài khoản operator/viewer trước khi cấp quyền.</p><div class="modal-actions"><button class="btn" data-action="close-modal">Đóng</button></div>'}`;
  updateGrantFields();
}
function updateGrantFields() {
  const form = modal.querySelector('[data-form="grant"]'); if (!form) return;
  const id = Number(form.elements.user_id.value), operator = state.users.find(u => u.id === id)?.role === 'operator';
  const grant = modalGrants.find(g => g.user_id === id);
  for (const name of ['can_control', 'can_configure']) { form.elements[name].disabled = !operator; form.elements[name].checked = operator && !!grant?.[name]; }
}
function removeGrantModal(id, userId) {
  const d = deviceContext(id), user = state.users.find(u => u.id === Number(userId));
  openModal('Thu hồi quyền thiết bị', `<form data-form="remove-grant" data-id="${d.id}" data-user="${Number(userId)}"><p class="small">Thu hồi toàn bộ quyền của <strong>${e(user?.username || userId)}</strong> đối với <strong>${e(d.name)}</strong>?</p><p class="form-hint command-hint">Tài khoản sẽ không còn truy cập thiết bị, dữ liệu, cảnh báo và lịch sử lệnh thuộc thiết bị này.</p>${buttons('Thu hồi quyền', true)}</form>`);
}
function assignSlotModal(id) {
  const d = deviceContext(id);
  openModal('Gán thiết bị cho ô đỗ', `<form data-form="assign-slot" data-id="${d.id}"><p class="small">Thiết bị: <strong>${e(d.name)}</strong></p><br><label class="field">Ô đỗ<select name="slot"><option value="P1">P1 · GPIO27</option><option value="P2">P2 · GPIO26</option></select></label>
    <div class="banner">${icon('info')}Mỗi ô thuộc một thiết bị. Gán lại sẽ thay thế thiết bị đang theo dõi ô đó. Chỉ thực hiện khi đấu nối thực tế đã đúng.</div>
    <label class="checkbox"><input type="checkbox" name="confirm_assignment" required>Tôi xác nhận gán hoặc thay thế thiết bị cho ô đã chọn.</label>${buttons('Xác nhận gán ô')}</form>`);
}
function userModal(id) {
  const user = id ? state.users.find(u => u.id === Number(id)) : null;
  const self = user?.id === state.me.id;
  if (id && !user) throw new Error('Tài khoản không còn tồn tại.');
  openModal(user ? 'Quản lý tài khoản' : 'Tạo tài khoản', `<form data-form="${user ? 'edit-user' : 'create-user'}"${user ? ' data-id="' + user.id + '"' : ''}>
    ${user ? '<p class="small"><strong>' + e(user.username) + '</strong></p><br>' : field('Tên đăng nhập', 'username', '', { required: true, min: 3, max: 64, pattern: '[a-zA-Z0-9_.\\-]+', autocomplete: 'off' }) + field('Mật khẩu ban đầu', 'password', '', { required: true, min: 10, max: 128, type: 'password', autocomplete: 'new-password' })}
    <label class="field">Vai trò<select name="role"${self ? ' disabled' : ''}>${Object.entries(ROLE).map(([v, t]) => `<option value="${v}"${(user?.role || 'viewer') === v ? ' selected' : ''}>${t}</option>`).join('')}</select></label>
    ${user ? `<label class="checkbox"><input type="checkbox" name="active"${user.active ? ' checked' : ''}${self ? ' disabled' : ''}>Cho phép tài khoản hoạt động</label><p class="form-hint">${self ? 'Không thể tự khóa hoặc hạ quyền tài khoản đang đăng nhập.' : 'Thay đổi vai trò/trạng thái sẽ thu hồi các phiên đăng nhập của tài khoản này.'}</p>` : '<p class="form-hint">Sau khi tạo, cấp quyền theo từng thiết bị trong trang Thiết bị. Mật khẩu không được hiển thị lại.</p>'}${buttons(user ? 'Lưu thay đổi' : 'Tạo tài khoản')}</form>`);
}
function commandDetails(c) {
  return `<div class="row between"><strong>${c.action === 'ping' ? 'Kiểm tra phản hồi' : 'Đổi chu kỳ gửi'}</strong>${V.commandBadge(c.status)}</div><dl class="detail-list"><dt>Mã lệnh</dt><dd><code>${e(c.id)}</code></dd><dt>Tạo lúc</dt><dd>${e(dateTime(c.created_at))}</dd><dt>Hết hạn</dt><dd>${e(dateTime(c.expires_at))}</dd><dt>Hoàn tất</dt><dd>${c.completed_at ? e(dateTime(c.completed_at)) : 'Chưa hoàn tất'}</dd><dt>Số lần gửi</dt><dd>${c.attempts}</dd></dl>
    <h3>Tham số yêu cầu</h3><pre class="result-json">${e(JSON.stringify(c.arguments, null, 2))}</pre><h3>Phản hồi từ thiết bị</h3><pre class="result-json">${e(c.result ? JSON.stringify(c.result, null, 2) : 'Chưa nhận phản hồi xác nhận')}</pre>${c.error ? '<div class="banner error">' + e(V.commandError(c.error)) + '</div>' : ''}`;
}
async function commandModal(id) {
  const token = state.token;
  const c = await api('/commands/' + encodeURIComponent(id));
  if (!state.me || token !== state.token) return;
  openModal('Chi tiết lệnh', `<div data-region="command-detail">${commandDetails(c)}</div><div class="modal-actions"><button class="btn" data-action="close-modal">Đóng</button></div>`);
  modal.dataset.commandId = c.id;
}
async function afterMutation({ rerender = true } = {}) {
  await refreshCore({ full: true, render: false }); await loadView(false);
  if (rerender && state.me) renderMain(); renderLive();
}
function busy(form, value) {
  if (value) form.dataset.busy = 'true'; else delete form.dataset.busy;
  for (const button of form.querySelectorAll('button[type="submit"]')) button.disabled = value;
  if (form.closest('dialog')) modal.dataset.busy = value ? 'true' : '';
}
async function submit(form, submitter) {
  if (form.dataset.busy) return;
  const errorNode = form.querySelector('.form-error'); if (errorNode) errorNode.textContent = '';
  const data = new FormData(form), kind = form.dataset.form, id = Number(form.dataset.id);
  busy(form, true);
  try {
    if (kind === 'login') {
      const result = await api('/auth/login', { method: 'POST', body: { username: String(data.get('username')).trim(), password: String(data.get('password')) } });
      saveToken(result.access_token); await startSession();
    } else if (kind === 'password') {
      if (data.get('new_password') !== data.get('confirm_password')) throw new Error('Mật khẩu nhập lại chưa khớp.');
      await api('/auth/password', { method: 'POST', body: { old_password: data.get('old_password'), new_password: data.get('new_password') } });
      endSession('Đã đổi mật khẩu. Vui lòng đăng nhập bằng mật khẩu mới.');
    } else if (kind === 'create-device') {
      const d = await api('/devices', { method: 'POST', body: { name: String(data.get('name')).trim(), code: String(data.get('code')).trim() } });
      closeModal(true); await refreshCore({ full: true }); location.hash = '#/devices/' + d.id;
      toast('Đã đăng ký thiết bị. Tiếp theo, cấp kết nối MQTT.');
    } else if (kind === 'metadata') {
      await api('/devices/' + id + '/metadata', { method: 'PATCH', body: { location: String(data.get('location')).trim(), fault: String(data.get('fault')).trim() || null } });
      closeModal(true); await afterMutation(); toast('Đã cập nhật thông tin thiết bị.');
    } else if (kind === 'lifecycle') {
      await api('/devices/' + id, { method: 'PATCH', body: { status: data.get('status') } });
      closeModal(true); await afterMutation(); toast('Backend và broker đã xác nhận trạng thái mới.');
    } else if (kind === 'provision' || kind === 'rotate') {
      const result = await api('/devices/' + id + (kind === 'provision' ? '/provision' : '/credentials/rotate'), { method: 'POST' });
      credentialsModal(result, id);
      try { await afterMutation(); } catch { toast('Đã cấp thông tin MQTT. Hãy lưu mật khẩu; danh sách thiết bị sẽ cập nhật khi kết nối phục hồi.', true); }
    } else if (kind === 'grant') {
      await api('/devices/' + id + '/grants/' + Number(data.get('user_id')), { method: 'PUT', body: { can_control: data.get('can_control') === 'on', can_configure: data.get('can_configure') === 'on' } });
      await grantsModal(id); await afterMutation(); toast('Đã cập nhật quyền thiết bị.');
    } else if (kind === 'remove-grant') {
      await api('/devices/' + id + '/grants/' + Number(form.dataset.user), { method: 'DELETE' });
      closeModal(true); await afterMutation(); await grantsModal(id); toast('Đã thu hồi quyền truy cập.');
    } else if (kind === 'assign-slot') {
      await api('/devices/' + id + '/slot', { method: 'PUT', body: { slot: data.get('slot') } });
      closeModal(true); await afterMutation(); toast('Đã gán thiết bị cho ' + data.get('slot') + '.');
    } else if (kind === 'create-user') {
      await api('/users', { method: 'POST', body: { username: String(data.get('username')).trim(), password: data.get('password'), role: data.get('role') } });
      closeModal(true); await afterMutation(); toast('Đã tạo tài khoản. Cấp quyền thiết bị để người dùng truy cập dữ liệu.');
    } else if (kind === 'edit-user') {
      const user = state.users.find(u => u.id === id);
      await api('/users/' + id, { method: 'PATCH', body: { role: data.get('role') || user.role, active: id === state.me.id ? user.active : data.get('active') === 'on' } });
      closeModal(true); await afterMutation(); toast('Đã cập nhật tài khoản và thu hồi các phiên đăng nhập cũ.');
    } else if (kind === 'rules') {
      const d = V.selected(state); if (!d) throw new Error('Hãy chọn thiết bị.');
      await api('/devices/' + d.id + '/rules', { method: 'PUT', body: { offline_enabled: data.get('offline_enabled') === 'on', full_enabled: data.get('full_enabled') === 'on', offline_timeout_s: Number(data.get('offline_timeout_s')) } });
      await afterMutation({ rerender: false }); toast('Đã lưu quy tắc cảnh báo trên máy chủ.');
    } else if (kind === 'command') {
      const d = V.selected(state); if (!d) throw new Error('Hãy chọn thiết bị.');
      const action = submitter?.value;
      if (!['ping', 'configure'].includes(action)) throw new Error('Hãy chọn Ping thiết bị hoặc Gửi cấu hình.');
      const body = { action, timeout_s: Number(data.get('timeout_s')), ...(action === 'configure' ? { report_interval_ms: Number(data.get('report_interval_ms')) } : {}) };
      const fingerprint = JSON.stringify({ device: d.id, ...body });
      if (!commandAttempt || commandAttempt.fingerprint !== fingerprint) commandAttempt = { fingerprint, key: commandKey() };
      const command = await api('/devices/' + d.id + '/commands', { method: 'POST', body: { ...body, idempotency_key: commandAttempt.key } });
      commandAttempt = null; await loadSelection(); renderLive();
      toast(command.status === 'acknowledged' ? 'Thiết bị đã xác nhận thực hiện lệnh.' : 'Đã tạo yêu cầu. Đang chờ thiết bị xác nhận ACK.');
    } else if (kind === 'history-filter') {
      const from = String(data.get('from') || ''), to = String(data.get('to') || '');
      const range = timeRange(from, to);
      state.historyInputs = { from, to }; state.historyRange = range;
      await loadSelection({ force: true }); await loadHistory({ reset: true });
      region('chart', V.chart(state)); region('stats-breakdown', V.statsBreakdown(state));
    }
  } catch (error) {
    if (errorNode?.isConnected) errorNode.textContent = error.message; else if (state.me || kind === 'login') toast(error.message, true);
  } finally {
    busy(form, false); if (kind === 'command' || kind === 'rules') renderLive();
  }
}
async function exportCsv(button) {
  const d = V.selected(state); if (!d) throw new Error('Hãy chọn thiết bị để xuất dữ liệu.');
  button.disabled = true;
  try {
    const response = await api('/telemetry/export.csv' + query({ device_id: d.code, ...state.historyRange, limit: 10000 }), { raw: true });
    const blob = new Blob(['\uFEFF', await response.blob()], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob), a = document.createElement('a');
    a.href = url; a.download = 'parking-' + d.code + '-' + new Date().toISOString().slice(0, 10) + '.csv';
    document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000);
    toast('Đã xuất dữ liệu CSV trong khoảng thời gian đã chọn.');
  } finally { button.disabled = false; }
}
async function click(action, node) {
  const id = node.dataset.id;
  switch (action) {
    case 'ack-alert': {
      if (!['admin', 'operator'].includes(state.me.role) || state.alertBusy[id]) return;
      state.alertBusy[id] = true; renderLive();
      try {
        await api('/alerts/' + id + '/acknowledge', { method: 'POST' });
        await refreshCore({ full: true });
        toast('Đã ghi nhận bạn đã xem cảnh báo.');
      } finally { delete state.alertBusy[id]; renderLive(); }
      break;
    }
    case 'gate-mode': case 'gate-target': {
      const deviceId = Number(node.dataset.device), gate = node.dataset.gate;
      const key = deviceId + ':' + gate;
      if (state.me.role !== 'admin' || state.gateBusy[key]) return;
      state.gateBusy[key] = true; renderLive();
      try {
        await api('/devices/' + deviceId + '/commands', { method: 'POST', body: {
          action: action === 'gate-mode' ? 'gate_mode' : 'gate', gate,
          ...(action === 'gate-mode' ? { mode: node.dataset.value } : { target: node.dataset.value }),
          timeout_s: 5, idempotency_key: commandKey(),
        } });
        await refreshCore({ full: true });
        toast('Đã gửi yêu cầu đến cổng.');
      } finally { delete state.gateBusy[key]; renderLive(); }
      break;
    }
    case 'select-bay': state.viewerSlot = node.dataset.slot; renderLive(); break;
    case 'skip-content': {
      const main = document.querySelector('#main-content'); main?.focus(); main?.scrollIntoView({ block: 'start' }); break;
    }
    case 'menu': setMenu(!document.body.classList.contains('nav-open')); break;
    case 'close-menu': setMenu(false); break;
    case 'close-modal': closeModal(); break;
    case 'logout': {
      let confirmed = false; try { await api('/auth/logout', { method: 'POST' }); confirmed = true; } catch { /* Local logout still clears the token. */ }
      endSession(confirmed ? 'Bạn đã đăng xuất.' : 'Đã xóa phiên trên trình duyệt. Chưa nhận được xác nhận thu hồi từ máy chủ.'); break;
    }
    case 'refresh': {
      node.disabled = true; try { await refreshCore({ full: true }); await loadView(true); renderMain(); renderLive(); } finally { if (node.isConnected) node.disabled = false; } break;
    }
    case 'create-device': createDeviceModal(); break;
    case 'edit-metadata': metadataModal(id); break;
    case 'lifecycle': lifecycleModal(id); break;
    case 'provision': provisionModal(id); break;
    case 'rotate': provisionModal(id, true); break;
    case 'grants': await grantsModal(id); break;
    case 'remove-grant': removeGrantModal(id, node.dataset.user); break;
    case 'assign-slot': assignSlotModal(id); break;
    case 'create-user': userModal(); break;
    case 'edit-user': userModal(id); break;
    case 'go-history': case 'go-commands': {
      state.selectedDeviceId = String(id); clearSelection();
      location.hash = action === 'go-history' ? '#/telemetry' : '#/commands'; break;
    }
    case 'copy-secret': {
      const value = modal.querySelector('#mqtt-secret')?.textContent;
      if (value) { try { await navigator.clipboard.writeText(value); toast('Đã sao chép mật khẩu MQTT.'); } catch { toast('Trình duyệt chưa cho phép sao chép. Hãy chọn và sao chép mật khẩu trong hộp thoại.', true); } } break;
    }
    case 'command-detail': await commandModal(id); break;
    case 'history-tab': state.historyTab = node.dataset.tab; renderMain(); break;
    case 'load-history': await loadHistory({ mode: 'samples', more: true }); break;
    case 'load-events': await loadHistory({ mode: 'events', more: true }); break;
    case 'reset-history':
      state.historyInputs = { from: localInput(Date.now() - 86400000), to: '' }; state.historyRange = timeRange(state.historyInputs.from, '');
      await loadSelection({ force: true }); await loadHistory({ reset: true }); renderMain(); break;
    case 'export-csv': await exportCsv(node); break;
  }
}
function setMenu(open) {
  document.body.classList.toggle('nav-open', open);
  document.querySelector('[data-action="menu"]')?.setAttribute('aria-expanded', String(open));
}
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && document.body.classList.contains('nav-open')) {
    setMenu(false); document.querySelector('[data-action="menu"]')?.focus();
  }
});
document.addEventListener('submit', event => {
  const form = event.target.closest('form[data-form]');
  if (form) { event.preventDefault(); void submit(form, event.submitter); }
});
document.addEventListener('click', event => {
  const node = event.target.closest('[data-action]');
  if (node && node.tagName !== 'SELECT' && !node.disabled) {
    const action = node.dataset.action;
    if (action) { event.preventDefault(); void click(action, node).catch(error => { if (state.me) toast(error.message, true); }); }
  }
});
document.addEventListener('change', event => {
  const node = event.target;
  if (node.matches('[data-action="select-device"]')) {
    state.selectedDeviceId = node.value; clearSelection();
    void (async () => { renderMain(); await loadView(true); renderMain(); renderLive(); })().catch(error => toast(error.message, true));
  } else if (node.name === 'device-status') { state.deviceStatus = node.value; region('device-rows', V.deviceRows(state)); }
  else if (node.name === 'alert-filter') { state.alertFilter = node.value; region('alert-rows', V.alertRows(state)); }
  else if (node.matches('[data-grant-user]')) updateGrantFields();
});
document.addEventListener('input', event => {
  if (event.target.name === 'device-search') { state.deviceSearch = event.target.value; region('device-rows', V.deviceRows(state)); }
  if (event.target.name === 'user-search') { state.userSearch = event.target.value; region('user-rows', V.userRows(state)); }
});
modal.addEventListener('cancel', event => { if (modal.dataset.busy) event.preventDefault(); });
modal.addEventListener('close', () => {
  if (modal.open) return;
  modal.replaceChildren(); delete modal.dataset.commandId; delete modal.dataset.busy; modalGrants = [];
});
window.addEventListener('hashchange', () => { void activateRoute(); });
window.addEventListener('pagehide', () => { clearInterval(pollTimer); clearInterval(ageTimer); });
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && state.me) void refreshCore({ full: true }).then(() => loadView(false)).then(renderLive).catch(() => {});
});
if (state.token) {
  try { await startSession(); } catch (error) { endSession(error.message); }
} else endSession();
