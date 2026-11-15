/* Malkia Konnect - QR + GPS clock in/out (mobile). Server validates everything; this only collects input. */
(function () {
  var app = document.getElementById('clockApp');
  if (!app) return;
  var csrf = (app.querySelector('input[name=csrfmiddlewaretoken]') || {}).value || '';
  var $ = function (id) { return document.getElementById(id); };
  var gpsEl = $('gpsStatus'), gpsAcc = $('gpsAcc'), resultEl = $('clockResult');
  var action = null, scanner = null, lastFix = null, busy = false;

  function setGps(cls, text) { if (gpsEl) { gpsEl.className = cls; gpsEl.textContent = text; } }
  function show(el, kind, text) { if (!el) return; el.className = 'result-box result-' + kind; el.textContent = text; }
  function result(kind, text) { if (resultEl) { resultEl.innerHTML = '<div class="result-box result-' + kind + '"></div>'; resultEl.firstChild.textContent = text; } }

  function getFix() {
    return new Promise(function (resolve, reject) {
      if (!navigator.geolocation) { reject({code: 'unsupported', message: 'This phone or browser cannot provide GPS location.'}); return; }
      navigator.geolocation.getCurrentPosition(function (p) {
        lastFix = {latitude: p.coords.latitude, longitude: p.coords.longitude, accuracy: p.coords.accuracy};
        if (gpsAcc) gpsAcc.textContent = 'Accuracy: ±' + Math.round(p.coords.accuracy) + ' m';
        setGps('gps-ok', 'Location found');
        resolve(lastFix);
      }, function (e) {
        var msg = e.code === 1 ? 'Location permission required. Please allow location for this site.' : 'Could not get your location. Move to an open area and try again.';
        setGps('gps-bad', msg); reject({code: 'gps', message: msg});
      }, {enableHighAccuracy: true, timeout: 15000, maximumAge: 0});
    });
  }

  function tokenFrom(text) {
    text = (text || '').trim();
    try { var u = new URL(text); var t = u.searchParams.get('t'); if (t) return t; } catch (e) { /* not a URL */ }
    return text;
  }

  function updateRecord(r) {
    if (!r) return;
    var set = function (id, v) { var e = $(id); if (e) e.textContent = v; };
    set('rArr', r.clock_in || '--:--'); set('rDep', r.clock_out || '--:--'); set('rHrs', r.worked || '--'); set('rSt', r.status_label);
    var bi = $('btnIn'), bo = $('btnOut');
    if (bi) bi.disabled = !!r.clock_in;
    if (bo) bo.disabled = !r.clock_in || !!r.clock_out;
  }

  function submit(act, token, msgEl) {
    if (busy) return Promise.resolve();
    busy = true;
    return getFix().catch(function (e) { return null; }).then(function (fix) {
      var body = {token: token};
      if (fix) { body.latitude = fix.latitude; body.longitude = fix.longitude; body.accuracy = fix.accuracy; }
      return fetch(act === 'in' ? app.dataset.inUrl : app.dataset.outUrl, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: JSON.stringify(body)
      }).then(function (r) { return r.json().catch(function () { return {ok: false, message: 'Unexpected server response.'}; }); });
    }).then(function (j) {
      if (j.ok) { updateRecord(j.record); show(msgEl, 'ok', '✓ ' + j.message); result('ok', '✓ ' + j.message); setTimeout(closeScan, 1200); }
      else { var m = j.message || 'Attendance could not be recorded.'; if (j.distance_m != null) m += ' (' + Math.round(j.distance_m) + ' m from the branch)'; show(msgEl, 'err', m); result('err', m); }
    }).catch(function () { var m = 'Network problem. Check your connection and try again.'; show(msgEl, 'err', m); result('err', m); })
      .then(function () { busy = false; });
  }

  /* ---------- scanner modal (home page) ---------- */
  var modal = $('scanModal'), msg = $('scanMsg');
  function closeScan() {
    if (!modal) return;
    modal.classList.remove('show');
    if (scanner) { var s = scanner; scanner = null; try { Promise.resolve(s.stop()).then(function () { s.clear(); }).catch(function () {}); } catch (e) { /* scanner never started */ } }
  }
  function openScan(act) {
    action = act; if (!modal) return;
    $('scanTitle').textContent = act === 'in' ? 'Clock In - scan office QR code' : 'Clock Out - scan office QR code';
    show(msg, 'info', 'Point your camera at the Malkia Konnect QR code.');
    modal.classList.add('show');
    getFix().catch(function () {});
    if (typeof Html5Qrcode === 'undefined') { show(msg, 'err', 'Scanner could not load. Use the paste option below.'); return; }
    scanner = new Html5Qrcode('reader');
    scanner.start({facingMode: 'environment'}, {fps: 10, qrbox: {width: 230, height: 230}}, function (text) {
      if (busy) return; show(msg, 'info', 'QR code read. Verifying…'); submit(action, tokenFrom(text), msg);
    }, function () {}).catch(function () { show(msg, 'err', 'Camera not available. Allow camera access or paste the code below.'); });
  }
  var bIn = $('btnIn'), bOut = $('btnOut'), bScan = $('scanBtn');
  if (modal && bScan) {
    if (bIn) bIn.addEventListener('click', function () { openScan('in'); });
    if (bOut) bOut.addEventListener('click', function () { openScan('out'); });
    if (bScan) bScan.addEventListener('click', function () { openScan(app.dataset.hasIn && !app.dataset.hasOut ? 'out' : 'in'); });
    $('scanClose').addEventListener('click', closeScan);
    $('manualGo').addEventListener('click', function () { var v = tokenFrom($('manualToken').value); if (v) submit(action || 'in', v, msg); });
  }

  /* ---------- landing page after scanning with the phone's own camera app ---------- */
  var tok = app.dataset.token;
  if (tok && !modal.classList.contains('show') && $('qrInfo')) {
    var info = $('qrInfo');
    fetch(app.dataset.checkUrl, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf}, body: JSON.stringify({token: tok})})
      .then(function (r) { return r.json(); }).then(function (j) {
        if (!j.ok) { show(info, 'err', j.message || 'This QR code is not valid.'); return; }
        if (!j.allowed) { show(info, 'err', 'You are not allowed to clock in at ' + j.branch + '.'); return; }
        show(info, 'ok', 'Branch: ' + j.branch + '. Choose Clock In or Clock Out.');
        $('btnIn').disabled = false; $('btnOut').disabled = false;
        $('btnIn').onclick = function () { submit('in', tok, info); };
        $('btnOut').onclick = function () { submit('out', tok, info); };
      }).catch(function () { show(info, 'err', 'Network problem. Please try again.'); });
  }
  getFix().catch(function () {});
})();
