'use strict';
/* Video Parser · 视频工作台学习布局原型
   全部为内存中的示例数据：不联网、不读写文件、不调用模型或业务接口。 */
(() => {
  /* ---------- 基础工具 ---------- */
  const $ = (id) => document.getElementById(id);
  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ESC[c]);
  const pad = (n) => String(n).padStart(2, '0');
  const fmt = (seconds) => {
    const s = Math.max(0, Math.round(seconds));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${pad(m)}:${pad(s % 60)}`;
  };
  const toSeconds = (text) => text.split(':').reduce((sum, part) => sum * 60 + Number(part), 0);
  const stamp = () => {
    const d = new Date();
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  const mobileQuery = matchMedia('(max-width: 760px)');

  /* ---------- 图标：Lucide 形状，本地内嵌，不请求图标服务 ---------- */
  const ICONS = {
    clapperboard: '<path d="m12.296 3.464 3.02 3.956M20.2 6 3 11l-.9-2.4c-.3-1.1.3-2.2 1.3-2.5l13.5-4c1.1-.3 2.2.3 2.5 1.3zM3 11h18v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zm3.18-5.724 3.1 3.899"/>',
    'circle-play': '<path d="M9 9.003a1 1 0 0 1 1.517-.859l4.997 2.997a1 1 0 0 1 0 1.718l-4.997 2.997A1 1 0 0 1 9 14.996z"/><circle cx="12" cy="12" r="10"/>',
    captions: '<rect x="2" y="4" width="20" height="16" rx="3"/><path d="M6 10h3m-3 4h3m6-4h3m-3 4h3"/>',
    'list-checks': '<path d="m3 6 2 2 3-4m4 2h9M3 13h5m4 0h9M3 20h5m4 0h9"/>',
    'user-round': '<circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
    x: '<path d="m6 6 12 12M6 18 18 6"/>',
    settings: '<path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915"/><circle cx="12" cy="12" r="3"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32 1.41 1.41M2 12h2m16 0h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
    moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9"/>',
    send: '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11zM21.854 2.147l-10.94 10.939"/>',
    loader: '<path d="M21 12a9 9 0 1 1-6.219-8.56"/>',
    play: '<polygon points="6 3 20 12 6 21 6 3"/>',
    pause: '<rect x="14" y="4" width="4" height="16" rx="1"/><rect x="6" y="4" width="4" height="16" rx="1"/>',
    image: '<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
    'scan-eye': '<path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2"/><circle cx="12" cy="12" r="1"/><path d="M18.944 12.33a1 1 0 0 0 0-.66 7.5 7.5 0 0 0-13.888 0 1 1 0 0 0 0 .66 7.5 7.5 0 0 0 13.888 0"/>',
    link: '<path d="M9 17H7A5 5 0 0 1 7 7h2M15 7h2a5 5 0 1 1 0 10h-2M8 12h8"/>',
    download: '<path d="M12 15V3M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/>',
    copy: '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    'file-down': '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4M12 18v-6M9 15l3 3 3-3"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
  };
  const icon = (name, extra = '') => `<svg class="icon${extra ? ` ${extra}` : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${ICONS[name] || ''}</svg>`;

  /* ---------- 示例课程：一个 B站多分集视频，每一集是一个视频项目 ---------- */
  const COURSE = { title: '麻省理工公开课：线性代数', platform: '哔哩哔哩', video: 'BV1EXAMPLE01' };
  const LIST = [
    ['方程组的几何解释', '39:49'], ['矩阵消元', '47:41'], ['乘法和逆矩阵', '46:48'], ['A 的 LU 分解', '48:05'],
    ['转置、置换、向量空间 R', '47:42'], ['列空间和零空间', '46:01'], ['求解 Ax=0：主变量、特解', '43:22'],
    ['求解 Ax=b：可解性和解的结构', '47:51'], ['线性相关性、基、维数', '50:14'], ['四个基本子空间', '49:20'],
    ['矩阵空间、秩 1 矩阵和小世界图', '45:55'], ['图和网络', '49:43'], ['复习一', '47:23'], ['正交向量与子空间', '49:47'],
    ['子空间投影', '48:51'], ['投影矩阵和最小二乘', '48:05'], ['正交矩阵和 Gram-Schmidt 正交化', '49:09'],
    ['行列式及其性质', '49:12'], ['行列式公式和代数余子式', '50:52'], ['克拉默法则、逆矩阵、体积', '47:38'],
    ['特征值和特征向量', '51:23'], ['对角化和 A 的幂', '51:51'], ['微分方程和 exp(At)', '51:22'],
    ['马尔可夫矩阵、傅里叶级数', '51:16'], ['复习二', '47:19'], ['对称矩阵及正定性', '43:54'],
    ['复数矩阵和快速傅里叶变换', '46:21'], ['正定矩阵和最小值', '50:28'], ['相似矩阵和若尔当形', '46:44'],
    ['奇异值分解', '40:28'], ['线性变换及对应矩阵', '49:27'], ['基变换和图像压缩', '49:59'], ['复习三', '48:38'],
    ['左右逆和伪逆', '41:51'], ['期末复习', '43:06'],
  ];
  const EPISODES = LIST.map(([title, length], i) => ({ p: i + 1, title, duration: toSeconds(length) }));
  const TOTAL = EPISODES.length;
  const ep = (p) => EPISODES[p - 1];

  const TEMPLATES = [
    { id: 'summary', name: '内容摘要', desc: '一句话概括、核心要点和结论', source: 'both' },
    { id: 'chapters', name: '章节时间轴', desc: '按时间分段，每段一个标题和说明', source: 'both' },
    { id: 'notes', name: '学习笔记', desc: '知识点、公式、易错点和自测题，适合课程', source: 'both' },
    { id: 'breakdown', name: '短视频拆解', desc: '开头钩子、结构节奏、镜头和文案', source: 'both' },
    { id: 'storyboard', name: '分镜表', desc: '每张画面一行：时间、内容、景别和台词', source: 'both' },
    { id: 'script', name: '提取口播文案', desc: '把字幕整理成通顺、分段的文案', source: 'transcript' },
    { id: 'custom', name: '自定义', desc: '只按你写的要求分析', source: 'both' },
  ];
  const SOURCES = [['both', '字幕 + 画面'], ['transcript', '只用字幕'], ['frames', '只用画面']];
  const template = (id) => TEMPLATES.find((t) => t.id === id) || TEMPLATES[0];

  /* 示例分析记录：内容为原型示例文本，不是对资料库视频的实际分析 */
  const P1_NOTES = `## 主题概览
从「行图像」和「列图像」两个角度看线性方程组，并引出矩阵形式 Ax = b。

## 知识点
- [01:20] 行图像：二元方程组里每个方程是平面上的一条直线，解是两条直线的交点。
- [08:10] 列图像：把方程组看成列向量的线性组合，找出能组合出右端 b 的系数。
- [17:40] 三元方程组：行图像是三个平面交于一点，列图像是三维列向量的组合。
- [27:30] 矩阵形式 Ax = b：Ax 是 A 的各列的线性组合。
- [33:50] 关键问题：是否对任意 b，Ax = b 都有解？取决于 A 的各列能否组合出整个空间。

## 自测题
1. 用列图像解释方程组 2x − y = 0，−x + 2y = 3 的解 x = 1，y = 2。
2. 三维空间里，三个列向量在什么情况下组合不出所有的 b？`;
  const P2_CHAPTERS = `- [00:00] 消元的目标：把 A 化成上三角矩阵 U
- [04:25] 主元和消元乘数
- [10:40] 消元失败：主元为 0 时交换行；交换后仍没有主元，A 不可逆
- [16:55] 增广矩阵与回代求解
- [21:30] 用矩阵表示消元：初等矩阵 E₂₁、E₃₂
- [33:00] 置换矩阵 P：左乘交换行，右乘交换列
- [40:15] 逆矩阵的引入：怎样撤销一步消元`;
  const P3_NOTES = `## 主题概览
本讲用四种方式看矩阵乘法，然后讲逆矩阵：什么时候存在，怎样用 Gauss-Jordan 消元求出来。

## 知识点
- [00:42] 按元素算：C = AB 中，c₃₄ 等于 A 的第 3 行与 B 的第 4 列的点积。
- [05:36] 按列看：AB 的每一列都是 A 的各列的线性组合，系数来自 B 的对应列。
- [09:48] 按行看：AB 的每一行都是 B 的各行的线性组合，系数来自 A 的对应行。
- [13:12] 列乘行：AB 等于「A 的第 k 列 × B 的第 k 行」逐项相加，每一项的秩都不超过 1。
- [17:30] 分块乘法：把矩阵切成块，块与块按同样的规则相乘。
- [20:24] 逆矩阵：方阵 A 可逆时，A⁻¹A = I = AA⁻¹。
- [24:10] 奇异矩阵：如果有非零向量 x 使 Ax = 0，A 就不可逆。
- [31:05] Gauss-Jordan：对 [A | I] 做消元，左边化成 I 时，右边就是 A⁻¹。

## 公式
- cᵢⱼ = Σₖ aᵢₖbₖⱼ
- (m×n)(n×p) = (m×p)
- E[A | I] = [I | E]，其中 EA = I，所以 E = A⁻¹

## 易错点
- 一般 AB ≠ BA，乘法顺序不能随便交换。
- 只有 A 的列数等于 B 的行数时，AB 才有定义。
- 只有方阵才讨论两边的逆：A⁻¹A = I = AA⁻¹。

## 自测题
1. A 是 3×2、B 是 2×4，AB 是几行几列？
2. 为什么存在非零 x 使 Ax = 0 时，A 一定不可逆？
3. 用 Gauss-Jordan 求 [[1, 3], [2, 7]] 的逆（例题从 [38:20] 开始）。`;
  const P3_FOLLOWUP = 'A 的第 k 列是 m×1 的列向量，B 的第 k 行是 1×p 的行向量，相乘得到一个 m×p 矩阵。这个矩阵的每一列都是同一个列向量的倍数，所以秩不超过 1。把 k 从 1 加到 n，就得到 AB。课上从 [13:12] 开始讲，[15:40] 有一个具体例子。';
  const P3_CHAPTERS = `- [00:00] 矩阵乘法：按元素算
- [05:36] 按列看：A 的列的组合
- [09:48] 按行看：B 的行的组合
- [13:12] 列乘行
- [17:30] 分块乘法
- [20:24] 逆矩阵（方阵）
- [24:10] 奇异矩阵：什么时候没有逆
- [31:05] Gauss-Jordan 求逆
- [38:20] 例题：求 [[1, 3], [2, 7]] 的逆`;

  function record(id, tpl, created, text, extra = {}) {
    return { id, template: tpl, name: template(tpl).name, created, source: '字幕 + 画面（平台字幕）', frames: 12, model: '示例模型', prompt: '', text, followups: [], ...extra };
  }

  function generatedText(p, tpl) {
    const e = ep(p);
    const [t1, t2, t3] = [0.12, 0.45, 0.8].map((r) => `[${fmt(e.duration * r)}]`);
    if (tpl === 'notes') {
      return `## 主题概览\n（示例内容）这里显示模型根据「P${p} ${e.title}」的字幕和画面整理的学习笔记。\n\n## 知识点\n- ${t1} 第一个知识点的说明。\n- ${t2} 第二个知识点的说明。\n- ${t3} 第三个知识点的说明。\n\n## 易错点\n- 示例易错点。\n\n## 自测题\n1. 示例自测题一。\n2. 示例自测题二。`;
    }
    if (tpl === 'chapters') return `（示例内容）P${p} ${e.title}\n\n- [00:00] 开场与本讲目标\n- ${t1} 第一部分\n- ${t2} 第二部分\n- ${t3} 小结`;
    return `（示例内容）这里显示「${template(tpl).name}」模板的结果。结果里的时间点同样可以点击，例如 ${t1}、${t2}。`;
  }

  /* ---------- 状态 ---------- */
  function createState() {
    return {
      page: 'workspace',
      tab: 'ai',
      p: 3,
      time: 0,
      playing: false,
      learned: new Set([1, 2]),
      archived: new Set([1, 2, 3, 4, 5, 6]),
      archiving: new Map(),
      analyzing: new Set(),
      records: {
        1: [record('r1-notes', 'notes', '10-12 20:41', P1_NOTES)],
        2: [record('r2-chapters', 'chapters', '10-13 21:05', P2_CHAPTERS)],
        3: [
          record('r3-notes', 'notes', '10-14 21:30', P3_NOTES, { followups: [{ q: '列乘行那部分再展开讲讲', a: P3_FOLLOWUP }] }),
          record('r3-chapters', 'chapters', '10-14 21:12', P3_CHAPTERS),
        ],
      },
      active: {},
      form: { template: 'summary', source: 'both', prompt: '' },
      newOpen: null,
      listOpen: false,
      menuOpen: false,
      seq: 0,
    };
  }
  let S = createState();
  const recordsOf = (p) => S.records[p] || [];
  const activeRecord = () => {
    const list = recordsOf(S.p);
    return list.find((r) => r.id === S.active[S.p]) || list[0] || null;
  };
  const nextUnlearned = () => (EPISODES.find((e) => !S.learned.has(e.p)) || {}).p || null;

  /* ---------- 简易 Markdown：标题、列表、段落；[mm:ss] 时间点变成跳转按钮 ---------- */
  function inline(text, duration) {
    return esc(text)
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\[(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\]/g, (match, h, m, s) => {
        const t = Number(h || 0) * 3600 + Number(m) * 60 + Number(s);
        if (t > duration) return match;
        return `<button type="button" class="time-link" data-seek="${t}" aria-label="跳到 ${fmt(t)}">${fmt(t)}</button>`;
      });
  }
  function markdown(text, duration) {
    const out = [];
    let list = null;
    const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
    const open = (tag) => { if (list !== tag) { close(); out.push(`<${tag}>`); list = tag; } };
    for (const raw of text.split('\n')) {
      const line = raw.trim();
      let m;
      if (!line) close();
      else if ((m = line.match(/^##\s+(.*)$/))) { close(); out.push(`<h4>${inline(m[1], duration)}</h4>`); }
      else if ((m = line.match(/^-\s+(.*)$/))) { open('ul'); out.push(`<li>${inline(m[1], duration)}</li>`); }
      else if ((m = line.match(/^\d+\.\s+(.*)$/))) { open('ol'); out.push(`<li>${inline(m[1], duration)}</li>`); }
      else { close(); out.push(`<p>${inline(line, duration)}</p>`); }
    }
    close();
    return out.join('');
  }

  /* ---------- 渲染 ---------- */
  function withFocus(fn) {
    const active = document.activeElement;
    const key = active && active.dataset ? active.dataset.focusKey || '' : '';
    const list = $('episode-list');
    const listTop = list ? list.scrollTop : 0;
    fn();
    if ($('episode-list')) $('episode-list').scrollTop = listTop;
    if (key) {
      const el = document.querySelector(`[data-focus-key="${CSS.escape(key)}"]`);
      if (el && el !== document.activeElement && el.getClientRects().length) el.focus({ preventScroll: true });
    }
  }

  function render() {
    withFocus(() => {
      document.querySelectorAll('[role="tab"]').forEach((b) => {
        const selected = b.dataset.tab === S.tab;
        b.setAttribute('aria-selected', String(selected));
        b.tabIndex = selected ? 0 : -1;
      });
      $('tabpanel').setAttribute('aria-labelledby', `tab-${S.tab}`);
      $('work-grid').className = `work-grid ${S.tab === 'ai' ? 'ai' : 'full'}`;
      $('tabpanel').innerHTML = S.tab === 'cover' ? coverHtml() : S.tab === 'video' ? mediaHtml() : studyHtml();
      $('inspector').className = 'panel details-panel';
      $('inspector').innerHTML = inspectorHtml();
      const details = $('new-analysis');
      if (details) details.addEventListener('toggle', () => { S.newOpen = details.open; });
    });
    renderPlayer();
  }

  function coverHtml() {
    const e = ep(S.p);
    return `<div class="media-stage"><div class="cover-art"><span class="screen-label">封面（示例）</span><strong>${esc(COURSE.title)}</strong><span>P${e.p} ${esc(e.title)}</span></div></div>`;
  }

  function mediaHtml() {
    const e = ep(S.p);
    if (S.archived.has(S.p)) {
      return `<div class="player" id="player">
        <div class="screen" aria-hidden="true"><span class="screen-label">示例画面 · 不播放真实视频</span><strong>P${e.p} · ${esc(e.title)}</strong><span class="screen-time" id="screen-time">00:00</span></div>
        <div class="controls">
          <button type="button" class="icon-button" id="play-button" data-action="toggle-play" data-focus-key="play" aria-label="播放">${icon('play')}</button>
          <span class="player-time" id="player-time"></span>
          <div class="track" id="player-track" role="slider" tabindex="0" data-focus-key="track" aria-label="播放进度" aria-valuemin="0" aria-valuemax="${e.duration}"><i id="track-fill"></i></div>
        </div>
      </div>`;
    }
    if (S.archiving.has(S.p)) {
      const v = S.archiving.get(S.p);
      return `<div class="media-stage"><div class="stage-status"><strong>视频下载与归档</strong><p role="status" id="stage-progress-text">正在下载（示例）· ${v}%</p><div class="bar"><i id="stage-progress-bar" style="width:${v}%"></i></div></div></div>`;
    }
    return `<div class="media-stage"><div class="empty-stage">${icon('circle-play')}<p>选择画质并下载归档后预览</p></div></div>`;
  }

  function studyHtml() {
    const e = ep(S.p);
    return `<div class="study">
      <div class="study-media" id="study-media">
        ${mediaHtml()}
        <div class="study-episode">
          <h2 id="episode-title" tabindex="-1" data-focus-key="episode-title">P${e.p} · ${esc(e.title)}</h2>
          <label class="check-line"><input type="checkbox" id="learned-current" data-learned="${e.p}" data-focus-key="learned-current" ${S.learned.has(e.p) ? 'checked' : ''}>已学完</label>
        </div>
      </div>
      <div class="study-notes" id="study-notes">${recordsHtml()}${formHtml()}</div>
    </div>`;
  }

  function recordsHtml() {
    const list = recordsOf(S.p);
    const r = activeRecord();
    if (!r) return '';
    const duration = ep(S.p).duration;
    const options = list.map((x) => `<option value="${x.id}"${x.id === r.id ? ' selected' : ''}>${esc(x.name)} · ${x.created}${x.followups.length ? ` · 追问 ${x.followups.length}` : ''}</option>`).join('');
    const followups = r.followups.map((f) => `<section class="followup" aria-label="追问：${esc(f.q)}"><p class="followup-q"><span>追问</span>${esc(f.q)}</p><div class="md">${markdown(f.a, duration)}</div></section>`).join('');
    return `<section class="panel records" aria-labelledby="records-title">
      <div class="record-bar">
        <h3 class="panel-title" id="records-title" tabindex="-1" data-focus-key="records-title">分析记录</h3>
        <select id="record-select" data-focus-key="record-select" aria-label="选择分析记录">${options}</select>
      </div>
      <article class="record" id="record" aria-label="${esc(r.name)}结果">
        <p class="record-meta">${esc(r.source)} · ${r.frames} 张画面 · ${esc(r.model)}</p>
        ${r.prompt ? `<p class="record-meta">要求：${esc(r.prompt)}</p>` : ''}
        <div class="record-actions">
          <button type="button" class="btn small" data-action="file">${icon('copy')}复制</button>
          <button type="button" class="btn small" data-action="file">${icon('file-down')}导出 Markdown</button>
          <button type="button" class="btn small" data-action="file">${icon('file-down')}导出 Word</button>
        </div>
        <div class="md" id="record-text">${markdown(r.text, duration)}</div>
        ${followups}
        <form class="ask" id="ask-form" novalidate>
          <label class="sr-only" for="ask-input">追问这次分析</label>
          <textarea id="ask-input" rows="2" maxlength="2000" data-focus-key="ask-input" placeholder="接着问，例如：第二部分再展开讲讲"></textarea>
          <button type="submit" class="btn" data-focus-key="ask-submit">${icon('send')}追问</button>
        </form>
        <p class="hint">追问会带上这次的字幕、画面和之前的问答一起发送。</p>
      </article>
    </section>`;
  }

  function formHtml() {
    const hasRecords = recordsOf(S.p).length > 0;
    const open = S.newOpen ?? !hasRecords;
    const chips = TEMPLATES.map((t) => `<button type="button" class="chip-button" data-template="${t.id}" data-focus-key="tpl-${t.id}" aria-pressed="${S.form.template === t.id}">${t.name}</button>`).join('');
    const sources = SOURCES.map(([value, label]) => `<label><input type="radio" name="analysis-source" value="${value}" data-focus-key="src-${value}" ${S.form.source === value ? 'checked' : ''}>${label}</label>`).join('');
    return `<details class="panel new-analysis" id="new-analysis"${open ? ' open' : ''}>
      <summary data-focus-key="new-summary">${hasRecords ? '新建分析' : 'AI 分析'}</summary>
      ${hasRecords ? '' : '<p class="analysis-empty">这一讲还没有分析记录。选「学习笔记」或「章节时间轴」，结果会显示在视频旁边。</p>'}
      <div class="field">
        <span class="field-label" id="tpl-label">分析模板</span>
        <div class="chips" role="group" aria-labelledby="tpl-label">${chips}</div>
        <p class="hint" id="tpl-desc">${esc(template(S.form.template).desc)}</p>
      </div>
      <fieldset class="field">
        <legend class="field-label">分析依据</legend>
        <div class="segment">${sources}</div>
        <p class="hint">使用平台字幕：612 条，到 ${fmt(ep(S.p).duration - 8)}。画面按镜头切换自动选取 12 张。</p>
      </fieldset>
      <div class="field">
        <label class="field-label" for="prompt">补充要求（选填）</label>
        <textarea id="prompt" rows="2" maxlength="4000" data-focus-key="prompt" placeholder="选填，例如：只整理和特征值有关的部分">${esc(S.form.prompt)}</textarea>
      </div>
      <p class="hint">预计发送约 1.6 万 tokens（字幕约 1.2 万 · 画面 12 张），输出约 1,500。</p>
      <div class="form-actions">
        <button type="button" class="btn primary" id="analyze-button" data-action="analyze" data-focus-key="analyze"></button>
      </div>
    </details>`;
  }

  function inspectorHtml() {
    const e = ep(S.p);
    const full = S.tab !== 'ai';
    const archived = S.archived.has(e.p);
    const archiving = S.archiving.has(e.p);
    const size = `${(e.duration * 0.111).toFixed(1)} MB`;
    const meta = full ? `<dl class="media-meta">
        <div><dt>视频时长</dt><dd>${fmt(e.duration)}</dd></div>
        <div><dt>分集</dt><dd>P${e.p}</dd></div>
        <div><dt>分辨率</dt><dd>${archived ? '1920 × 1080' : '—'}</dd></div>
        <div><dt>实际大小</dt><dd>${archived ? size : '—'}</dd></div>
      </dl>
      <div class="field"><label class="field-label" for="quality">归档画质</label>
        <select id="quality"><option>1080P 高清${archived ? ' · 已归档' : ''}</option><option>720P 高清</option><option>480P 清晰</option></select></div>` : '';
    const archive = archived ? (full ? '<p class="status">所选视频已归档</p>' : '')
      : `<button type="button" class="btn primary block" id="archive-button" data-action="archive" data-focus-key="archive"${archiving ? ' aria-disabled="true"' : ''}>${archiving ? icon('loader', 'spin') : icon('download')}${archiving ? '下载归档中…' : full ? '下载并归档' : '先归档视频'}</button>
        <p class="status">${archiving ? '正在下载归档（示例，不会真的下载）。' : '这一讲还没有归档。'}</p>`;
    return `<h2 class="panel-title" id="details-heading">${full ? '项目与归档' : '当前项目'}</h2>
      <div class="inspector-main">
        <div class="identity"><h3>${esc(COURSE.title)}</h3><span class="platform-mark">${COURSE.platform}${full ? '' : ` · P${e.p}`}</span></div>
        ${meta}${archive}
      </div>
      ${episodesHtml()}
      ${full ? `<p class="project-box">项目文件夹：library/bilibili/${COURSE.video}__P${String(e.p).padStart(3, '0')}/</p>` : ''}`;
  }

  function episodesHtml() {
    const rows = EPISODES.map((e) => {
      const learned = S.learned.has(e.p);
      const current = e.p === S.p;
      return `<li class="episode${learned ? ' learned' : ''}${current ? ' current' : ''}" data-row="${e.p}">
        <input type="checkbox" id="learned-${e.p}" data-learned="${e.p}" data-focus-key="learned-${e.p}" ${learned ? 'checked' : ''} aria-label="P${e.p} ${esc(e.title)} 已学完">
        <button type="button" class="episode-open" data-open="${e.p}" data-focus-key="open-${e.p}"${current ? ' aria-current="true"' : ''}><span class="ep-no">P${e.p}</span><span class="ep-title">${esc(e.title)}</span><span class="ep-meta">${S.archived.has(e.p) ? fmt(e.duration) : '未归档'}</span></button>
      </li>`;
    }).join('');
    return `<section class="episodes${S.listOpen ? ' open' : ''}" id="episodes" aria-labelledby="episodes-title">
      <div class="episodes-head"><h3 id="episodes-title">分集</h3><span class="learned-count" id="learned-count"></span></div>
      <div class="progress" aria-hidden="true"><i id="learned-bar"></i></div>
      <p class="episodes-next" id="episodes-next"></p>
      <div class="episodes-actions">
        <button type="button" class="btn small" id="continue-button" data-action="continue" data-focus-key="continue"></button>
        <button type="button" class="btn small episodes-toggle" id="episodes-toggle" data-action="toggle-list" data-focus-key="episodes-toggle" aria-controls="episode-list" aria-expanded="${S.listOpen}">${S.listOpen ? '收起分集列表' : '展开分集列表'}</button>
      </div>
      <ol class="episode-list" id="episode-list" aria-label="分集列表">${rows}</ol>
    </section>`;
  }

  /* 只更新已学完相关的显示，不重绘：焦点和列表滚动位置保持不变 */
  function syncLearned() {
    const n = S.learned.size;
    const next = nextUnlearned();
    document.querySelectorAll('[data-learned]').forEach((box) => { box.checked = S.learned.has(Number(box.dataset.learned)); });
    document.querySelectorAll('.episode').forEach((row) => row.classList.toggle('learned', S.learned.has(Number(row.dataset.row))));
    if (!$('learned-count')) return;
    $('learned-count').textContent = `已学完 ${n} / ${TOTAL}`;
    $('learned-bar').style.width = `${((n / TOTAL) * 100).toFixed(2)}%`;
    $('episodes-next').innerHTML = next ? `学到 <b>P${next} ${esc(ep(next).title)}</b>` : `<b>${TOTAL} 讲全部学完</b>`;
    const cont = $('continue-button');
    cont.hidden = !next || next === S.p;
    cont.textContent = next ? `继续学 P${next}` : '';
  }

  function syncAnalyzeButton() {
    const b = $('analyze-button');
    if (!b) return;
    const busy = S.archiving.has(S.p) ? '归档中…' : S.analyzing.has(S.p) ? '分析中…' : '';
    if (busy) b.setAttribute('aria-disabled', 'true'); else b.removeAttribute('aria-disabled');
    b.innerHTML = busy ? `${icon('loader', 'spin')}${busy}` : `${icon(S.archived.has(S.p) ? 'scan-eye' : 'download')}${S.archived.has(S.p) ? '开始分析' : '归档并分析'}`;
  }

  function renderPlayer() {
    syncLearned();
    syncAnalyzeButton();
    const e = ep(S.p);
    const fill = $('track-fill');
    if (!fill) return;
    const text = `${fmt(S.time)} / ${fmt(e.duration)}`;
    $('player-time').textContent = text;
    $('screen-time').textContent = fmt(S.time);
    fill.style.width = `${((S.time / e.duration) * 100).toFixed(2)}%`;
    const track = $('player-track');
    track.setAttribute('aria-valuenow', String(Math.round(S.time)));
    track.setAttribute('aria-valuetext', text);
    const play = $('play-button');
    play.innerHTML = icon(S.playing ? 'pause' : 'play');
    play.setAttribute('aria-label', S.playing ? '暂停' : '播放');
  }

  function scrollListToCurrent() {
    const list = $('episode-list');
    const row = list && list.querySelector('.current');
    if (row && list.clientHeight) list.scrollTop = row.offsetTop - (list.clientHeight - row.offsetHeight) / 2;
  }

  /* ---------- 播放演示 ---------- */
  let timer = null;
  function pause() {
    S.playing = false;
    clearInterval(timer);
    timer = null;
    renderPlayer();
  }
  function play() {
    if (S.time >= ep(S.p).duration) S.time = 0;
    S.playing = true;
    timer = setInterval(() => {
      S.time = Math.min(ep(S.p).duration, S.time + 1);
      if (S.time >= ep(S.p).duration) pause();
      else renderPlayer();
    }, 1000);
    renderPlayer();
  }
  function seek(t, quiet = false) {
    S.time = Math.max(0, Math.min(ep(S.p).duration, t));
    renderPlayer();
    if (!quiet) announce(`视频已跳到 ${fmt(S.time)}，笔记保持不动`);
  }

  /* ---------- 动作 ---------- */
  function listCollapsible() {
    const toggle = $('episodes-toggle');
    return !!toggle && getComputedStyle(toggle).display !== 'none';
  }

  function focusFirst(...elements) {
    const el = elements.find((x) => x && x.getClientRects().length);
    if (el) el.focus({ preventScroll: true });
  }

  function selectEpisode(p, { focusTitle = false } = {}) {
    if (!ep(p) || p === S.p) return;
    const collapse = listCollapsible() && S.listOpen;
    pause();
    S.p = p;
    S.time = 0;
    S.newOpen = null;
    if (collapse) S.listOpen = false;
    render();
    scrollListToCurrent();
    if (focusTitle || collapse) focusFirst($('episode-title'), document.querySelector(`[data-open="${p}"]`), $('episodes-toggle'));
    announce(`已切换到 P${p} ${ep(p).title}`);
  }

  function setLearned(p, value) {
    if (value) S.learned.add(p); else S.learned.delete(p);
    syncLearned();
    announce(`P${p} ${value ? '已标记为已学完' : '已取消已学完'}。已学完 ${S.learned.size} / ${TOTAL}`);
  }

  function setTab(tab, focus = false) {
    if (S.tab !== tab) {
      S.tab = tab;
      render();
    }
    if (focus) $(`tab-${tab}`).focus();
  }

  function archive(p, then) {
    if (S.archived.has(p) || S.archiving.has(p)) return;
    S.archiving.set(p, 0);
    if (S.p === p) render();
    const step = () => {
      const v = Math.min(100, S.archiving.get(p) + 25);
      if (v < 100) {
        S.archiving.set(p, v);
        if (S.p === p && $('stage-progress-bar')) {
          $('stage-progress-bar').style.width = `${v}%`;
          $('stage-progress-text').textContent = `正在下载（示例）· ${v}%`;
        }
        setTimeout(step, 220);
        return;
      }
      S.archiving.delete(p);
      S.archived.add(p);
      const hadFocus = document.activeElement && document.activeElement.dataset.focusKey === 'archive';
      if (S.p === p) {
        render();
        if (hadFocus) focusFirst($('play-button'), $('analyze-button'));
      }
      else document.querySelectorAll(`[data-open="${p}"] .ep-meta`).forEach((m) => { m.textContent = fmt(ep(p).duration); });
      toast(`P${p} 已归档（原型模拟，没有下载）。`);
      if (then) then();
    };
    setTimeout(step, 220);
  }

  function analyze() {
    const p = S.p;
    if (S.analyzing.has(p) || S.archiving.has(p)) return;
    const run = () => {
      const tpl = S.form.template;
      const prompt = S.form.prompt.trim();
      S.analyzing.add(p);
      syncAnalyzeButton();
      setTimeout(() => {
        S.analyzing.delete(p);
        S.seq += 1;
        const r = record(`r${p}-new${S.seq}`, tpl, stamp(), generatedText(p, tpl), { prompt });
        S.records[p] = [r, ...recordsOf(p)];
        S.active[p] = r.id;
        if (S.p === p) {
          const lostFocus = !document.activeElement || document.activeElement === document.body || document.activeElement.dataset.focusKey === 'analyze';
          S.newOpen = false;
          render();
          if (lostFocus && $('records-title')) $('records-title').focus({ preventScroll: true });
        }
        toast(`P${p} 的「${r.name}」已生成（示例内容）。`);
        announce(`P${p} 的${r.name}已生成，显示在视频旁边`);
      }, 900);
    };
    if (!S.archived.has(p)) archive(p, run);
    else run();
  }

  function ask(form) {
    const input = form.querySelector('textarea');
    const q = input.value.trim();
    const r = activeRecord();
    if (!q || !r) return;
    const t = Math.min(ep(S.p).duration - 60, 600);
    r.followups.push({ q, a: `（示例回答）这里显示模型对「${q}」的回答。回答里的时间点同样可以点击，例如 [${fmt(t)}]。` });
    render();
    announce('追问已添加（示例回答）');
  }

  /* ---------- 导航与菜单 ---------- */
  const TITLES = { workspace: '视频工作台', transcription: '字幕与转写', tasks: '任务中心', accounts: '账号与登录' };
  function go(page, { focusTitle = false } = {}) {
    if (page !== 'workspace') pause();
    S.page = page;
    document.querySelectorAll('[data-page-section]').forEach((sec) => { sec.hidden = sec.dataset.pageSection !== page; });
    document.querySelectorAll('#nav [data-page]').forEach((b) => {
      if (b.dataset.page === page) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
    });
    $('page-title').textContent = TITLES[page];
    if (S.menuOpen) setMenu(false);
    window.scrollTo(0, 0);
    if (focusTitle) $('page-title').focus({ preventScroll: true });
  }

  function syncInert() {
    const mobile = mobileQuery.matches;
    $('sidebar').inert = mobile && !S.menuOpen;
    $('shell').inert = mobile && S.menuOpen;
    if (mobile && S.menuOpen) {
      $('sidebar').setAttribute('role', 'dialog');
      $('sidebar').setAttribute('aria-modal', 'true');
    } else {
      $('sidebar').removeAttribute('role');
      $('sidebar').removeAttribute('aria-modal');
    }
  }

  function setMenu(open, restoreFocus = false) {
    S.menuOpen = open;
    $('sidebar').classList.toggle('open', open);
    $('nav-scrim').hidden = !open;
    $('menu-button').setAttribute('aria-expanded', String(open));
    syncInert();
    if (open) ($('sidebar').querySelector('[aria-current="page"]') || $('sidebar').querySelector('button')).focus();
    else if (restoreFocus) $('menu-button').focus();
  }

  /* ---------- 提示、弹窗、主题 ---------- */
  function announce(message) {
    const el = $('sr-status');
    el.textContent = '';
    setTimeout(() => { el.textContent = message; }, 30);
  }

  function toast(message) {
    const region = $('toast-region');
    const el = document.createElement('div');
    el.className = 'toast';
    el.innerHTML = `${icon('info')}<p class="toast-text"></p><button type="button" class="toast-close" aria-label="关闭提示">${icon('x')}</button>`;
    el.querySelector('.toast-text').textContent = message;
    el.querySelector('.toast-close').addEventListener('click', () => el.remove());
    region.append(el);
    while (region.children.length > 2) region.firstElementChild.remove();
    setTimeout(() => el.remove(), 5000);
  }

  let opener = null;
  function openDialog(id) {
    opener = document.activeElement;
    $(id).showModal();
    $(id).querySelector('.dialog-foot button').focus();
  }

  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    const b = $('theme-button');
    b.innerHTML = icon(theme === 'dark' ? 'sun' : 'moon');
    b.setAttribute('aria-label', theme === 'dark' ? '切换到浅色主题' : '切换到深色主题');
    b.title = theme === 'dark' ? '浅色主题' : '深色主题';
  }

  /* ---------- 事件 ---------- */
  document.addEventListener('click', (event) => {
    const t = event.target.closest('button');
    if (!t || t.disabled || t.getAttribute('aria-disabled') === 'true') return;
    const d = t.dataset;
    if (d.page) return go(d.page, { focusTitle: true });
    if (d.go) return go(d.go, { focusTitle: true });
    if (d.closeDialog != null) return t.closest('dialog').close();
    if (d.tab) return setTab(d.tab);
    if (d.seek != null) return seek(Number(d.seek));
    if (d.open) return selectEpisode(Number(d.open));
    if (d.template) {
      S.form.template = d.template;
      S.form.source = template(d.template).source;
      document.querySelectorAll('[data-template]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.template === d.template)));
      document.querySelectorAll('input[name="analysis-source"]').forEach((r) => { r.checked = r.value === S.form.source; });
      $('tpl-desc').textContent = template(d.template).desc;
      return undefined;
    }
    switch (d.action || t.id) {
      case 'toggle-play': return S.playing ? pause() : play();
      case 'continue': return selectEpisode(nextUnlearned(), { focusTitle: true });
      case 'toggle-list':
        S.listOpen = !S.listOpen;
        $('episodes').classList.toggle('open', S.listOpen);
        t.setAttribute('aria-expanded', String(S.listOpen));
        t.textContent = S.listOpen ? '收起分集列表' : '展开分集列表';
        if (S.listOpen) scrollListToCurrent();
        return undefined;
      case 'archive': return archive(S.p);
      case 'analyze': return analyze();
      case 'file': return toast('原型不生成文件；正式应用里这里复制或导出这条记录。');
      case 'menu-button': return setMenu(!S.menuOpen);
      case 'nav-scrim': return setMenu(false, true);
      case 'settings-button': return openDialog('settings-dialog');
      case 'theme-button': return setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
      default: return undefined;
    }
  });

  document.addEventListener('change', (event) => {
    const t = event.target;
    if (t.dataset.learned) return setLearned(Number(t.dataset.learned), t.checked);
    if (t.id === 'record-select') {
      S.active[S.p] = t.value;
      return render();
    }
    if (t.name === 'analysis-source') S.form.source = t.value;
    return undefined;
  });

  document.addEventListener('input', (event) => {
    if (event.target.id === 'prompt') S.form.prompt = event.target.value;
  });

  document.addEventListener('submit', (event) => {
    event.preventDefault();
    if (event.target.id === 'ask-form') return ask(event.target);
    if (event.target.id === 'source-form') toast('原型不联网解析；示例课程已经载入。');
    return undefined;
  });

  $('tabpanel').addEventListener('pointerdown', (event) => {
    const track = event.target.closest('#player-track');
    if (!track) return;
    const box = track.getBoundingClientRect();
    seek(((event.clientX - box.left) / box.width) * ep(S.p).duration, true);
  });

  document.addEventListener('keydown', (event) => {
    const t = event.target;
    if (t.getAttribute && t.getAttribute('role') === 'tab') {
      const order = ['cover', 'video', 'ai'];
      const i = order.indexOf(t.dataset.tab);
      const next = { ArrowRight: (i + 1) % 3, ArrowLeft: (i + 2) % 3, Home: 0, End: 2 }[event.key];
      if (next != null) { event.preventDefault(); setTab(order[next], true); }
      return;
    }
    if (t.id === 'player-track') {
      const step = { ArrowRight: 5, ArrowUp: 5, ArrowLeft: -5, ArrowDown: -5 }[event.key];
      if (step) { event.preventDefault(); seek(S.time + step, true); }
      if (event.key === 'Home') { event.preventDefault(); seek(0, true); }
      if (event.key === 'End') { event.preventDefault(); seek(ep(S.p).duration, true); }
      return;
    }
    if (t.id === 'ask-input' && (event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      event.preventDefault();
      ask(t.form);
      return;
    }
    if (event.key === 'Escape' && S.menuOpen) setMenu(false, true);
  });

  $('settings-dialog').addEventListener('close', () => { if (opener) opener.focus(); });
  $('settings-dialog').addEventListener('click', (event) => { if (event.target === event.currentTarget) event.currentTarget.close(); });
  mobileQuery.addEventListener('change', () => { if (!mobileQuery.matches && S.menuOpen) setMenu(false); syncInert(); });

  /* ---------- 启动 ---------- */
  document.querySelectorAll('[data-icon]').forEach((el) => { el.innerHTML = icon(el.dataset.icon); });
  setTheme('light');
  go('workspace');
  render();
  scrollListToCurrent();
  syncInert();
  window.__prototype = { get state() { return S; } };
})();
