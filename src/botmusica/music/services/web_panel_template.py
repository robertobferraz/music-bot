from __future__ import annotations


def build_web_panel_html() -> str:
    return '''<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Music Bot Discord | Admin Panel</title>
  <style>
    @import url("https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap");
    :root {
      --bg:#030611;
      --bg-soft:#081231;
      --surface:#0b1432cc;
      --surface-2:#101d45c9;
      --line:#40508d;
      --line-soft:#30406f;
      --txt:#edf2ff;
      --muted:#9ea9cc;
      --ok:#2ee8a7;
      --warn:#ffbf63;
      --bad:#ff4f7c;
      --cyan:#18c7ff;
      --vio:#7d54ff;
      --mono:"JetBrains Mono", monospace;
      --sans:"Sora", "Segoe UI", sans-serif;
    }
    * { box-sizing:border-box; }
    body {
      margin:0;
      color:var(--txt);
      font-family:var(--sans);
      background:
        radial-gradient(900px 540px at -12% -8%, rgba(24,199,255,.22), transparent 60%),
        radial-gradient(760px 440px at 112% -16%, rgba(125,84,255,.26), transparent 56%),
        radial-gradient(720px 420px at 70% 114%, rgba(46,232,167,.12), transparent 60%),
        linear-gradient(165deg, var(--bg), #060f27 44%, #0b1b43 100%);
      min-height:100vh;
    }

    .app {
      max-width:1620px;
      margin:0 auto;
      padding:14px 14px 30px;
      display:block;
    }

    .side {
      border:1px solid var(--line-soft);
      background:linear-gradient(180deg, #09112bcf, #060c1ed1);
      border-radius:16px;
      padding:10px 12px;
      box-shadow:0 12px 34px rgba(2,6,20,.56);
      display:grid;
      grid-template-columns:auto 1fr auto;
      align-items:center;
      gap:12px;
      min-height:auto;
      position:sticky;
      top:10px;
      z-index:40;
      backdrop-filter:blur(8px);
      -webkit-backdrop-filter:blur(8px);
      margin-bottom:10px;
    }
    .brand {
      display:flex;
      align-items:center;
      gap:10px;
      padding:4px 8px 4px 2px;
      border-bottom:none;
      border-right:1px solid #1c2a56;
    }
    .logo {
      width:36px;height:36px;border-radius:12px;
      display:grid;place-items:center;
      background:linear-gradient(135deg, rgba(24,199,255,.24), rgba(125,84,255,.36));
      border:1px solid #3d54aa;
      font-size:20px;
    }
    .brand h1 { margin:0; font-size:1rem; letter-spacing:.02em; }
    .brand p { margin:2px 0 0; font-size:.69rem; color:var(--muted); }

    .nav-title {
      color:#aeb8da;
      text-transform:uppercase;
      letter-spacing:.08em;
      font-size:.68rem;
      margin:0 4px;
    }
    .nav-list { display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
    .nav-item {
      border:1px solid transparent;
      border-radius:12px;
      color:#c5d2f6;
      text-decoration:none;
      font-size:.88rem;
      padding:9px 10px;
      background:#0b143000;
      display:flex;
      justify-content:flex-start;
      align-items:center;
      gap:8px;
      white-space:nowrap;
    }
    .nav-item .left { display:flex; align-items:center; gap:8px; }
    .nav-ico {
      width:22px; height:22px; border-radius:8px;
      display:grid; place-items:center;
      background:#0f1c44;
      border:1px solid #31477f;
      font-size:.82rem;
    }
    .nav-item.active {
      background:linear-gradient(180deg, rgba(125,84,255,.18), rgba(24,199,255,.12));
      border-color:#445fae;
      color:#fff;
    }
    .nav-item:hover {
      border-color:#4b63b1;
      background:linear-gradient(180deg, rgba(89,112,192,.18), rgba(24,199,255,.08));
    }
    .nodes {
      margin-top:0;
      padding-top:0;
      border-top:none;
      border-left:1px solid #1d2a53;
      padding-left:10px;
      display:flex;
      flex-wrap:wrap;
      gap:10px;
      justify-content:flex-end;
    }
    .node { font-size:.8rem; color:#c6d1f7; display:flex; align-items:center; gap:8px; }
    .sig { width:8px; height:8px; border-radius:999px; display:inline-block; }
    .sig.ok { background:var(--ok); }
    .sig.warn { background:var(--warn); }
    .sig.bad { background:var(--bad); }

    .main { min-width:0; }

    .top {
      border:1px solid var(--line-soft);
      background:linear-gradient(180deg, #0d1840cc, #0a1333d4);
      border-radius:16px;
      padding:14px 16px;
      box-shadow:0 12px 26px rgba(2,6,18,.48);
      margin-bottom:10px;
      display:grid;
      grid-template-columns: 1fr auto;
      gap:10px;
      align-items:center;
    }
    .top h2 { margin:0; font-size:1.65rem; letter-spacing:.01em; }
    .top p { margin:4px 0 0; font-size:.91rem; color:var(--muted); }

    .toolbar {
      display:flex;
      align-items:center;
      gap:8px;
      flex-wrap:wrap;
      justify-content:flex-end;
    }

    .pill {
      border:1px solid #3e4f8b;
      border-radius:999px;
      padding:8px 12px;
      background:#0b1535d9;
      display:inline-flex;
      align-items:center;
      gap:8px;
      font:700 .78rem var(--mono);
    }
    .dot { width:10px;height:10px;border-radius:999px;background:var(--warn); }
    .dot.ok { background:var(--ok); }
    .dot.bad { background:var(--bad); }

    .badge {
      border-radius:999px;
      border:1px solid transparent;
      font-size:.72rem;
      padding:4px 10px;
      display:inline-block;
    }
    .b-admin { color:#9ff8dd; background:#2ee8a720; border-color:#2ee8a749; }
    .b-dj { color:#9fd9ff; background:#18c7ff1f; border-color:#18c7ff49; }
    .b-view { color:#d2dcff; background:#8ea2de1e; border-color:#8ea2de49; }

    .btn {
      appearance:none;
      border:1px solid #42518f;
      border-radius:12px;
      padding:9px 12px;
      font:700 .84rem var(--sans);
      color:var(--txt);
      cursor:pointer;
      background:linear-gradient(180deg, #1d2d5fe6, #101d44f2);
      transition:.18s ease;
    }
    .btn:hover { transform:translateY(-1px); border-color:#4a63b8; }
    .btn.warn { border-color:#9c7944; }
    .btn.bad { border-color:#99506a; }
    .btn:disabled { opacity:.5; cursor:not-allowed; transform:none; }
    .ghost {
      width:34px; height:34px; border-radius:999px;
      border:1px solid #3d4f8b;
      background:#0b1535e3;
      color:#d5dfff;
      display:grid; place-items:center;
      font-size:1rem;
    }

    input, select {
      width:100%;
      border-radius:10px;
      border:1px solid #34467f;
      background:#0b1738f0;
      color:var(--txt);
      padding:8px 10px;
      font:.78rem var(--mono);
    }

    .cards {
      display:grid;
      grid-template-columns:repeat(6, minmax(0,1fr));
      gap:8px;
      margin-bottom:10px;
    }
    .card {
      border:1px solid #364987;
      border-radius:14px;
      padding:10px 11px;
      background:linear-gradient(180deg, #122458ca, #0d183fd6);
      box-shadow:0 8px 20px rgba(3,8,23,.45);
    }
    .k { color:var(--muted); font-size:.7rem; text-transform:uppercase; letter-spacing:.08em; }
    .v { margin-top:3px; font:800 1.01rem var(--mono); }
    .workspace {
      display:grid;
      grid-template-columns: 265px minmax(0, 1fr) 320px;
      gap:10px;
      margin-bottom:10px;
    }

    .panel {
      border:1px solid #34457f;
      border-radius:16px;
      background:linear-gradient(180deg, #101d45d4, #0a1432e0);
      box-shadow:0 12px 28px rgba(2,7,21,.52);
      overflow:hidden;
    }
    .panel-head {
      padding:12px 12px;
      border-bottom:1px solid #1e2d59;
      display:flex;
      justify-content:space-between;
      align-items:center;
      gap:8px;
    }
    .panel-title { margin:0; font-size:.96rem; letter-spacing:.04em; text-transform:uppercase; }
    .panel-body { padding:10px; }

    .guild-list { display:grid; gap:8px; max-height:620px; overflow:auto; }
    .guild-item {
      border:1px solid #2e4075;
      border-radius:12px;
      padding:10px;
      background:#0a1635de;
      cursor:pointer;
      transition:.18s ease;
    }
    .guild-item:hover { border-color:#4b6ece; transform:translateY(-1px); }
    .guild-item.active {
      border-color:#3af0b0;
      box-shadow:0 0 0 1px #2ee8a741 inset;
      background:linear-gradient(180deg, #122a57ec, #0c1c3eeb);
    }

    .ops-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin-bottom:8px; }
    .ops-mini {
      border:1px solid #2c3d6f;
      border-radius:12px;
      padding:8px;
      background:#0a1633cf;
    }
    .ops-mini .v { font-size:.88rem; }

    .now-block {
      border:1px solid #355097;
      border-radius:14px;
      padding:12px;
      background:linear-gradient(140deg, rgba(16,36,74,.88), rgba(11,19,44,.95));
      margin-bottom:8px;
    }
    .now-meta { display:flex; align-items:center; gap:10px; margin-bottom:6px; }
    .guild-avatar {
      width:48px; height:48px; border-radius:12px; object-fit:cover;
      border:1px solid #3b54a2;
      background:linear-gradient(135deg, rgba(24,199,255,.24), rgba(125,84,255,.34));
    }
    .now-title { font-size:1.8rem; line-height:1.2; margin:0 0 6px; font-weight:700; }
    .now-sub { color:#b8c3e8; margin:0 0 8px; }
    .wave {
      margin:10px 0;
      height:28px;
      display:flex;
      align-items:flex-end;
      gap:4px;
    }
    .wave span {
      width:5px;
      border-radius:999px;
      background:linear-gradient(180deg, #2ee8a7, #18c7ff, #7d54ff);
      opacity:.92;
    }
    .progress {
      width:100%; height:8px; border-radius:999px; background:#1b2852;
      overflow:hidden; border:1px solid #2c3d74;
    }
    .progress > span {
      display:block; height:100%; width:36%;
      background:linear-gradient(90deg, #2ee8a7, #18c7ff, #7d54ff);
      border-radius:999px;
      transition:width .35s ease;
    }
    .progress-text { margin:7px 0 2px; font:.76rem var(--mono); color:#b8c3e8; }
    .wave.playing span { animation: beat 1.25s ease-in-out infinite; }
    .wave.playing span:nth-child(2n){ animation-duration:1.05s; }
    .wave.playing span:nth-child(3n){ animation-duration:1.55s; }
    .wave.paused span { opacity:.35; animation:none; }
    @keyframes beat { 0%,100%{ transform:scaleY(.55);} 50%{ transform:scaleY(1.12);} }

    .controls {
      display:grid;
      grid-template-columns:repeat(5,minmax(0,1fr));
      gap:8px;
      margin-top:10px;
    }

    .queue-box { max-height:540px; overflow:auto; padding-right:3px; }
    .queue { margin:0; padding-left:18px; }
    .queue li { margin:5px 0; font-size:.92rem; }

    .forms {
      display:grid;
      grid-template-columns:repeat(3,minmax(0,1fr));
      gap:10px;
    }
    .form-card {
      border:1px solid #2f3f73;
      border-radius:14px;
      background:#0a1533de;
      padding:10px;
    }
    .form-card h3 {
      margin:0 0 8px;
      font-size:.84rem;
      text-transform:uppercase;
      letter-spacing:.08em;
      color:#b1bce0;
    }
    .line { display:grid; grid-template-columns:1fr 1fr; gap:7px; }
    .log {
      border:1px solid #304172;
      border-radius:10px;
      background:#060f25ea;
      margin-top:8px;
      padding:10px;
      font:.78rem var(--mono);
      color:#cbdbff;
      white-space:pre-wrap;
      word-break:break-word;
    }

    @media (max-width:1400px) {
      .cards { grid-template-columns:repeat(4,minmax(0,1fr)); }
      .workspace { grid-template-columns:250px minmax(0,1fr); }
      .workspace > :last-child { grid-column:1 / -1; }
      .controls { grid-template-columns:repeat(4,minmax(0,1fr)); }
    }
    @media (max-width:1120px) {
      .side {
        position:sticky;
        top:0;
        border-radius:12px;
        grid-template-columns:1fr;
        align-items:flex-start;
      }
      .brand {
        border-right:none;
        border-bottom:1px solid #1c2a56;
        padding:4px 4px 10px;
      }
      .nodes {
        border-left:none;
        border-top:1px solid #1d2a53;
        padding-left:0;
        padding-top:8px;
        justify-content:flex-start;
      }
      .cards { grid-template-columns:repeat(3,minmax(0,1fr)); }
      .workspace { grid-template-columns:1fr; }
      .forms { grid-template-columns:1fr; }
      .top { grid-template-columns:1fr; }
      .toolbar { justify-content:flex-start; }
    }
    @media (max-width:680px) {
      .cards { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .ops-grid { grid-template-columns:1fr 1fr; }
      .controls { grid-template-columns:repeat(2,minmax(0,1fr)); }
    }
  </style>
</head>
<body>
  <main class="app">
    <aside class="side">
      <div class="brand">
        <div class="logo">🎵</div>
        <div>
          <h1>Admin Panel</h1>
          <p>Music Bot Discord</p>
        </div>
      </div>

      <div>
        <p class="nav-title">Navegação</p>
        <div class="nav-list">
          <a class="nav-item active" href="#metrics"><span class="left"><span class="nav-ico">📊</span>Métricas</span><span>▸</span></a>
          <a class="nav-item" href="#workspace"><span class="left"><span class="nav-ico">🎚️</span>Operação</span><span>▸</span></a>
          <a class="nav-item" href="#forms"><span class="left"><span class="nav-ico">⚙️</span>Configurações</span><span>▸</span></a>
          <a class="nav-item" href="#event-log"><span class="left"><span class="nav-ico">🧾</span>Eventos</span><span>▸</span></a>
        </div>
      </div>

      <div class="nodes">
        <p class="nav-title">Runtime</p>
        <div class="node"><span class="sig ok"></span> Backend: <strong id="side-backend">-</strong></div>
        <div class="node"><span class="sig warn"></span> Lavalink: <strong id="side-lavalink">-</strong></div>
        <div class="node"><span class="sig bad"></span> Servidores: <strong id="side-guilds">0</strong></div>
      </div>
    </aside>

    <section class="main">
      <header class="top">
        <div>
          <h2>Music Bot Discord Admin Panel</h2>
          <p>Operação e monitoramento em tempo real.</p>
        </div>
        <div class="toolbar">
          <div class="pill"><span id="status-dot" class="dot"></span><span id="status-text">Conectando...</span></div>
          <button class="ghost" type="button" aria-label="alerts">✧</button>
          <button class="ghost" type="button" aria-label="security">⟡</button>
          <span id="role-badge" class="badge b-view">viewer</span>
          <span id="auth-source" class="pill" style="font-weight:600">auth: -</span>
          <button id="login-btn" class="btn" type="button">Login Discord</button>
          <button id="logout-btn" class="btn" type="button">Logout</button>
          <input id="admin-token" type="password" placeholder="X-Admin-Token (fallback)" style="width:280px">
        </div>
      </header>

      <section id="metrics" class="cards">
        <article class="card"><div class="k">Bot</div><div id="bot-user" class="v">-</div></article>
        <article class="card"><div class="k">Servidores</div><div id="guilds-total" class="v">0</div></article>
        <article class="card"><div class="k">Comandos</div><div id="command-calls" class="v">0</div></article>
        <article class="card"><div class="k">Erros</div><div id="command-errors" class="v">0</div></article>
        <article class="card"><div class="k">Latência</div><div id="avg-latency" class="v">0.0 ms</div></article>
        <article class="card"><div class="k">Uptime</div><div id="uptime" class="v">0s</div></article>
        <article class="card"><div class="k">Backend</div><div id="runtime-backend" class="v">-</div></article>
        <article class="card"><div class="k">Lavalink</div><div id="lavalink-mode" class="v">-</div></article>
        <article class="card"><div class="k">Play p95 / p99</div><div class="v"><span id="p95-play">0.0</span> / <span id="p99-play">0.0</span></div></article>
        <article class="card"><div class="k">Search p95 / p99</div><div class="v"><span id="p95-search">0.0</span> / <span id="p99-search">0.0</span></div></article>
        <article class="card"><div class="k">Play p50</div><div id="p50-play" class="v">0.0 ms</div></article>
        <article class="card"><div class="k">Search p50</div><div id="p50-search" class="v">0.0 ms</div></article>
      </section>

      <section id="workspace" class="workspace">
        <aside class="panel">
          <div class="panel-head">
            <h3 class="panel-title">Servidores</h3>
            <button id="refresh-btn" class="btn" type="button">Atualizar</button>
          </div>
          <div class="panel-body">
            <input id="guild-search" type="text" placeholder="Buscar servidores...">
            <div id="guild-list" class="guild-list" style="margin-top:9px"><div class="k">Carregando...</div></div>
          </div>
        </aside>

        <section class="panel">
          <div class="panel-head">
            <h3 class="panel-title">Operação</h3>
            <span id="selected-role" class="k">perfil: viewer</span>
          </div>
          <div class="panel-body">
            <select id="guild-select" style="margin-bottom:8px"></select>

            <div class="ops-grid">
              <div class="ops-mini"><div class="k">Estado</div><div id="guild-state" class="v">-</div></div>
              <div class="ops-mini"><div class="k">Canal</div><div id="guild-voice" class="v">-</div></div>
              <div class="ops-mini"><div class="k">Fila</div><div id="guild-queue" class="v">0</div></div>
            </div>

            <div class="now-block">
              <div class="now-meta">
                <img id="guild-avatar" class="guild-avatar" alt="avatar do servidor">
                <div style="min-width:0">
                  <h4 id="guild-current" class="now-title">Nenhuma faixa tocando</h4>
                </div>
              </div>
              <p id="guild-settings" class="now-sub">vol=100% | filter=off | loop=off | autoplay=off | 24/7=off</p>
              <div class="progress"><span id="guild-progress-fill"></span></div>
              <p id="guild-progress-text" class="progress-text">00:00 / 00:00</p>
              <div id="guild-wave" class="wave paused">
                <span style="height:8px"></span><span style="height:14px"></span><span style="height:10px"></span><span style="height:17px"></span>
                <span style="height:21px"></span><span style="height:12px"></span><span style="height:16px"></span><span style="height:24px"></span>
                <span style="height:13px"></span><span style="height:20px"></span><span style="height:9px"></span><span style="height:15px"></span>
                <span style="height:11px"></span><span style="height:18px"></span><span style="height:8px"></span><span style="height:14px"></span>
              </div>
              <p id="guild-moderation" class="k" style="margin-top:9px">max=0s | wl=0 | bl=0</p>

              <div class="controls">
                <button class="btn action" data-action="pause">Pause</button>
                <button class="btn action" data-action="resume">Resume</button>
                <button class="btn action" data-action="skip">Skip</button>
                <button class="btn action" data-action="replay">Replay</button>
                <button class="btn bad action" data-action="stop">Stop</button>
                <button class="btn warn action" data-action="shuffle">Shuffle</button>
                <button class="btn bad action" data-action="clear_queue">Clear Queue</button>
                <button class="btn bad action" data-action="disconnect">Disconnect</button>
              </div>
            </div>
          </div>
        </section>

        <aside class="panel">
          <div class="panel-head">
            <h3 class="panel-title">Fila de Músicas</h3>
          </div>
          <div class="panel-body queue-box">
            <ol id="queue-preview" class="queue"><li class="k">Fila vazia.</li></ol>
          </div>
        </aside>
      </section>

      <section id="forms" class="forms">
        <article class="form-card">
          <h3>Player Config</h3>
          <label>Volume (%)</label>
          <input id="volume-input" type="number" min="1" max="200" value="100">
          <button id="set-volume-btn" class="btn" type="button">Aplicar volume</button>

          <label style="margin-top:7px">Filtro</label>
          <select id="filter-select">
            <option value="off">off</option>
            <option value="bassboost">bassboost</option>
            <option value="nightcore">nightcore</option>
            <option value="vaporwave">vaporwave</option>
            <option value="karaoke">karaoke</option>
          </select>
          <button id="set-filter-btn" class="btn" type="button">Aplicar filtro</button>

          <label style="margin-top:7px">Loop</label>
          <select id="loop-select">
            <option value="off">off</option>
            <option value="track">track</option>
            <option value="queue">queue</option>
          </select>
          <button id="set-loop-btn" class="btn" type="button">Aplicar loop</button>

          <label style="margin-top:7px">Autoplay</label>
          <select id="autoplay-select"><option value="true">on</option><option value="false">off</option></select>
          <button id="set-autoplay-btn" class="btn" type="button">Aplicar autoplay</button>

          <label style="margin-top:7px">24/7</label>
          <select id="stay-select"><option value="true">on</option><option value="false">off</option></select>
          <button id="set-stay-btn" class="btn" type="button">Aplicar 24/7</button>
        </article>

        <article class="form-card">
          <h3>Queue Ops</h3>
          <label>Remover posição</label>
          <input id="remove-position" type="number" min="1">
          <button id="remove-btn" class="btn" type="button">Remover item</button>

          <label style="margin-top:7px">Mover origem</label>
          <input id="move-source" type="number" min="1">

          <label>Mover destino</label>
          <input id="move-target" type="number" min="1">
          <button id="move-btn" class="btn" type="button">Mover item</button>

          <label style="margin-top:7px">Jump posição</label>
          <input id="jump-position" type="number" min="1">
          <button id="jump-btn" class="btn" type="button">Jump item</button>
        </article>

        <article class="form-card">
          <h3>Admin Center</h3>
          <label>Control Room (canal)</label>
          <input id="control-room-name" type="text" placeholder="bot-controle">
          <button id="control-room-btn" class="btn admin-only" type="button">Criar/Atualizar central</button>

          <label style="margin-top:7px">Max duração (seg)</label>
          <input id="mod-duration" type="number" min="0">
          <button id="mod-duration-btn" class="btn admin-only" type="button">Aplicar duração</button>

          <label style="margin-top:7px">Whitelist domínio</label>
          <input id="mod-whitelist" type="text" placeholder="youtube.com">
          <div class="line">
            <button id="mod-whitelist-add" class="btn admin-only" type="button">Adicionar</button>
            <button id="mod-whitelist-remove" class="btn admin-only" type="button">Remover</button>
          </div>
          <button id="mod-whitelist-clear" class="btn warn admin-only" type="button" style="margin-top:7px">Limpar whitelist</button>

          <label style="margin-top:7px">Blacklist domínio</label>
          <input id="mod-blacklist" type="text" placeholder="example.com">
          <div class="line">
            <button id="mod-blacklist-add" class="btn admin-only" type="button">Adicionar</button>
            <button id="mod-blacklist-remove" class="btn admin-only" type="button">Remover</button>
          </div>
          <button id="mod-blacklist-clear" class="btn warn admin-only" type="button" style="margin-top:7px">Limpar blacklist</button>

          <div class="line" style="margin-top:7px">
            <button id="cache-stats-btn" class="btn admin-only" type="button">Cache stats</button>
            <button id="cache-clear-search" class="btn admin-only" type="button">Clear search</button>
          </div>
          <div class="line" style="margin-top:7px">
            <button id="cache-clear-all" class="btn bad admin-only" type="button">Clear all</button>
            <button id="diagnostics-btn" class="btn admin-only" type="button">Diagnostics</button>
          </div>
        </article>
      </section>

      <div id="event-log" class="log">Pronto.</div>
    </section>
  </main>

  <script>
    const refs = {
      statusDot: document.getElementById("status-dot"), statusText: document.getElementById("status-text"),
      roleBadge: document.getElementById("role-badge"), authSource: document.getElementById("auth-source"),
      loginBtn: document.getElementById("login-btn"), logoutBtn: document.getElementById("logout-btn"),
      botUser: document.getElementById("bot-user"), guildsTotal: document.getElementById("guilds-total"),
      commandCalls: document.getElementById("command-calls"), commandErrors: document.getElementById("command-errors"),
      avgLatency: document.getElementById("avg-latency"), uptime: document.getElementById("uptime"),
      runtimeBackend: document.getElementById("runtime-backend"), lavalinkMode: document.getElementById("lavalink-mode"),
      p95Play: document.getElementById("p95-play"), p99Play: document.getElementById("p99-play"),
      p95Search: document.getElementById("p95-search"), p99Search: document.getElementById("p99-search"),
      p50Play: document.getElementById("p50-play"), p50Search: document.getElementById("p50-search"),
      sideBackend: document.getElementById("side-backend"), sideLavalink: document.getElementById("side-lavalink"), sideGuilds: document.getElementById("side-guilds"),
      guildList: document.getElementById("guild-list"), guildSearch: document.getElementById("guild-search"), guildSelect: document.getElementById("guild-select"),
      refreshBtn: document.getElementById("refresh-btn"), selectedRole: document.getElementById("selected-role"),
      guildState: document.getElementById("guild-state"), guildVoice: document.getElementById("guild-voice"), guildQueue: document.getElementById("guild-queue"),
      guildCurrent: document.getElementById("guild-current"), guildSettings: document.getElementById("guild-settings"), guildModeration: document.getElementById("guild-moderation"),
      guildAvatar: document.getElementById("guild-avatar"), guildProgressFill: document.getElementById("guild-progress-fill"), guildProgressText: document.getElementById("guild-progress-text"), guildWave: document.getElementById("guild-wave"),
      queuePreview: document.getElementById("queue-preview"), eventLog: document.getElementById("event-log"),
      tokenInput: document.getElementById("admin-token"),
      volumeInput: document.getElementById("volume-input"), filterSelect: document.getElementById("filter-select"), loopSelect: document.getElementById("loop-select"),
      autoplaySelect: document.getElementById("autoplay-select"), staySelect: document.getElementById("stay-select"),
      removePosition: document.getElementById("remove-position"), moveSource: document.getElementById("move-source"), moveTarget: document.getElementById("move-target"), jumpPosition: document.getElementById("jump-position"),
      setVolumeBtn: document.getElementById("set-volume-btn"), setFilterBtn: document.getElementById("set-filter-btn"), setLoopBtn: document.getElementById("set-loop-btn"),
      setAutoplayBtn: document.getElementById("set-autoplay-btn"), setStayBtn: document.getElementById("set-stay-btn"),
      removeBtn: document.getElementById("remove-btn"), moveBtn: document.getElementById("move-btn"), jumpBtn: document.getElementById("jump-btn"),
      controlRoomName: document.getElementById("control-room-name"), controlRoomBtn: document.getElementById("control-room-btn"),
      modDuration: document.getElementById("mod-duration"), modDurationBtn: document.getElementById("mod-duration-btn"),
      modWhitelist: document.getElementById("mod-whitelist"), modWhitelistAdd: document.getElementById("mod-whitelist-add"), modWhitelistRemove: document.getElementById("mod-whitelist-remove"), modWhitelistClear: document.getElementById("mod-whitelist-clear"),
      modBlacklist: document.getElementById("mod-blacklist"), modBlacklistAdd: document.getElementById("mod-blacklist-add"), modBlacklistRemove: document.getElementById("mod-blacklist-remove"), modBlacklistClear: document.getElementById("mod-blacklist-clear"),
      cacheStatsBtn: document.getElementById("cache-stats-btn"), cacheClearSearch: document.getElementById("cache-clear-search"), cacheClearAll: document.getElementById("cache-clear-all"), diagnosticsBtn: document.getElementById("diagnostics-btn"),
    };

    const state = { payload: null, selectedGuildId: null, auth: { role: "viewer", oauth_enabled: false, authenticated: false, source: "none" } };
    const esc = (v) => String(v || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const fmtMs = (v) => Number(v || 0).toFixed(1);
    const fmtUptime = (s) => {
      const n=Math.max(Number(s||0),0);
      const h=Math.floor(n/3600),m=Math.floor((n%3600)/60),x=Math.floor(n%60);
      return h>0?`${h}h ${m}m`:m>0?`${m}m ${x}s`:`${x}s`;
    };
    const fmtClock = (s) => {
      const n = Math.max(Number(s || 0), 0);
      const m = Math.floor(n / 60);
      const x = Math.floor(n % 60);
      return `${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}`;
    };
    const badge = (g) => g.playing ? '<span class="badge b-admin">playing</span>' : g.paused ? '<span class="badge b-dj">paused</span>' : '<span class="badge b-view">idle</span>';
    const guildIdOf = (g) => String((g && g.guild_id) || "");

    function setConnection(ok, txt){ refs.statusDot.className=`dot ${ok?"ok":"bad"}`; refs.statusText.textContent=txt; }
    function log(msg){ refs.eventLog.textContent=`[${new Date().toLocaleTimeString()}] ${msg}`; }
    function selectedGuild(){
      const gs=(state.payload&&state.payload.guilds)||[];
      return gs.find(g=>guildIdOf(g)===state.selectedGuildId)||gs[0]||null;
    }

    function applyRoleUi(){
      const role=state.auth.role||"viewer";
      const hasAdminToken=(refs.tokenInput.value||"").trim().length >= 32;
      const canOperate=(role === "admin" || role === "dj" || hasAdminToken);
      const canAdmin=(role === "admin" || hasAdminToken);
      refs.roleBadge.textContent=role;
      refs.roleBadge.className=`badge ${role==="admin"?"b-admin":role==="dj"?"b-dj":"b-view"}`;
      refs.authSource.textContent=`auth: ${state.auth.source||"none"}`;
      refs.selectedRole.textContent=`perfil: ${role}${hasAdminToken ? " + token" : ""}`;
      document.querySelectorAll(".admin-only").forEach(el=>{el.disabled=!canAdmin;});
      document.querySelectorAll(".action").forEach(el=>{el.disabled=!canOperate;});
      const oauthSessionActive = state.auth.source === "oauth";
      refs.loginBtn.style.display = state.auth.oauth_enabled && !oauthSessionActive ? "inline-block" : "none";
      refs.logoutBtn.style.display = state.auth.oauth_enabled && oauthSessionActive ? "inline-block" : "none";
    }

    async function refreshAuth(){
      try {
        const r=await fetch('/auth/me',{cache:'no-store'});
        const j=await r.json();
        if(r.ok && j.ok){
          state.auth={
            role:j.role||"viewer",
            oauth_enabled:!!j.oauth_enabled,
            authenticated:!!j.authenticated,
            source:j.source||"none",
          };
        }
      } catch (_){ }
      applyRoleUi();
    }

    function renderGuilds(guilds){
      if(!guilds.length){
        refs.guildList.innerHTML='<div class="k">Nenhum servidor conectado.</div>';
        refs.guildSelect.innerHTML='';
        return;
      }
      const q=(refs.guildSearch.value||'').trim().toLowerCase();
      const filtered=guilds.filter(g=>!q||String(g.guild_name||'').toLowerCase().includes(q)||guildIdOf(g).includes(q));
      refs.guildList.innerHTML=filtered.map(g=>`
        <div class="guild-item ${guildIdOf(g)===state.selectedGuildId?'active':''}" data-id="${guildIdOf(g)}">
          <div><strong>${esc(g.guild_name)}</strong></div>
          <div>${badge(g)}</div>
          <div class="k">#${guildIdOf(g)} | queue=${g.queue_size||0}</div>
        </div>
      `).join('');
      refs.guildSelect.innerHTML=filtered.map(g=>`<option value="${guildIdOf(g)}" ${guildIdOf(g)===state.selectedGuildId?'selected':''}>${esc(g.guild_name)} (#${guildIdOf(g)})</option>`).join('');
    }

    function renderSelected(){
      const g=selectedGuild();
      if(!g){
        refs.guildState.textContent='-';
        refs.guildVoice.textContent='-';
        refs.guildQueue.textContent='0';
        refs.guildCurrent.textContent='Nenhuma faixa tocando';
        refs.guildSettings.textContent='vol=100% | filter=off | loop=off | autoplay=off | 24/7=off';
        refs.guildModeration.textContent='max=0s | wl=0 | bl=0';
        refs.guildAvatar.removeAttribute('src');
        refs.guildProgressFill.style.width = '0%';
        refs.guildProgressText.textContent = '00:00 / 00:00';
        refs.guildWave.classList.remove('playing');
        refs.guildWave.classList.add('paused');
        refs.queuePreview.innerHTML='<li class="k">Fila vazia.</li>';
        return;
      }
      refs.guildState.innerHTML=`${badge(g)} <span class="k">${esc(g.player_state||'unknown')}</span>`;
      refs.guildVoice.textContent=g.voice_channel||'-';
      refs.guildQueue.textContent=String(g.queue_size||0);
      refs.guildCurrent.textContent=g.current||'Nenhuma faixa tocando';
      if (g.guild_icon_url) {
        refs.guildAvatar.src = g.guild_icon_url;
      } else {
        refs.guildAvatar.removeAttribute('src');
      }
      const s=g.settings||{};
      refs.volumeInput.value=String(s.volume_percent||100);
      refs.filterSelect.value=s.filter||'off';
      refs.loopSelect.value=s.loop_mode||'off';
      refs.autoplaySelect.value=s.autoplay?'true':'false';
      refs.staySelect.value=s.stay_connected?'true':'false';
      refs.guildSettings.textContent=`vol=${s.volume_percent||100}% | filter=${s.filter||'off'} | loop=${s.loop_mode||'off'} | autoplay=${s.autoplay?'on':'off'} | 24/7=${s.stay_connected?'on':'off'}`;
      const m=g.moderation||{};
      refs.guildModeration.textContent=`max=${m.max_track_duration_seconds||0}s | wl=${(m.whitelist||[]).length} | bl=${(m.blacklist||[]).length}`;
      refs.modDuration.value=String(m.max_track_duration_seconds||0);
      const elapsed = Number(g.current_elapsed_seconds || 0);
      const total = Number(g.current_duration_seconds || 0);
      const ratio = total > 0 ? Math.min(100, Math.max(0, (elapsed / total) * 100)) : 0;
      refs.guildProgressFill.style.width = `${ratio}%`;
      refs.guildProgressText.textContent = total > 0 ? `${fmtClock(elapsed)} / ${fmtClock(total)}` : 'ao vivo';
      refs.guildWave.classList.toggle('playing', !!g.playing);
      refs.guildWave.classList.toggle('paused', !g.playing);
      const q=Array.isArray(g.queue_preview)?g.queue_preview:[];
      refs.queuePreview.innerHTML=q.length?q.map(t=>`<li>${esc(t)}</li>`).join(''):'<li class="k">Fila vazia.</li>';
    }

    function render(payload){
      const guilds=payload.guilds||[];
      if(!state.selectedGuildId&&guilds.length){ state.selectedGuildId=guildIdOf(guilds[0]); }
      refs.botUser.textContent=payload.bot_user||'-';
      refs.guildsTotal.textContent=String(guilds.length);
      refs.commandCalls.textContent=String(payload.metrics?.command_calls||0);
      refs.commandErrors.textContent=String(payload.metrics?.command_errors||0);
      refs.avgLatency.textContent=`${fmtMs(payload.metrics?.average_latency_ms)} ms`;
      refs.uptime.textContent=fmtUptime(payload.runtime?.uptime_seconds);
      refs.runtimeBackend.textContent=payload.runtime?.repository_backend||'-';
      refs.lavalinkMode.textContent=payload.runtime?.lavalink_enabled?'enabled':'fallback';
      refs.sideBackend.textContent=payload.runtime?.repository_backend||'-';
      refs.sideLavalink.textContent=payload.runtime?.lavalink_enabled?'enabled':'fallback';
      refs.sideGuilds.textContent=String(guilds.length);
      const slo=payload.metrics?.slo_5m||{};
      refs.p95Play.textContent=fmtMs(slo.play_p95_ms);
      refs.p99Play.textContent=fmtMs(slo.play_p99_ms);
      refs.p95Search.textContent=fmtMs(slo.search_p95_ms);
      refs.p99Search.textContent=fmtMs(slo.search_p99_ms);
      refs.p50Play.textContent=`${fmtMs(slo.play_p50_ms)} ms`;
      refs.p50Search.textContent=`${fmtMs(slo.search_p50_ms)} ms`;
      renderGuilds(guilds);
      renderSelected();
    }

    async function tick(){
      try {
        const r=await fetch('/api/status',{cache:'no-store'});
        if(!r.ok){ throw new Error(`status ${r.status}`); }
        const j=await r.json();
        state.payload=j;
        if(j.auth){
          state.auth={
            role:j.auth.role||'viewer',
            oauth_enabled:!!j.auth.oauth_enabled,
            authenticated:(j.auth.source==='oauth'||j.auth.source==='token'),
            source:j.auth.source||'none',
          };
        }
        applyRoleUi();
        render(j);
        setConnection(true,'Online');
      } catch (err){
        log(`Falha ao atualizar painel: ${String(err)}`);
        setConnection(false,'Falha');
      }
    }

    async function callAction(action,payload={}){
      const g=selectedGuild();
      if(!g){ log('Selecione um servidor.'); return; }
      const token=(refs.tokenInput.value||'').trim();
      if(token){ localStorage.setItem('botmusica_admin_token',token); }
      try {
        const r=await fetch('/api/action',{
          method:'POST',
          headers:Object.assign({'Content-Type':'application/json'},token?{'X-Admin-Token':token}:{}),
          body:JSON.stringify(Object.assign({action,guild_id:guildIdOf(g)},payload)),
        });
        const j=await r.json();
        if(!r.ok||!j.ok){ log(`Falha: ${j.error||('status '+r.status)}`); return; }
        log(`OK: ${action}` + (j.summary?` | ${j.summary}`:''));
        if(j.moderation){ log(`Moderation: ${JSON.stringify(j.moderation)}`); }
        if(j.diagnostics){ log(`Diagnostics: ${JSON.stringify(j.diagnostics)}`); }
        await tick();
      } catch (err){
        log(`Erro de rede: ${String(err)}`);
      }
    }

    refs.loginBtn.addEventListener('click',()=>{window.location.href='/auth/login';});
    refs.logoutBtn.addEventListener('click',async()=>{await fetch('/auth/logout',{method:'POST'}); await refreshAuth(); await tick();});
    refs.tokenInput.addEventListener('input', applyRoleUi);
    refs.refreshBtn.addEventListener('click',tick);
    refs.guildSearch.addEventListener('input',()=>render(state.payload||{guilds:[]}));
    refs.guildList.addEventListener('click',(e)=>{
      const x=e.target.closest('.guild-item'); if(!x) return;
      const id=String(x.dataset.id||'').trim(); if(!id) return;
      state.selectedGuildId=id;
      render(state.payload||{guilds:[]});
    });
    refs.guildSelect.addEventListener('change',()=>{
      const id=String(refs.guildSelect.value||'').trim(); if(!id) return;
      state.selectedGuildId=id;
      render(state.payload||{guilds:[]});
    });

    document.querySelectorAll('.action').forEach(btn=>btn.addEventListener('click',()=>callAction(btn.dataset.action)));
    refs.setVolumeBtn.addEventListener('click',()=>callAction('set_volume',{volume_percent:Number(refs.volumeInput.value||'100')}));
    refs.setFilterBtn.addEventListener('click',()=>callAction('set_filter',{filter:refs.filterSelect.value}));
    refs.setLoopBtn.addEventListener('click',()=>callAction('set_loop',{loop_mode:refs.loopSelect.value}));
    refs.setAutoplayBtn.addEventListener('click',()=>callAction('set_autoplay',{enabled:refs.autoplaySelect.value==='true'}));
    refs.setStayBtn.addEventListener('click',()=>callAction('set_stay_connected',{enabled:refs.staySelect.value==='true'}));
    refs.removeBtn.addEventListener('click',()=>callAction('remove',{position:Number(refs.removePosition.value||'0')}));
    refs.moveBtn.addEventListener('click',()=>callAction('move',{source_pos:Number(refs.moveSource.value||'0'),target_pos:Number(refs.moveTarget.value||'0')}));
    refs.jumpBtn.addEventListener('click',()=>callAction('jump',{position:Number(refs.jumpPosition.value||'0')}));

    refs.controlRoomBtn.addEventListener('click',()=>callAction('control_room_create',{name:refs.controlRoomName.value||'bot-controle'}));
    refs.modDurationBtn.addEventListener('click',()=>callAction('moderation_set_duration',{seconds:Number(refs.modDuration.value||'0')}));
    refs.modWhitelistAdd.addEventListener('click',()=>callAction('moderation_add_whitelist',{domain:refs.modWhitelist.value||''}));
    refs.modWhitelistRemove.addEventListener('click',()=>callAction('moderation_remove_whitelist',{domain:refs.modWhitelist.value||''}));
    refs.modWhitelistClear.addEventListener('click',()=>callAction('moderation_clear_whitelist'));
    refs.modBlacklistAdd.addEventListener('click',()=>callAction('moderation_add_blacklist',{domain:refs.modBlacklist.value||''}));
    refs.modBlacklistRemove.addEventListener('click',()=>callAction('moderation_remove_blacklist',{domain:refs.modBlacklist.value||''}));
    refs.modBlacklistClear.addEventListener('click',()=>callAction('moderation_clear_blacklist'));
    refs.cacheStatsBtn.addEventListener('click',()=>callAction('cache_stats'));
    refs.cacheClearSearch.addEventListener('click',()=>callAction('cache_clear_search'));
    refs.cacheClearAll.addEventListener('click',()=>callAction('cache_clear_all'));
    refs.diagnosticsBtn.addEventListener('click',()=>callAction('diagnostics'));

    refs.tokenInput.value = localStorage.getItem('botmusica_admin_token') || '';
    refreshAuth().then(tick);
    setInterval(tick, 3000);
  </script>
</body>
</html>'''
