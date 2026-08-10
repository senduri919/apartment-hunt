document.addEventListener('DOMContentLoaded', () => {
  const listingsData = JSON.parse(document.getElementById('listings-data').textContent);
  const grid = document.getElementById('listings-grid');

  const filterNeighborhood = document.getElementById('filter-neighborhood');
  const filterStatus = document.getElementById('filter-status');
  const filterSource = document.getElementById('filter-source');
  const sortBy = document.getElementById('sort-by');
  const searchInput = document.getElementById('search-input');

  function scoreClass(score) {
    if (score >= 75) return 'score-high';
    if (score >= 50) return 'score-med';
    return 'score-low';
  }

  function formatPrice(price) {
    return price.toLocaleString('en-US');
  }

  function renderTags(listing) {
    let tags = '';
    if (listing.has_in_unit_laundry) tags += '<span class="tag">W/D In-Unit</span>';
    if (listing.has_parking) tags += `<span class="tag">${listing.parking_type ? listing.parking_type.charAt(0).toUpperCase() + listing.parking_type.slice(1) + ' Parking' : 'Parking'}</span>`;
    if (listing.is_pet_friendly) tags += `<span class="tag">${listing.pet_details || 'Pet-Friendly'}</span>`;
    if (listing.has_outdoor_space) tags += `<span class="tag">${listing.outdoor_details || 'Outdoor Space'}</span>`;
    if (listing.building_type) tags += `<span class="tag tag-modern">${listing.building_type.charAt(0).toUpperCase() + listing.building_type.slice(1)}</span>`;
    if (listing.lease_term) tags += `<span class="tag">${listing.lease_term}</span>`;
    if (listing.nearest_transit) tags += `<span class="tag">${listing.nearest_transit}</span>`;
    return tags;
  }

  function renderScoreBreakdown(breakdown) {
    if (!breakdown) return '';
    const labels = {
      sqft: 'Square Footage', building_type: 'Building Type', laundry: 'In-Unit Laundry',
      transit: 'Transit', parking: 'Parking', pets: 'Pets',
      outdoor: 'Outdoor', move_in: 'Move-in Date', lease: 'Lease', price: 'Price'
    };
    let rows = '';
    for (const [key, value] of Object.entries(breakdown)) {
      rows += `<div class="score-row">
        <span>${labels[key] || key}</span>
        <div class="score-bar"><div class="score-fill" style="width:${value}%"></div></div>
        <span>${value}</span>
      </div>`;
    }
    return rows;
  }

  function renderCard(listing) {
    const score = listing.score || 0;
    const imgHtml = listing.images && listing.images.length > 0
      ? `<img class="card-img" src="${listing.images[0]}" alt="Listing photo" loading="lazy" onerror="this.outerHTML='<div class=\\'card-img-placeholder\\'>&#127968;</div>'">`
      : '<div class="card-img-placeholder">&#127968;</div>';

    const votes = listing.votes || {};
    const upCount = Object.values(votes).filter(v => v === 'up').length;
    const downCount = Object.values(votes).filter(v => v === 'down').length;

    const notes = listing.notes || [];

    return `<div class="card" data-id="${listing.id}" data-neighborhood="${listing.neighborhood || ''}" data-status="${listing.status || 'new'}" data-source="${listing.source || ''}" data-score="${score}" data-price="${listing.price}" data-sqft="${listing.sqft || 0}" data-date="${listing.first_seen || ''}">
      ${imgHtml}
      <div class="card-body">
        <div class="card-header">
          <span class="score-badge ${scoreClass(score)}">Score: ${score}/100</span>
          <span class="price">$${formatPrice(listing.price)}/mo</span>
        </div>
        <div class="address">${listing.address || 'Address not available'}</div>
        ${listing.neighborhood ? `<div class="neighborhood">${listing.neighborhood}</div>` : ''}
        <div class="details">
          ${listing.bedrooms ? `${listing.bedrooms} bed` : 'Beds: Contact'}
          &middot;
          ${listing.bathrooms ? `${listing.bathrooms} bath` : 'Bath: Contact'}
          ${listing.sqft ? ` &middot; ${formatPrice(listing.sqft)} sqft` : ''}
          ${listing.available_date ? ` &middot; Avail: ${listing.available_date}` : ''}
        </div>
        <div class="tags">${renderTags(listing)}<span class="tag tag-source">${listing.source || ''}</span></div>
        <div class="card-footer">
          <a class="card-link" href="${listing.source_url}" target="_blank" rel="noopener">View Listing &rarr;</a>
          <button class="notes-toggle" onclick="toggleBreakdown('${listing.id}')">Score Details</button>
        </div>
        <div class="score-breakdown" id="breakdown-${listing.id}">${renderScoreBreakdown(listing.score_breakdown)}</div>
        <div class="collab-section">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
            <div class="vote-buttons">
              <button class="vote-btn" onclick="vote('${listing.id}','up')">&#128077; ${upCount}</button>
              <button class="vote-btn" onclick="vote('${listing.id}','down')">&#128078; ${downCount}</button>
            </div>
            <select class="status-select" onchange="setStatus('${listing.id}', this.value)">
              ${['new','contacted','toured','favorite','rejected'].map(s =>
                `<option value="${s}" ${listing.status === s ? 'selected' : ''}>${s.charAt(0).toUpperCase() + s.slice(1)}</option>`
              ).join('')}
            </select>
          </div>
          ${notes.length > 0 ? `
          <button class="notes-toggle" onclick="toggleNotes('${listing.id}')">Notes (${notes.length})</button>
          <div class="notes-panel" id="notes-${listing.id}">
            ${notes.map(n => `<div class="note"><span class="note-author">${n.author || 'Anonymous'}</span> <span class="note-date">${n.date || ''}</span><br>${n.text}</div>`).join('')}
          </div>` : ''}
        </div>
      </div>
    </div>`;
  }

  function applyFilters() {
    const hood = filterNeighborhood.value;
    const status = filterStatus.value;
    const source = filterSource.value;
    const sort = sortBy.value;
    const search = (searchInput.value || '').toLowerCase();

    let filtered = listingsData.filter(l => {
      if (hood && l.neighborhood !== hood) return false;
      if (status && (l.status || 'new') !== status) return false;
      if (source && l.source !== source) return false;
      if (search) {
        const haystack = `${l.address} ${l.neighborhood} ${l.description} ${l.source}`.toLowerCase();
        if (!haystack.includes(search)) return false;
      }
      return true;
    });

    filtered.sort((a, b) => {
      switch (sort) {
        case 'score': return (b.score || 0) - (a.score || 0);
        case 'price-low': return a.price - b.price;
        case 'price-high': return b.price - a.price;
        case 'sqft': return (b.sqft || 0) - (a.sqft || 0);
        case 'date': return (b.first_seen || '').localeCompare(a.first_seen || '');
        default: return (b.score || 0) - (a.score || 0);
      }
    });

    if (filtered.length === 0) {
      grid.innerHTML = '<div class="empty-state"><h2>No listings match your filters</h2><p>Try adjusting the filters above.</p></div>';
    } else {
      grid.innerHTML = filtered.map(renderCard).join('');
    }

    document.getElementById('filtered-count').textContent = filtered.length;
  }

  filterNeighborhood.addEventListener('change', applyFilters);
  filterStatus.addEventListener('change', applyFilters);
  filterSource.addEventListener('change', applyFilters);
  sortBy.addEventListener('change', applyFilters);
  searchInput.addEventListener('input', applyFilters);

  applyFilters();

  window.toggleBreakdown = function(id) {
    const el = document.getElementById('breakdown-' + id);
    if (el) el.classList.toggle('open');
  };

  window.toggleNotes = function(id) {
    const el = document.getElementById('notes-' + id);
    if (el) el.classList.toggle('open');
  };

  window.vote = function(id, direction) {
    const listing = listingsData.find(l => l.id === id);
    if (!listing) return;
    if (!listing.votes) listing.votes = {};
    const user = localStorage.getItem('apartment-hunt-user') || 'anonymous';
    listing.votes[user] = direction;
    applyFilters();
  };

  window.setStatus = function(id, status) {
    const listing = listingsData.find(l => l.id === id);
    if (!listing) return;
    listing.status = status;
  };

  const savedUser = localStorage.getItem('apartment-hunt-user');
  if (!savedUser) {
    const name = prompt('Enter your name for collaboration (votes & notes):');
    if (name) localStorage.setItem('apartment-hunt-user', name.trim());
  }
});
