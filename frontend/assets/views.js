import { viewerShell, viewerPage, viewerContent } from './viewer.js?v=20261106-lot-map1';
export { viewerContent };
import { esc as e, icon, car, number, ROLE, LIFE, COMMAND, TRANSITIONS, dateTime, ago, timestamp, countSlots, slotState, sampleSummary, durationSummary } from './core.js?v=20261106-lot-map1';

export const TITLES = { overview: 'Tổng quan', devices: 'Thiết bị', telemetry: 'Dữ liệu & lịch sử', alerts: 'Cảnh báo', commands: 'Lệnh & cấu hình', users: 'Người dùng', audit: 'Nhật ký hệ thống', account: 'Tài khoản' };
export function empty(title, description = '', glyph = 'info', action = '') {
  return `<div class="empty-state">${icon(glyph)}<h3>${e(title)}</h3><p>${e(description)}</p>${action}</div>`;
}
export const loading = () => '<div class="loading"><span class="spinner"></span>Đang tải dữ liệu…</div>';
export function badge(text, tone = 'neutral') { return `<span class="badge badge-${tone}">${e(text)}</span>`; }
export function connection(d, connected = true) {
  if (!connected) return badge('Mất kết nối máy chủ', 'amber');
  const c = { online: ['Trực tuyến', 'green'], offline: ['Ngoại tuyến', 'amber'], disabled: ['Đã khóa kết nối', 'neutral'], unknown: ['Chưa có tín hiệu', 'neutral'] };
  const [label, tone] = c[d?.connectivity] || c.unknown;
  return badge(label, tone);
}
export function lifecycle(d) { return badge(LIFE[d?.status] || d?.status || 'Chưa biết', ({ active: 'green', maintenance: 'amber', revoked: 'red', provisioned: 'blue' })[d?.status] || 'neutral'); }
export function commandBadge(status) {
  return badge(COMMAND[status] || status, ({ acknowledged: 'green', failed: 'red', timed_out: 'red', queued: 'blue', sent: 'amber' })[status] || 'neutral');
}
export function occupancy(value) { return value === true ? badge('Có xe', 'amber') : value === false ? badge('Trống', 'green') : badge('Không xác định'); }
export function deviceOptions(s, value = s.selectedDeviceId) {
  return s.devices.length ? s.devices.map(d => `<option value="${d.id}"${String(d.id) === String(value) ? ' selected' : ''}>${e(d.name)} · ${e(d.code)}</option>`).join('')
    : '<option value="">Chưa có thiết bị được cấp quyền</option>';
}
function heading(title, description, actions = '') {
  return `<div class="page-heading"><div><h1>${e(title)}</h1>${description ? `<p>${e(description)}</p>` : ''}</div>${actions ? `<div class="heading-actions">${actions}</div>` : ''}</div>`;
}
const refreshButton = () => `<button class="btn" data-action="refresh">${icon('refresh')}Làm mới</button>`;
function selectDevice(s) { return `<select aria-label="Chọn thiết bị" data-action="select-device">${deviceOptions(s)}</select>`; }
export function loginView(message = '') {
  return `<main class="login-layout" id="main-content" tabindex="-1"><section class="login-story">
    <div class="brand"><span class="brand-mark">P<span>↗</span></span><div class="brand-name">ParkFlow<small>SMART PARKING IOT</small></div></div>
    <div class="login-intro"><p class="eyebrow">MỘT GÓC NHÌN. MỌI TRẠNG THÁI.</p><h1>Bãi đỗ xe trong<br><span>tầm kiểm soát.</span></h1><p>Theo dõi chỗ đỗ, quản lý thiết bị và phản hồi kịp thời từ một không gian làm việc.</p>
    <div class="login-parking" aria-hidden="true"><div class="login-space"><strong>P1</strong>${car()}</div><div class="login-space outline"><strong>P2</strong>${car()}</div></div></div>
    <p class="login-footer">NGUYÊN MẪU 2 Ô ĐỖ &nbsp; / &nbsp; ESP32 · WIFI · MQTT</p>
    </section><section class="login-form-side"><div class="login-form-wrap">
    <p class="eyebrow">CHÀO MỪNG TRỞ LẠI</p><h2>Đăng nhập ParkFlow</h2><p>Truy cập không gian quản lý bãi đỗ xe của bạn.</p>
    <form data-form="login"><label class="field">Tên đăng nhập<input name="username" autocomplete="username" required minlength="3" maxlength="64" pattern="[a-zA-Z0-9_.\\-]+" placeholder="Nhập tên đăng nhập"></label>
    <label class="field">Mật khẩu<input type="password" name="password" autocomplete="current-password" required minlength="10" maxlength="128" placeholder="Nhập mật khẩu"></label>
    <p class="form-error" role="alert">${e(message)}</p><button class="btn btn-primary" type="submit">Đăng nhập ${icon('arrow')}</button></form>
    <div class="login-help">${icon('shield')}<div><strong>Quyền truy cập theo tài khoản</strong>Sử dụng tài khoản do quản trị viên cấp. Liên hệ quản trị viên nếu bạn chưa có tài khoản hoặc cần hỗ trợ đăng nhập.</div></div>
    </div></section></main>`;
}
export function shellView(s) {
  if (s.me.role === 'viewer') return viewerShell(s);
  const nav = [
    ['overview', 'dashboard', 'Tổng quan'], ['devices', 'device', 'Thiết bị'], ['telemetry', 'chart', 'Dữ liệu & lịch sử'],
    ['alerts', 'bell', 'Cảnh báo'], ['commands', 'command', s.me.role === 'viewer' ? 'Lịch sử lệnh' : 'Lệnh & cấu hình'],
  ];
  const navHtml = items => items.map(([route, glyph, label]) => `<a class="nav-link${s.route.page === route ? ' active' : ''}" href="#/${route}" data-nav="${route}"${s.route.page === route ? ' aria-current="page"' : ''}>${icon(glyph)}${e(label)}${route === 'alerts' ? '<span class="nav-count" data-region="alert-count">0</span>' : ''}</a>`).join('');
  return `<div class="app-shell"><aside class="sidebar" id="main-navigation" aria-label="Điều hướng chính">
    <a class="brand" href="#/overview"><span class="brand-mark">P<span>↗</span></span><div class="brand-name">ParkFlow<small>SMART PARKING IOT</small></div></a>
    <p class="sidebar-label">KHÔNG GIAN VẬN HÀNH</p><nav class="nav-list">${navHtml(nav)}</nav>
    ${s.me.role === 'admin' ? `<p class="sidebar-label">QUẢN TRỊ</p><nav class="nav-list">${navHtml([['users', 'users', 'Người dùng'], ['audit', 'shield', 'Nhật ký hệ thống']])}</nav>` : ''}
    <div class="sidebar-bottom"><a class="nav-link${s.route.page === 'account' ? ' active' : ''}" href="#/account" data-nav="account">${icon('settings')}Tài khoản</a>
    </div></aside>
    <button class="nav-backdrop" data-action="close-menu" aria-label="Đóng điều hướng" tabindex="-1"></button>
    <div class="main-shell"><header class="topbar"><div class="row"><button class="btn-icon mobile-only" data-action="menu" aria-controls="main-navigation" aria-expanded="false" aria-label="Mở điều hướng">${icon('menu')}</button>
    <div class="breadcrumb"><span>Không gian làm việc</span><span>/</span><strong id="breadcrumb-current">${e(TITLES[s.route.page])}</strong></div></div>
    <div class="topbar-right"><div data-region="header-health"></div><span class="topbar-divider"></span>
    <a class="profile-button" href="#/account"><span class="avatar">${e(s.me.username.slice(0, 2).toUpperCase())}</span><span class="profile-copy"><strong>${e(s.me.username)}</strong><small>${e(ROLE[s.me.role])}</small></span></a>
    <button class="btn-icon" data-action="logout" aria-label="Đăng xuất">${icon('logout')}</button></div></header>
    <main class="main-content" id="main-content" tabindex="-1"><div data-region="network-banner"></div><div id="page-content"></div></main>
    <footer class="app-footer"><span>ParkFlow · Hệ thống giám sát bãi đỗ xe IoT</span><span>Múi giờ UTC+7 &nbsp;·&nbsp; Cập nhật mỗi 3 giây</span></footer></div></div>`;
}
export function networkBanner(s) {
  if (!s.apiConnected) return `<div class="banner error" role="alert">${icon('wifi')}<span>Không kết nối được máy chủ. Các ô hiện tại được đánh dấu <strong>Không xác định</strong>; dữ liệu lịch sử có thể chưa được cập nhật.</span></div>`;
  if (s.loadError) return `<div class="banner error" role="alert">${icon('info')}${e(s.loadError)}</div>`;
  return '';
}
export function healthMarkup(s, sidebar = false) {
  const ready = s.apiConnected && s.health?.mqtt_connected && s.health?.mqtt_subscribed;
  return `<span class="status-line ${ready ? '' : 'offline'}"><span class="dot"></span>${s.apiConnected ? (ready ? 'MQTT đã kết nối' : 'MQTT chưa sẵn sàng') : 'Máy chủ mất kết nối'}</span>${sidebar ? '' : ''}`;
}
export function overviewStats(s) {
  const n = countSlots(s.slots, s.devices, s.apiConnected);
  return `<section class="parking-summary" aria-label="Thống kê chỗ đỗ"><div><span class="muted small">Chỗ còn trống</span><div class="summary-number">${number(n.free)}<span> / ${number(n.capacity)}</span></div></div>
    <div class="summary-details"><span>${number(n.occupied)} chỗ có xe</span>${n.unknown ? `<span class="text-unknown">${number(n.unknown)} chỗ chưa xác định</span>` : ''}</div></section>`;
}
export function parking(s) {
  if (!s.slots.length) return empty('Chưa có ô đỗ trong phạm vi truy cập', s.me.role === 'admin' ? 'Gán thiết bị cho P1/P2 trong trang Thiết bị để bắt đầu theo dõi.' : 'Quản trị viên cần cấp quyền thiết bị cho tài khoản của bạn.', 'pin', '<a class="btn btn-small" href="#/devices">Xem thiết bị</a>');
  const deviceIds = [...new Set(s.slots.map(slot => slot.device_id))];
  return deviceIds.map(id => {
    const d = (s.gates || []).find(d => d.device_id === id) || { device_id: id, gates: [] };
    return `<section class="lot-plan" aria-label="Sơ đồ bãi xe ${e(s.devices.find(d => d.id === id)?.name || '')}">
    <div class="lot-plan-caption"><span>${deviceIds.length > 1 ? e(s.devices.find(d => d.id === id)?.name) : 'KHU VỰC ĐỖ XE'}</span><div class="lot-key"><span><i class="dot free"></i>Trống</span><span><i class="dot occupied"></i>Có xe</span><span><i class="dot unknown"></i>Chưa rõ</span></div></div>
    <div class="lot-surface"><div class="lot-bays">${s.slots.filter(slot => slot.device_id === id).map(slot => {
      const status = slotState(slot, s.devices, s.apiConnected);
      const label = { occupied: 'Có xe', free: 'Trống', unknown: 'Không xác định' }[status];
      return `<div class="parking-spot lot-bay ${status}" aria-label="${e(slot.name)}: ${label}"><span class="spot-label">${e(slot.name)}</span>${status === 'unknown' ? '<span class="lot-question" aria-hidden="true">?</span>' : car()}<span class="spot-status"><span class="dot"></span>${label}</span></div>`;
    }).join('')}</div><div class="lot-aisle" aria-hidden="true"><span>↑</span><span>ĐƯỜNG NỘI BỘ</span><span>↓</span></div>
    <div class="lot-lanes">${['entrance', 'exit'].map(name => gateLane(s, d, name)).join('')}</div>
    <div class="lot-street" aria-hidden="true"><span>LỐI TIẾP CẬN BÃI XE</span></div></div>
    <p class="lot-note">Thanh chắn hiển thị theo tín hiệu điều khiển của ESP32.</p></section>`;
  }).join('');
}

function gateLane(s, d, name) {
  const g = d.gates?.find(g => g.id === name);
  const fresh = s.apiConnected && d.fresh && timestamp(d.valid_until) > Date.now();
  const presence = fresh && typeof g?.detected === 'boolean' ? (g.detected ? 'occupied' : 'free') : 'unknown';
  const target = fresh && g?.pwm_ready && ['open', 'closed'].includes(g.target) ? g.target : 'unknown';
  const entry = name === 'entrance';
  const title = entry ? 'Cổng vào' : 'Cổng ra';
  const label = { occupied: 'Có xe', free: 'Trống', unknown: 'Không xác định' }[presence];
  return `<div class="lot-lane ${name}" data-lane="${name}"><div class="lot-gate-heading"><h3>${title}</h3><span class="lot-gate-status ${target}">${{ open: 'Mở', closed: 'Đóng', unknown: 'Chưa rõ' }[target]}</span></div>
    <div class="lot-barrier ${target}" role="img" aria-label="${title}: ${{ open: 'tín hiệu mở', closed: 'tín hiệu đóng', unknown: 'không xác định' }[target]}"><span class="lot-barrier-base"></span><span class="lot-barrier-arm"></span><span class="lot-direction" aria-hidden="true">${entry ? '↑' : '↓'}</span></div>
    <div class="parking-spot lot-waiting ${presence}" aria-label="Ô chờ ${entry ? 'vào' : 'ra'}: ${label}"><span class="lot-waiting-label">Ô chờ ${entry ? 'vào' : 'ra'}</span>${presence === 'unknown' ? '<span class="lot-question" aria-hidden="true">?</span>' : car()}<span class="spot-status"><span class="dot"></span>${label}</span></div>
    ${s.me.role === 'admin' ? `<div class="lot-gate-actions">${g ? gateControl(s, d, g) : '<p class="muted small">Chưa có tín hiệu cổng</p>'}</div>` : ''}</div>`;
}
export function chart(s) {
  if (s.selectionLoading && !s.stats) return loading();
  const buckets = s.stats?.buckets || [];
  if (!buckets.length) return empty('Chưa có thời gian tổng hợp', 'Thống kê thời gian bắt đầu khi hệ thống nhận dữ liệu mới.', 'chart');
  const byHour = new Map();
  for (const b of buckets) {
    const row = byHour.get(b.hour) || { P1: 0, P2: 0 };
    row[b.slot] = b.occupied_seconds / 60; byHour.set(b.hour, row);
  }
  const rows = [...byHour].sort(([a], [b]) => timestamp(a) - timestamp(b)).slice(-48);
  const width = 560, height = 155, top = 12, left = 34, bottom = 23, plotHeight = height - top - bottom;
  const step = (width - left - 12) / rows.length, barWidth = Math.max(2, Math.min(10, step / 3));
  const lines = [0, 30, 60].map(v => { const y = height - bottom - v / 60 * plotHeight; return `<line class="grid-line" x1="${left}" x2="${width}" y1="${y}" y2="${y}"/><text x="${left - 8}" y="${y + 3}" text-anchor="end">${v}</text>`; }).join('');
  const bars = rows.map(([hour, row], i) => {
    const x = left + i * step + step / 2;
    const rect = (v, cls, offset, slot) => `<rect class="${cls}" x="${x + offset}" y="${height - bottom - v / 60 * plotHeight}" width="${barWidth}" height="${v / 60 * plotHeight}" rx="1"><title>${e(dateTime(hour))} · ${slot}: ${number(Math.round(v * 10) / 10)} phút có xe</title></rect>`;
    const tick = i % Math.max(1, Math.ceil(rows.length / 6)) === 0 || i === rows.length - 1;
    return rect(row.P1, 'bar-one', -barWidth - 1, 'P1') + rect(row.P2, 'bar-two', 1, 'P2')
      + (tick ? `<text x="${x}" y="${height - 4}" text-anchor="middle">${e(dateTime(hour, true).slice(0, 5))}</text>` : '');
  }).join('');
  return `<svg class="plot" viewBox="0 0 ${width} ${height}" role="img" aria-label="Số phút có xe theo giờ, hai chuỗi P1 và P2">${lines}${bars}</svg>
    <div class="row between"><div class="legend"><span class="legend-item"><i class="legend-dot"></i>P1</span><span class="legend-item"><i class="legend-dot series-two"></i>P2</span></div><span class="muted tiny">Đơn vị: phút có xe / giờ</span></div>
    <p class="plot-caption">Tổng hợp mỗi 30 giây theo giờ UTC+7, tối đa 48 khung giờ hiển thị. Khoảng trước mẫu đầu tiên không được suy diễn.</p>`;
}

export function overviewDevices(s) {
  return s.devices.length ? `<div class="device-health">${s.devices.slice(0, 3).map(d => `<a class="device-health-row" href="#/devices/${d.id}"><span class="device-icon">${icon('device')}</span><div class="grow"><strong>${e(d.name)}</strong><small>${e(d.code)} · ${e(d.location || 'Chưa gán vị trí')}</small></div>${connection(d, s.apiConnected)}</a>`).join('')}</div>`
    : empty('Chưa có thiết bị', 'Thiết bị được cấp quyền sẽ xuất hiện tại đây.', 'device');
}
export function activeParkingAlerts(s) {
  return s.alerts.filter(a => {
    if (a.kind !== 'parking_full' || !a.active || !s.apiConnected) return false;
    const slots = s.slots.filter(slot => slot.device_id === a.device_id);
    return slots.length > 0 && slots.every(slot => slotState(slot, s.devices, s.apiConnected) === 'occupied');
  });
}
export function activeAlerts(s) {
  if (!s.apiConnected) return [];
  const full = new Set(activeParkingAlerts(s).map(a => a.id));
  return s.alerts.filter(a => a.active && (a.kind === 'device_offline' || full.has(a.id)));
}
export function overviewAlerts(s) {
  const alerts = activeParkingAlerts(s);
  return alerts.length ? `<div class="full-notice" role="alert">${icon('bell')}<div><strong>Bãi đỗ đã đầy</strong><p>${alerts.map(a => e(s.devices.find(d => d.id === a.device_id)?.name || 'Khu vực đỗ xe')).join(' · ')} hiện không còn chỗ trống.</p></div></div>` : '';
}
export function overviewEvents(s) {
  if (!s.events.length) return `<tr><td colspan="4" class="table-empty">Chưa ghi nhận thay đổi trạng thái ô đỗ.</td></tr>`;
  return s.events.slice(0, 6).map(ev => `<tr><td class="mono">${e(dateTime(ev.occurred_at, true))}</td><td><strong>${e(ev.slot)}</strong></td><td>${e(eventTitle(ev.kind))}</td><td>${occupancy(ev.occupied)}</td></tr>`).join('');
}
export function gateControls(s) {
  if (s.me.role !== 'admin') return '';
  const devices = s.gates || [];
  return devices.filter(d => d.supported || d.connectivity === 'online').map(d => {
    if (!d.supported) return `<section class="panel gate-panel"><div class="panel-header"><h2>Cổng vào / ra</h2></div><div class="panel-body muted small">${e(d.name)}: cần nạp firmware 0.4.0 để điều khiển cổng.</div></section>`;
    return `<section class="panel gate-panel"><div class="panel-header"><h2>Cổng vào / ra</h2><span class="muted small">${e(d.name)}</span></div>${d.gates.map(g => `<div class="gate-row"><strong>${g.id === 'entrance' ? 'Cổng vào' : 'Cổng ra'}</strong>${gateControl(s, d, g)}</div>`).join('')}</section>`;
  }).join('');
}
function gateControl(s, d, g) {
      const busy = !!s.gateBusy?.[d.device_id + ':' + g.id] || !!g.pending;
      const ready = s.apiConnected && d.fresh && timestamp(d.valid_until) > Date.now() && g.pwm_ready;
      const attrs = `data-device="${d.device_id}" data-gate="${g.id}"`;
      const modeButton = (value, label) => `<button class="btn btn-small${g.mode === value && ready ? ' btn-teal' : ''}" data-action="gate-mode" ${attrs} data-value="${value}"${!ready || busy || g.mode === value ? ' disabled' : ''}>${label}</button>`;
      const failed = g.last_command && ['failed', 'timed_out', 'cancelled'].includes(g.last_command.status);
      const status = !ready ? 'Chưa có tín hiệu điều khiển' : busy ? 'Đang xử lý…' : g.close_remaining_ms > 0 ? 'Đang chờ tự đóng' : g.target === 'open' ? 'Tín hiệu: mở' : 'Tín hiệu: đóng';
      return `<div class="row gate-mode" aria-label="Chế độ ${g.id === 'entrance' ? 'cổng vào' : 'cổng ra'}">${modeButton('auto', 'Tự động')}${modeButton('manual', 'Điều khiển')}</div><div class="row lot-manual-buttons"><button class="btn btn-small" data-action="gate-target" ${attrs} data-value="open"${!ready || busy || g.mode !== 'manual' ? ' disabled' : ''}>Mở</button><button class="btn btn-small" data-action="gate-target" ${attrs} data-value="closed"${!ready || busy || g.mode !== 'manual' ? ' disabled' : ''}>Đóng</button></div><p class="lot-command-status">${e(status)}</p>${failed ? '<p class="text-danger small">Yêu cầu trước chưa hoàn tất. Kiểm tra kết nối và thử lại.</p>' : ''}`;
}
function overviewView(s) {
  return heading('Bãi đỗ xe', '', refreshButton())
    + `<div data-region="overview-alerts">${overviewAlerts(s)}</div>
    <section class="panel overview-parking"><div class="panel-header"><h2>Sơ đồ bãi xe</h2><a class="btn btn-ghost" href="#/telemetry">Xem lịch sử ${icon('arrow')}</a></div>
    <div data-region="overview-stats">${overviewStats(s)}</div>
    <div data-region="parking">${parking(s)}</div></section>`;
}
export function selected(s) { return s.devices.find(d => String(d.id) === String(s.selectedDeviceId)); }
export function eventTitle(kind) { return ({ initial: 'Ghi nhận đầu tiên', occupied: 'Ô đỗ có vật / xe', available: 'Ô đỗ trở về trống', unknown: 'Không xác định', after_gap: 'Khôi phục dữ liệu' })[kind] || kind; }
export function alertTitle(a) { return ({ parking_full: 'Tất cả ô đỗ đang có xe', device_offline: 'Thiết bị mất kết nối', command_timeout: 'Lệnh quá thời hạn xác nhận' })[a.kind] || a.message; }
export function deviceRows(s) {
  const search = s.deviceSearch.toLowerCase();
  const rows = s.devices.filter(d => (!s.deviceStatus || d.status === s.deviceStatus) && [d.name, d.code, d.location].join(' ').toLowerCase().includes(search));
  return rows.length ? rows.map(d => `<tr><td><a href="#/devices/${d.id}"><strong>${e(d.name)}</strong></a><small>${e(d.code)}</small></td><td>${e(d.location || 'Chưa gán vị trí')}</td><td>${lifecycle(d)}</td><td>${connection(d, s.apiConnected)}</td><td>${e(d.firmware || 'Chưa ghi nhận')}<small>${e(ago(d.last_seen))}</small></td><td><a class="btn btn-small" href="#/devices/${d.id}">Chi tiết ${icon('arrow')}</a></td></tr>`).join('')
    : '<tr><td colspan="6" class="table-empty">Không có thiết bị phù hợp hoặc chưa được cấp quyền.</td></tr>';
}
function devicesView(s) {
  return heading('Quản lý thiết bị', 'Quản lý kết nối, thông tin và vòng đời của các node IoT.', refreshButton() + (s.me.role === 'admin' ? `<button class="btn btn-primary" data-action="create-device">${icon('plus')}Đăng ký thiết bị</button>` : ''))
    + `<section class="panel"><div class="toolbar"><label class="search-field">${icon('search')}<input name="device-search" aria-label="Tìm thiết bị" placeholder="Tìm tên, mã hoặc vị trí…" value="${e(s.deviceSearch)}"></label>
    <label>Trạng thái vòng đời<select name="device-status"><option value="">Tất cả trạng thái</option>${Object.entries(LIFE).map(([v, t]) => `<option value="${v}"${s.deviceStatus === v ? ' selected' : ''}>${t}</option>`).join('')}</select></label><span class="muted small">${s.devices.length} thiết bị trong phạm vi truy cập</span></div>
    <div class="table-wrap"><table><thead><tr><th>THIẾT BỊ</th><th>VỊ TRÍ</th><th>VÒNG ĐỜI</th><th>KẾT NỐI</th><th>FIRMWARE / TÍN HIỆU</th><th></th></tr></thead><tbody data-region="device-rows">${deviceRows(s)}</tbody></table></div></section>
    <p class="scope-note">${icon('shield')} Admin quản lý toàn bộ thiết bị. Operator chỉ thấy thiết bị được cấp quyền; viewer dùng trang tìm chỗ đỗ riêng; trạng thái trực tuyến được theo dõi riêng với vòng đời thiết bị.</p>`;
}
export function detailLive(s) {
  const d = s.devices.find(d => d.id === s.route.deviceId);
  if (!d) return empty('Không tìm thấy thiết bị', 'Thiết bị không tồn tại hoặc bạn không có quyền truy cập.', 'lock');
  const p = s.permissions?.device_id === d.id ? s.permissions : null;
  const steps = ['registered', 'provisioned', 'active', 'maintenance', 'revoked', 'decommissioned'];
  const terminal = d.status === 'decommissioned';
  return `<div class="device-detail-grid"><section class="panel"><div class="panel-header"><div><h2>${e(d.name)}</h2><p>${e(d.code)}</p></div>${connection(d, s.apiConnected)}</div><div class="panel-body">
    <div class="lifecycle">${steps.map((v, i) => (i ? '<span class="lifecycle-arrow">›</span>' : '') + `<span class="lifecycle-step${d.status === v ? ' current' : ''}">${LIFE[v]}</span>`).join('')}</div>
    <dl class="detail-list"><dt>Mã định danh</dt><dd><code>${e(d.code)}</code></dd><dt>Vòng đời</dt><dd>${lifecycle(d)}</dd><dt>Vị trí / khu vực</dt><dd>${e(d.location || 'Chưa gán vị trí')}</dd><dt>Phần cứng</dt><dd>${e(d.hardware || 'Chưa ghi nhận')}</dd><dt>Firmware</dt><dd>${e(d.firmware || 'Chưa ghi nhận')}</dd><dt>Tín hiệu gần nhất</dt><dd>${e(dateTime(d.last_seen))}</dd><dt>Kết nối MQTT</dt><dd>${d.broker_provisioned ? 'Đã cấp thông tin kết nối riêng' : 'Chưa cấp thông tin kết nối'}</dd><dt>Ghi nhận lỗi / bảo trì</dt><dd>${e(d.fault || 'Chưa ghi nhận lỗi')}</dd></dl>
    ${s.me.role === 'admin' ? `<div class="detail-actions"><button class="btn btn-small" data-action="edit-metadata" data-id="${d.id}">Sửa thông tin</button>${d.status === 'registered' ? `<button class="btn btn-small btn-teal" data-action="provision" data-id="${d.id}">${icon('key')}Cấp kết nối MQTT</button>` : ''}
    ${!terminal && TRANSITIONS[d.status]?.length ? `<button class="btn btn-small" data-action="lifecycle" data-id="${d.id}">Đổi trạng thái</button>` : ''}
    ${d.broker_provisioned && !terminal ? `<button class="btn btn-small" data-action="rotate" data-id="${d.id}">Đổi mật khẩu MQTT</button>` : ''}</div>` : ''}</div></section>
    <div class="stack"><section class="panel"><div class="panel-header"><h2>Cấu hình & quyền truy cập</h2>${icon('shield')}</div><div class="panel-body"><dl class="detail-list"><dt>Chu kỳ đã ghi nhận</dt><dd>${number(s.config?.report_interval_ms ?? d.report_interval_ms)} ms</dd><dt>Ngưỡng offline thực tế</dt><dd>${number(d.effective_offline_timeout_s)} giây</dd><dt>Quyền xem</dt><dd>${badge('Được phép', 'green')}</dd><dt>Quyền ping</dt><dd>${p ? badge(p.can_control ? 'Được phép' : 'Không được cấp', p.can_control ? 'green' : 'neutral') : 'Đang tải…'}</dd><dt>Quyền cấu hình</dt><dd>${p ? badge(p.can_configure ? 'Được phép' : 'Không được cấp', p.can_configure ? 'green' : 'neutral') : 'Đang tải…'}</dd></dl>
    <div class="detail-actions"><button class="btn btn-small" data-action="go-history" data-id="${d.id}">${icon('chart')}Dữ liệu</button><button class="btn btn-small" data-action="go-commands" data-id="${d.id}">${icon('command')}Lệnh & cấu hình</button></div></div></section>
    ${s.me.role === 'admin' ? `<section class="panel"><div class="panel-header"><h2>Phân công thiết bị</h2>${icon('users')}</div><div class="panel-body"><p class="muted small">Gán thiết bị cho người dùng và ô đỗ trong mô hình P1/P2.</p><div class="detail-actions"><button class="btn btn-small" data-action="grants" data-id="${d.id}">Quản lý quyền</button><button class="btn btn-small" data-action="assign-slot" data-id="${d.id}">Gán ô P1/P2</button></div></div></section>` : ''}</div></div>`;
}
function detailView(s) {
  const d = s.devices.find(d => d.id === s.route.deviceId);
  return heading(d?.name || 'Chi tiết thiết bị', 'Theo dõi vòng đời và thao tác theo quyền được cấp.', '<a class="btn" href="#/devices">← Danh sách thiết bị</a>' + refreshButton())
    + `<div data-region="device-detail">${detailLive(s)}</div>`;
}

export function historyContent(s) {
  if (s.historyLoading) return loading();
  if (!selected(s)) return empty('Chưa có thiết bị để tra cứu', 'Chỉ dữ liệu thuộc thiết bị được cấp quyền mới xuất hiện.', 'lock');
  if (s.historyTab === 'events') {
    return `<div class="table-wrap"><table><thead><tr><th>THỜI GIAN (UTC+7)</th><th>Ô ĐỖ</th><th>SỰ KIỆN</th><th>TRẠNG THÁI GHI NHẬN</th></tr></thead><tbody>${s.historyEvents.length
      ? s.historyEvents.map(ev => `<tr><td class="mono">${e(dateTime(ev.occurred_at))}</td><td><strong>${e(ev.slot)}</strong></td><td>${e(eventTitle(ev.kind))}</td><td>${occupancy(ev.occupied)}</td></tr>`).join('')
      : '<tr><td colspan="4" class="table-empty">Không có sự kiện trong khoảng thời gian đã chọn.</td></tr>'}</tbody></table></div>
      <div class="panel-footer">${icon('info')}Sự kiện phản ánh thay đổi trạng thái ô; không phải nhận diện xe hoặc đếm lượt ra vào.</div>${s.eventsHasMore ? '<div class="load-more"><button class="btn" data-action="load-events">Xem sự kiện cũ hơn</button></div>' : ''}`;
  }
  return `<div class="table-wrap"><table><thead><tr><th>THỜI GIAN NHẬN (UTC+7)</th><th>MẪU</th><th>P1 · GPIO27</th><th>P2 · GPIO26</th><th>UPTIME</th></tr></thead><tbody>${s.history.length
    ? s.history.map(item => {
      const slot = name => { const row = item.slots.find(s => s.name === name); return row ? `${occupancy(row.occupied)}<small>DO = ${e(row.do)}</small>` : '<span class="muted">Không có mẫu</span>'; };
      return `<tr><td class="mono">${e(dateTime(item.received_at))}</td><td><strong>#${item.id}</strong><small>${item.simulated ? 'Dữ liệu mô phỏng' : e(item.device_id)}</small></td><td>${slot('P1')}</td><td>${slot('P2')}</td><td>${number(item.uptime_s)} giây</td></tr>`;
    }).join('') : '<tr><td colspan="5" class="table-empty">Không có mẫu dữ liệu trong khoảng thời gian đã chọn.</td></tr>'}</tbody></table></div>
    <div class="panel-footer">${icon('clock')}Bảng lịch sử giữ giá trị tại thời điểm nhận. Uptime là thời gian từ khi thiết bị khởi động.</div>${s.historyHasMore ? '<div class="load-more"><button class="btn" data-action="load-history">Xem mẫu cũ hơn</button></div>' : ''}`;
}
export function statsBreakdown(s) {
  const rows = durationSummary(s.stats);
  return rows.length ? `<div class="stat-breakdown">${rows.map(r => `<div><strong>${r.percent === null ? '—' : number(Math.round(r.percent * 10) / 10) + '%'}</strong><small>${e(r.slot)} · ${number(Math.round(r.occupied / 60 * 10) / 10)} phút có xe · ${number(Math.round(r.unknown / 60 * 10) / 10)} phút chưa xác định</small></div>`).join('')}</div><p class="plot-caption">Tỷ lệ thời gian có xe trong khoảng đã quan sát được; loại trừ thời gian chưa xác định. Biểu đồ tổng hợp theo toàn bộ giờ giao với bộ lọc; lịch sử bên dưới vẫn lọc đúng thời điểm.</p>` : '';
}

function telemetryView(s) {
  return heading('Dữ liệu & lịch sử', 'Tra cứu mẫu cảm biến, sự kiện và thống kê theo thiết bị.', refreshButton()
    + `<button class="btn btn-primary" data-action="export-csv"${!selected(s) ? ' disabled' : ''}>${icon('download')}Xuất CSV</button>`)
    + `<section class="panel"><form class="toolbar" data-form="history-filter"><label>Thiết bị<select data-action="select-device" aria-label="Chọn thiết bị">${deviceOptions(s)}</select></label>
    <label>Từ thời điểm (UTC+7)<input type="datetime-local" name="from" value="${e(s.historyInputs.from)}"></label>
    <label>Đến thời điểm (UTC+7)<input type="datetime-local" name="to" value="${e(s.historyInputs.to)}"></label>
    <button class="btn btn-teal" type="submit">${icon('search')}Áp dụng</button><button class="btn" type="button" data-action="reset-history">24 giờ gần nhất</button></form>
    <div class="panel-header"><div><h2>Thời gian có xe theo giờ</h2><p>${e(selected(s)?.name || 'Chưa chọn thiết bị')}</p></div><span class="badge badge-blue">THỐNG KÊ THỜI GIAN</span></div>
    <div class="panel-body"><div data-region="chart">${chart(s)}</div><div data-region="stats-breakdown">${statsBreakdown(s)}</div></div></section>
    <section class="panel history-panel"><div class="tabs"><button class="tab${s.historyTab === 'samples' ? ' active' : ''}" data-action="history-tab" data-tab="samples">Mẫu cảm biến</button><button class="tab${s.historyTab === 'events' ? ' active' : ''}" data-action="history-tab" data-tab="events">Sự kiện ô đỗ</button></div>
    <div data-region="history-content">${historyContent(s)}</div></section>
    <p class="scope-note">Lịch sử/CSV lưu khi trạng thái đổi hoặc mỗi 60 giây; giữ 3 ngày. Sự kiện giữ 90 ngày, tổng hợp thời gian giữ 365 ngày. CSV tối đa 10.000 dòng/lần.</p>`;
}
function filteredAlerts(s) {
  return s.alerts.filter(a => ['parking_full', 'device_offline'].includes(a.kind) && (s.alertFilter === 'active' ? a.active : s.alertFilter === 'resolved' ? !a.active : true));
}
function alertReview(a, s) {
  if (a.acknowledged) {
    const actor = s.users?.find(u => u.id === a.acknowledged_by)?.username || '#' + a.acknowledged_by;
    return `<span>Đã xem · ${e(actor)}</span><small>${e(dateTime(a.acknowledged_at))}</small>`;
  }
  if (!['admin', 'operator'].includes(s.me.role)) return 'Chưa xem';
  const busy = s.alertBusy?.[a.id];
  return `<button class="btn btn-small" data-action="ack-alert" data-id="${e(a.id)}"${!s.apiConnected || busy ? ' disabled' : ''}>${busy ? 'Đang lưu…' : 'Đánh dấu đã xem'}</button>`;
}
export function alertRows(s) {
  const rows = filteredAlerts(s);
  return rows.length ? rows.map(a => `<tr><td><strong>${e(alertTitle(a))}</strong></td><td>${e(s.devices.find(d => d.id === a.device_id)?.name || 'Khu vực đỗ xe')}</td><td>${badge(a.active ? 'Đang diễn ra' : 'Đã kết thúc', a.active ? 'amber' : 'neutral')}</td><td class="mono">${e(dateTime(a.created_at))}</td><td class="mono">${a.resolved_at ? e(dateTime(a.resolved_at)) : '—'}</td><td>${alertReview(a, s)}</td></tr>`).join('')
    : '<tr><td colspan="6" class="table-empty">Không có cảnh báo trong bộ lọc này.</td></tr>';
}
function alertsView(s) {
  return heading('Cảnh báo hệ thống', 'Theo dõi bãi đầy và thiết bị mất kết nối. Đánh dấu đã xem không kết thúc cảnh báo; hệ thống tự kết thúc khi sự cố hết.', refreshButton())
    + `<section class="panel"><div class="toolbar"><label>Trạng thái<select name="alert-filter"><option value="active"${s.alertFilter === 'active' ? ' selected' : ''}>Đang diễn ra</option><option value="all"${s.alertFilter === 'all' ? ' selected' : ''}>Tất cả</option><option value="resolved"${s.alertFilter === 'resolved' ? ' selected' : ''}>Đã kết thúc</option></select></label></div>
    <div class="table-wrap"><table><thead><tr><th>CẢNH BÁO</th><th>KHU VỰC</th><th>TRẠNG THÁI</th><th>BẮT ĐẦU</th><th>KẾT THÚC</th><th>NGƯỜI ĐÃ XEM</th></tr></thead><tbody data-region="alert-rows">${alertRows(s)}</tbody></table></div></section>`;
}
export function commandRows(s) {
  return s.commands.length ? s.commands.map(c => `<tr><td><strong>${c.action === 'configure' ? 'Đổi chu kỳ gửi' : 'Kiểm tra phản hồi (ping)'}</strong><small><code>${e(c.id.slice(0, 12))}…</code></small></td><td>${commandBadge(c.status)}</td><td>${number(c.attempts)}</td><td class="mono">${e(dateTime(c.created_at))}</td><td>${c.error ? `<span class="text-danger">${e(commandError(c.error))}</span>` : c.result?.report_interval_ms ? number(c.result.report_interval_ms) + ' ms' : c.status === 'acknowledged' ? 'Thiết bị đã phản hồi' : 'Chưa có kết quả'}</td><td><button class="btn btn-small" data-action="command-detail" data-id="${e(c.id)}">Chi tiết</button></td></tr>`).join('')
    : '<tr><td colspan="6" class="table-empty">Chưa có lệnh cho thiết bị này.</td></tr>';
}
export function commandError(value) {
  return ({
    'Device lifecycle changed': 'Vòng đời thiết bị đã thay đổi',
    'Command expired': 'Lệnh đã hết thời hạn',
    'Command timed out': 'Thiết bị chưa xác nhận trong thời hạn',
    'No device acknowledgement before deadline': 'Thiết bị chưa xác nhận trong thời hạn',
    'Device did not confirm the requested configuration': 'Thiết bị chưa xác nhận cấu hình đã yêu cầu',
    'Device is not enabled': 'Thiết bị chưa được kích hoạt',
  })[value] || value;
}
export function commandLive(s) {
  const d = selected(s), p = s.permissions;
  if (!d) return empty('Chưa chọn thiết bị', 'Chọn một thiết bị được cấp quyền để xem cấu hình và lịch sử lệnh.', 'device');
  return `<div class="command-status"><div class="row between"><strong class="small">${e(d.name)}</strong>${connection(d, s.apiConnected)}</div><p>Chu kỳ đã ghi nhận: <strong>${number(s.config?.report_interval_ms ?? d.report_interval_ms)} ms</strong></p>
    ${s.config?.pending ? `<p>Yêu cầu thay đổi: ${commandBadge(s.config.pending.status)} · ${number(s.config.pending.arguments?.report_interval_ms)} ms</p>` : '<p>Không có yêu cầu cấu hình đang chờ.</p>'}</div>
    ${p && !p.can_control && !p.can_configure ? `<div class="banner info">${icon('lock')}Bạn có quyền xem lịch sử; chưa được cấp quyền gửi lệnh hoặc cấu hình thiết bị này.</div>` : ''}`;
}
function commandsView(s) {
  const d = selected(s), p = s.permissions;
  const enabled = s.apiConnected && d?.connectivity === 'online' && ['active', 'provisioned'].includes(d?.status);
  return heading(s.me.role === 'viewer' ? 'Lịch sử lệnh' : 'Lệnh & cấu hình', 'Theo dõi kết quả xác nhận từ thiết bị, không chỉ trạng thái gửi yêu cầu.', selectDevice(s) + refreshButton())
    + (!d ? `<section class="panel">${empty('Chưa có thiết bị', 'Chỉ thiết bị được cấp quyền mới xuất hiện tại đây.', 'device')}</section>`
      : `<div class="two-columns"><section class="panel"><div class="panel-header"><h2>Điều khiển & cấu hình từ xa</h2>${icon('command')}</div><div class="panel-body"><div data-region="command-live">${commandLive(s)}</div>
    <form data-form="command"><div class="form-grid"><label class="field">Chu kỳ gửi (ms)<input name="report_interval_ms" type="number" min="500" max="10000" step="1" value="${s.config?.report_interval_ms ?? d.report_interval_ms ?? 1000}" required><small>Từ 500 đến 10.000 ms, lưu trên ESP32 sau khi áp dụng.</small></label>
    <label class="field">Thời hạn xác nhận (giây)<input name="timeout_s" type="number" min="5" max="60" step="1" value="15" required><small>Quá thời hạn, backend ghi nhận lệnh timeout.</small></label></div>
    <p class="form-error" role="alert"></p><div class="row"><button class="btn btn-teal" type="submit" name="action" value="configure" data-command="configure"${enabled && p?.can_configure ? '' : ' disabled'}>Gửi cấu hình</button>
    <button class="btn" type="submit" name="action" value="ping" data-command="ping"${enabled && p?.can_control ? '' : ' disabled'}>${icon('wifi')}Ping thiết bị</button></div></form>
    <p class="form-hint command-hint">Yêu cầu chỉ hoàn tất khi nhận ACK hợp lệ. Thiết bị cần trực tuyến và tài khoản có quyền tương ứng.</p></div></section>
    <section class="panel"><div class="panel-header"><h2>Giám sát bãi đỗ</h2>${icon('settings')}</div><div class="panel-body"><form data-form="rules">
    <label class="checkbox"><input name="full_enabled" type="checkbox"${s.rules?.full_enabled !== false ? ' checked' : ''}${p?.can_configure ? '' : ' disabled'}><span>Cảnh báo bãi đầy<small>Khi tất cả ô được giám sát đều có xe.</small></span></label>
    <label class="checkbox"><input name="offline_enabled" type="checkbox"${s.rules?.offline_enabled ? ' checked' : ''}${p?.can_configure ? '' : ' disabled'}><span>Cảnh báo thiết bị mất kết nối<small>Khi thiết bị đã từng gửi dữ liệu nhưng im lặng quá thời gian chờ. Mặc định tắt.</small></span></label>
    <label class="field">Thời gian chờ dữ liệu (giây)<input name="offline_timeout_s" type="number" min="5" max="120" step="1" value="${s.rules?.offline_timeout_s ?? 10}" required${p?.can_configure ? '' : ' disabled'}><small data-region="rule-effective">Ngưỡng thực tế: ${number(s.rules?.effective_offline_timeout_s ?? d.effective_offline_timeout_s)} giây, tối thiểu bằng 3 chu kỳ gửi.</small></label>
    <p class="form-error" role="alert"></p><button class="btn" type="submit" data-rule-submit${s.apiConnected && p?.can_configure ? '' : ' disabled'}>Lưu cài đặt</button></form></div></section></div>
    <section class="panel history-panel"><div class="panel-header"><div><h2>Lịch sử lệnh</h2><p>50 yêu cầu gần nhất của thiết bị đang chọn</p></div><span class="badge badge-blue">CÓ XÁC NHẬN ACK</span></div>
    <div class="table-wrap"><table><thead><tr><th>LỆNH</th><th>TRẠNG THÁI</th><th>LẦN GỬI</th><th>THỜI ĐIỂM TẠO</th><th>KẾT QUẢ</th><th></th></tr></thead><tbody data-region="command-rows">${commandRows(s)}</tbody></table></div></section>`)
    + '<p class="scope-note">Điều khiển cổng vào/ra ở trang Tổng quan; chỉ admin được thao tác.</p>';
}
export function userRows(s) {
  const rows = s.users.filter(u => [u.username, ROLE[u.role]].join(' ').toLowerCase().includes(s.userSearch.toLowerCase()));
  return rows.length ? rows.map(u => `<tr><td><div class="row"><span class="avatar">${e(u.username.slice(0, 2).toUpperCase())}</span><div><strong>${e(u.username)} ${u.id === s.me.id ? '<span class="muted tiny">(Bạn)</span>' : ''}</strong><small>ID #${u.id}</small></div></div></td><td>${badge(ROLE[u.role], u.role === 'admin' ? 'blue' : 'neutral')}</td><td>${badge(u.active ? 'Đang hoạt động' : 'Đã khóa', u.active ? 'green' : 'red')}</td><td><button class="btn btn-small" data-action="edit-user" data-id="${u.id}">Quản lý</button></td></tr>`).join('')
    : '<tr><td colspan="4" class="table-empty">Không tìm thấy tài khoản phù hợp.</td></tr>';
}
function usersView(s) {
  return heading('Quản lý người dùng', 'Tạo tài khoản, phân vai trò và kiểm soát trạng thái truy cập.', refreshButton() + `<button class="btn btn-primary" data-action="create-user">${icon('plus')}Tạo tài khoản</button>`)
    + `<section class="panel"><div class="toolbar"><label class="search-field">${icon('search')}<input name="user-search" aria-label="Tìm người dùng" value="${e(s.userSearch)}" placeholder="Tìm tên hoặc vai trò…"></label><span class="muted small">${s.users.length} tài khoản</span></div><div class="table-wrap"><table><thead><tr><th>TÀI KHOẢN</th><th>VAI TRÒ</th><th>TRẠNG THÁI</th><th></th></tr></thead><tbody data-region="user-rows">${userRows(s)}</tbody></table></div></section>
    <p class="scope-note">Quyền theo thiết bị được cấp trong trang chi tiết thiết bị. Thay đổi vai trò hoặc khóa tài khoản sẽ thu hồi các phiên đăng nhập đang có.</p>`;
}
export function auditRows(s) {
  const labels = { 'auth.login': 'Đăng nhập', 'auth.login_failed': 'Đăng nhập thất bại', 'auth.logout': 'Đăng xuất', 'auth.password_changed': 'Đổi mật khẩu', 'auth.password_change_failed': 'Đổi mật khẩu thất bại', 'users.create': 'Tạo tài khoản', 'users.update': 'Cập nhật tài khoản', 'devices.create': 'Đăng ký thiết bị', 'devices.provision': 'Cấp kết nối MQTT', 'devices.status': 'Chuyển vòng đời thiết bị', 'devices.metadata': 'Cập nhật thông tin thiết bị', 'devices.grant': 'Cấp quyền thiết bị', 'devices.ungrant': 'Thu hồi quyền thiết bị', 'devices.assign_slot': 'Gán ô đỗ', 'devices.rotate_credentials': 'Đổi mật khẩu MQTT', 'devices.rules': 'Cập nhật quy tắc', 'commands.create': 'Tạo lệnh thiết bị', 'alerts.acknowledge': 'Đánh dấu cảnh báo đã xem', 'telemetry.export_csv': 'Xuất dữ liệu CSV' };
  return s.audit.length ? s.audit.map(a => `<tr><td class="mono">${e(dateTime(a.created_at))}</td><td><strong>${e(s.users.find(u => u.id === a.actor_id)?.username || '#' + a.actor_id)}</strong></td><td><strong>${e(labels[a.action.split(':')[0]] || 'Thao tác hệ thống')}</strong><small><code>${e(a.action)}</code></small></td><td class="mono">#${a.id}</td></tr>`).join('')
    : '<tr><td colspan="4" class="table-empty">Chưa có thao tác được ghi nhận.</td></tr>';
}
function auditView(s) {
  return heading('Nhật ký hệ thống', 'Tra cứu 200 thao tác quan trọng gần nhất. Chỉ quản trị viên được truy cập.', refreshButton())
    + `<section class="panel"><div class="table-wrap"><table><thead><tr><th>THỜI ĐIỂM (UTC+7)</th><th>NGƯỜI THỰC HIỆN</th><th>THAO TÁC</th><th>MÃ BẢN GHI</th></tr></thead><tbody data-region="audit-rows">${auditRows(s)}</tbody></table></div></section>`;
}
function accountView(s) {
  return heading('Tài khoản của bạn', 'Thông tin truy cập và bảo vệ tài khoản.')
    + `<section class="panel account-card"><div class="panel-header"><h2>Hồ sơ truy cập</h2>${icon('shield')}</div><div class="panel-body"><div class="account-profile"><span class="avatar">${e(s.me.username.slice(0, 2).toUpperCase())}</span><div><h2>${e(s.me.username)}</h2><p class="muted small">${e(ROLE[s.me.role])} · ${s.me.active ? 'Đang hoạt động' : 'Đã khóa'}</p></div></div>
    <div class="banner info">${icon('lock')}${s.me.role === 'admin' ? 'Bạn có quyền quản trị người dùng và toàn bộ thiết bị trong hệ thống.' : (s.me.role === 'viewer' ? 'Bạn có thể xem tình trạng và vị trí chỗ đỗ trong nhà xe được cấp quyền.' : 'Bạn chỉ truy cập thiết bị và dữ liệu trong phạm vi được cấp quyền.')}</div>
    <form data-form="password"><div class="form-grid"><label class="field full">Mật khẩu hiện tại<input type="password" name="old_password" autocomplete="current-password" required maxlength="128"></label><label class="field">Mật khẩu mới<input type="password" name="new_password" autocomplete="new-password" minlength="10" maxlength="128" required><small>Từ 10 đến 128 ký tự.</small></label><label class="field">Nhập lại mật khẩu mới<input type="password" name="confirm_password" autocomplete="new-password" minlength="10" maxlength="128" required></label></div>
    <p class="form-error" role="alert"></p><button class="btn btn-primary" type="submit">${icon('key')}Đổi mật khẩu</button><p class="form-hint command-hint">Đổi mật khẩu sẽ kết thúc các phiên đăng nhập hiện tại. Bạn cần đăng nhập lại.</p></form></div></section>`;
}
export function renderPage(s) {
  if (s.me.role === 'viewer') {
    if (s.route.page === 'account') return accountView(s);
    return viewerPage(s);
  }
  if (['users', 'audit'].includes(s.route.page) && s.me.role !== 'admin') return empty('Không có quyền truy cập', 'Trang này chỉ dành cho quản trị viên.', 'lock');
  const renderers = { overview: overviewView, devices: s.route.deviceId ? detailView : devicesView, telemetry: telemetryView, alerts: alertsView, commands: commandsView, users: usersView, audit: auditView, account: accountView };
  return (renderers[s.route.page] || overviewView)(s);
}
