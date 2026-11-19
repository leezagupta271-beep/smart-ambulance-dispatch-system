document.addEventListener('DOMContentLoaded', () => {
  const views = [...document.querySelectorAll('.view')];
  const navLinks = [...document.querySelectorAll('.nav-link')];
  const pageTitle = document.getElementById('pageTitle');
  const sidebar = document.getElementById('sidebar');
  const modal = document.getElementById('emergencyModal');
  const confirmation = document.getElementById('confirmation');
  let latestBookingId = null;
  let currentFleetFilter = 'all';
  let analyticsPeriodDays = 7;

  const labels = {
    home: 'Home',
    dispatch: 'Smart Dispatch',
    dashboard: 'Live Dashboard',
    ambulances: 'Ambulances',
    hospitals: 'Hospitals',
    analytics: 'Analytics'
  };

  // -------------------------------------------------------------
  // VIEW SWITCHING
  // -------------------------------------------------------------
  const showView = (viewId, updateHash = true) => {
    const target = document.getElementById(viewId) || document.getElementById('home');
    views.forEach(view => view.classList.toggle('active', view === target));
    navLinks.forEach(link => link.classList.toggle('active', link.dataset.view === target.id));
    pageTitle.textContent = labels[target.id] || 'Home';
    sidebar.classList.remove('open');
    if (updateHash) history.replaceState(null, '', `#${target.id}`);
    window.scrollTo({ top: 0, behavior: 'smooth' });

    // Refresh view-specific data when opened
    if (target.id === 'dashboard') loadDashboardStats();
    if (target.id === 'ambulances') loadFleetData();
    if (target.id === 'hospitals') loadHospitalData();
  };

  navLinks.forEach(link => link.addEventListener('click', event => {
    event.preventDefault();
    showView(link.dataset.view);
  }));

  document.querySelectorAll('[data-view-target]').forEach(button => {
    button.addEventListener('click', () => showView(button.dataset.viewTarget));
  });

  const loadTrafficAreas = async () => {
    const list = document.getElementById('trafficAreaList');
    if (!list) return;
    try {
      const res = await fetch('/api/traffic-areas');
      const data = await res.json();
      if (!data.success) throw new Error(data.message);
      list.innerHTML = data.traffic_areas.length ? data.traffic_areas.map(area => `
        <div class="traffic-area-item">
          <div><strong>${area.area_name}</strong><small>${area.latitude.toFixed(4)}, ${area.longitude.toFixed(4)}</small></div>
          <span class="traffic-severity ${area.severity.toLowerCase()}">${area.severity} · +${area.delay_minutes} min</span>
          <small>${area.alternative_route || 'No alternative route recorded'}</small>
        </div>`).join('') : '<p class="muted-label">No traffic-prone areas configured.</p>';
      const sync = document.getElementById('trafficSyncStatus');
      if (sync) sync.textContent = `${data.traffic_areas.length} monitored areas`;
    } catch (err) {
      list.innerHTML = '<p class="muted-label">Traffic data unavailable.</p>';
    }
  };

  document.getElementById('trafficAreaForm').addEventListener('submit', async event => {
    event.preventDefault();
    const payload = {
      area_name: document.getElementById('trafficAreaName').value.trim(),
      latitude: Number(document.getElementById('trafficAreaLat').value),
      longitude: Number(document.getElementById('trafficAreaLon').value),
      severity: document.getElementById('trafficAreaSeverity').value,
      delay_minutes: Number(document.getElementById('trafficAreaDelay').value),
      alternative_route: document.getElementById('trafficAreaRoute').value.trim()
    };
    const res = await fetch('/api/traffic-areas', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
    const data = await res.json();
    if (!data.success) { alert(data.message || 'Unable to add traffic area.'); return; }
    event.currentTarget.reset();
    document.getElementById('trafficAreaDelay').value = 5;
    await loadTrafficAreas();
    loadDashboardStats();
  });

  document.getElementById('menuToggle').addEventListener('click', () => sidebar.classList.toggle('open'));

  // -------------------------------------------------------------
  // MODALS CONTROL
  // -------------------------------------------------------------
  const openModal = () => {
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    confirmation.classList.remove('show');
    document.getElementById('quickEmergencyForm').style.display = '';
  };

  const closeModal = () => {
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
  };

  document.querySelectorAll('[data-open-modal]').forEach(button => button.addEventListener('click', openModal));
  document.querySelectorAll('[data-close-modal]').forEach(button => button.addEventListener('click', closeModal));
  modal.addEventListener('click', event => {
    if (event.target === modal) closeModal();
  });

  // Auth Modal Controls
  const authModal = document.getElementById('authModal');
  const authBtn = document.getElementById('authBtn');
  const authModalClose = document.getElementById('authModalClose');

  authBtn.addEventListener('click', () => authModal.classList.add('open'));
  authModalClose.addEventListener('click', () => authModal.classList.remove('open'));

  const tabLoginBtn = document.getElementById('tabLoginBtn');
  const tabRegisterBtn = document.getElementById('tabRegisterBtn');
  const registerFields = document.getElementById('registerFields');
  const authTitle = document.getElementById('authTitle');
  const authSubmitBtn = document.getElementById('authSubmitBtn');
  let authMode = 'login';

  tabLoginBtn.addEventListener('click', () => {
    authMode = 'login';
    tabLoginBtn.classList.add('active');
    tabRegisterBtn.classList.remove('active');
    registerFields.style.display = 'none';
    authTitle.textContent = 'User Sign In';
    authSubmitBtn.innerHTML = 'Sign In <span>→</span>';
  });

  tabRegisterBtn.addEventListener('click', () => {
    authMode = 'register';
    tabRegisterBtn.classList.add('active');
    tabLoginBtn.classList.remove('active');
    registerFields.style.display = 'block';
    authTitle.textContent = 'Create New Account';
    authSubmitBtn.innerHTML = 'Register Account <span>→</span>';
  });

  // Notifications Modal Controls
  const notifModal = document.getElementById('notificationsModal');
  const notifBellBtn = document.getElementById('notifBellBtn');
  const notifModalClose = document.getElementById('notifModalClose');

  notifBellBtn.addEventListener('click', () => {
    notifModal.classList.add('open');
    loadNotifications();
  });
  notifModalClose.addEventListener('click', () => notifModal.classList.remove('open'));

  // -------------------------------------------------------------
  // AUTHENTICATION API INTEGRATION
  // -------------------------------------------------------------
  const checkCurrentUser = async () => {
    try {
      const res = await fetch('/api/current_user');
      const data = await res.json();
      if (data.authenticated && data.user) {
        document.getElementById('userName').textContent = data.user.name;
        document.getElementById('userRole').textContent = `${data.user.role.toUpperCase()} ACCESS`;
        document.getElementById('userAvatar').textContent = data.user.name.slice(0, 2).toUpperCase();
        document.getElementById('authForm').style.display = 'none';
        document.getElementById('loggedInView').style.display = 'block';
        document.getElementById('loggedMsg').textContent = `Logged in as ${data.user.name} (${data.user.role})`;
      } else {
        document.getElementById('userName').textContent = 'Dispatch Operator';
        document.getElementById('userRole').textContent = '';
        document.getElementById('userAvatar').textContent = 'OP';
        document.getElementById('authForm').style.display = 'block';
        document.getElementById('loggedInView').style.display = 'none';
      }
    } catch (err) {
      console.warn('Auth check fallback:', err);
    }
  };

  document.getElementById('authForm').addEventListener('submit', async event => {
    event.preventDefault();
    const email = document.getElementById('authEmail').value;
    const password = document.getElementById('authPassword').value;

    try {
      let endpoint = authMode === 'login' ? '/api/login' : '/api/register';
      let payload = { email, password };

      if (authMode === 'register') {
        payload.name = document.getElementById('authName').value || 'User';
        payload.phone = document.getElementById('authPhone').value || '9876543210';
        payload.role = document.getElementById('authRole').value;
      }

      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();

      if (data.success) {
        alert(data.message);
        authModal.classList.remove('open');
        checkCurrentUser();
      } else {
        alert(data.message || 'Authentication failed.');
      }
    } catch (err) {
      alert('Error connecting to backend auth API.');
    }
  });

  document.getElementById('logoutBtn').addEventListener('click', async () => {
    await fetch('/api/logout', { method: 'POST' });
    authModal.classList.remove('open');
    checkCurrentUser();
  });

  // -------------------------------------------------------------
  // SMART DISPATCH API INTENT & RENDERING
  // -------------------------------------------------------------
  const submitEmergencyBooking = async (payload) => {
    try {
      const res = await fetch('/api/book-ambulance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.success) {
        latestBookingId = data.booking.id;
        window.localStorage.setItem('latestBookingId', String(latestBookingId));
        renderDispatchResults(data);
        loadDashboardStats();
      } else {
        renderDispatchError(data.message || 'Dispatch allocation failed.');
      }
    } catch (err) {
      console.error('Dispatch error:', err);
      renderDispatchError('The dispatch service is unavailable. Please try again shortly.');
    }
  };

  const setDefaultDateTimeValue = (elementId) => {
    const input = document.getElementById(elementId);
    if (!input) return;
    const now = new Date();
    const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    input.value = input.value || local;
  };

  setDefaultDateTimeValue('requestedAt');
  setDefaultDateTimeValue('quickRequestedAt');

  document.getElementById('dispatchForm').addEventListener('submit', async event => {
    event.preventDefault();
    const btn = document.getElementById('dispatchSubmitBtn');
    btn.disabled = true;
    btn.innerHTML = 'Finding nearest suitable ambulance...';

    const payload = {
      caller_name: document.getElementById('callerName').value,
      description: document.getElementById('description').value,
      pickup_location: document.getElementById('locationSelect').value,
      emergency_type: document.getElementById('emergencyType').value,
      patients: document.getElementById('patients').value,
      severity: document.getElementById('severity').value,
      requested_at: document.getElementById('requestedAt').value
    };

    await submitEmergencyBooking(payload);
    btn.disabled = false;
    btn.innerHTML = 'Execute Smart Dispatch <span aria-hidden="true">→</span>';
    document.getElementById('dispatchResults').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  document.getElementById('quickEmergencyForm').addEventListener('submit', async event => {
    event.preventDefault();
    const btn = document.getElementById('quickSubmitBtn');
    btn.disabled = true;

    const payload = {
      caller_name: 'Quick Intake Caller',
      description: document.getElementById('quickDescription').value || 'Urgent ambulance request submitted.',
      pickup_location: document.getElementById('quickLocation').value,
      emergency_type: document.getElementById('quickType').value,
      severity: document.getElementById('quickSeverity').value,
      patients: document.getElementById('quickPatients').value,
      requested_at: document.getElementById('quickRequestedAt').value
    };

    event.currentTarget.style.display = 'none';
    confirmation.classList.add('show');
    await submitEmergencyBooking(payload);

    setTimeout(() => {
      closeModal();
      showView('dispatch');
      btn.disabled = false;
    }, 1200);
  });

  const renderDispatchResults = (data) => {
    const b = data.booking;
    const amb = data.assigned_ambulance;
    const alts = data.alternative_ambulances || [];
    const hosp = data.recommended_hospital;
    const traffic = data.traffic_info || {};

    const symptomsHtml = (b.symptoms || []).map(s => `<span>${s}</span>`).join('');
    const equipmentHtml = (amb.equipment || []).map(eq => `<span>✓ ${eq}</span>`).join('');
    const resourceHtml = (amb.matched_resources || []).map(resource => `<span>✓ ${resource}</span>`).join('');
    const missingResourceHtml = (amb.missing_resources || []).map(resource => `<span class="resource-missing">! ${resource}</span>`).join('');
    
    const altRowsHtml = alts.map(alt => `
      <div class="alternative-row">
        <strong>${alt.ambulance_number} (${alt.type})</strong>
        <span>${alt.distance_km} km</span>
        <span class="traffic-medium">${alt.status}</span>
        <strong>ETA ${alt.eta_minutes} min</strong>
      </div>
    `).join('');

    const trafficWarningHtml = traffic.severity !== 'Low' ? `
      <div style="margin-top:10px;padding:8px 12px;background:#fff0ef;border:1px solid #f9c0b9;border-radius:8px;font-size:11px;color:#d64545;">
        ⚠️ <strong>Traffic Bottleneck Detected:</strong> ${traffic.affected_area} (+${traffic.delay_minutes} min delay penalty).<br>
        <em>Suggested Bypass: ${traffic.alternative_route || 'Reroute via outer ring road'}</em>
      </div>
    ` : '';

    document.getElementById('dispatchResults').innerHTML = `
      <div class="analysis-wrap">
          <div class="result-card">
          <div class="result-head">
            <div>
              <span class="eyebrow">Python/Flask Emergency NLP Analysis</span>
              <h2>Emergency Assessment</h2>
              <p>${b.emergency_type} Emergency · ${b.patient_count} · ${b.booking_code}</p>
            </div>
            <div class="severity-box">Severity<strong>${b.severity}</strong></div>
          </div>
          <div class="symptoms">${symptomsHtml}</div>
          <div class="priority-line"><span>Priority score: <strong>${b.priority_score}/100</strong></span><i><b style="width:${b.priority_score}%"></b></i></div>
          ${trafficWarningHtml}
        </div>

        <div class="result-card recommended-card">
          <div class="result-head">
            <div>
              <span class="eyebrow">Smart Dispatch Selection</span>
              <h2>${amb.ambulance_number}</h2>
              <p>${amb.type} · Driver: ${amb.driver_name} (${amb.driver_phone})</p>
            </div>
            <span class="route-fastest">OPTIMAL HAVERSINE MATCH</span>
          </div>
          <div class="ambulance-details">
            <div><small>Haversine Dist.</small><strong>${amb.distance_km} km</strong></div>
            <div><small>Traffic Delay</small><strong class="${traffic.severity === 'Heavy' ? 'traffic-heavy' : 'traffic-low'}">${traffic.delay_minutes || 0} min</strong></div>
            <div><small>Total ETA</small><strong class="green-text">${amb.eta_minutes} min</strong></div>
          </div>
          <div class="equipment-list">${equipmentHtml}</div>
          <div class="resource-match"><small>Resource match</small><div>${resourceHtml || '<span>No direct resource match</span>'}${missingResourceHtml}</div></div>
          <button class="dispatch-btn" id="confirmDispatchBtn">✓ Dispatch Confirmed (${amb.ambulance_number})</button>
          <div class="alternatives">
            <span class="eyebrow">Alternative Fleet Options Evaluated</span>
            ${altRowsHtml || '<div class="alternative-row"><span>No alternative options available</span></div>'}
          </div>
        </div>

        <div class="result-card">
          <span class="eyebrow">Algorithmic Decision Factors</span>
          <h3>Why ${amb.ambulance_number}?</h3>
          <ul class="why-list">
            <li>Haversine distance from base (${amb.distance_km} km)</li>
            <li>Adjusted arrival ETA considering ${traffic.affected_area || 'local traffic'}</li>
            <li>Resource match: ${(amb.matched_resources || []).join(', ') || 'standard response kit'}</li>
            <li>Driver readiness & assigned vehicle status</li>
          </ul>
        </div>

        <div class="result-card">
          <div class="result-head">
            <div>
              <span class="eyebrow">SQLite Matched Hospital</span>
              <h2>${hosp ? hosp.name : 'Central District Hospital'}</h2>
              <p>${hosp ? hosp.address : 'Ludhiana'} · ${hosp ? hosp.distance_km : 5.8} km away</p>
            </div>
            <span class="status-badge available">Bed Capacity: ${hosp ? hosp.available_beds : 18}</span>
          </div>
          <div class="hospital-metrics">
            <div class="hospital-metric"><small>Emergency</small><strong class="green-text">Available</strong></div>
            <div class="hospital-metric"><small>ICU</small><strong class="${hosp && hosp.icu_available ? 'green-text' : 'red-text'}">${hosp && hosp.icu_available ? 'Ready' : 'Full'}</strong></div>
            <div class="hospital-metric"><small>Cardiology</small><strong class="${hosp && hosp.cardiology_available ? 'green-text' : 'red-text'}">${hosp && hosp.cardiology_available ? 'Ready' : 'Full'}</strong></div>
            <div class="hospital-metric"><small>Trauma Care</small><strong class="${hosp && hosp.trauma_available ? 'green-text' : 'red-text'}">${hosp && hosp.trauma_available ? 'Ready' : 'Full'}</strong></div>
          </div>
          <p class="hospital-reason">Matched using ${hosp && hosp.matched_resources && hosp.matched_resources.length ? hosp.matched_resources.join(', ') : 'available emergency resources'} plus facility readiness and travel distance.</p>
          <button class="recommend-hospital" id="hospitalNotifSentBtn">✓ Hospital Notified via SQLite</button>
        </div>

        <div class="result-card tracking-card">
          <div class="result-head">
            <div><span class="eyebrow">Latest known status</span><h2 id="trackingStatus">Assigned</h2><p id="trackingMeta">Refreshing ambulance status from Flask...</p></div>
            <span class="status-badge route" id="trackingEta">ETA ${amb.eta_minutes} min</span>
          </div>
          <div class="tracking-steps" id="trackingSteps">
            <span class="active">Request</span><span class="active">Assigned</span><span>Dispatched</span><span>Arriving</span><span>Hospital</span>
          </div>
        </div>
      </div>
    `;

    // Update Hero snapshot on Home tab
    document.getElementById('heroReqId').textContent = `Active response · ${b.booking_code}`;
    document.getElementById('heroRouteText').innerHTML = `${b.pickup_location} <span>→</span> ${hosp ? hosp.name : 'Hospital'}`;
    document.getElementById('heroAmbNum').textContent = amb.ambulance_number;
    document.getElementById('heroEtaText').textContent = `${amb.eta_minutes} min`;
    document.getElementById('heroPriorityText').textContent = b.severity;
    refreshLatestTracking();
  };

  const renderDispatchError = message => {
    document.getElementById('dispatchResults').innerHTML = `<div class="empty-state error-state"><span>!</span><h2>Dispatch unavailable</h2><p>${message}</p><button class="outline-btn" data-view-target="dispatch">Try again</button></div>`;
  };

  const refreshLatestTracking = async () => {
    if (!latestBookingId) return;
    try {
      const res = await fetch(`/api/booking/${latestBookingId}/tracking`);
      const data = await res.json();
      if (!data.success) return;
      const tracking = data.tracking;
      const status = document.getElementById('trackingStatus');
      const meta = document.getElementById('trackingMeta');
      const eta = document.getElementById('trackingEta');
      if (status) status.textContent = tracking.status.replaceAll('_', ' ');
      if (meta) meta.textContent = `${tracking.ambulance.number} · ${tracking.ambulance.status.replaceAll('_', ' ')} · ${tracking.distance_km} km to pickup`;
      if (eta) eta.textContent = `ETA ${tracking.eta_minutes} min`;
      document.querySelectorAll('#trackingSteps span').forEach((step, index) => step.classList.toggle('active', index <= ({ ASSIGNED: 1, ON_THE_WAY: 3, ARRIVED: 4, COMPLETED: 4 }[tracking.status] ?? 1)));
    } catch (err) {
      console.warn('Tracking refresh fallback:', err);
    }
  };

  // -------------------------------------------------------------
  // DASHBOARD DATA FETCHING
  // -------------------------------------------------------------
  const loadDashboardStats = async () => {
    try {
      const res = await fetch(`/api/dashboard/stats?period=${analyticsPeriodDays}`);
      const data = await res.json();
      if (!data.success) return;

      const m = data.metrics;
      renderLiveMap(data.map || {});
      renderLiveAnalytics(data.analytics || {});
      document.getElementById('metricAvailAmb').innerHTML = `${m.available_ambulances} <b>/ ${m.total_ambulances}</b>`;
      document.getElementById('metricFleetNote').textContent = `Updated ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
      document.getElementById('metricActiveEmerg').textContent = String(m.active_emergencies);
      document.getElementById('metricCritCount').textContent = `${m.critical_cases} critical cases`;
      document.getElementById('metricAvgEta').innerHTML = m.average_eta_min === null ? '--' : `${m.average_eta_min} <b>min</b>`;
      document.getElementById('metricEtaNote').textContent = m.average_eta_min === null ? 'No active routes' : 'Haversine routing';
      document.getElementById('metricAvailHosp').innerHTML = `${m.available_hospitals} <b>/ ${m.total_hospitals}</b>`;

      document.getElementById('dashActiveCount').textContent = String(m.active_emergencies).padStart(2, '0');
      document.getElementById('dashCritCount').textContent = String(m.critical_cases).padStart(2, '0');
      document.getElementById('dashAvailAmb').textContent = m.available_ambulances;
      document.getElementById('dashRouteAmb').textContent = m.on_route_ambulances;
      document.getElementById('dashHospCount').textContent = m.available_hospitals;
      document.getElementById('dashAvgEta').innerHTML = m.average_eta_min === null ? '--' : `${m.average_eta_min} <b>min</b>`;

      // Dynamic Hero Snapshot Update
      const heroReqId = document.getElementById('heroReqId');
      const heroRouteText = document.getElementById('heroRouteText');
      const heroAmbNum = document.getElementById('heroAmbNum');
      const heroEtaText = document.getElementById('heroEtaText');
      const heroPriorityText = document.getElementById('heroPriorityText');

      if (data.latest_active_booking) {
        const lab = data.latest_active_booking;
        if (heroReqId) heroReqId.textContent = `Active Response · ${lab.booking_code}`;
        if (heroRouteText) heroRouteText.innerHTML = `${lab.pickup_location} <span>→</span> ${lab.destination}`;
        if (heroAmbNum) heroAmbNum.textContent = lab.ambulance_number;
        if (heroEtaText) heroEtaText.textContent = `${lab.eta_minutes} min`;
        if (heroPriorityText) heroPriorityText.textContent = lab.priority;
      } else {
        if (heroReqId) heroReqId.textContent = `NO ACTIVE EMERGENCY`;
        if (heroRouteText) heroRouteText.textContent = `All fleet units standing by at base stations`;
        if (heroAmbNum) heroAmbNum.textContent = `Ready`;
        if (heroEtaText) heroEtaText.textContent = `-- min`;
        if (heroPriorityText) heroPriorityText.textContent = `Standby`;
      }

      // Render Queue with Actionable Lifecycle Controls
      const queueList = document.getElementById('queueList');
      if (queueList) {
        if (data.emergency_queue && data.emergency_queue.length > 0) {
          queueList.innerHTML = data.emergency_queue.map(q => `
            <div class="queue-item">
              <div>
                <strong>${q.booking_code}</strong>
                <small>${q.location}</small>
              </div>
              <span class="severity ${q.severity.toLowerCase()}">${q.severity}</span>
              <span>${q.ambulance}</span>
              <strong>${q.eta_min}</strong>
            </div>
          `).join('');
        } else {
          queueList.innerHTML = `
            <div class="empty-state" style="padding:24px;min-height:auto;">
              <span style="font-size:24px;">✓</span>
              <h2>No Active Emergencies</h2>
              <p>All emergency dispatch requests have been completed or cleared.</p>
            </div>
          `;
        }
      }

      // Populate full bookings table if present
      loadAllBookingsTable();
    } catch (err) {
      console.warn('Dashboard stats fallback:', err);
    }
  };

  const renderLiveMap = mapData => {
    const container = document.getElementById('liveMapMarkers');
    if (!container) return;
    const trafficBadge = document.getElementById('mapTrafficBadge');
    const trafficAreas = mapData.traffic || [];
    if (trafficBadge) {
      const highestTraffic = trafficAreas[0];
      trafficBadge.textContent = highestTraffic ? `${highestTraffic.severity} traffic · +${highestTraffic.delay_minutes} min near ${highestTraffic.area_name}` : 'Traffic clear · Monitoring routes';
      trafficBadge.classList.toggle('traffic-heavy', Boolean(highestTraffic && highestTraffic.severity === 'Heavy'));
      trafficBadge.classList.toggle('traffic-low', !highestTraffic || highestTraffic.severity !== 'Heavy');
    }
    const toPosition = (latitude, longitude) => ({
      left: `${Math.min(94, Math.max(6, ((longitude - 75.80) / 0.08) * 100))}%`,
      top: `${Math.min(88, Math.max(8, (1 - ((latitude - 30.88) / 0.06)) * 100))}%`
    });
    const ambulances = (mapData.ambulances || []).map(ambulance => {
      const position = toPosition(ambulance.latitude, ambulance.longitude);
      const state = ambulance.status === 'AVAILABLE' ? 'available' : 'route';
      return `<div class="map-marker ambulance ${state}" style="left:${position.left};top:${position.top}" title="${ambulance.ambulance_number} · ${ambulance.status}">▣<small>${ambulance.ambulance_number}</small></div>`;
    });
    const hospitals = (mapData.hospitals || []).map(hospital => {
      const position = toPosition(hospital.latitude, hospital.longitude);
      return `<div class="map-marker hospital" style="left:${position.left};top:${position.top}" title="${hospital.name}">+</div>`;
    });
    const emergencies = (mapData.emergencies || []).map(emergency => {
      const position = toPosition(emergency.pickup_lat, emergency.pickup_lon);
      return `<div class="map-marker emergency" style="left:${position.left};top:${position.top}" title="${emergency.booking_code} · ${emergency.priority}">!</div>`;
    });
    const trafficMarkers = trafficAreas.map(area => {
      const position = toPosition(area.latitude, area.longitude);
      return `<div class="map-marker traffic-point" style="left:${position.left};top:${position.top}" title="${area.area_name} · ${area.severity} traffic">!</div>`;
    });
    container.innerHTML = [...ambulances, ...hospitals, ...emergencies, ...trafficMarkers].join('');
  };

  const renderLiveAnalytics = analytics => {
    const chart = document.getElementById('analyticsTypeChart');
    const total = document.getElementById('analyticsTotalCases');
    const eta = document.getElementById('analyticsEtaValue');
    const utilization = document.getElementById('analyticsUtilization');
    const utilizationLabel = document.getElementById('analyticsUtilizationLabel');
    const statusChart = document.getElementById('analyticsStatusChart');
    const utilizationLegend = document.querySelectorAll('.util-legend span');
    const types = analytics.emergency_types || [];
    const max = Math.max(...types.map(item => item.count), 1);
    if (total) total.textContent = `${analytics.total_cases || 0} total records`;
    if (eta) eta.textContent = analytics.total_cases ? (analytics.average_eta_min === null ? 'No active routes' : `${analytics.average_eta_min} min`) : 'No data';
    const utilizationPercent = analytics.utilization_percent || 0;
    if (utilization) utilization.textContent = utilizationPercent ? `${utilizationPercent}%` : 'All ambulances available';
    if (utilizationLabel) utilizationLabel.textContent = utilizationPercent ? 'in use' : 'fleet ready';
    if (utilizationLegend.length >= 3) {
      utilizationLegend[0].innerHTML = `<i class="legend-ambulance"></i> Active routes (${analytics.active_routes || 0})`;
      utilizationLegend[1].innerHTML = `<i class="legend-hospital"></i> At hospitals (${analytics.at_hospitals || 0})`;
      utilizationLegend[2].innerHTML = `<i class="legend-emergency"></i> Waiting dispatch (${analytics.waiting_dispatch || 0})`;
    }
    if (chart) chart.innerHTML = types.length ? types.slice(0, 6).map(item => `<div><i style="height:${Math.max(8, (item.count / max) * 100)}%"></i><small>${item.type}</small><b>${item.count}</b></div>`).join('') : '<p class="muted-label">No emergency records yet</p>';
    if (statusChart) {
      const statuses = analytics.status_summary || [];
      statusChart.innerHTML = statuses.length ? statuses.map(item => `<div class="analytics-status-row"><span>${item.status.replaceAll('_', ' ')}</span><strong>${item.count}</strong></div>`).join('') : '<p class="muted-label">No response records in this period</p>';
    }
  };

  const loadAllBookingsTable = async () => {
    try {
      const res = await fetch('/api/bookings');
      const data = await res.json();
      if (!data.success || !document.getElementById('bookingsTableBody')) return;

      const tbody = document.getElementById('bookingsTableBody');
      tbody.innerHTML = data.bookings.map(b => `
        <tr>
          <td><strong>${b.booking_code}</strong><small>${b.caller_name}</small></td>
          <td>${b.pickup_location} <span>→</span> ${b.destination}</td>
          <td><span class="severity ${b.priority.toLowerCase()}">${b.priority} (${b.priority_score})</span></td>
          <td>${b.ambulance_number}</td>
          <td><span class="status-badge ${b.booking_status === 'ASSIGNED' ? 'warning' : b.booking_status === 'COMPLETED' ? 'available' : 'route'}">${b.booking_status}</span></td>
          <td>
            ${b.booking_status !== 'COMPLETED' ? `
              <select onchange="updateBookingStatus(${b.id}, this.value)" style="font-size:11px;padding:4px 6px;">
                <option value="">Update Status...</option>
                <option value="ON_THE_WAY">ON THE WAY</option>
                <option value="ARRIVED">ARRIVED</option>
                <option value="COMPLETED">COMPLETE BOOKING ✓</option>
                <option value="CANCELLED">CANCEL</option>
              </select>
            ` : '<span style="color:var(--green);font-weight:700;">✓ COMPLETED</span>'}
          </td>
        </tr>
      `).join('');
    } catch (err) {
      console.warn('Bookings table fetch fallback:', err);
    }
  };

  window.updateBookingStatus = async (bookingId, newStatus) => {
    if (!newStatus) return;
    try {
      const res = await fetch(`/api/bookings/${bookingId}/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus })
      });
      const data = await res.json();
      if (data.success) {
        alert(data.message);
        loadDashboardStats();
        loadFleetData();
      }
    } catch (err) {
      alert('Failed to update booking status.');
    }
  };

  // -------------------------------------------------------------
  // FLEET & AMBULANCES DATA FETCHING
  // -------------------------------------------------------------
  const loadFleetData = async (filter = 'all') => {
    try {
      currentFleetFilter = filter;
      const res = await fetch(`/api/ambulances?status=${filter}`);
      const data = await res.json();
      if (!data.success) return;

      const tbody = document.getElementById('fleetTable');
      tbody.innerHTML = data.ambulances.map(amb => `
        <tr data-status="${amb.status.toLowerCase()}">
          <td><strong>${amb.ambulance_number}</strong><small>${amb.driver_name} (${amb.driver_phone})</small></td>
          <td>${amb.type}<small>${amb.eta_minutes ? `ETA ${amb.eta_minutes} min` : 'No active assignment'}</small></td>
          <td>${amb.current_location}</td>
          <td>${amb.assigned_patient ? `<strong>${amb.assigned_patient}</strong><small>${amb.booking_code}</small>` : '<span class="muted-label">Unassigned</span>'}</td>
          <td><span class="status-badge ${amb.status === 'AVAILABLE' ? 'available' : amb.status === 'MAINTENANCE' ? 'maintenance' : 'route'}">${amb.status}</span></td>
          <td>
            <button class="sim-btn" onclick="simulateAmbMove(${amb.id})">Simulate GPS</button>
            <select class="fleet-status-select" onchange="updateAmbulanceStatus(${amb.id}, this.value)">
              <option value="">Set status...</option><option value="AVAILABLE">Available</option><option value="ON_THE_WAY">On route</option><option value="MAINTENANCE">Maintenance</option><option value="OFFLINE">Offline</option>
            </select>
          </td>
          <td>${amb.equipment.join(', ')}</td>
        </tr>
      `).join('');

      // Update counters
      const allRes = await fetch('/api/ambulances');
      const allData = await allRes.json();
      if (allData.success) {
        const ambs = allData.ambulances;
        document.getElementById('fleetCntAll').textContent = ambs.length;
        document.getElementById('fleetCntAvail').textContent = ambs.filter(a => a.status === 'AVAILABLE').length;
        document.getElementById('fleetCntRoute').textContent = ambs.filter(a => a.status !== 'AVAILABLE' && a.status !== 'MAINTENANCE').length;
        document.getElementById('fleetCntAls').textContent = ambs.filter(a => a.type.includes('ALS')).length;
      }
    } catch (err) {
      console.warn('Fleet data fallback:', err);
    }
  };

  window.simulateAmbMove = async (ambId) => {
    try {
      const res = await fetch(`/api/ambulances/${ambId}/simulate-movement`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        if (!data.moved) {
          alert(data.message);
          return;
        }
        alert(`${data.booking_code} updated: ${data.status.replaceAll('_', ' ')}. ${data.remaining_distance_km.toFixed(2)} km remaining to pickup.`);
        loadFleetData(currentFleetFilter);
        loadDashboardStats();
      } else {
        alert(data.message || 'No active pickup route is available for this ambulance.');
      }
    } catch (err) {
      alert('Unable to update simulated GPS movement.');
    }
  };

  window.updateAmbulanceStatus = async (ambId, status) => {
    if (!status) return;
    try {
      const res = await fetch(`/api/ambulances/${ambId}/status`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) });
      const data = await res.json();
      if (!data.success) { alert(data.message || 'Unable to update ambulance status.'); return; }
      await loadFleetData(currentFleetFilter);
      loadDashboardStats();
    } catch (err) {
      alert('Unable to update ambulance status.');
    }
  };

  document.querySelectorAll('.filter-btn').forEach(button => {
    button.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(item => item.classList.remove('active'));
      button.classList.add('active');
      loadFleetData(button.dataset.filter);
    });
  });

  // -------------------------------------------------------------
  // HOSPITALS DATA FETCHING & BED CAPACITY MANAGEMENT
  // -------------------------------------------------------------
  const loadHospitalData = async () => {
    try {
      const res = await fetch('/api/hospitals');
      const data = await res.json();
      if (!data.success) return;

      const container = document.getElementById('hospitalGrid');
      container.innerHTML = data.hospitals.map((h, idx) => `
        <article class="hospital-card ${idx === 0 ? 'recommended' : ''}">
          <div class="card-top">
            <span class="status-badge ${h.emergency_available ? 'available' : 'warning'}">${h.emergency_available ? (idx === 0 ? 'Recommended' : 'Open') : 'Busy'}</span>
            <span>${h.status === 'ACTIVE' ? 'Receiving open' : 'Temporarily closed'}</span>
          </div>
          <h2>${h.name}</h2>
          <p>${h.address}</p>
          <div class="availability-list">
            <span><i class="${h.emergency_available ? 'check' : 'cross'}">${h.emergency_available ? '✓' : '×'}</i> Emergency dept <b>${h.emergency_available ? 'Open' : 'Full'}</b></span>
            <span><i class="${h.icu_available ? 'check' : 'cross'}">${h.icu_available ? '✓' : '×'}</i> ICU <b>${h.icu_available ? 'Available' : 'Full'}</b></span>
            <span><i class="${h.cardiology_available ? 'check' : 'cross'}">${h.cardiology_available ? '✓' : '×'}</i> Cardiology <b>${h.cardiology_available ? 'Available' : 'Limited'}</b></span>
            <span><i class="${h.trauma_available ? 'check' : 'cross'}">${h.trauma_available ? '✓' : '×'}</i> Trauma Care <b>${h.trauma_available ? 'Available' : 'Full'}</b></span>
          </div>
          <div class="bed-meter">
            <span><small>Available Beds</small><strong>${h.available_beds} / ${h.total_beds}</strong></span>
            <i><b style="width:${h.bed_percentage}%"></b></i>
          </div>
          <div style="margin-top:12px;display:flex;gap:6px;align-items:center;">
            <button class="sim-btn" onclick="adjustBeds(${h.id}, ${h.available_beds - 1})">- Bed</button>
            <button class="sim-btn" onclick="adjustBeds(${h.id}, ${h.available_beds + 1})">+ Bed</button>
            <button class="sim-btn" onclick="toggleDept(${h.id}, ${h.emergency_available ? 0 : 1})" style="margin-left:auto;">Toggle Dept</button>
          </div>
        </article>
      `).join('');
    } catch (err) {
      console.warn('Hospital data fallback:', err);
    }
  };

  window.adjustBeds = async (hospId, newBeds) => {
    if (newBeds < 0) return;
    try {
      const res = await fetch(`/api/hospitals/${hospId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ available_beds: newBeds })
      });
      const data = await res.json();
      if (data.success) {
        loadHospitalData();
        loadDashboardStats();
      }
    } catch (err) {
      alert('Error updating beds.');
    }
  };

  window.toggleDept = async (hospId, emergencyAvailable) => {
    try {
      const res = await fetch(`/api/hospitals/${hospId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ emergency_available: Boolean(emergencyAvailable) })
      });
      const data = await res.json();
      if (!data.success) {
        alert(data.message || 'Unable to update hospital availability.');
        return;
      }
      loadHospitalData();
      loadDashboardStats();
    } catch (err) {
      alert('Unable to update hospital availability.');
    }
  };

  window.deleteAmbulance = async (ambId) => {
    if (!confirm(`Are you sure you want to delete Ambulance #${ambId}?`)) return;
    try {
      const res = await fetch(`/api/ambulances/${ambId}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.success) {
        alert(data.message);
        loadFleetData();
        loadDashboardStats();
      }
    } catch (err) {
      alert('Error deleting ambulance.');
    }
  };

  window.deleteHospital = async (hospId) => {
    if (!confirm(`Are you sure you want to delete Hospital #${hospId}?`)) return;
    try {
      const res = await fetch(`/api/hospitals/${hospId}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.success) {
        alert(data.message);
        loadHospitalData();
        loadDashboardStats();
      }
    } catch (err) {
      alert('Error deleting hospital.');
    }
  };

  // -------------------------------------------------------------
  // NOTIFICATIONS DATA FETCHING
  // -------------------------------------------------------------
  const loadNotifications = async () => {
    try {
      const res = await fetch('/api/notifications');
      const data = await res.json();
      if (!data.success) return;

      const unreadCount = data.notifications.filter(n => n.status === 'UNREAD').length;
      const badge = document.getElementById('notifBadge');
      if (unreadCount > 0) {
        badge.style.display = 'inline-block';
      } else {
        badge.style.display = 'none';
      }

      const listContainer = document.getElementById('notifListContainer');
      listContainer.innerHTML = data.notifications.map(n => `
        <div class="notif-item ${n.status.toLowerCase()}">
          <header>
            <span>${n.hospital_name}</span>
            <small>${n.created_at}</small>
          </header>
          <p>${n.message}</p>
          ${n.status === 'UNREAD' ? `<button class="ack-btn" onclick="ackNotification(${n.id})">Acknowledge Alert</button>` : '<span style="font-size:10px;color:var(--green);font-weight:700;">✓ Acknowledged</span>'}
        </div>
      `).join('');
    } catch (err) {
      console.warn('Notifications fallback:', err);
    }
  };

  window.ackNotification = async (notifId) => {
    await fetch(`/api/notifications/${notifId}/acknowledge`, { method: 'POST' });
    loadNotifications();
  };

  document.getElementById('refreshDashboard').addEventListener('click', async event => {
    event.currentTarget.textContent = '↻ Syncing SQLite...';
    await loadDashboardStats();
    setTimeout(() => {
      event.currentTarget.textContent = '↻ Refresh data';
    }, 1200);
  });

  document.getElementById('analyticsPeriod').addEventListener('change', event => {
    analyticsPeriodDays = Number(event.target.value) === 30 ? 30 : 7;
    loadDashboardStats();
  });

  // Live Clock Update
  const headerDateTime = document.getElementById('headerDateTime');
  const heroDateTime = document.getElementById('heroDateTime');
  const updateClock = () => {
    const now = new Date();
    const dayAndDate = now.toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' });
    const shortTime = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (headerDateTime) headerDateTime.textContent = `· ${dayAndDate} · ${shortTime}`;
    if (heroDateTime) {
      heroDateTime.textContent = `${now.toLocaleDateString([], { weekday: 'long' })} · ${shortTime}`;
    }
  };
  updateClock();
  setInterval(updateClock, 1000);

  latestBookingId = Number(window.localStorage.getItem('latestBookingId')) || null;
  setInterval(refreshLatestTracking, 10000);

  // Initialize
  checkCurrentUser();
  loadDashboardStats();
  loadTrafficAreas();
  loadNotifications();
  setInterval(loadDashboardStats, 15000);
  setInterval(loadTrafficAreas, 15000);
  setInterval(() => loadFleetData(currentFleetFilter), 15000);
  setInterval(loadNotifications, 15000); // Poll notifications every 15s

  const initialView = window.location.hash.slice(1);
  if (document.getElementById(initialView)) showView(initialView, false);
});
