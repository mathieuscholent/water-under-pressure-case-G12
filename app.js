const europeBounds = L.latLngBounds([[34, -25], [72, 45]]);
const map = L.map('map', {
  zoomControl: true,
  minZoom: 3,
  maxZoom: 11,
  maxBounds: europeBounds,
  maxBoundsViscosity: 0.85
}).fitBounds(europeBounds, { padding: [12, 12] });

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap contributors',
  maxZoom: 19
}).addTo(map);

const result = document.querySelector('#result');
const ecologicalLabels = { '1': 'High', '2': 'Good', '3': 'Moderate', '4': 'Poor', '5': 'Bad' };
const chemicalLabels = { '2': 'Good', '3': 'Failing to achieve good' };
const colors = { High: '#177a56', Good: '#5bb883', Moderate: '#e7b85c', Poor: '#dc765e', Bad: '#b94e4e' };
const pointsLayer = L.layerGroup().addTo(map);
const maxClickDistanceKm = 75;

function ecologicalLabel(code) {
  return ecologicalLabels[String(code)] || 'No data';
}

function chemicalLabel(code) {
  return chemicalLabels[String(code)] || 'No data';
}

function statusEmoji(status) {
  if (['High', 'Good'].includes(status)) return '🌿';
  if (status === 'Moderate') return '🌱';
  if (['Poor', 'Bad'].includes(status)) return '⚠️';
  return '❔';
}

function bindClose() {
  const close = document.querySelector('#close');
  if (close) close.addEventListener('click', () => result.classList.remove('visible'));
}

function renderRecord(record, distanceKm) {
  const ecological = ecologicalLabel(record.e);
  const chemical = chemicalLabel(record.h);
  const chemicalEmoji = chemical === 'Good' ? '🧪' : chemical === 'No data' ? '❔' : '⚗️';
  result.innerHTML = `<button id="close" aria-label="Close">×</button>
    <div class="result-kicker">EEA WISE · NEAREST RECORD</div>
    <h2>${record.n && record.n !== 'NO INTERNATIONAL NAME' ? record.n : 'Unnamed water body'}</h2>
    <div class="status"><span class="status-dot" style="background:${colors[ecological] || '#8ca49d'}"></span>${statusEmoji(ecological)} ${ecological} ecological status</div>
    <p>${chemicalEmoji} Chemical status: <strong>${chemical}</strong><br>
    🗺️ Country: ${record.c || 'No data'}<br>
    📅 Ecological year: ${record.ey || 'No data'}<br>
    🔎 Ecological confidence: ${record.ec || 'No data'}<br>
    📅 Chemical year: ${record.hy || 'No data'}<br>
    🔬 Chemical method: ${record.m || 'No data'}<br>
    <small>Nearest displayed record · ${Math.round(distanceKm)} km away</small></p>`;
  result.classList.add('visible');
  bindClose();
}

function visibleRecords() {
  const zoom = map.getZoom();
  const step = zoom < 5 ? 6 : zoom < 7 ? 3 : 1;
  return WATER_BODIES.filter((_, index) => index % step === 0);
}

function drawPoints() {
  pointsLayer.clearLayers();
  visibleRecords().forEach(record => {
    const status = ecologicalLabel(record.e);
    L.circleMarker([record.lat, record.lon], {
      radius: map.getZoom() >= 7 ? 5 : 4,
      color: '#ffffff',
      weight: 1.5,
      fillColor: colors[status] || '#8ca49d',
      fillOpacity: 0.9
    }).on('click', event => {
      L.DomEvent.stopPropagation(event);
      renderRecord(record, 0);
    }).addTo(pointsLayer);
  });
}

function showNearest(latlng) {
  if (!WATER_BODIES.length) {
    result.innerHTML = '<button id="close" aria-label="Close">×</button><div class="result-kicker">LOCATION CHECK</div><h2>No data</h2><p>No local EEA record is available.</p>';
    result.classList.add('visible'); bindClose(); return;
  }
  const nearest = WATER_BODIES.reduce((best, record) => {
    const distance = map.distance(latlng, [record.lat, record.lon]) / 1000;
    return distance < best.distance ? { record, distance } : best;
  }, { record: null, distance: Infinity });
  if (nearest.distance > maxClickDistanceKm) {
    result.innerHTML = `<button id="close" aria-label="Close">×</button><div class="result-kicker">LOCATION CHECK</div><h2>No data</h2><p>The nearest EEA water-body record is more than ${maxClickDistanceKm} km from this location.</p>`;
    result.classList.add('visible'); bindClose(); return;
  }
  renderRecord(nearest.record, nearest.distance);
}

map.on('zoomend', drawPoints);
map.on('click', event => showNearest(event.latlng));
drawPoints();
