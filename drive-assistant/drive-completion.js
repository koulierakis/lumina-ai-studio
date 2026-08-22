// LUMINA Drive Assistant completion layer
// Keeps the deployed UI reliable on mobile browsers without replacing core routing logic.
(() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const safeClick = el => { if (el) el.click(); };

  function setText(id, value) { const el = $(id); if (el) el.textContent = value; }

  function enterFreeDriveUI() {
    document.body.classList.add('free-drive-active');
    const cockpit = $('#navCockpit');
    const dock = $('#navVoiceDock');
    cockpit?.classList.remove('hidden');
    dock?.classList.remove('hidden');
    setText('#navDestination', 'Free Drive');
    setText('#navRoad', $('#roadName')?.textContent || 'Τρέχουσα θέση');
    setText('#navSpeed', $('#speed')?.textContent || '0');
    setText('#navSpeedLimit', $('#speedLimit')?.textContent || '—');
    setTimeout(() => window.dispatchEvent(new Event('resize')), 100);
  }

  function leaveFreeDriveUI() {
    document.body.classList.remove('free-drive-active');
    if (!document.body.classList.contains('navigation-active')) {
      $('#navCockpit')?.classList.add('hidden');
      $('#navVoiceDock')?.classList.add('hidden');
    }
  }

  function freeDriveIsOn() {
    const b = $('#freeDriveBtn');
    return !!(b && /ON/i.test(b.textContent));
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
    u.lang = 'el-GR'; u.rate = 0.96;
    speechSynthesis.speak(u);
  }

  function reportDanger() {
    const list = $('#alertsList');
    if (list) list.insertAdjacentHTML('afterbegin', '<div class="alert manual-danger"><span>⚠️</span><div><b>Κίνδυνος</b><small>Χειροκίνητη οδηγική επισήμανση.</small></div></div>');
    if ('vibrate' in navigator) navigator.vibrate([180,100,180]);
  }

  function bind() {
    const free = $('#freeDriveBtn');
    free?.addEventListener('click', () => setTimeout(syncFreeDrive, 0));

    // Make the cockpit stop control also leave Free Drive when no route is active.
    $('#navStopBtn')?.addEventListener('click', () => {
      if (freeDriveIsOn()) safeClick(free);
      setTimeout(leaveFreeDriveUI, 0);
    });

    // Fast, dependable status action in the navigation cockpit.
    const statusBtn = document.createElement('button');
    statusBtn.type = 'button';
    statusBtn.id = 'navStatusBtn';
    statusBtn.className = 'nav-mini';
    statusBtn.textContent = '🔊';
    statusBtn.setAttribute('aria-label', 'Κατάσταση οδήγησης');
    statusBtn.addEventListener('click', speakStatus);
    const dock = $('#navVoiceDock');
    if (dock && !$('#navStatusBtn')) dock.appendChild(statusBtn);

    // Long press on LUMINA mic is an immediate danger marker; normal tap remains voice input.
    const mic = $('#navVoiceBtn');
    let timer = null;
    mic?.addEventListener('pointerdown', () => { timer = setTimeout(reportDanger, 900); });
    ['pointerup','pointercancel','pointerleave'].forEach(ev => mic?.addEventListener(ev, () => { if (timer) clearTimeout(timer); timer = null; }));

    syncFreeDrive();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind, {once:true});
  else bind();
})();