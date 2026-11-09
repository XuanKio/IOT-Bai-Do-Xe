import { esc as e, icon, car, timestamp, dateTime } from './core.js?v=20261106-lot-map1';

export function driverSlots(parking, connected, at = Date.now()) {
  return (parking?.slots || []).map(slot => ({ ...slot,
    status: connected && ['available', 'occupied'].includes(slot.status)
      && Number.isFinite(timestamp(slot.valid_until)) && at >= timestamp(slot.updated_at) && at < timestamp(slot.valid_until)
      ? slot.status : 'unknown',
  }));
}
export function driverSummary(parking, connected, at = Date.now()) {
  const slots = driverSlots(parking, connected, at);
  return { slots, capacity: slots.length, available: slots.filter(s => s.status === 'available').length,
    occupied: slots.filter(s => s.status === 'occupied').length, unknown: slots.filter(s => s.status === 'unknown').length };
}
const labels = { available: 'Còn trống', occupied: 'Đã có xe', unknown: 'Chưa xác định' };

export function viewerShell(s) {
  return `<div class="driver-app"><header class="driver-header"><a class="driver-brand" href="#/overview"><span class="brand-mark">P<span>↗</span></span><span>ParkFlow<small>TÌM CHỖ ĐỖ DỄ HƠN</small></span></a>
    <nav aria-label="Điều hướng"><a href="#/overview" data-nav="overview">Nhà xe</a><a href="#/account" data-nav="account">Tài khoản</a></nav>
    <div class="driver-profile"><span class="avatar">${e(s.me.username.slice(0, 2).toUpperCase())}</span><span>${e(s.me.username)}</span><button class="btn-icon" data-action="logout" aria-label="Đăng xuất">${icon('logout')}</button></div></header>
    <main id="main-content" class="driver-main" tabindex="-1"><div id="page-content"></div></main>
    <footer class="driver-footer"><span>ParkFlow · Nhà xe mô hình 2 ô</span><span>Sơ đồ vị trí minh họa · Thời gian UTC+7</span></footer></div>`;
}

export function viewerPage(s) { return `<div data-region="driver-live">${viewerContent(s)}</div>`; }

export function viewerContent(s) {
  const n = driverSummary(s.parking, s.apiConnected);
  const chosen = n.slots.find(p => p.name === s.viewerSlot) || n.slots.find(p => p.status === 'available') || n.slots[0];
  const stateText = !s.apiConnected ? 'Đang gián đoạn cập nhật' : !s.parking ? 'Đang lấy thông tin' : n.unknown ? 'Một số ô chưa có thông tin mới' : 'Đang cập nhật';
  const title = n.capacity ? (n.available ? 'Vẫn còn chỗ cho bạn.' : n.unknown ? 'Đang kiểm tra chỗ đỗ.' : 'Nhà xe hiện đã đầy.') : 'Tìm chỗ đỗ, trước khi vào bãi.';
  const updated = s.parking?.generated_at ? dateTime(s.parking.generated_at, true) : 'Chưa có thông tin';
  const bays = n.slots.map(p => `<button class="driver-bay ${p.status}${chosen?.name === p.name ? ' selected' : ''}" data-action="select-bay" data-slot="${e(p.name)}" aria-pressed="${chosen?.name === p.name}" aria-label="Ô ${e(p.name)}: ${labels[p.status]}">
    <span class="bay-top"><strong>${e(p.name)}</strong><span>KHU ${e(p.zone)}</span></span>${car()}<span class="bay-state"><i></i>${labels[p.status]}</span></button>`).join('');
  return `<section class="driver-intro"><div><p class="driver-eyebrow">NHÀ XE CỦA BẠN</p><h1>${title}</h1><p>Xem chỗ trống và chọn vị trí phù hợp trên sơ đồ.</p></div>
    <div class="driver-sync${!s.apiConnected || n.unknown ? ' uncertain' : ''}" role="status"><span class="dot"></span>${stateText}<small>Cập nhật lúc ${e(updated)}</small></div></section>
    ${!s.apiConnected ? '<div class="driver-warning" role="alert">Thông tin hiện tại chưa được xác nhận. Các ô được đánh dấu chưa xác định cho đến khi kết nối phục hồi.</div>' : ''}
    <section class="driver-counts" aria-label="Tình trạng nhà xe"><div class="driver-main-count"><span>SỐ XE TRONG NHÀ XE</span><div><strong>${n.occupied}</strong><span>/ ${n.capacity}</span></div></div>
    <div class="driver-count"><span class="count-glyph available">${icon('check')}</span><div><strong>${n.available}</strong><span>Số chỗ còn lại</span></div></div><div class="driver-count"><span class="count-glyph unknown">${icon('info')}</span><div><strong>${n.unknown}</strong><span>Chưa xác định</span></div></div></section>
    ${n.capacity ? `<div class="driver-layout"><section class="driver-map-card"><div class="driver-section-head"><div><p class="driver-eyebrow">TÌM VỊ TRÍ</p><h2>Sơ đồ nhà xe</h2></div><button class="btn" data-action="refresh">${icon('refresh')}Làm mới</button></div>
      <div class="driver-legend"><span><i class="available"></i>Còn trống</span><span><i class="occupied"></i>Đã có xe</span><span><i class="unknown"></i>Chưa xác định</span></div>
      <div class="driver-floorplan"><div class="floor-label"><span>KHU A · Ô ĐỖ XE</span><span>PHÍA TRONG NHÀ XE</span></div><div class="driver-bays">${bays}</div>
      <div class="driver-lane" aria-label="Làn di chuyển từ lối vào sang lối ra"><span class="lane-entry">LỐI VÀO ${icon('arrow')}</span><span class="lane-dashes" aria-hidden="true"></span><span class="lane-exit">${icon('arrow')} LỐI RA</span></div></div>
      <p class="driver-map-note">${icon('info')}Sơ đồ mô phỏng. Chọn một ô để xem vị trí và trạng thái.</p></section>
      <aside class="driver-side"><section class="driver-location"><p class="driver-eyebrow">VỊ TRÍ ĐANG CHỌN</p><div class="location-number"><span>Ô</span><strong>${e(chosen.name)}</strong></div><span class="driver-status ${chosen.status}"><i></i>${labels[chosen.status]}</span>
      <div class="location-info"><p>${icon('pin')}Khu ${e(chosen.zone)} · Nhà xe mô hình</p><p>${icon('arrow')}${chosen.name === 'P1' ? 'Ô đầu tiên từ phía lối vào.' : 'Ô phía bên phải khu A, đi theo làn di chuyển.'}</p></div>
      <p class="location-help">${chosen.status === 'available' ? 'Bạn có thể di chuyển đến vị trí này. Trạng thái có thể thay đổi khi xe khác vào bãi.' : chosen.status === 'occupied' ? 'Ô này đang có xe. Hãy chọn một ô còn trống trên sơ đồ.' : 'Chưa có thông tin mới cho ô này. Vui lòng kiểm tra lại trước khi di chuyển.'}</p></section>
      <section class="driver-help"><span>${icon('shield')}</span><div><h3>Thông tin giúp bạn chọn chỗ</h3><p>Số chỗ trống được cập nhật tự động. Chọn ô trên sơ đồ để xem vị trí; thao tác này không giữ chỗ.</p></div></section></aside></div>`
      : `<section class="driver-no-access">${icon('pin')}<h2>${s.parking ? 'Chưa có nhà xe để hiển thị' : 'Đang tải thông tin nhà xe'}</h2><p>${s.parking ? 'Liên hệ quản trị viên để được cấp quyền xem nhà xe.' : 'Vui lòng chờ trong giây lát.'}</p><button class="btn" data-action="refresh">${icon('refresh')}Thử lại</button></section>`}`;
}
