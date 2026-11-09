import test from 'node:test';
import assert from 'node:assert/strict';
import { slotState, countSlots, sampleSummary, durationSummary, timestamp, dateTime, timeRange, query, esc } from '../assets/core.js';
import { renderPage, parking, activeParkingAlerts, activeAlerts, overviewAlerts, alertRows, gateControls, auditRows } from '../assets/views.js';
import { driverSummary, viewerShell, viewerContent } from '../assets/viewer.js';

const at = Date.parse('2026-10-26T08:00:00Z');
const device = { id: 1, status: 'active', connectivity: 'online', effective_offline_timeout_s: 30 };
const slot = { device_id: 1, updated_at: '2026-10-26T07:59:40Z', fresh: true, occupied: false };

test('an old free sample is never shown as a currently available space', () => {
  assert.equal(slotState(slot, [device], true, at), 'free');
  assert.equal(slotState(slot, [device], true, at + 10000), 'unknown');
  assert.equal(slotState(slot, [device], false, at), 'unknown');
  assert.equal(slotState({ ...slot, fresh: false }, [device], true, at), 'unknown');
  assert.equal(slotState(slot, [{ ...device, status: 'maintenance' }], true, at), 'unknown');
  assert.equal(slotState(slot, [{ ...device, connectivity: 'offline' }], true, at), 'unknown');
});

test('a lost API connection changes both visible spaces to unknown', () => {
  const result = countSlots([slot, { ...slot, occupied: true }], [device], false, at);
  assert.deepEqual(result, { capacity: 2, free: 0, occupied: 0, unknown: 2 });
});

test('percentages are weighted by samples rather than averaging hourly percentages', () => {
  assert.deepEqual(sampleSummary({ buckets: [
    { slot: 'P1', samples: 1, occupied_samples: 1 }, { slot: 'P1', samples: 9, occupied_samples: 1 },
  ] }), [{ slot: 'P1', samples: 10, occupied: 2, percent: 20 }]);
});

test('filters convert the displayed UTC+7 time correctly and reject inverted ranges', () => {
  assert.deepEqual(timeRange('2026-10-26T00:00', '2026-10-26T07:00'), {
    from_at: '2026-10-25T17:00:00.000Z', to_at: '2026-10-26T00:00:00.000Z',
  });
  assert.throws(() => timeRange('2026-10-27T12:00', '2026-10-26T12:00'));
  assert.equal(timestamp('2026-10-26T08:00:00'), at);
  assert.match(dateTime('2026-10-26T00:00:00Z', true), /07:00:00/);
});

test('history query encoding preserves timezone signs and excludes unset filters', () => {
  const encoded = query({ device_id: 'esp32_01', from_at: '2026-10-26T08:00:00+07:00', to_at: undefined });
  const decoded = new URLSearchParams(encoded);
  assert.equal(decoded.get('from_at'), '2026-10-26T08:00:00+07:00');
  assert.equal(decoded.has('to_at'), false);
});

test('untrusted labels are escaped and direct admin routes stay hidden for viewer', () => {
  assert.equal(esc('<img src=x onerror="alert(1)">'), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
  const html = renderPage({ me: { role: 'viewer' }, route: { page: 'users' } });
  assert.match(html, /NHÀ XE CỦA BẠN/);
  assert.doesNotMatch(html, /data-action="create-device"/);
  assert.doesNotMatch(html, /data-action="create-user"/);
});

test('driver counts use freshness and never treat unknown spaces as a full car park', () => {
  const parking = { slots: [
    { name: 'P1', status: 'available', updated_at: '2026-10-26T07:59:59Z', valid_until: '2026-10-26T08:00:10Z' },
    { name: 'P2', status: 'occupied', updated_at: '2026-10-26T07:59:59Z', valid_until: '2026-10-26T08:00:10Z' },
  ] };
  assert.equal(driverSummary(parking, true, at).available, 1);
  assert.equal(driverSummary(parking, true, at + 10000).unknown, 2);
  assert.equal(driverSummary(parking, false, at).available, 0);
  assert.equal(driverSummary(parking, true, at - 2000).unknown, 2);
  const html = viewerContent({ me: { role: 'viewer' }, parking, apiConnected: false });
  assert.match(html, /Đang kiểm tra chỗ đỗ/);
  assert.doesNotMatch(html, /Nhà xe hiện đã đầy/);
});

test('the driver navigation and parking screen omit technical administration', () => {
  const s = { me: { role: 'viewer', username: '<driver>' }, route: { page: 'overview' }, parking: null, apiConnected: true };
  const html = viewerShell(s) + viewerContent(s);
  assert.match(html, /&lt;driver&gt;/);
  for (const word of ['#/devices', '#/telemetry', '#/commands', '#/alerts', '#/users', 'GPIO', 'MQTT', 'firmware']) {
    assert.ok(!html.includes(word), word);
  }
});

test('duration percentages exclude unknown time and combine by seconds', () => {
  const rows = durationSummary({ buckets: [
    { slot: 'P1', occupied_seconds: 5, available_seconds: 5, unknown_seconds: 50 },
    { slot: 'P1', occupied_seconds: 15, available_seconds: 75, unknown_seconds: 0 },
    { slot: 'P2', occupied_seconds: 0, available_seconds: 0, unknown_seconds: 100 },
  ] });
  assert.equal(rows[0].percent, 20);
  assert.equal(rows[0].observed, 100);
  assert.equal(rows[0].unknown, 50);
  assert.equal(rows[1].percent, null);
});

function adminState() {
  return {
    me: { role: 'admin' }, route: { page: 'overview' }, apiConnected: true,
    devices: [device], slots: ['P1', 'P2'].map(name => ({ ...slot, name, occupied: true, updated_at: new Date().toISOString() })),
    alerts: [
      { id: 1, kind: 'parking_full', device_id: 1, active: true, acknowledged: true, acknowledged_by: 7, acknowledged_at: new Date().toISOString() },
      { id: 2, kind: 'device_offline', device_id: 1, active: true },
      { id: 3, kind: 'command_timeout', device_id: 1, active: true },
      { id: 4, kind: 'parking_full', device_id: 1, active: false },
    ], alertFilter: 'all',
  };
}

test('full warnings need fresh occupied spaces and do not depend on acknowledgement', () => {
  const s = adminState();
  assert.deepEqual(activeParkingAlerts(s).map(a => a.id), [1]);
  assert.match(overviewAlerts(s), /role="alert"/);
  assert.doesNotMatch(overviewAlerts(s), /ack-alert|Đánh dấu|Thiết bị mất kết nối/);
  s.slots[1].occupied = false;
  assert.equal(overviewAlerts(s), '');
  s.slots[1].occupied = true;
  s.slots[1].fresh = false;
  assert.equal(overviewAlerts(s), '');
  s.slots[1].fresh = true;
  s.apiConnected = false;
  assert.equal(overviewAlerts(s), '');
});

test('alert history shows supported incidents and review never hides an active incident', () => {
  const s = adminState();
  s.users = [{ id: 7, username: '<admin>' }];
  assert.deepEqual(activeAlerts(s).map(a => a.id), [1, 2]);
  let html = alertRows(s);
  assert.match(html, /Thiết bị mất kết nối/);
  assert.match(html, /Đã xem · &lt;admin&gt;/);
  assert.match(html, /data-action="ack-alert" data-id="2"/);
  assert.doesNotMatch(html, /Lệnh quá thời hạn|data-id="3"|data-id="1"/);
  s.alertFilter = 'active';
  assert.doesNotMatch(alertRows(s), /data-id="4"/);
  s.alertBusy = { 2: true };
  assert.match(alertRows(s), /data-id="2" disabled>Đang lưu/);
  s.alertFilter = 'resolved';
  assert.doesNotMatch(alertRows(s), /Thiết bị mất kết nối/);
  s.apiConnected = false;
  assert.deepEqual(activeAlerts(s), []);
  assert.match(alertRows(s), /data-id="4" disabled/);
});

test('offline alerts are opt-in and the dashboard explains review separately from resolution', () => {
  const s = { ...adminState(), route: { page: 'commands' }, selectedDeviceId: '1',
    permissions: { can_configure: true }, rules: { offline_enabled: false }, commands: [] };
  assert.match(renderPage(s), /name="offline_enabled" type="checkbox">/);
  s.rules.offline_enabled = true;
  assert.match(renderPage(s), /name="offline_enabled" type="checkbox" checked/);
  s.route.page = 'alerts';
  assert.match(renderPage(s), /Đánh dấu đã xem không kết thúc cảnh báo/);
  s.audit = [{ id: 1, actor_id: 7, action: 'auth.login_failed', created_at: new Date().toISOString() },
    { id: 2, actor_id: 7, action: 'telemetry.export_csv:esp32_01', created_at: new Date().toISOString() }];
  s.users = [];
  assert.match(auditRows(s), /Đăng nhập thất bại/);
  assert.match(auditRows(s), /Xuất dữ liệu CSV/);
});

test('admin overview focuses on current spaces and keeps details on their own pages', () => {
  const html = renderPage(adminState());
  assert.match(html, /Chỗ còn trống/);
  assert.match(html, /Xem lịch sử/);
  assert.doesNotMatch(html, /Thời gian có xe|Hoạt động gần đây|Kết nối thiết bị|GPIO|ack-alert|select-device/);
  assert.equal((html.match(/data-region="overview-stats"/g) || []).length, 1);
});


test('gate controls are admin-only and manual actions require manual mode and fresh data', () => {
  const s = adminState();
  s.gates = [{device_id: 1, name: 'ESP32', supported: true, fresh: true,
    valid_until: new Date(Date.now() + 10000).toISOString(),
    gates: [{id: 'entrance', mode: 'auto', target: 'open', pwm_ready: true, close_remaining_ms: 1000}]}];
  let html = gateControls(s);
  assert.match(html, /Đang chờ tự đóng/);
  assert.match(html, /data-action="gate-target"[^>]* disabled/);
  s.gates[0].gates[0].mode = 'manual';
  s.gates[0].gates[0].close_remaining_ms = 0;
  html = gateControls(s);
  assert.doesNotMatch(html, /data-action="gate-target"[^>]* disabled/);
  s.gates[0].valid_until = new Date(Date.now() - 1).toISOString();
  assert.match(gateControls(s), /data-action="gate-target"[^>]* disabled/);
  s.me.role = 'operator';
  assert.equal(gateControls(s), '');
});

test('the lot diagram separates parking, gate presence and barrier signals', () => {
  const s = adminState();
  s.gates = [{ device_id: 1, supported: true, fresh: true,
    valid_until: new Date(Date.now() + 10000).toISOString(), gates: [
      { id: 'entrance', detected: true, target: 'closed', mode: 'manual', pwm_ready: true },
      { id: 'exit', detected: false, target: 'open', mode: 'auto', pwm_ready: true },
    ] }];
  const html = parking(s);
  assert.match(html, /P1: Có xe/);
  assert.match(html, /P2: Có xe/);
  assert.match(html, /Ô chờ vào: Có xe/);
  assert.match(html, /Ô chờ ra: Trống/);
  assert.match(html, /Cổng vào: tín hiệu đóng/);
  assert.match(html, /Cổng ra: tín hiệu mở/);
  assert.equal((html.match(/data-action="gate-target"/g) || []).length, 4);
  // A stale gate response cannot leave an open barrier or free waiting zone on the map.
  s.gates[0].valid_until = new Date(Date.now() - 1).toISOString();
  assert.match(parking(s), /Ô chờ ra: Không xác định/);
  assert.match(parking(s), /Cổng ra: không xác định/);
  s.me.role = 'operator';
  assert.doesNotMatch(parking(s), /data-action="gate-/);
});

test('the lot diagram keeps gate sensors attached to their own device', () => {
  const s = adminState();
  s.gates = [{ device_id: 2, fresh: true, valid_until: new Date(Date.now() + 10000).toISOString(),
    gates: [{ id: 'entrance', detected: true, target: 'open', pwm_ready: true }] }];
  assert.match(parking(s), /Ô chờ vào: Không xác định/);
  assert.doesNotMatch(parking(s), /Ô chờ vào: Có xe/);
});
