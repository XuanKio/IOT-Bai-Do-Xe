export const ROLE = { admin: 'Quản trị viên', operator: 'Người vận hành', viewer: 'Người xem' };
export const LIFE = { registered: 'Đã đăng ký', provisioned: 'Đã cấp kết nối', active: 'Đang hoạt động', maintenance: 'Bảo trì', revoked: 'Đã thu hồi', decommissioned: 'Ngừng sử dụng' };
export const COMMAND = { queued: 'Đang chờ gửi', sent: 'Đã gửi, chờ ACK', acknowledged: 'Đã xác nhận', failed: 'Thất bại', timed_out: 'Quá thời hạn', cancelled: 'Đã hủy' };
export const TRANSITIONS = {
  registered: ['provisioned', 'revoked', 'decommissioned'], provisioned: ['active', 'revoked', 'decommissioned'],
  active: ['maintenance', 'revoked', 'decommissioned'], maintenance: ['active', 'revoked', 'decommissioned'],
  revoked: ['provisioned', 'decommissioned'], decommissioned: [],
};
export const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const number = value => new Intl.NumberFormat('vi-VN').format(Number(value) || 0);
export function timestamp(value) {
  if (!value) return NaN;
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : value + 'Z';
  return Date.parse(normalized);
}
export function dateTime(value, short = false) {
  const time = timestamp(value);
  if (!Number.isFinite(time)) return 'Chưa có dữ liệu';
  return new Intl.DateTimeFormat('vi-VN', { timeZone: 'Asia/Bangkok', ...(short
    ? { hour: '2-digit', minute: '2-digit', second: '2-digit' }
    : { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }) }).format(time);
}
export function ago(value, at = Date.now()) {
  const seconds = Math.max(0, Math.floor((at - timestamp(value)) / 1000));
  if (!Number.isFinite(seconds)) return 'Chưa nhận dữ liệu';
  if (seconds < 60) return seconds + ' giây trước';
  if (seconds < 3600) return Math.floor(seconds / 60) + ' phút trước';
  if (seconds < 86400) return Math.floor(seconds / 3600) + ' giờ trước';
  return Math.floor(seconds / 86400) + ' ngày trước';
}
export function localInput(at = Date.now()) {
  return new Date(at + 7 * 3600000).toISOString().slice(0, 16);
}
export function timeRange(from, to) {
  const parse = value => value ? new Date(value + ':00+07:00').toISOString() : undefined;
  const range = { from_at: parse(from), to_at: parse(to) };
  if (range.from_at && range.to_at && range.from_at > range.to_at) throw new Error('Thời điểm bắt đầu phải trước thời điểm kết thúc.');
  return range;
}
export function query(values) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  return params.size ? '?' + params.toString() : '';
}
export function slotState(slot, devices, connected, at = Date.now()) {
  const device = devices.find(d => d.id === slot.device_id);
  const age = (at - timestamp(slot.updated_at)) / 1000;
  const fresh = connected && slot.fresh && device?.status === 'active' && device?.connectivity === 'online'
    && Number.isFinite(age) && age >= 0 && age < device.effective_offline_timeout_s;
  return fresh && typeof slot.occupied === 'boolean' ? (slot.occupied ? 'occupied' : 'free') : 'unknown';
}
export function countSlots(slots, devices, connected, at = Date.now()) {
  return slots.reduce((total, slot) => { total[slotState(slot, devices, connected, at)]++; return total; },
    { capacity: slots.length, free: 0, occupied: 0, unknown: 0 });
}
export function sampleSummary(stats) {
  const totals = {};
  for (const b of stats?.buckets ?? []) {
    const row = totals[b.slot] ??= { samples: 0, occupied: 0 };
    row.samples += b.samples; row.occupied += b.occupied_samples;
  }
  return Object.entries(totals).map(([slot, row]) => ({ slot, ...row, percent: row.samples ? 100 * row.occupied / row.samples : null }));
}

export function durationSummary(stats) {
  const totals = {};
  for (const b of stats?.buckets || []) {
    const row = totals[b.slot] ??= { occupied: 0, available: 0, unknown: 0 };
    row.occupied += b.occupied_seconds || 0; row.available += b.available_seconds || 0; row.unknown += b.unknown_seconds || 0;
  }
  return Object.entries(totals).map(([slot, r]) => ({ slot, ...r,
    observed: r.occupied + r.available, percent: r.occupied + r.available ? r.occupied / (r.occupied + r.available) * 100 : null }));
}
export function commandKey() {
  return 'web-' + Array.from(crypto.getRandomValues(new Uint8Array(16)), v => v.toString(16).padStart(2, '0')).join('');
}
const errors = {
  'Invalid credentials': 'Tên đăng nhập hoặc mật khẩu không đúng, hoặc tài khoản đã bị khóa.',
  'Invalid or expired token': 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.',
  'Incorrect current password': 'Mật khẩu hiện tại không đúng.',
  'Username already exists': 'Tên đăng nhập này đã được sử dụng.',
  'Device code already exists': 'Mã thiết bị đã tồn tại.',
  'Reserved device code': 'Mã thiết bị này được hệ thống dành riêng.',
  'Device not found': 'Thiết bị không tồn tại hoặc bạn không còn quyền truy cập.',
  'Insufficient permissions': 'Bạn không có quyền thực hiện thao tác này.',
  'Insufficient device permission': 'Bạn chưa được cấp quyền thực hiện thao tác này trên thiết bị.',
  'Device is not online and enabled': 'Thiết bị cần trực tuyến và ở trạng thái được phép nhận lệnh.',
  'MQTT receiver is not ready': 'Kết nối MQTT chưa sẵn sàng. Vui lòng kiểm tra broker.',
  'Broker administration is not configured': 'Dịch vụ quản trị broker chưa được cấu hình.',
  'Broker did not confirm the change; retry after checking MQTT': 'Broker chưa xác nhận thay đổi. Trạng thái chưa được cập nhật; hãy kiểm tra MQTT và thử lại.',
  'Invalid lifecycle transition': 'Không thể chuyển sang trạng thái này từ trạng thái hiện tại.',
  'Provision device credentials first': 'Hãy cấp thông tin kết nối MQTT cho thiết bị trước.',
  'Device already provisioned or not in registered state': 'Thiết bị đã được cấp kết nối hoặc không còn ở trạng thái mới đăng ký.',
  'Device is not provisioned': 'Thiết bị chưa được cấp kết nối hoặc đã ngừng sử dụng.',
  'Cannot disable or demote yourself': 'Bạn không thể tự khóa hoặc hạ quyền tài khoản đang đăng nhập.',
  'User not found': 'Tài khoản không tồn tại.',
  'Grant not found': 'Quyền truy cập này không còn tồn tại.',
  'Alert not found': 'Cảnh báo không tồn tại hoặc không thuộc phạm vi được cấp quyền.',
  'Command not found': 'Không tìm thấy lệnh trong phạm vi được cấp quyền.',
};
export class ApiError extends Error {
  constructor(status, detail) {
    const message = Array.isArray(detail) ? 'Dữ liệu chưa hợp lệ. Kiểm tra các trường và giới hạn giá trị.'
      : errors[detail] || (status === 0 ? 'Không kết nối được máy chủ. Kiểm tra kết nối và thử lại.' : 'Không thực hiện được thao tác. Mã phản hồi: ' + status + '.');
    super(message); this.status = status; this.detail = detail;
  }
}
export function createApi(getToken, onUnauthorized) {
  return async function api(path, { method = 'GET', body, raw = false, signal } = {}) {
    const token = getToken();
    const abort = new AbortController();
    const cancel = () => abort.abort();
    signal?.addEventListener('abort', cancel, { once: true });
    if (signal?.aborted) abort.abort();
    const timer = setTimeout(cancel, 12000);
    try {
      const response = await fetch(path, {
        method, cache: 'no-store', credentials: 'same-origin', signal: abort.signal,
        headers: { ...(token ? { Authorization: 'Bearer ' + token } : {}), ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      });
      if (!response.ok) {
        let detail; try { detail = (await response.json()).detail; } catch { detail = ''; }
        if (response.status === 401 && token && token === getToken()) onUnauthorized();
        throw new ApiError(response.status, detail);
      }
      if (raw) return response;
      return response.status === 204 ? null : response.json();
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (signal?.aborted) throw error;
      throw new ApiError(0, '');
    } finally {
      clearTimeout(timer); signal?.removeEventListener('abort', cancel);
    }
  };
}
const paths = {
  dashboard: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  device: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 1v5m6-5v5M9 18v5m6-5v5M1 9h5m-5 6h5m12-6h5m-5 6h5"/><path d="M10 10h4v4h-4z"/>',
  chart: '<path d="M3 3v18h18M7 16l5-6 4 3 5-7"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
  command: '<path d="m5 5 7 7-7 7m9 0h6"/>',
  users: '<circle cx="9" cy="7" r="4"/><path d="M2 21v-3a7 7 0 0 1 14 0v3M17 4a4 4 0 0 1 0 7m2 4a6 6 0 0 1 3 5"/>',
  shield: '<path d="m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6z"/><path d="m8 12 3 3 5-6"/>',
  settings: '<path d="m9 3 1-2h4l1 2 3 2 2 1 2 3-1 3v3l-2 3-3 1-2 3h-4l-2-3-3-1-2-3v-3L2 9l2-3 3-1z"/><circle cx="12" cy="12" r="3"/>',
  logout: '<path d="M9 3H4v18h5m6-14 5 5-5 5m-7-5h12"/>',
  refresh: '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 6a8 8 0 0 1 13 3M5 15a8 8 0 0 0 13 3"/>',
  arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  plus: '<path d="M12 4v16M4 12h16"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  menu: '<path d="M3 6h18M3 12h18M3 18h18"/>',
  pin: '<path d="M19 10c0 5-7 12-7 12S5 15 5 10a7 7 0 1 1 14 0z"/><circle cx="12" cy="10" r="2"/>',
  link: '<path d="m9 15 6-6M8 17l-2 2a4 4 0 0 1-6-6l6-6a4 4 0 0 1 6 0m0 10a4 4 0 0 0 6 0l6-6a4 4 0 0 0-6-6l-2 2"/>',
  wifi: '<path d="M2 8a16 16 0 0 1 20 0M5 12a11 11 0 0 1 14 0m-10 4a5 5 0 0 1 6 0"/><circle cx="12" cy="20" r="1"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
  lock: '<rect x="4" y="10" width="16" height="12" rx="2"/><path d="M7 10V6a5 5 0 0 1 10 0v4m-5 5v3"/>',
  key: '<circle cx="8" cy="8" r="5"/><path d="m12 12 10 10m-6-6 3-3m0 6 3-3"/>',
  file: '<path d="M5 2h9l5 5v15H5zM14 2v6h5M8 12h8m-8 4h8"/>',
};
export function icon(name, cls = '') {
  return `<svg class="icon ${esc(cls)}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.info}</svg>`;
}
export function car() {
  return '<svg class="parking-car" viewBox="0 0 180 320" aria-hidden="true"><rect class="car-tire" x="29" y="67" width="14" height="48" rx="5"/><rect class="car-tire" x="137" y="67" width="14" height="48" rx="5"/><rect class="car-tire" x="29" y="218" width="14" height="48" rx="5"/><rect class="car-tire" x="137" y="218" width="14" height="48" rx="5"/><path class="car-body" d="M42 61Q44 28 90 28t48 33l5 60v121q0 45-53 45t-53-45V121z"/><path class="car-glass" d="m51 100 10-31q29-12 58 0l10 31-7 20H58zm7 117h64l5 28q-37 16-74 0z"/><path class="car-detail" d="M52 125v81m76-81v81M54 48h20m32 0h20M58 268h64"/><path class="car-lights" d="M49 62h15m52 0h15M49 252h12m58 0h12"/></svg>';
}
