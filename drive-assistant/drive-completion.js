// LUMINA Drive Assistant completion layer
// Keeps the deployed UI reliable on mobile browsers without replacing core routing logic.
(() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const SESSION_KEY = 'lumina-drive-session-v1';
  const safeClick = el => { if (el) el.click(); };
  let arrivalHandled = false;

  function setText(id, value) { const el = $(id); if (el) el.textContent = value; }

  function persistFreeDrive(on) {
    try {
      const raw = JSON.parse(localStorage.getItem(SESSION_KEY) || '{}');
      raw.freeDrive = !!on;
      localStorage.setItem(SESSION_KEY, JSON.stringify(raw));
    } catch {}
  }

  function normalizeFreeDriveButton(on) {
    const button = $('#freeDriveBtn');
    if (!button) return;
    const icon = button.querySelector('.home-action-icon');
    const title = button.querySelector('strong');
    if (icon) icon.textContent = '◎';
    if (title) title.textContent = on ? 'Free Drive ON' : 'Free Drive';
    button.setAttribute('aria-pressed', String(!!on));
  }

  function enterFreeDriveUI() {
    document.body.classList.add('free-drive-active');
    $('#navCockpit')?.classList.remove('hidden');
    $('#navVoiceDock')?.classList.remove('hidden');
    setText('#navDestination', 'Free Drive');
    setText('#navRoad', $('#roadName')?.textContent || 'Τρέχουσα θέση');
    setText('#navSpeed', $('#speed')?.textContent || '0');
    setText('#navSpeedLimit', $('#speedLimit')?.textContent || '—');
    normalizeFreeDriveButton(true);
    persistFreeDrive(true);
    setTimeout(() => window.dispatchEvent(new Event('resize')), 100);
  }

  function leaveFreeDriveUI() {
    document.body.classList.remove('free-drive-active');
    normalizeFreeDriveButton(false);
    persistFreeDrive(false);
    if (!document.body.classList.contains('navigation-active')) {
      $('#navCockpit')?.classList.add('hidden');
      $('#navVoiceDock')?.classList.add('hidden');
    }
  }

  function freeDriveIsOn() {
    const b = $('#freeDriveBtn');
    return !!(b && (/ON/i.test(b.querySelector('strong')?.textContent || '') || b.getAttribute('aria-pressed') === 'true'));
  }

  function syncFreeDrive() {
    freeDriveIsOn() ? enterFreeDriveUI() : leaveFreeDriveUI();
  }

  function speakStatus() {
    const speed = $('#speed')?.textContent || '0';
    const limit = $('#speedLimit')?.textContent || 'άγνωστο';
    const road = $('#roadName')?.textContent || 'την τρέχουσα θέση';
    if (!('speechSynthesis' in window)) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(`Τρέχουσα ταχύτητα ${speed} χιλιόμετρα την ώρα. Όριο ${limit}. Βρίσκεσαι σε ${road}.`);
    u.lang = 'el-GR';
    u.rate = 0.96;
    speechSynthesis.speak(u);
  }

  function reportDanger() {
    const list = $('#alertsList');
    if (list) list.insertAdjacentHTML('afterbegin', '<div class="alert manual-danger"><span>⚠️</span><div><b>Κίνδυνος</b><small>Χειροκίνητη οδηγική επισήμανση.</small></div></div>');
    if ('vibrate' in navigator) navigator.vibrate([180,100,180]);
  }

  function observeArrival() {
    const maneuver = $('#maneuverText');
    if (!maneuver || !window.MutationObserver) return;
    const check = () => {
      const arrived = maneuver.textContent.trim() === 'Άφιξη';
      if (!arrived) {
        arrivalHandled = false;
        return;
      }
      if (arrivalHandled) return;
      arrivalHandled = true;
      setTimeout(() => {
        if (maneuver.textContent.trim() === 'Άφιξη') safeClick($('#stopRouteBtn'));
      }, 2500);
    };
    new MutationObserver(check).observe(maneuver, {childList:true, characterData:true, subtree:true});
    check();
  }

  function bind() {
    const free = $('#freeDriveBtn');
    free?.addEventListener('click', () => setTimeout(syncFreeDrive, 0));

    $('#navStopBtn')?.addEventListener('click', () => {
      if (freeDriveIsOn()) safeClick(free);
      setTimeout(leaveFreeDriveUI, 0);
    });

    const statusBtn = document.createElement('button');
    statusBtn.type = 'button';
    statusBtn.id = 'navStatusBtn';
    statusBtn.className = 'nav-mini';
    statusBtn.textContent = '🔊';
    statusBtn.setAttribute('aria-label', 'Κατάσταση οδήγησης');
    statusBtn.addEventListener('click', speakStatus);
    const dock = $('#navVoiceDock');
    if (dock && !$('#navStatusBtn')) dock.appendChild(statusBtn);

    const mic = $('#navVoiceBtn');
    let timer = null;
    mic?.addEventListener('pointerdown', () => { timer = setTimeout(reportDanger, 900); });
    ['pointerup','pointercancel','pointerleave'].forEach(ev => mic?.addEventListener(ev, () => { if (timer) clearTimeout(timer); timer = null; }));

    syncFreeDrive();
    observeArrival();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind, {once:true});
  else bind();
})();
