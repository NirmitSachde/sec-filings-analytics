// ─────────────────────────────────────────────────────────────────────────
// SEC Filings Analytics — Dashboard
// ─────────────────────────────────────────────────────────────────────────

const fmtCurrency = (n) => {
  if (n >= 1e12) return '$' + (n / 1e12).toFixed(2) + 'T';
  if (n >= 1e9) return '$' + (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
  if (n >= 1e3) return '$' + (n / 1e3).toFixed(1) + 'K';
  return '$' + n.toFixed(2);
};

const fmtNumber = (n) => {
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return n.toString();
};

const fmtShares = (n) => new Intl.NumberFormat('en-US').format(Math.round(n));

// ───────────── Market time ─────────────
function updateMarketTime() {
  const now = new Date();
  const day = now.toLocaleDateString('en-US', { weekday: 'short' });
  const time = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
  document.getElementById('market-time').textContent = `${day} ${time} ET`;
}
updateMarketTime();
setInterval(updateMarketTime, 30000);

// ───────────── Ticker tape ─────────────
function renderTickerTape() {
  const track = document.getElementById('ticker-track');
  const items = [...SEC_DATA.ticker_tape, ...SEC_DATA.ticker_tape, ...SEC_DATA.ticker_tape];
  track.innerHTML = items.map(t => {
    const sign = t.change >= 0 ? '+' : '';
    const dir = t.change >= 0 ? 'up' : 'down';
    const price = t.price >= 1000 ? t.price.toLocaleString('en-US', { maximumFractionDigits: 2 }) : t.price.toFixed(2);
    return `
      <div class="ticker-item">
        <span class="ticker-symbol">${t.sym}</span>
        <span class="ticker-price">${price}</span>
        <span class="ticker-change ${dir}">${sign}${t.change.toFixed(2)}%</span>
      </div>
    `;
  }).join('');
}
renderTickerTape();

// ───────────── Animated counters ─────────────
function animateCounter(el) {
  const target = parseFloat(el.dataset.target);
  const suffix = el.dataset.suffix || '';
  const duration = 1800;
  const start = performance.now();

  function tick(now) {
    const t = Math.min(1, (now - start) / duration);
    const ease = 1 - Math.pow(1 - t, 3);
    const value = target * ease;

    let text;
    if (target % 1 !== 0) {
      text = value.toFixed(1);
    } else if (target >= 1e6) {
      text = (value / 1e6).toFixed(2) + 'M';
    } else if (target >= 1e3) {
      text = Math.round(value).toLocaleString('en-US');
    } else {
      text = Math.round(value).toString();
    }

    el.textContent = text + suffix;
    if (t < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

// ───────────── Cluster Buying Screener ─────────────
function renderScreener() {
  const minInsiders = parseInt(document.getElementById('filter-insiders').value);
  const minValue = parseInt(document.getElementById('filter-value').value);
  const window = parseInt(document.getElementById('filter-window').value);

  const filtered = SEC_DATA.cluster_signals.filter(s =>
    s.insiders >= minInsiders && s.total_value >= minValue && s.days_ago <= window
  );

  document.getElementById('result-count').textContent = filtered.length;
  document.getElementById('screener-body').innerHTML = filtered.map(s => `
    <div class="screener-row">
      <div class="ticker">${s.ticker}</div>
      <div class="company">${s.name}</div>
      <div class="insiders num"><span class="insider-badge">${s.insiders}</span></div>
      <div class="value-big num">${fmtCurrency(s.total_value)}</div>
      <div class="num">$${s.avg_price.toFixed(2)}</div>
      <div class="filer-name">${s.latest_filer}</div>
      <div class="days num">${s.days_ago}d</div>
    </div>
  `).join('');
}

document.getElementById('filter-insiders').addEventListener('change', renderScreener);
document.getElementById('filter-value').addEventListener('change', renderScreener);
document.getElementById('filter-window').addEventListener('change', renderScreener);
renderScreener();

// ───────────── Hedge Fund Tracker ─────────────
let activeManagerCik = SEC_DATA.managers[0].cik;
let activeTab = 'portfolio';

function renderManagersList() {
  document.getElementById('funds-list-body').innerHTML = SEC_DATA.managers.map(m => `
    <div class="fund-item ${m.cik === activeManagerCik ? 'active' : ''}" data-cik="${m.cik}">
      <div class="fund-item-name">${m.name}</div>
      <div class="fund-item-meta">CIK ${m.cik} · ${m.n_positions} positions</div>
      <div class="fund-item-aum">${fmtCurrency(m.aum)}</div>
    </div>
  `).join('');

  document.querySelectorAll('.fund-item').forEach(el => {
    el.addEventListener('click', () => {
      activeManagerCik = parseInt(el.dataset.cik);
      renderManagersList();
      renderManagerDetail();
    });
  });
}

function renderManagerDetail() {
  const m = SEC_DATA.managers.find(x => x.cik === activeManagerCik);
  if (!m) return;

  document.getElementById('fund-name').textContent = m.name;
  document.getElementById('fund-cik').textContent = `CIK ${m.cik}`;
  document.getElementById('fund-period').textContent = m.period;
  document.getElementById('fund-aum').textContent = fmtCurrency(m.aum);
  document.getElementById('fund-positions').textContent = m.n_positions.toLocaleString('en-US');

  // Treemap — single accent with opacity gradient by position weight
  const positions = m.portfolio.slice(0, 8);
  const maxPct = Math.max(...positions.map(p => p.pct));
  document.getElementById('treemap').innerHTML = positions.map((p) => {
    const barWidth = Math.max(15, (p.pct / maxPct) * 100);
    const opacity = Math.max(0.25, p.pct / maxPct);
    return `
      <div class="treemap-cell" style="--cell-bar-width: ${barWidth}%; --cell-opacity: ${opacity};">
        <div>
          <div class="tm-ticker">${p.ticker}</div>
          <div class="tm-name">${p.name}</div>
        </div>
        <div>
          <div class="tm-value">${fmtCurrency(p.value)}</div>
          <div class="tm-pct">${p.pct.toFixed(1)}% of portfolio</div>
        </div>
      </div>
    `;
  }).join('');

  // Changes
  document.getElementById('changes-list').innerHTML = m.changes.map(c => {
    const up = c.value_delta > 0;
    return `
      <div class="change-row ${c.type}">
        <div class="change-badge ${c.type}">${c.type.replace('_', ' ')}</div>
        <div>
          <div class="change-ticker">${c.ticker}</div>
          <div style="font-size: 12px; color: var(--text-secondary); margin-top: 2px;">${c.name}</div>
        </div>
        <div class="change-value ${up ? 'up' : 'down'}">${up ? '+' : ''}${fmtCurrency(c.value_delta)}</div>
        <div style="color: var(--text-muted); font-family: var(--font-mono); font-size: 11px;">Δ value</div>
      </div>
    `;
  }).join('');
}

document.querySelectorAll('.fund-tabs .tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.fund-tabs .tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    activeTab = tab.dataset.tab;
    document.getElementById('panel-portfolio').classList.toggle('hidden', activeTab !== 'portfolio');
    document.getElementById('panel-changes').classList.toggle('hidden', activeTab !== 'changes');
  });
});

renderManagersList();
renderManagerDetail();

// ───────────── Charts ─────────────
const chartGridColor = 'rgba(255, 255, 255, 0.04)';
const chartTickColor = '#5b6271';
const chartFont = { family: 'JetBrains Mono', size: 10.5 };
const ACCENT = '#c89240';
const ACCENT_DIM = '#7a5a28';
const BUY_COLOR = '#16a86b';
const SELL_COLOR = '#c2364a';
const TOOLTIP_BG = '#161a23';

Chart.defaults.color = chartTickColor;
Chart.defaults.font.family = 'JetBrains Mono';
Chart.defaults.borderColor = chartGridColor;

// HHI distribution
function renderHHIChart() {
  const ctx = document.getElementById('hhi-chart').getContext('2d');
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: SEC_DATA.hhi_distribution.buckets,
      datasets: [{
        label: 'Issuers',
        data: SEC_DATA.hhi_distribution.counts,
        backgroundColor: ACCENT,
        hoverBackgroundColor: '#d9a050',
        borderRadius: 1,
        barPercentage: 0.65,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: TOOLTIP_BG,
          borderColor: ACCENT_DIM,
          borderWidth: 1,
          padding: 10,
          titleFont: chartFont,
          bodyFont: chartFont,
          displayColors: false,
          callbacks: {
            title: (items) => `HHI ${items[0].label}`,
            label: (item) => `${item.parsed.y} issuers`,
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: chartFont, color: chartTickColor } },
        y: { grid: { color: chartGridColor, drawTicks: false }, ticks: { font: chartFont, color: chartTickColor, padding: 8 }, beginAtZero: true, border: { display: false } },
      },
    },
  });
}
renderHHIChart();

// Most concentrated list
function renderConcList() {
  document.getElementById('conc-list').innerHTML = SEC_DATA.most_concentrated.map(c => `
    <div class="conc-row">
      <div class="ticker">${c.ticker}</div>
      <div class="conc-bar-wrap">
        <div class="conc-bar">
          <div class="conc-bar-fill" style="width: ${c.top10_pct}%;"></div>
        </div>
      </div>
      <div class="conc-pct">${c.top10_pct.toFixed(1)}%</div>
    </div>
  `).join('');
}
renderConcList();

// Activity chart
function renderActivityChart() {
  const ctx = document.getElementById('activity-chart').getContext('2d');
  const months = SEC_DATA.activity_timeline.months;
  const buys = SEC_DATA.activity_timeline.buys;
  const sells = SEC_DATA.activity_timeline.sells;
  const ratio = buys.map((b, i) => (b / sells[i]).toFixed(2));

  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: months,
      datasets: [
        {
          type: 'bar',
          label: 'Buys ($M)',
          data: buys,
          backgroundColor: BUY_COLOR,
          borderRadius: 1,
          yAxisID: 'y',
          barPercentage: 0.7,
        },
        {
          type: 'bar',
          label: 'Sells ($M)',
          data: sells.map(v => -v),
          backgroundColor: SELL_COLOR,
          borderRadius: 1,
          yAxisID: 'y',
          barPercentage: 0.7,
        },
        {
          type: 'line',
          label: 'Buy/Sell Ratio',
          data: ratio,
          borderColor: ACCENT,
          backgroundColor: 'rgba(200, 146, 64, 0.06)',
          borderWidth: 1.5,
          tension: 0.25,
          pointBackgroundColor: ACCENT,
          pointBorderColor: ACCENT,
          pointRadius: 3,
          pointHoverRadius: 5,
          yAxisID: 'y1',
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: TOOLTIP_BG,
          borderColor: ACCENT_DIM,
          borderWidth: 1,
          padding: 10,
          titleFont: chartFont,
          bodyFont: chartFont,
          callbacks: {
            label: (ctx) => {
              if (ctx.dataset.label === 'Buy/Sell Ratio') return `Ratio: ${ctx.parsed.y}`;
              return `${ctx.dataset.label}: $${Math.abs(ctx.parsed.y)}M`;
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: chartFont, color: chartTickColor }, stacked: false, border: { color: chartGridColor } },
        y: {
          position: 'left',
          grid: { color: chartGridColor, drawTicks: false },
          ticks: {
            font: chartFont,
            color: chartTickColor,
            padding: 8,
            callback: (v) => '$' + Math.abs(v) + 'M',
          },
          border: { display: false },
        },
        y1: {
          position: 'right',
          grid: { display: false },
          ticks: { font: chartFont, color: ACCENT, padding: 8 },
          border: { display: false },
        },
      },
    },
  });
}
renderActivityChart();

// ───────────── Risk Diff Cards ─────────────
function renderDiffs() {
  document.getElementById('diff-grid').innerHTML = SEC_DATA.risk_diffs.map(d => {
    const sentClass = d.sentiment === 'more cautionary' ? 'cautionary'
                     : d.sentiment === 'more confident' ? 'confident' : 'similar';
    return `
      <div class="diff-card">
        <div class="diff-header">
          <div>
            <div class="diff-ticker">${d.ticker}</div>
            <div class="diff-company">${d.company}</div>
          </div>
          <div class="diff-year">10-K ${d.year - 1} / ${d.year}</div>
        </div>
        <div class="diff-section new">
          <span class="diff-section-label">NEW THIS YEAR</span>
          <div class="diff-section-text">${d.new}</div>
        </div>
        <div class="diff-section dropped">
          <span class="diff-section-label">DROPPED</span>
          <div class="diff-section-text">${d.dropped}</div>
        </div>
        <div class="diff-section sentiment">
          <span class="diff-section-label">SENTIMENT SHIFT</span>
          <div class="diff-sentiment ${sentClass}">${d.sentiment}</div>
        </div>
      </div>
    `;
  }).join('');
}
renderDiffs();

// ───────────── Scroll reveal + counter trigger ─────────────
const sections = document.querySelectorAll('.section, .hero');
const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('in-view');
      // Trigger counters in hero
      entry.target.querySelectorAll('.stat-num[data-target]').forEach(el => {
        if (!el.dataset.animated) {
          el.dataset.animated = 'true';
          animateCounter(el);
        }
      });
    }
  });
}, { threshold: 0.15 });

sections.forEach(s => observer.observe(s));

// Trigger hero stats immediately if visible on load
document.querySelectorAll('.hero .stat-num[data-target]').forEach(el => {
  el.dataset.animated = 'true';
  animateCounter(el);
});

// ───────────── Smooth scroll for nav links ─────────────
document.querySelectorAll('.topbar-nav a, .hero-cta a').forEach(a => {
  a.addEventListener('click', (e) => {
    const href = a.getAttribute('href');
    if (href.startsWith('#')) {
      e.preventDefault();
      const el = document.querySelector(href);
      if (el) window.scrollTo({ top: el.offsetTop - 80, behavior: 'smooth' });
    }
  });
});
