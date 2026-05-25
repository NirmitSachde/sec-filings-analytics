// ─────────────────────────────────────────────────────────────────────────
// Sample data : synthesized to be plausible. Real platform pulls live from
// SEC EDGAR; this static demo bundles representative records.
// ─────────────────────────────────────────────────────────────────────────

const SEC_DATA = {
  ticker_tape: [
    { sym: 'AAPL', price: 234.10, change: 1.42 },
    { sym: 'NVDA', price: 138.07, change: 3.21 },
    { sym: 'MSFT', price: 420.55, change: -0.34 },
    { sym: 'GOOGL', price: 174.20, change: 0.89 },
    { sym: 'BRK.A', price: 712340, change: 0.18 },
    { sym: 'TSLA', price: 358.91, change: -2.14 },
    { sym: 'META', price: 580.34, change: 1.78 },
    { sym: 'JPM', price: 248.55, change: 0.42 },
    { sym: 'V', price: 312.10, change: -0.51 },
    { sym: 'XOM', price: 119.88, change: 1.05 },
    { sym: 'WMT', price: 92.13, change: 0.31 },
    { sym: 'PLTR', price: 87.44, change: 5.32 },
    { sym: 'SNOW', price: 174.66, change: -1.88 },
    { sym: 'MRNA', price: 38.92, change: -3.45 },
    { sym: 'NFLX', price: 925.40, change: 1.20 },
    { sym: 'AMD', price: 142.87, change: 2.91 },
    { sym: 'CRM', price: 348.21, change: 0.76 },
    { sym: 'CVX', price: 165.40, change: 0.94 },
    { sym: 'OXY', price: 49.22, change: -0.85 },
    { sym: 'BAC', price: 47.18, change: 0.62 },
  ],

  // Cluster buying : companies with 3+ insiders buying open-market shares
  cluster_signals: [
    { ticker: 'PLTR', name: 'Palantir Technologies', insiders: 7, total_value: 18420000, avg_price: 87.44, latest_filer: 'Karp, Alexander C.', days_ago: 2 },
    { ticker: 'SNOW', name: 'Snowflake Inc.', insiders: 6, total_buy: 12830000, total_value: 12830000, avg_price: 174.66, latest_filer: 'Slootman, Frank', days_ago: 4 },
    { ticker: 'CRWD', name: 'CrowdStrike Holdings', insiders: 5, total_value: 9280000, avg_price: 358.40, latest_filer: 'Kurtz, George R.', days_ago: 5 },
    { ticker: 'NET', name: 'Cloudflare Inc.', insiders: 5, total_value: 7140000, avg_price: 119.20, latest_filer: 'Prince, Matthew', days_ago: 7 },
    { ticker: 'MDB', name: 'MongoDB Inc.', insiders: 4, total_value: 5910000, avg_price: 268.34, latest_filer: 'Ittycheria, Dev', days_ago: 9 },
    { ticker: 'OXY', name: 'Occidental Petroleum', insiders: 4, total_value: 4820000, avg_price: 49.22, latest_filer: 'Hollub, Vicki', days_ago: 11 },
    { ticker: 'DDOG', name: 'Datadog Inc.', insiders: 4, total_value: 4100000, avg_price: 142.10, latest_filer: 'Pomel, Olivier', days_ago: 12 },
    { ticker: 'NET', name: 'NET Power Inc.', insiders: 3, total_value: 3450000, avg_price: 8.40, latest_filer: 'Bowe, Daniel', days_ago: 14 },
    { ticker: 'ZS', name: 'Zscaler Inc.', insiders: 3, total_value: 2890000, avg_price: 198.20, latest_filer: 'Chaudhry, Jay', days_ago: 18 },
    { ticker: 'BILL', name: 'Bill Holdings', insiders: 3, total_value: 2240000, avg_price: 78.91, latest_filer: 'Lacerte, Rene', days_ago: 21 },
    { ticker: 'TWLO', name: 'Twilio Inc.', insiders: 3, total_value: 1980000, avg_price: 108.50, latest_filer: 'Aghdaei, Khozema', days_ago: 24 },
    { ticker: 'OKTA', name: 'Okta Inc.', insiders: 3, total_value: 1450000, avg_price: 84.20, latest_filer: 'McKinnon, Todd', days_ago: 28 },
    { ticker: 'U', name: 'Unity Software', insiders: 3, total_value: 1280000, avg_price: 22.10, latest_filer: 'Whitehurst, James', days_ago: 33 },
    { ticker: 'PATH', name: 'UiPath Inc.', insiders: 3, total_value: 980000, avg_price: 13.45, latest_filer: 'Dines, Daniel', days_ago: 41 },
    { ticker: 'FROG', name: 'JFrog Ltd.', insiders: 3, total_value: 720000, avg_price: 38.20, latest_filer: 'Ben Haim, Shlomi', days_ago: 47 },
    { ticker: 'ESTC', name: 'Elastic N.V.', insiders: 3, total_value: 580000, avg_price: 95.70, latest_filer: 'Banon, Shay', days_ago: 52 },
  ],

  // 13F managers + their portfolios
  managers: [
    {
      cik: 1067983,
      name: 'Berkshire Hathaway Inc.',
      period: '2026 Q1',
      aum: 312000000000,
      n_positions: 38,
      portfolio: [
        { ticker: 'AAPL', name: 'Apple Inc.', value: 91300000000, pct: 29.3 },
        { ticker: 'AXP', name: 'American Express', value: 41200000000, pct: 13.2 },
        { ticker: 'BAC', name: 'Bank of America', value: 34800000000, pct: 11.2 },
        { ticker: 'KO', name: 'Coca-Cola Co', value: 27800000000, pct: 8.9 },
        { ticker: 'CVX', name: 'Chevron Corp', value: 18900000000, pct: 6.1 },
        { ticker: 'OXY', name: 'Occidental Petroleum', value: 16400000000, pct: 5.3 },
        { ticker: 'KHC', name: 'Kraft Heinz Co', value: 11200000000, pct: 3.6 },
        { ticker: 'MCO', name: 'Moody\'s Corp', value: 11000000000, pct: 3.5 },
      ],
      changes: [
        { ticker: 'SIRI', name: 'Sirius XM Holdings', type: 'NEW', value_delta: 1200000000 },
        { ticker: 'CB', name: 'Chubb Limited', type: 'INCREASED', value_delta: 580000000 },
        { ticker: 'PARA', name: 'Paramount Global', type: 'EXITED', value_delta: -420000000 },
        { ticker: 'HPQ', name: 'HP Inc.', type: 'REDUCED', value_delta: -380000000 },
        { ticker: 'FND', name: 'Floor & Decor', type: 'INCREASED', value_delta: 240000000 },
        { ticker: 'CHTR', name: 'Charter Communications', type: 'REDUCED', value_delta: -190000000 },
        { ticker: 'LSXMK', name: 'Liberty SiriusXM', type: 'EXITED', value_delta: -120000000 },
        { ticker: 'NVR', name: 'NVR Inc.', type: 'NEW', value_delta: 70000000 },
      ],
    },
    {
      cik: 102909,
      name: 'Vanguard Group Inc.',
      period: '2026 Q1',
      aum: 5410000000000,
      n_positions: 4218,
      portfolio: [
        { ticker: 'AAPL', name: 'Apple Inc.', value: 412000000000, pct: 7.6 },
        { ticker: 'MSFT', name: 'Microsoft Corp', value: 398000000000, pct: 7.4 },
        { ticker: 'NVDA', name: 'NVIDIA Corp', value: 312000000000, pct: 5.8 },
        { ticker: 'GOOGL', name: 'Alphabet Class A', value: 218000000000, pct: 4.0 },
        { ticker: 'AMZN', name: 'Amazon.com Inc.', value: 198000000000, pct: 3.7 },
        { ticker: 'META', name: 'Meta Platforms', value: 156000000000, pct: 2.9 },
        { ticker: 'BRK.B', name: 'Berkshire Hathaway B', value: 134000000000, pct: 2.5 },
        { ticker: 'LLY', name: 'Eli Lilly & Co', value: 121000000000, pct: 2.2 },
      ],
      changes: [
        { ticker: 'NVDA', name: 'NVIDIA Corp', type: 'INCREASED', value_delta: 18000000000 },
        { ticker: 'TSLA', name: 'Tesla Inc.', type: 'REDUCED', value_delta: -4200000000 },
        { ticker: 'AMD', name: 'Advanced Micro Devices', type: 'INCREASED', value_delta: 3800000000 },
        { ticker: 'NFLX', name: 'Netflix Inc.', type: 'INCREASED', value_delta: 2100000000 },
        { ticker: 'INTC', name: 'Intel Corp', type: 'REDUCED', value_delta: -1900000000 },
      ],
    },
    {
      cik: 1037389,
      name: 'Renaissance Technologies LLC',
      period: '2026 Q1',
      aum: 89200000000,
      n_positions: 1247,
      portfolio: [
        { ticker: 'NVDA', name: 'NVIDIA Corp', value: 3200000000, pct: 3.6 },
        { ticker: 'META', name: 'Meta Platforms', value: 2800000000, pct: 3.1 },
        { ticker: 'PLTR', name: 'Palantir Technologies', value: 2100000000, pct: 2.4 },
        { ticker: 'AAPL', name: 'Apple Inc.', value: 1900000000, pct: 2.1 },
        { ticker: 'NFLX', name: 'Netflix Inc.', value: 1700000000, pct: 1.9 },
        { ticker: 'AMZN', name: 'Amazon.com Inc.', value: 1600000000, pct: 1.8 },
        { ticker: 'COST', name: 'Costco Wholesale', value: 1400000000, pct: 1.6 },
        { ticker: 'LLY', name: 'Eli Lilly & Co', value: 1300000000, pct: 1.5 },
      ],
      changes: [
        { ticker: 'PLTR', name: 'Palantir Technologies', type: 'INCREASED', value_delta: 890000000 },
        { ticker: 'TSLA', name: 'Tesla Inc.', type: 'NEW', value_delta: 720000000 },
        { ticker: 'SMCI', name: 'Super Micro Computer', type: 'EXITED', value_delta: -510000000 },
        { ticker: 'COIN', name: 'Coinbase Global', type: 'INCREASED', value_delta: 380000000 },
      ],
    },
    {
      cik: 1336528,
      name: 'Pershing Square Capital',
      period: '2026 Q1',
      aum: 14200000000,
      n_positions: 12,
      portfolio: [
        { ticker: 'CMG', name: 'Chipotle Mexican Grill', value: 2400000000, pct: 16.9 },
        { ticker: 'QSR', name: 'Restaurant Brands Intl', value: 1800000000, pct: 12.7 },
        { ticker: 'HLT', name: 'Hilton Worldwide', value: 1700000000, pct: 12.0 },
        { ticker: 'HHH', name: 'Howard Hughes Holdings', value: 1500000000, pct: 10.6 },
        { ticker: 'GOOGL', name: 'Alphabet Class A', value: 1300000000, pct: 9.2 },
        { ticker: 'NKE', name: 'Nike Inc.', value: 1200000000, pct: 8.5 },
      ],
      changes: [
        { ticker: 'NKE', name: 'Nike Inc.', type: 'NEW', value_delta: 1200000000 },
        { ticker: 'CP', name: 'Canadian Pacific Kansas', type: 'INCREASED', value_delta: 340000000 },
      ],
    },
    {
      cik: 1418814,
      name: 'Citadel Advisors LLC',
      period: '2026 Q1',
      aum: 542000000000,
      n_positions: 8412,
      portfolio: [
        { ticker: 'SPY', name: 'SPDR S&P 500 ETF', value: 12400000000, pct: 2.3 },
        { ticker: 'NVDA', name: 'NVIDIA Corp', value: 9800000000, pct: 1.8 },
        { ticker: 'AAPL', name: 'Apple Inc.', value: 8200000000, pct: 1.5 },
        { ticker: 'MSFT', name: 'Microsoft Corp', value: 7900000000, pct: 1.5 },
        { ticker: 'QQQ', name: 'Invesco QQQ Trust', value: 7200000000, pct: 1.3 },
        { ticker: 'TSLA', name: 'Tesla Inc.', value: 5400000000, pct: 1.0 },
      ],
      changes: [
        { ticker: 'NVDA', name: 'NVIDIA Corp', type: 'INCREASED', value_delta: 2100000000 },
        { ticker: 'AMD', name: 'Advanced Micro Devices', type: 'INCREASED', value_delta: 1800000000 },
        { ticker: 'INTC', name: 'Intel Corp', type: 'EXITED', value_delta: -890000000 },
      ],
    },
    {
      cik: 1709323,
      name: 'Scion Asset Management',
      period: '2026 Q1',
      aum: 198000000,
      n_positions: 9,
      portfolio: [
        { ticker: 'BABA', name: 'Alibaba Group', value: 42000000, pct: 21.2 },
        { ticker: 'BIDU', name: 'Baidu Inc.', value: 28000000, pct: 14.1 },
        { ticker: 'JD', name: 'JD.com Inc.', value: 26000000, pct: 13.1 },
        { ticker: 'OSCR', name: 'Oscar Health', value: 14000000, pct: 7.1 },
      ],
      changes: [
        { ticker: 'BABA', name: 'Alibaba Group', type: 'NEW', value_delta: 42000000 },
        { ticker: 'BIDU', name: 'Baidu Inc.', type: 'NEW', value_delta: 28000000 },
      ],
    },
  ],

  // Ownership concentration : HHI distribution
  hhi_distribution: {
    buckets: ['<500', '500-1000', '1000-1500', '1500-2500', '2500+'],
    counts: [142, 287, 318, 184, 69],
  },

  most_concentrated: [
    { ticker: 'TSLA', name: 'Tesla Inc.', top10_pct: 94.2, hhi: 2840 },
    { ticker: 'GME', name: 'GameStop Corp', top10_pct: 91.8, hhi: 2710 },
    { ticker: 'AMC', name: 'AMC Entertainment', top10_pct: 89.4, hhi: 2580 },
    { ticker: 'BBBY', name: 'Bed Bath & Beyond', top10_pct: 88.2, hhi: 2450 },
    { ticker: 'NVDA', name: 'NVIDIA Corp', top10_pct: 86.7, hhi: 2310 },
    { ticker: 'PLTR', name: 'Palantir Technologies', top10_pct: 85.9, hhi: 2280 },
    { ticker: 'SMCI', name: 'Super Micro Computer', top10_pct: 84.1, hhi: 2190 },
    { ticker: 'COIN', name: 'Coinbase Global', top10_pct: 82.4, hhi: 2050 },
    { ticker: 'RIVN', name: 'Rivian Automotive', top10_pct: 80.8, hhi: 1980 },
  ],

  // Insider activity : buys vs sells over time
  activity_timeline: {
    months: ['2025-06', '2025-07', '2025-08', '2025-09', '2025-10', '2025-11', '2025-12', '2026-01', '2026-02', '2026-03', '2026-04', '2026-05'],
    buys:  [ 412, 380, 525, 610, 484, 372, 290, 348, 540, 720, 612, 580],
    sells: [1820, 2140, 1980, 1640, 1810, 2350, 2840, 2100, 1620, 1180, 1340, 1490],
  },

  // Risk factor year-over-year diffs (LLM-generated)
  risk_diffs: [
    {
      ticker: 'NVDA',
      company: 'NVIDIA Corp',
      year: 2026,
      new: 'New risk added around export-control compliance for advanced semiconductors to certain regions, including discussion of supply chain rerouting through allied jurisdictions.',
      dropped: 'Removed prior-year language about pandemic-related manufacturing disruption and component shortages.',
      sentiment: 'more cautionary',
    },
    {
      ticker: 'TSLA',
      company: 'Tesla Inc.',
      year: 2026,
      new: 'Expanded language around CEO key-person dependence, board governance disputes, and exposure to litigation outcomes from executive compensation packages.',
      dropped: 'Removed discussion of Model 3/Y production ramp risks now that volume manufacturing is mature.',
      sentiment: 'more cautionary',
    },
    {
      ticker: 'MRNA',
      company: 'Moderna Inc.',
      year: 2026,
      new: 'Added risk factor around uncertainty in long-term demand for COVID-19 boosters and dependence on respiratory franchise revenue.',
      dropped: 'Removed material discussion of pandemic-era revenue concentration and government procurement contract risk.',
      sentiment: 'more cautionary',
    },
    {
      ticker: 'META',
      company: 'Meta Platforms',
      year: 2026,
      new: 'New extensive section on AI training data licensing obligations, copyright litigation exposure, and EU AI Act compliance costs.',
      dropped: 'Reduced prior emphasis on iOS ATT-related ad targeting disruption now that mitigations are in place.',
      sentiment: 'more cautionary',
    },
    {
      ticker: 'BA',
      company: 'Boeing Co',
      year: 2026,
      new: 'Added significant new disclosure around FAA production cap restrictions, ongoing DOJ deferred-prosecution-agreement matters, and 737 MAX quality remediation costs.',
      dropped: 'Reduced previously-prominent language about supply-chain inflation pressures.',
      sentiment: 'more cautionary',
    },
    {
      ticker: 'AAPL',
      company: 'Apple Inc.',
      year: 2026,
      new: 'Added forward-looking section on antitrust enforcement in services revenue (App Store) across DOJ and EU DMA matters.',
      dropped: 'Removed prior mention of pandemic-era retail closures and supply chain Asia-region concentration.',
      sentiment: 'similar',
    },
  ],

  // Backtest: cluster-buy signals from 2014-01 to 2025-12, joined to
  // forward 180-day adjusted-close returns from Stooq, benchmarked against
  // SPY over the same window. Sample stats here are realistic for an
  // academically-published cluster-buy strategy (Cohen, Malloy, Pomorski
  // 2012 reported ~9.3% annualized excess returns; Lakonishok-Lee shows
  // strong opportunistic-trader effects).
  backtest: {
    horizon_days: 180,
    period: '2014-01-01 to 2025-12-31',
    benchmark: 'SPY (total return)',

    overall: {
      n_signals: 2147,
      avg_stock_return_180d: 0.1042,    // +10.42%
      avg_bench_return_180d: 0.0586,    // +5.86%
      avg_excess_return_180d: 0.0456,   // +4.56% alpha
      median_excess_return_180d: 0.0312,
      hit_rate_30d: 0.541,
      hit_rate_90d: 0.567,
      hit_rate_180d: 0.598,             // 59.8% beat SPY at 180d
      stddev_excess_180d: 0.2184,
      info_ratio_180d: 0.209,
    },

    by_sector: [
      { sector: 'Energy',                 n: 187, hit_rate: 0.668, avg_excess: 0.0921, avg_stock: 0.1380, avg_bench: 0.0459 },
      { sector: 'Financials',             n: 312, hit_rate: 0.641, avg_excess: 0.0732, avg_stock: 0.1218, avg_bench: 0.0486 },
      { sector: 'Materials',              n: 124, hit_rate: 0.621, avg_excess: 0.0658, avg_stock: 0.1118, avg_bench: 0.0460 },
      { sector: 'Industrials',            n: 248, hit_rate: 0.605, avg_excess: 0.0541, avg_stock: 0.1090, avg_bench: 0.0549 },
      { sector: 'Consumer Discretionary', n: 219, hit_rate: 0.598, avg_excess: 0.0498, avg_stock: 0.1112, avg_bench: 0.0614 },
      { sector: 'Real Estate',            n:  98, hit_rate: 0.582, avg_excess: 0.0420, avg_stock: 0.0894, avg_bench: 0.0474 },
      { sector: 'Information Technology', n: 401, hit_rate: 0.572, avg_excess: 0.0381, avg_stock: 0.1156, avg_bench: 0.0775 },
      { sector: 'Health Care',            n: 286, hit_rate: 0.566, avg_excess: 0.0298, avg_stock: 0.0884, avg_bench: 0.0586 },
      { sector: 'Consumer Staples',       n: 142, hit_rate: 0.549, avg_excess: 0.0240, avg_stock: 0.0801, avg_bench: 0.0561 },
      { sector: 'Communication Services', n:  87, hit_rate: 0.540, avg_excess: 0.0204, avg_stock: 0.0892, avg_bench: 0.0688 },
      { sector: 'Utilities',              n:  43, hit_rate: 0.512, avg_excess: 0.0078, avg_stock: 0.0608, avg_bench: 0.0530 },
    ],

    // Histogram of excess returns at 180d (bucket midpoint -> count).
    distribution_180d: [
      { bucket: '<-40%',  count:  41 },
      { bucket: '-40--30%', count:  72 },
      { bucket: '-30--20%', count: 118 },
      { bucket: '-20--10%', count: 198 },
      { bucket: '-10-0%',   count: 433 },
      { bucket:  '0-10%',   count: 521 },
      { bucket: '10-20%',   count: 348 },
      { bucket: '20-30%',   count: 201 },
      { bucket: '30-40%',   count: 104 },
      { bucket: '40-60%',   count:  78 },
      { bucket: '>60%',     count:  33 },
    ],

    // Notable winners + losers for the case-studies strip.
    case_studies: [
      { ticker: 'OXY',  name: 'Occidental Petroleum', signal_date: '2020-04-15', stock_return: 1.84, bench_return: 0.27, excess: 1.57 },
      { ticker: 'NVDA', name: 'NVIDIA Corp',          signal_date: '2022-11-08', stock_return: 1.22, bench_return: 0.18, excess: 1.04 },
      { ticker: 'PLTR', name: 'Palantir Technologies',signal_date: '2023-05-22', stock_return: 0.94, bench_return: 0.11, excess: 0.83 },
      { ticker: 'CCL',  name: 'Carnival Corp',        signal_date: '2020-11-03', stock_return: 0.71, bench_return: 0.21, excess: 0.50 },
      { ticker: 'PTON', name: 'Peloton Interactive',  signal_date: '2022-02-11', stock_return: -0.42, bench_return: -0.06, excess: -0.36 },
      { ticker: 'BBBY', name: 'Bed Bath & Beyond',    signal_date: '2022-08-17', stock_return: -0.78, bench_return: 0.04, excess: -0.82 },
    ],
  },
};
