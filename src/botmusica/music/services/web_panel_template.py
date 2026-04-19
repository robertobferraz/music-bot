from __future__ import annotations


def build_web_panel_html() -> str:  # noqa: PLR0915
    return '''<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MusicBot \u00b7 Studio Panel</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg:     #080a0f; --bg1: #0e1118; --bg2: #14171f; --bg3: #1b1f2b;
      --bdr:    #242735; --bdr2: #2e3248;
      --txt:    #e8eaf0; --muted: #5a6080; --muted2: #8890b0;
      --amber:  #f59e0b; --amber2: #fcd34d;
      --ok:     #10b981; --warn: #f59e0b; --bad: #f43f5e;
      --sans:   "Manrope", system-ui, sans-serif;
      --mono:   "DM Mono", "Fira Code", monospace;
    }
    *{box-sizing:border-box;margin:0;padding:0}
    html{scroll-behavior:smooth}
    body{font-family:var(--sans);background:var(--bg);color:var(--txt);min-height:100vh;line-height:1.5}
    ::-webkit-scrollbar{width:5px;height:5px}
    ::-webkit-scrollbar-track{background:var(--bg1)}
    ::-webkit-scrollbar-thumb{background:var(--bdr2);border-radius:9px}

    .shell{display:grid;grid-template-rows:56px 1fr;min-height:100vh}

    /* topbar */
    .topbar{
      position:sticky;top:0;z-index:60;
      background:rgba(8,10,15,.93);backdrop-filter:blur(12px);
      border-bottom:1px solid var(--bdr);
      display:flex;align-items:center;padding:0 18px;gap:0;
    }
    .topbar-brand{display:flex;align-items:center;gap:10px;padding-right:18px;border-right:1px solid var(--bdr);flex-shrink:0}
    .brand-icon{width:32px;height:32px;border-radius:8px;display:grid;place-items:center;background:linear-gradient(135deg,#f59e0b22,#f59e0b44);border:1px solid #f59e0b55;font-size:16px}
    .brand-name{font-size:.85rem;font-weight:700;letter-spacing:.04em}
    .brand-sub{font-size:.65rem;color:var(--muted);letter-spacing:.06em;text-transform:uppercase}
    .topbar-nav{display:flex;align-items:center;gap:2px;padding:0 14px;flex:1}
    .nav-tab{display:flex;align-items:center;gap:6px;padding:6px 12px;border-radius:7px;font-size:.82rem;font-weight:500;color:var(--muted2);text-decoration:none;cursor:pointer;border:1px solid transparent;transition:all .15s}
    .nav-tab:hover{color:var(--txt);background:var(--bg2)}
    .nav-tab.active{color:var(--amber);background:#f59e0b12;border-color:#f59e0b22}
    .topbar-right{display:flex;align-items:center;gap:8px;padding-left:14px;border-left:1px solid var(--bdr);flex-shrink:0}
    .status-pill{display:flex;align-items:center;gap:6px;padding:5px 10px;border-radius:9px;background:var(--bg2);border:1px solid var(--bdr);font:.72rem var(--mono)}
    .s-dot{width:7px;height:7px;border-radius:50%;background:var(--warn);animation:pulse 2s ease infinite}
    .s-dot.ok{background:var(--ok)} .s-dot.bad{background:var(--bad);animation:none}
    @keyframes pulse{0%{box-shadow:0 0 0 0 #10b98166}70%{box-shadow:0 0 0 6px transparent}100%{box-shadow:0 0 0 0 transparent}}
    .role-badge{padding:3px 9px;border-radius:99px;font:700 .7rem var(--mono);letter-spacing:.04em;border:1px solid var(--bdr)}
    .role-badge.admin{color:#86efac;background:#10b98118;border-color:#10b98133}
    .role-badge.dj{color:#93c5fd;background:#3b82f618;border-color:#3b82f633}
    .role-badge.viewer{color:var(--muted2)}
    .token-wrap input{padding:5px 9px;border-radius:7px;background:var(--bg2);border:1px solid var(--bdr);color:var(--txt);font:.75rem var(--mono);width:200px}
    .token-wrap input:focus{outline:none;border-color:var(--amber)}
    .auth-btn{padding:6px 12px;border-radius:8px;font:600 .75rem var(--sans);cursor:pointer;border:1px solid;transition:all .15s}
    .auth-btn.login{color:#5865F2;border-color:#5865F233;background:#5865F212}
    .auth-btn.login:hover{background:#5865F224}
    .auth-btn.logout{color:var(--muted2);border-color:var(--bdr);background:transparent}
    .auth-btn.logout:hover{color:var(--bad);border-color:var(--bad)}

    /* content */
    .content{padding:16px 18px 28px;max-width:1720px;margin:0 auto;display:flex;flex-direction:column;gap:12px}

    /* metrics */
    .metrics-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px}
    .metric-card{background:var(--bg1);border:1px solid var(--bdr);border-radius:10px;padding:12px 14px}
    .mk{font:.68rem var(--mono);color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
    .mv{font:700 1.1rem var(--mono);margin-top:4px}
    .mv.amber{color:var(--amber)} .mv.ok{color:var(--ok)} .mv.bad{color:var(--bad)} .mv.sm{font-size:.82rem}

    /* workspace */
    .workspace{display:grid;grid-template-columns:240px 1fr 300px;gap:12px}
    .panel{background:var(--bg1);border:1px solid var(--bdr);border-radius:12px;overflow:hidden;display:flex;flex-direction:column}
    .panel-head{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;border-bottom:1px solid var(--bdr);flex-shrink:0}
    .panel-title{font:600 .78rem var(--mono);text-transform:uppercase;letter-spacing:.08em;color:var(--muted2)}
    .panel-body{padding:12px;overflow:auto;flex:1}

    /* guild list */
    .guild-list{display:flex;flex-direction:column;gap:6px}
    .guild-item{padding:9px 10px;border-radius:8px;background:var(--bg2);border:1px solid transparent;cursor:pointer;transition:all .15s}
    .guild-item:hover{border-color:var(--bdr2)}
    .guild-item.active{border-color:var(--amber);background:#f59e0b0d}
    .gi-name{font:600 .83rem var(--sans)}
    .gi-meta{font:.7rem var(--mono);color:var(--muted);margin-top:2px}

    /* player */
    .player-top{display:flex;align-items:center;gap:12px;margin-bottom:10px}
    .guild-avatar-img{width:44px;height:44px;border-radius:10px;border:1px solid var(--bdr2);object-fit:cover;background:var(--bg3);flex-shrink:0}
    .player-track{font:700 1rem var(--sans);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .player-sub{font:.75rem var(--mono);color:var(--muted2);margin-top:2px}
    .progress-bar{height:4px;background:var(--bg3);border-radius:99px;overflow:hidden;margin-bottom:5px}
    .progress-fill{height:100%;width:0%;border-radius:99px;background:linear-gradient(90deg,var(--amber),var(--amber2));transition:width .4s ease}
    .progress-time{font:.72rem var(--mono);color:var(--muted)}
    .vu-wrap{display:flex;align-items:flex-end;gap:3px;height:24px;margin:8px 0 10px}
    .vu-bar{width:4px;border-radius:2px;opacity:.2;background:linear-gradient(180deg,var(--amber2),var(--amber),var(--ok))}
    .vu-wrap.playing .vu-bar{opacity:1;animation:vu 1.2s ease-in-out infinite}
    .vu-wrap.playing .vu-bar:nth-child(2n){animation-duration:.95s}
    .vu-wrap.playing .vu-bar:nth-child(3n){animation-duration:1.5s}
    .vu-wrap.playing .vu-bar:nth-child(5n){animation-duration:.78s}
    @keyframes vu{0%,100%{transform:scaleY(.3)}50%{transform:scaleY(1)}}
    .state-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:10px}
    .state-cell{background:var(--bg2);border:1px solid var(--bdr);border-radius:8px;padding:7px 9px}
    .settings-bar{font:.72rem var(--mono);color:var(--muted2);background:var(--bg2);border:1px solid var(--bdr);border-radius:7px;padding:6px 10px;margin-bottom:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .controls{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:10px}

    /* queue */
    .queue-list{display:flex;flex-direction:column;gap:4px}
    .queue-item{padding:6px 9px;border-radius:7px;background:var(--bg2);font:.78rem var(--sans);display:flex;align-items:baseline;gap:8px;border:1px solid transparent}
    .queue-num{font:.68rem var(--mono);color:var(--muted);flex-shrink:0;width:18px}

    /* forms */
    .forms-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
    .form-card{background:var(--bg1);border:1px solid var(--bdr);border-radius:12px;padding:14px}
    .form-title{font:700 .72rem var(--mono);text-transform:uppercase;letter-spacing:.1em;color:var(--amber);margin-bottom:12px;display:flex;align-items:center;gap:8px}
    .form-title::after{content:"";flex:1;height:1px;background:linear-gradient(90deg,var(--bdr),transparent)}
    .field{margin-bottom:8px}
    .field label{display:block;font:500 .72rem var(--mono);color:var(--muted2);margin-bottom:4px}
    .field input,.field select{width:100%;padding:7px 9px;border-radius:7px;background:var(--bg2);border:1px solid var(--bdr);color:var(--txt);font:.78rem var(--mono);transition:border-color .15s}
    .field input:focus,.field select:focus{outline:none;border-color:var(--amber)}
    .field-row{display:grid;grid-template-columns:1fr 1fr;gap:6px}

    /* buttons */
    .btn{appearance:none;padding:7px 12px;border-radius:8px;font:600 .78rem var(--sans);cursor:pointer;border:1px solid var(--bdr);background:var(--bg2);color:var(--txt);transition:all .15s;white-space:nowrap}
    .btn:hover{border-color:var(--amber);color:var(--amber)}
    .btn:disabled{opacity:.35;cursor:not-allowed;pointer-events:none}
    .btn.primary{background:#f59e0b18;border-color:var(--amber);color:var(--amber)}
    .btn.primary:hover{background:#f59e0b28}
    .btn.danger{border-color:#f43f5e44;color:var(--bad)}
    .btn.danger:hover{background:#f43f5e12;border-color:var(--bad)}
    .btn.warn-btn{border-color:#f59e0b44;color:var(--warn)}
    .btn.warn-btn:hover{background:#f59e0b12}
    .btn.sm{padding:5px 9px;font-size:.72rem}
    .btn.full{width:100%;display:block;text-align:center;margin-top:6px}

    /* misc */
    .search-input{width:100%;padding:7px 10px;border-radius:8px;background:var(--bg2);border:1px solid var(--bdr);color:var(--txt);font:.78rem var(--mono);margin-bottom:8px}
    .search-input:focus{outline:none;border-color:var(--amber)}
    .guild-select-mobile{width:100%;padding:7px 9px;border-radius:7px;background:var(--bg2);border:1px solid var(--bdr);color:var(--txt);font:.78rem var(--mono);margin-bottom:10px;display:none}
    .event-log{background:var(--bg1);border:1px solid var(--bdr);border-radius:10px;padding:11px 14px;font:.76rem var(--mono);color:var(--muted2);min-height:42px}
    .log-time{color:var(--muted)} .log-ok{color:var(--ok)} .log-bad{color:var(--bad)}
    .sep{height:1px;background:var(--bdr);margin:10px 0}

    @media(max-width:1280px){.workspace{grid-template-columns:220px 1fr}.workspace>:last-child{grid-column:1/-1}}
    @media(max-width:900px){.workspace{grid-template-columns:1fr}.workspace>:first-child{display:none}.guild-select-mobile{display:block}.forms-grid{grid-template-columns:1fr}.metrics-grid{grid-template-columns:repeat(3,1fr)}.topbar-nav{display:none}}
    @media(max-width:560px){.metrics-grid{grid-template-columns:repeat(2,1fr)}.controls{grid-template-columns:repeat(2,1fr)}.state-grid{grid-template-columns:1fr 1fr}.topbar-right .token-wrap{display:none}}
  </style>
</head>
<body>
<div class="shell">

  <nav class="topbar">
    <div class="topbar-brand">
      <div class="brand-icon">\U0001f39a</div>
      <div><div class="brand-name">Studio Panel</div><div class="brand-sub">MusicBot</div></div>
    </div>
    <div class="topbar-nav">
      <a class="nav-tab active" href="#metrics">\U0001f4ca M\u00e9tricas</a>
      <a class="nav-tab" href="#workspace">\U0001f39b Player</a>
      <a class="nav-tab" href="#forms">\u2699\ufe0f Config</a>
      <a class="nav-tab" href="#event-log">\U0001f5d2 Log</a>
    </div>
    <div class="topbar-right">
      <div class="status-pill"><span id="s-dot" class="s-dot"></span><span id="s-text" style="font-size:.72rem">Conectando\u2026</span></div>
      <span id="role-badge" class="role-badge viewer">viewer</span>
      <span id="auth-source" style="font:.7rem var(--mono);color:var(--muted)">auth: \u2014</span>
      <button id="login-btn"  class="auth-btn login"  style="display:none">Login Discord</button>
      <button id="logout-btn" class="auth-btn logout" style="display:none">Sair</button>
      <div class="token-wrap"><input id="admin-token" type="password" placeholder="X-Admin-Token (fallback)"></div>
    </div>
  </nav>

  <main class="content">

    <section id="metrics" class="metrics-grid">
      <div class="metric-card"><div class="mk">Bot</div><div id="m-bot" class="mv sm">\u2014</div></div>
      <div class="metric-card"><div class="mk">Servidores</div><div id="m-guilds" class="mv">0</div></div>
      <div class="metric-card"><div class="mk">Comandos</div><div id="m-calls" class="mv">0</div></div>
      <div class="metric-card"><div class="mk">Erros</div><div id="m-errors" class="mv bad">0</div></div>
      <div class="metric-card"><div class="mk">Lat\u00eancia avg</div><div id="m-latency" class="mv amber">0.0 ms</div></div>
      <div class="metric-card"><div class="mk">Uptime</div><div id="m-uptime" class="mv ok">0s</div></div>
      <div class="metric-card"><div class="mk">Backend</div><div id="m-backend" class="mv sm">\u2014</div></div>
      <div class="metric-card"><div class="mk">Play p50</div><div id="m-p50-play" class="mv">0.0</div></div>
      <div class="metric-card"><div class="mk">Play p95/p99</div><div class="mv sm"><span id="m-p95-play">0</span>/<span id="m-p99-play">0</span></div></div>
      <div class="metric-card"><div class="mk">Search p50</div><div id="m-p50-search" class="mv">0.0</div></div>
      <div class="metric-card"><div class="mk">Search p95/p99</div><div class="mv sm"><span id="m-p95-search">0</span>/<span id="m-p99-search">0</span></div></div>
    </section>

    <section id="workspace" class="workspace">
      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">Servidores</span>
          <button id="refresh-btn" class="btn sm">\u21ba</button>
        </div>
        <div class="panel-body">
          <input class="search-input" id="guild-search" type="text" placeholder="Buscar\u2026">
          <div id="guild-list" class="guild-list"><div class="guild-item"><div class="gi-meta">Carregando\u2026</div></div></div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head">
          <span class="panel-title">Opera\u00e7\u00e3o</span>
          <span id="op-role" class="role-badge viewer" style="font-size:.68rem">viewer</span>
        </div>
        <div class="panel-body">
          <select id="guild-select" class="guild-select-mobile"></select>
          <div class="state-grid">
            <div class="state-cell"><div class="mk">Estado</div><div id="g-state" class="mv sm">\u2014</div></div>
            <div class="state-cell"><div class="mk">Canal</div><div id="g-voice" class="mv sm">\u2014</div></div>
            <div class="state-cell"><div class="mk">Fila</div><div id="g-queue" class="mv">0</div></div>
          </div>
          <div id="g-settings" class="settings-bar">vol=100% | filter=off | loop=off | autoplay=off | 24/7=off</div>
          <div class="player-top">
            <img id="g-avatar" class="guild-avatar-img" alt="">
            <div style="min-width:0">
              <div id="g-track" class="player-track">Nenhuma faixa tocando</div>
              <div id="g-mod" class="player-sub">max=0s | wl=0 | bl=0</div>
            </div>
          </div>
          <div class="progress-bar"><div id="g-prog-fill" class="progress-fill"></div></div>
          <div id="g-prog-text" class="progress-time">00:00 / 00:00</div>
          <div id="g-vu" class="vu-wrap paused">
            <div class="vu-bar" style="height:8px"></div><div class="vu-bar" style="height:14px"></div>
            <div class="vu-bar" style="height:10px"></div><div class="vu-bar" style="height:18px"></div>
            <div class="vu-bar" style="height:22px"></div><div class="vu-bar" style="height:13px"></div>
            <div class="vu-bar" style="height:17px"></div><div class="vu-bar" style="height:24px"></div>
            <div class="vu-bar" style="height:12px"></div><div class="vu-bar" style="height:20px"></div>
            <div class="vu-bar" style="height:9px"></div><div class="vu-bar" style="height:16px"></div>
            <div class="vu-bar" style="height:11px"></div><div class="vu-bar" style="height:19px"></div>
            <div class="vu-bar" style="height:15px"></div><div class="vu-bar" style="height:8px"></div>
            <div class="vu-bar" style="height:21px"></div><div class="vu-bar" style="height:14px"></div>
            <div class="vu-bar" style="height:10px"></div><div class="vu-bar" style="height:18px"></div>
          </div>
          <div class="controls">
            <button class="btn action" data-action="pause">\u23f8 Pause</button>
            <button class="btn action" data-action="resume">\u25b6 Resume</button>
            <button class="btn action" data-action="skip">\u23ed Skip</button>
            <button class="btn action" data-action="replay">\u21a9 Replay</button>
            <button class="btn action warn-btn" data-action="shuffle">\U0001f500 Shuffle</button>
            <button class="btn action danger" data-action="stop">\u23f9 Stop</button>
            <button class="btn action danger" data-action="clear_queue">\U0001f5d1 Clear Queue</button>
            <button class="btn action danger" data-action="disconnect">\u23cf Disconnect</button>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head"><span class="panel-title">Fila de M\u00fasicas</span></div>
        <div class="panel-body"><div id="queue-list" class="queue-list"><div class="queue-item"><span class="queue-num">\u2014</span>Fila vazia.</div></div></div>
      </div>
    </section>

    <section id="forms" class="forms-grid">
      <div class="form-card">
        <div class="form-title">Player Config</div>
        <div class="field"><label>Volume (%)</label><input id="volume-input" type="number" min="1" max="200" value="100"></div>
        <button id="set-volume-btn" class="btn primary full">Aplicar Volume</button>
        <div class="sep"></div>
        <div class="field"><label>Filtro de \u00c1udio</label>
          <select id="filter-select"><option value="off">off</option><option value="bassboost">bassboost</option><option value="nightcore">nightcore</option><option value="vaporwave">vaporwave</option><option value="karaoke">karaoke</option></select>
        </div>
        <button id="set-filter-btn" class="btn primary full">Aplicar Filtro</button>
        <div class="sep"></div>
        <div class="field"><label>Modo Loop</label>
          <select id="loop-select"><option value="off">off</option><option value="track">track</option><option value="queue">queue</option></select>
        </div>
        <button id="set-loop-btn" class="btn primary full">Aplicar Loop</button>
        <div class="sep"></div>
        <div class="field-row">
          <div class="field"><label>Autoplay</label><select id="autoplay-select"><option value="true">on</option><option value="false">off</option></select></div>
          <div class="field"><label>Modo 24/7</label><select id="stay-select"><option value="false">off</option><option value="true">on</option></select></div>
        </div>
        <div class="field-row">
          <button id="set-autoplay-btn" class="btn primary">Autoplay</button>
          <button id="set-stay-btn" class="btn primary">24/7</button>
        </div>
      </div>

      <div class="form-card">
        <div class="form-title">Queue Ops</div>
        <div class="field"><label>Remover posi\u00e7\u00e3o</label><input id="remove-position" type="number" min="1" placeholder="1"></div>
        <button id="remove-btn" class="btn danger full">Remover Item</button>
        <div class="sep"></div>
        <div class="field-row">
          <div class="field"><label>Mover de</label><input id="move-source" type="number" min="1" placeholder="1"></div>
          <div class="field"><label>Mover para</label><input id="move-target" type="number" min="1" placeholder="2"></div>
        </div>
        <button id="move-btn" class="btn primary full">Mover Item</button>
        <div class="sep"></div>
        <div class="field"><label>Jump para posi\u00e7\u00e3o</label><input id="jump-position" type="number" min="1" placeholder="1"></div>
        <button id="jump-btn" class="btn primary full">Jump</button>
      </div>

      <div class="form-card">
        <div class="form-title">Admin Center</div>
        <div class="field"><label>Control Room (nome do canal)</label><input id="control-room-name" type="text" placeholder="bot-controle"></div>
        <button id="control-room-btn" class="btn primary full admin-only">Criar Control Room</button>
        <div class="sep"></div>
        <div class="field"><label>Max dura\u00e7\u00e3o de faixa (seg, 0=sem limite)</label><input id="mod-duration" type="number" min="0" placeholder="0"></div>
        <button id="mod-duration-btn" class="btn warn-btn full admin-only">Aplicar Dura\u00e7\u00e3o</button>
        <div class="sep"></div>
        <div class="field"><label>Whitelist \u2014 Dom\u00ednio</label><input id="mod-whitelist" type="text" placeholder="youtube.com"></div>
        <div class="field-row">
          <button id="mod-wl-add" class="btn primary admin-only">+ Add</button>
          <button id="mod-wl-rem" class="btn danger admin-only">\u2212 Remove</button>
        </div>
        <button id="mod-wl-clear" class="btn warn-btn full admin-only" style="margin-top:6px">Limpar Whitelist</button>
        <div class="sep"></div>
        <div class="field"><label>Blacklist \u2014 Dom\u00ednio</label><input id="mod-blacklist" type="text" placeholder="example.com"></div>
        <div class="field-row">
          <button id="mod-bl-add" class="btn primary admin-only">+ Add</button>
          <button id="mod-bl-rem" class="btn danger admin-only">\u2212 Remove</button>
        </div>
        <button id="mod-bl-clear" class="btn warn-btn full admin-only" style="margin-top:6px">Limpar Blacklist</button>
        <div class="sep"></div>
        <div class="field-row">
          <button id="cache-stats-btn"    class="btn admin-only">Cache Stats</button>
          <button id="cache-clear-search" class="btn warn-btn admin-only">Clear Search</button>
        </div>
        <div class="field-row" style="margin-top:6px">
          <button id="cache-clear-all" class="btn danger admin-only">Clear All</button>
          <button id="diagnostics-btn" class="btn admin-only">Diagnostics</button>
        </div>
      </div>
    </section>

    <div id="event-log" class="event-log"><span class="log-time">\u2014</span> Pronto.</div>

  </main>
</div>

<script>
(function () {
"use strict";

// ---- helpers ----------------------------------------------------------------
function ge(id) { return document.getElementById(id); }

// All mutable DOM refs typed by id, no innerHTML needed for user data
var R = {
  sDot: ge("s-dot"), sText: ge("s-text"),
  roleBadge: ge("role-badge"), authSource: ge("auth-source"),
  loginBtn: ge("login-btn"), logoutBtn: ge("logout-btn"),
  opRole: ge("op-role"), adminToken: ge("admin-token"),
  mBot: ge("m-bot"), mGuilds: ge("m-guilds"), mCalls: ge("m-calls"),
  mErrors: ge("m-errors"), mLatency: ge("m-latency"), mUptime: ge("m-uptime"),
  mBackend: ge("m-backend"),
  mP50Play: ge("m-p50-play"), mP95Play: ge("m-p95-play"), mP99Play: ge("m-p99-play"),
  mP50Search: ge("m-p50-search"), mP95Search: ge("m-p95-search"), mP99Search: ge("m-p99-search"),
  guildList: ge("guild-list"), guildSearch: ge("guild-search"), guildSelect: ge("guild-select"),
  refreshBtn: ge("refresh-btn"),
  gState: ge("g-state"), gVoice: ge("g-voice"), gQueue: ge("g-queue"),
  gSettings: ge("g-settings"), gAvatar: ge("g-avatar"), gTrack: ge("g-track"),
  gMod: ge("g-mod"), gProgFill: ge("g-prog-fill"), gProgText: ge("g-prog-text"), gVu: ge("g-vu"),
  queueList: ge("queue-list"), eventLog: ge("event-log"),
  volumeInput: ge("volume-input"), filterSelect: ge("filter-select"), loopSelect: ge("loop-select"),
  autoplaySelect: ge("autoplay-select"), staySelect: ge("stay-select"),
  setVolumeBtn: ge("set-volume-btn"), setFilterBtn: ge("set-filter-btn"), setLoopBtn: ge("set-loop-btn"),
  setAutoplayBtn: ge("set-autoplay-btn"), setStayBtn: ge("set-stay-btn"),
  removePos: ge("remove-position"), moveSource: ge("move-source"), moveTarget: ge("move-target"),
  jumpPos: ge("jump-position"), removeBtn: ge("remove-btn"), moveBtn: ge("move-btn"), jumpBtn: ge("jump-btn"),
  controlRoomName: ge("control-room-name"), controlRoomBtn: ge("control-room-btn"),
  modDuration: ge("mod-duration"), modDurationBtn: ge("mod-duration-btn"),
  modWhitelist: ge("mod-whitelist"), modWlAdd: ge("mod-wl-add"), modWlRem: ge("mod-wl-rem"), modWlClear: ge("mod-wl-clear"),
  modBlacklist: ge("mod-blacklist"), modBlAdd: ge("mod-bl-add"), modBlRem: ge("mod-bl-rem"), modBlClear: ge("mod-bl-clear"),
  cacheStatsBtn: ge("cache-stats-btn"), cacheClearSearch: ge("cache-clear-search"),
  cacheClearAll: ge("cache-clear-all"), diagnosticsBtn: ge("diagnostics-btn"),
};

var S = { payload: null, selectedGuildId: null, auth: { role: "viewer", oauth_enabled: false, source: "none" } };

function num(v, d) { return Number(v != null ? v : (d != null ? d : 0)); }
function ms(v) { return num(v).toFixed(1); }
function gId(g) { return String((g && g.guild_id) ? g.guild_id : ""); }
function fmtUptime(s) {
  var n=Math.max(num(s),0), h=Math.floor(n/3600), m=Math.floor((n%3600)/60), x=Math.floor(n%60);
  return h>0 ? h+"h "+m+"m" : m>0 ? m+"m "+x+"s" : x+"s";
}
function fmtClock(s) {
  var n=Math.max(num(s),0);
  return String(Math.floor(n/60)).padStart(2,"0")+":"+String(Math.floor(n%60)).padStart(2,"0");
}

// ---- logging (textContent only) -------------------------------------------
function log(msg, type) {
  while (R.eventLog.firstChild) R.eventLog.removeChild(R.eventLog.firstChild);
  var t = document.createElement("span");
  t.className = "log-time";
  t.textContent = "[" + new Date().toLocaleTimeString() + "] ";
  var m = document.createElement("span");
  if (type === "ok") m.className = "log-ok";
  else if (type === "bad") m.className = "log-bad";
  m.textContent = String(msg || "");
  R.eventLog.appendChild(t);
  R.eventLog.appendChild(m);
}

// ---- connection -----------------------------------------------------------
function setConn(ok, txt) {
  R.sDot.className = "s-dot " + (ok ? "ok" : "bad");
  R.sText.textContent = txt;
}

// ---- role UI -------------------------------------------------------------
function applyRoleUI() {
  var role = (S.auth && S.auth.role) ? S.auth.role : "viewer";
  var hasToken = (R.adminToken.value || "").trim().length >= 16;
  var canOp    = role === "admin" || role === "dj" || hasToken;
  var canAdmin = role === "admin" || hasToken;
  R.roleBadge.textContent = role;
  R.roleBadge.className   = "role-badge " + role;
  R.opRole.textContent    = role + (hasToken ? "+token" : "");
  R.opRole.className      = "role-badge " + role;
  R.authSource.textContent = "auth: " + ((S.auth && S.auth.source) ? S.auth.source : "\u2014");
  document.querySelectorAll(".admin-only").forEach(function(b) { b.disabled = !canAdmin; });
  document.querySelectorAll(".action").forEach(function(b) { b.disabled = !canOp; });
  var oauthActive = S.auth && S.auth.source === "oauth";
  R.loginBtn.style.display  = (S.auth && S.auth.oauth_enabled && !oauthActive) ? "" : "none";
  R.logoutBtn.style.display = (S.auth && S.auth.oauth_enabled && oauthActive)  ? "" : "none";
}

async function refreshAuth() {
  try {
    var r = await fetch("/auth/me", { cache: "no-store" });
    var j = await r.json();
    if (r.ok && j.ok) S.auth = { role: j.role || "viewer", oauth_enabled: !!j.oauth_enabled, source: j.source || "none" };
  } catch(_) {}
  applyRoleUI();
}

// ---- guild list (DOM construction, no innerHTML with user data) -----------
function makeGuildItem(g, active) {
  var item = document.createElement("div");
  item.className = "guild-item" + (active ? " active" : "");
  item.dataset.id = gId(g);

  var name = document.createElement("div");
  name.className = "gi-name";
  name.textContent = String(g.guild_name || "");

  var state = g.playing ? "\u25b6 playing" : g.paused ? "\u23f8 paused" : "idle";
  var meta = document.createElement("div");
  meta.className = "gi-meta";
  meta.textContent = state + " \u00b7 fila=" + (g.queue_size || 0);

  item.appendChild(name);
  item.appendChild(meta);
  return item;
}

function renderGuilds(guilds) {
  // clear
  while (R.guildList.firstChild) R.guildList.removeChild(R.guildList.firstChild);
  while (R.guildSelect.firstChild) R.guildSelect.removeChild(R.guildSelect.firstChild);

  if (!guilds || !guilds.length) {
    var empty = document.createElement("div");
    empty.className = "guild-item";
    var emptyMeta = document.createElement("div");
    emptyMeta.className = "gi-meta";
    emptyMeta.textContent = "Nenhum servidor conectado.";
    empty.appendChild(emptyMeta);
    R.guildList.appendChild(empty);
    return;
  }
  var q = (R.guildSearch.value || "").trim().toLowerCase();
  var filtered = guilds.filter(function(g) {
    return !q || String(g.guild_name || "").toLowerCase().indexOf(q) >= 0 || gId(g).indexOf(q) >= 0;
  });
  filtered.forEach(function(g) {
    R.guildList.appendChild(makeGuildItem(g, gId(g) === S.selectedGuildId));
    var opt = document.createElement("option");
    opt.value = gId(g);
    opt.textContent = String(g.guild_name || "") + " (" + gId(g) + ")";
    if (gId(g) === S.selectedGuildId) opt.selected = true;
    R.guildSelect.appendChild(opt);
  });
}

// ---- queue list (DOM construction) --------------------------------------
function makeQueueItem(text, num) {
  var item = document.createElement("div");
  item.className = "queue-item";
  var n = document.createElement("span");
  n.className = "queue-num";
  n.textContent = String(num);
  var t = document.createElement("span");
  t.textContent = String(text || "");
  item.appendChild(n);
  item.appendChild(t);
  return item;
}
function makeQueueEmpty() {
  var item = document.createElement("div");
  item.className = "queue-item";
  var n = document.createElement("span");
  n.className = "queue-num";
  n.textContent = "\u2014";
  var t = document.createElement("span");
  t.textContent = "Fila vazia.";
  item.appendChild(n);
  item.appendChild(t);
  return item;
}

// ---- selected guild -------------------------------------------------------
function selectedGuild() {
  var gs = (S.payload && S.payload.guilds) ? S.payload.guilds : [];
  var found = gs.filter(function(g) { return gId(g) === S.selectedGuildId; });
  return found.length ? found[0] : (gs.length ? gs[0] : null);
}

function renderPlayer() {
  var g = selectedGuild();

  // clear queue list
  while (R.queueList.firstChild) R.queueList.removeChild(R.queueList.firstChild);

  if (!g) {
    R.gState.textContent = "\u2014";
    R.gState.style.color = "";
    R.gVoice.textContent = "\u2014";
    R.gQueue.textContent = "0";
    R.gTrack.textContent = "Nenhuma faixa tocando";
    R.gSettings.textContent = "vol=100% | filter=off | loop=off | autoplay=off | 24/7=off";
    R.gMod.textContent = "max=0s | wl=0 | bl=0";
    R.gAvatar.removeAttribute("src");
    R.gProgFill.style.width = "0%";
    R.gProgText.textContent = "00:00 / 00:00";
    R.gVu.className = "vu-wrap paused";
    R.queueList.appendChild(makeQueueEmpty());
    return;
  }

  R.gState.textContent = g.playing ? "\u25b6 playing" : g.paused ? "\u23f8 paused" : "idle";
  R.gState.style.color = g.playing ? "var(--ok)" : g.paused ? "var(--amber)" : "var(--muted)";
  R.gVoice.textContent = String(g.voice_channel || "\u2014");
  R.gQueue.textContent = String(g.queue_size || 0);
  R.gTrack.textContent = String(g.current || "Nenhuma faixa tocando");

  if (g.guild_icon_url) R.gAvatar.src = String(g.guild_icon_url);
  else R.gAvatar.removeAttribute("src");

  var s = g.settings || {};
  R.volumeInput.value    = String(s.volume_percent != null ? s.volume_percent : 100);
  R.filterSelect.value   = String(s.filter || "off");
  R.loopSelect.value     = String(s.loop_mode || "off");
  R.autoplaySelect.value = s.autoplay ? "true" : "false";
  R.staySelect.value     = s.stay_connected ? "true" : "false";
  R.gSettings.textContent =
    "vol=" + (s.volume_percent != null ? s.volume_percent : 100) + "%" +
    " | filter=" + (s.filter || "off") +
    " | loop=" + (s.loop_mode || "off") +
    " | autoplay=" + (s.autoplay ? "on" : "off") +
    " | 24/7=" + (s.stay_connected ? "on" : "off");

  var m = g.moderation || {};
  R.gMod.textContent = "max=" + (m.max_track_duration_seconds || 0) + "s | wl=" + ((m.whitelist || []).length) + " | bl=" + ((m.blacklist || []).length);
  R.modDuration.value = String(m.max_track_duration_seconds || 0);

  var elapsed = num(g.current_elapsed_seconds);
  var total   = num(g.current_duration_seconds);
  var ratio   = total > 0 ? Math.min(100, Math.max(0, (elapsed / total) * 100)) : 0;
  R.gProgFill.style.width = ratio + "%";
  R.gProgText.textContent = total > 0 ? fmtClock(elapsed) + " / " + fmtClock(total) : "ao vivo";
  R.gVu.className = "vu-wrap " + (g.playing ? "playing" : "paused");

  var q = Array.isArray(g.queue_preview) ? g.queue_preview : [];
  if (q.length) {
    q.forEach(function(t, i) { R.queueList.appendChild(makeQueueItem(t, i + 1)); });
  } else {
    R.queueList.appendChild(makeQueueEmpty());
  }
}

// ---- full render ---------------------------------------------------------
function render(payload) {
  var guilds = payload.guilds || [];
  if (!S.selectedGuildId && guilds.length) S.selectedGuildId = gId(guilds[0]);

  R.mBot.textContent     = String(payload.bot_user || "\u2014");
  R.mGuilds.textContent  = String(guilds.length);
  R.mCalls.textContent   = String((payload.metrics && payload.metrics.command_calls) || 0);
  R.mErrors.textContent  = String((payload.metrics && payload.metrics.command_errors) || 0);
  R.mLatency.textContent = ms((payload.metrics || {}).average_latency_ms) + " ms";
  R.mUptime.textContent  = fmtUptime((payload.runtime || {}).uptime_seconds);
  R.mBackend.textContent = String((payload.runtime && payload.runtime.repository_backend) || "\u2014");

  var slo = (payload.metrics && payload.metrics.slo_5m) ? payload.metrics.slo_5m : {};
  R.mP50Play.textContent   = ms(slo.play_p50_ms) + " ms";
  R.mP95Play.textContent   = ms(slo.play_p95_ms);
  R.mP99Play.textContent   = ms(slo.play_p99_ms);
  R.mP50Search.textContent = ms(slo.search_p50_ms) + " ms";
  R.mP95Search.textContent = ms(slo.search_p95_ms);
  R.mP99Search.textContent = ms(slo.search_p99_ms);

  renderGuilds(guilds);
  renderPlayer();
}

// ---- tick ----------------------------------------------------------------
async function tick() {
  try {
    var r = await fetch("/api/status", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    var j = await r.json();
    S.payload = j;
    if (j.auth) S.auth = { role: j.auth.role || "viewer", oauth_enabled: !!j.auth.oauth_enabled, source: j.auth.source || "none" };
    applyRoleUI();
    render(j);
    setConn(true, "Online");
  } catch(err) {
    log("Falha: " + String(err), "bad");
    setConn(false, "Offline");
  }
}

// ---- action --------------------------------------------------------------
async function callAction(action, extra) {
  var g = selectedGuild();
  if (!g) { log("Selecione um servidor.", "bad"); return; }
  var token = (R.adminToken.value || "").trim();
  if (token) localStorage.setItem("bm_token", token);
  var headers = { "Content-Type": "application/json" };
  if (token) headers["X-Admin-Token"] = token;
  var body = Object.assign({ action: action, guild_id: gId(g) }, extra || {});
  try {
    var r = await fetch("/api/action", { method: "POST", headers: headers, body: JSON.stringify(body) });
    var j = await r.json();
    if (!r.ok || !j.ok) { log("Erro: " + (j.error || "status " + r.status), "bad"); return; }
    var msg = "OK: " + action;
    if (j.summary)    msg += " | " + j.summary;
    if (j.title)      msg += " \u2014 \"" + j.title + "\"";
    if (j.moderation) msg += " | " + JSON.stringify(j.moderation);
    if (j.diagnostics)msg += " | " + JSON.stringify(j.diagnostics);
    log(msg, "ok");
    await tick();
  } catch(err) { log("Erro de rede: " + String(err), "bad"); }
}

// ---- event listeners -----------------------------------------------------
R.loginBtn.addEventListener("click", function() { window.location.href = "/auth/login"; });
R.logoutBtn.addEventListener("click", async function() { await fetch("/auth/logout", { method: "POST" }); await refreshAuth(); await tick(); });
R.adminToken.addEventListener("input", applyRoleUI);
R.refreshBtn.addEventListener("click", tick);
R.guildSearch.addEventListener("input", function() { render(S.payload || { guilds: [] }); });

R.guildList.addEventListener("click", function(e) {
  var item = e.target.closest(".guild-item");
  if (!item) return;
  var id = String(item.dataset.id || "").trim();
  if (!id) return;
  S.selectedGuildId = id;
  render(S.payload || { guilds: [] });
});
R.guildSelect.addEventListener("change", function() {
  var id = String(R.guildSelect.value || "").trim();
  if (!id) return;
  S.selectedGuildId = id;
  render(S.payload || { guilds: [] });
});

document.querySelectorAll(".action").forEach(function(btn) {
  btn.addEventListener("click", function() { callAction(btn.dataset.action); });
});
R.setVolumeBtn.addEventListener("click", function() { callAction("set_volume", { volume_percent: num(R.volumeInput.value, 100) }); });
R.setFilterBtn.addEventListener("click", function() { callAction("set_filter", { filter: R.filterSelect.value }); });
R.setLoopBtn.addEventListener("click", function() { callAction("set_loop", { loop_mode: R.loopSelect.value }); });
R.setAutoplayBtn.addEventListener("click", function() { callAction("set_autoplay", { enabled: R.autoplaySelect.value === "true" }); });
R.setStayBtn.addEventListener("click", function() { callAction("set_stay_connected", { enabled: R.staySelect.value === "true" }); });
R.removeBtn.addEventListener("click", function() { callAction("remove", { position: num(R.removePos.value) }); });
R.moveBtn.addEventListener("click", function() { callAction("move", { source_pos: num(R.moveSource.value), target_pos: num(R.moveTarget.value) }); });
R.jumpBtn.addEventListener("click", function() { callAction("jump", { position: num(R.jumpPos.value) }); });
R.controlRoomBtn.addEventListener("click", function() { callAction("control_room_create", { name: R.controlRoomName.value || "bot-controle" }); });
R.modDurationBtn.addEventListener("click", function() { callAction("moderation_set_duration", { seconds: num(R.modDuration.value) }); });
R.modWlAdd.addEventListener("click", function() { callAction("moderation_add_whitelist", { domain: R.modWhitelist.value }); });
R.modWlRem.addEventListener("click", function() { callAction("moderation_remove_whitelist", { domain: R.modWhitelist.value }); });
R.modWlClear.addEventListener("click", function() { callAction("moderation_clear_whitelist"); });
R.modBlAdd.addEventListener("click", function() { callAction("moderation_add_blacklist", { domain: R.modBlacklist.value }); });
R.modBlRem.addEventListener("click", function() { callAction("moderation_remove_blacklist", { domain: R.modBlacklist.value }); });
R.modBlClear.addEventListener("click", function() { callAction("moderation_clear_blacklist"); });
R.cacheStatsBtn.addEventListener("click", function() { callAction("cache_stats"); });
R.cacheClearSearch.addEventListener("click", function() { callAction("cache_clear_search"); });
R.cacheClearAll.addEventListener("click", function() { callAction("cache_clear_all"); });
R.diagnosticsBtn.addEventListener("click", function() { callAction("diagnostics"); });

document.querySelectorAll(".nav-tab").forEach(function(tab) {
  tab.addEventListener("click", function(e) {
    document.querySelectorAll(".nav-tab").forEach(function(t) { t.classList.remove("active"); });
    e.currentTarget.classList.add("active");
  });
});

R.adminToken.value = localStorage.getItem("bm_token") || "";
refreshAuth().then(tick);
setInterval(tick, 3000);

})();
</script>
</body>
</html>'''
