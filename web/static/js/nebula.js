/**
 * Code Nebula (代碼星雲圖) - D3.js 力導向知識圖譜視覺化引擎
 * 支援多層級中心輻射遍歷、即時搜尋補全、代碼自省抽屜、路徑高亮與圖片匯出
 */

(function () {
  'use strict';

  const Nebula = {
    state: {
      centerId: 'get_health_status',
      depth: 2,
      direction: 'both',
      includeExternal: false,
      graphData: null,
      selectedNode: null,
      historyStack: [],
      historyIndex: -1,
      simulation: null,
      svg: null,
      g: null,
      zoom: null,
      width: 0,
      height: 0,
      debounceTimer: null,
    },

    elements: {},

    init() {
      this.cacheDom();
      this.bindEvents();
      this.initD3();
      this.fetchProjectInfo();
      // 預設載入入口符號星雲圖
      this.loadGraph(this.state.centerId);
    },

    cacheDom() {
      this.elements = {
        container: document.getElementById('view-nebula-container'),
        canvasWrapper: document.getElementById('nebula-canvas-wrapper'),
        svg: document.getElementById('nebula-svg'),
        currentProjectName: document.getElementById('nebula-current-project-name'),
        currentProjectPath: document.getElementById('nebula-current-project-path'),
        customPathInput: document.getElementById('nebula-custom-path-input'),
        switchProjectBtn: document.getElementById('nebula-switch-project-btn'),
        resetProjectBtn: document.getElementById('nebula-reset-project-btn'),
        symbolInput: document.getElementById('nebula-symbol-input'),
        suggestions: document.getElementById('nebula-suggestions'),
        depthSlider: document.getElementById('nebula-depth-slider'),
        depthVal: document.getElementById('nebula-depth-val'),
        extChk: document.getElementById('nebula-ext-chk'),
        exportBtn: document.getElementById('nebula-export-btn'),
        rescanBtn: document.getElementById('nebula-rescan-btn'),
        resetCamBtn: document.getElementById('nebula-reset-cam-btn'),
        emptyState: document.getElementById('nebula-empty-state'),
        infoBadge: document.getElementById('nebula-info-badge'),
        inspector: document.getElementById('nebula-inspector'),
        closeInspectorBtn: document.getElementById('close-inspector-btn'),
        inspectorBackBtn: document.getElementById('inspector-back-btn'),
        inspectorFwdBtn: document.getElementById('inspector-fwd-btn'),
        inspectorTypeBadge: document.getElementById('inspector-type-badge'),
        inspectorName: document.getElementById('inspector-name'),
        inspectorPath: document.getElementById('inspector-path'),
        inspectorDocGroup: document.getElementById('inspector-doc-group'),
        inspectorDoc: document.getElementById('inspector-doc'),
        inspectorSig: document.getElementById('inspector-sig'),
        inspectorCode: document.getElementById('inspector-code'),
        inspectorCallersCount: document.getElementById('inspector-callers-count'),
        inspectorCallersList: document.getElementById('inspector-callers-list'),
        inspectorCalleesCount: document.getElementById('inspector-callees-count'),
        inspectorCalleesList: document.getElementById('inspector-callees-list'),
        inspectorRecenterBtn: document.getElementById('inspector-recenter-btn'),
        inspectorCopyPathBtn: document.getElementById('inspector-copy-path-btn'),
      };
    },

    bindEvents() {
      // 專案切換與匯入
      this.elements.switchProjectBtn?.addEventListener('click', () => {
        const pathVal = this.elements.customPathInput.value.trim();
        if (pathVal) {
          this.switchProject(pathVal);
        } else {
          alert('請先輸入或貼上本機專案目錄路徑');
        }
      });

      this.elements.customPathInput?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          const pathVal = this.elements.customPathInput.value.trim();
          if (pathVal) this.switchProject(pathVal);
        }
      });

      this.elements.resetProjectBtn?.addEventListener('click', () => {
        this.resetProject();
      });

      // 搜尋自動補全
      this.elements.symbolInput?.addEventListener('input', (e) => {
        const q = e.target.value.trim();
        clearTimeout(this.state.debounceTimer);
        this.state.debounceTimer = setTimeout(() => this.fetchSuggestions(q), 200);
      });

      this.elements.symbolInput?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          const q = e.target.value.trim();
          if (q) {
            this.hideSuggestions();
            this.loadGraph(q);
          }
        }
      });

      // 點擊頁面其他區域關閉搜尋建議
      document.addEventListener('click', (e) => {
        if (!e.target.closest('.nebula-search-box')) {
          this.hideSuggestions();
        }
      });

      // 深度調整
      this.elements.depthSlider?.addEventListener('input', (e) => {
        this.state.depth = parseInt(e.target.value, 10);
        this.elements.depthVal.textContent = this.state.depth;
        this.loadGraph(this.state.centerId);
      });

      // 方向切換
      document.querySelectorAll('.dir-chip').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          document.querySelectorAll('.dir-chip').forEach((b) => b.classList.remove('active'));
          e.target.classList.add('active');
          this.state.direction = e.target.dataset.direction;
          this.loadGraph(this.state.centerId);
        });
      });

      // 外部庫開關
      this.elements.extChk?.addEventListener('change', (e) => {
        this.state.includeExternal = e.target.checked;
        this.loadGraph(this.state.centerId);
      });

      // 匯出圖片
      this.elements.exportBtn?.addEventListener('click', () => this.exportGraphImage());

      // 重新掃描
      this.elements.rescanBtn?.addEventListener('click', () => this.rescanProject());

      // 重設鏡頭
      this.elements.resetCamBtn?.addEventListener('click', () => this.resetCamera());

      // 抽屜歷史巡航
      this.elements.inspectorBackBtn?.addEventListener('click', () => this.navigateHistory(-1));
      this.elements.inspectorFwdBtn?.addEventListener('click', () => this.navigateHistory(1));

      // 抽屜關閉
      this.elements.closeInspectorBtn?.addEventListener('click', () => this.closeInspector());

      // 抽屜重繪中心
      this.elements.inspectorRecenterBtn?.addEventListener('click', () => {
        if (this.state.selectedNode) {
          this.loadGraph(this.state.selectedNode.id);
        }
      });

      // 複製 ID
      this.elements.inspectorCopyPathBtn?.addEventListener('click', () => {
        if (this.state.selectedNode) {
          navigator.clipboard.writeText(this.state.selectedNode.id);
          this.elements.inspectorCopyPathBtn.textContent = '已複製!';
          setTimeout(() => {
            this.elements.inspectorCopyPathBtn.textContent = '📋 複製 ID';
          }, 1500);
        }
      });

      // 快速範例標籤
      document.querySelectorAll('.sample-tag').forEach((tag) => {
        tag.addEventListener('click', (e) => {
          const target = e.target.dataset.target;
          this.elements.symbolInput.value = target;
          this.loadGraph(target);
        });
      });

      // 視窗縮放自適應
      window.addEventListener('resize', () => this.handleResize());
    },

    initD3() {
      if (typeof d3 === 'undefined') {
        console.error('D3.js library not loaded');
        return;
      }

      const rect = this.elements.canvasWrapper.getBoundingClientRect();
      this.state.width = rect.width > 50 ? rect.width : Math.max(window.innerWidth - 64, 1000);
      this.state.height = rect.height > 50 ? rect.height : 720;

      const svg = d3.select(this.elements.svg)
        .attr('width', '100%')
        .attr('height', '100%')
        .attr('viewBox', [0, 0, this.state.width, this.state.height]);

      this.state.svg = svg;

      // 箭頭標記定義
      const defs = svg.append('defs');
      defs.append('marker')
        .attr('id', 'arrow-calls')
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 24)
        .attr('refY', 0)
        .attr('markerWidth', 6)
        .attr('markerHeight', 6)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-5L10,0L0,5')
        .attr('fill', 'rgba(56, 189, 248, 0.7)');

      defs.append('marker')
        .attr('id', 'arrow-inherits')
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 24)
        .attr('refY', 0)
        .attr('markerWidth', 6)
        .attr('markerHeight', 6)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-5L10,0L0,5')
        .attr('fill', 'rgba(168, 85, 247, 0.8)');

      // 縮放與平移群組
      const g = svg.append('g').attr('class', 'nebula-zoom-layer');
      this.state.g = g;

      const zoom = d3.zoom()
        .scaleExtent([0.15, 4])
        .on('zoom', (event) => {
          g.attr('transform', event.transform);
        });

      svg.call(zoom);
      this.state.zoom = zoom;
    },

    handleResize() {
      const rect = this.elements.canvasWrapper.getBoundingClientRect();
      if (rect.width > 50) {
        this.state.width = rect.width;
        this.state.height = rect.height;
      }
      if (this.state.simulation) {
        this.state.simulation.force('center', d3.forceCenter(this.state.width / 2, this.state.height / 2));
        this.state.simulation.alpha(0.3).restart();
      }
    },

    async fetchProjectInfo() {
      try {
        const res = await fetch('/api/v1/nebula/project');
        if (!res.ok) return;
        const info = await res.json();
        if (this.elements.currentProjectName) {
          this.elements.currentProjectName.textContent = info.project_name || '專案';
        }
        if (this.elements.currentProjectPath) {
          this.elements.currentProjectPath.textContent = `(${info.current_project_path})`;
        }
      } catch (e) {
        console.error('Fetch project info failed:', e);
      }
    },

    async switchProject(customPath) {
      this.elements.switchProjectBtn.disabled = true;
      this.elements.switchProjectBtn.textContent = '匯入中...';
      try {
        const res = await fetch('/api/v1/nebula/scan', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project_path: customPath }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '掃描失敗');

        alert(data.message || `成功匯入專案，共 ${data.total_symbols} 個符號`);
        await this.fetchProjectInfo();

        const symRes = await fetch('/api/v1/nebula/symbols?limit=1');
        const symList = await symRes.json();
        if (symList && symList.length > 0) {
          this.elements.symbolInput.value = symList[0].name;
          this.loadGraph(symList[0].id);
        } else {
          this.elements.emptyState.classList.remove('hidden');
          this.elements.infoBadge.textContent = '專案已載入，但未發現 Python 符號';
        }
      } catch (e) {
        alert(`匯入專案失敗: ${e.message}`);
      } finally {
        this.elements.switchProjectBtn.disabled = false;
        this.elements.switchProjectBtn.innerHTML = `
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"></path>
          </svg>
          匯入並分析專案`;
      }
    },

    async resetProject() {
      this.elements.customPathInput.value = '';
      this.elements.resetProjectBtn.disabled = true;
      try {
        const res = await fetch('/api/v1/nebula/scan', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project_path: null }),
        });
        await res.json();
        await this.fetchProjectInfo();
        this.state.centerId = 'get_health_status';
        this.elements.symbolInput.value = 'get_health_status';
        this.loadGraph('get_health_status');
      } catch (e) {
        alert(`還原失敗: ${e.message}`);
      } finally {
        this.elements.resetProjectBtn.disabled = false;
      }
    },

    async fetchSuggestions(query) {
      if (!query) {
        this.hideSuggestions();
        return;
      }

      try {
        const res = await fetch(`/api/v1/nebula/symbols?q=${encodeURIComponent(query)}&limit=8`);
        if (!res.ok) return;
        const list = await res.json();
        this.renderSuggestions(list);
      } catch (e) {
        console.error('Fetch symbols failed:', e);
      }
    },

    renderSuggestions(list) {
      if (!list || list.length === 0) {
        this.hideSuggestions();
        return;
      }

      this.elements.suggestions.innerHTML = '';
      list.forEach((item) => {
        const row = document.createElement('div');
        row.className = 'suggestion-item';
        row.innerHTML = `
          <div class="suggestion-main">
            <span class="suggestion-badge badge-${item.module_group}">${item.symbol_type}</span>
            <span class="suggestion-name">${item.name}</span>
          </div>
          <span class="suggestion-id">${item.id}</span>
        `;
        row.addEventListener('click', () => {
          this.elements.symbolInput.value = item.name;
          this.hideSuggestions();
          this.loadGraph(item.id);
        });
        this.elements.suggestions.appendChild(row);
      });

      this.elements.suggestions.classList.remove('hidden');
    },

    hideSuggestions() {
      this.elements.suggestions.classList.add('hidden');
    },

    async rescanProject() {
      this.elements.rescanBtn.disabled = true;
      this.elements.rescanBtn.textContent = '掃描中...';
      try {
        const res = await fetch('/api/v1/nebula/scan', { method: 'POST' });
        const data = await res.json();
        alert(data.message || '掃描完成');
        this.loadGraph(this.state.centerId);
      } catch (e) {
        alert(`掃描失敗: ${e.message}`);
      } finally {
        this.elements.rescanBtn.disabled = false;
        this.elements.rescanBtn.textContent = '重新掃描專案';
      }
    },

    async loadGraph(targetSymbol) {
      if (!targetSymbol) return;
      this.state.centerId = targetSymbol;
      this.elements.infoBadge.textContent = `🪐 正在解析 ${targetSymbol} 的關聯星雲...`;
      this.elements.emptyState.classList.add('hidden');

      const url = `/api/v1/nebula/graph?target=${encodeURIComponent(targetSymbol)}&depth=${this.state.depth}&direction=${this.state.direction}&include_external=${this.state.includeExternal}`;

      try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const graphData = await res.json();
        this.state.graphData = graphData;

        if (!graphData.nodes || graphData.nodes.length === 0) {
          this.elements.emptyState.classList.remove('hidden');
          this.elements.infoBadge.textContent = `未找到與 "${targetSymbol}" 相關的代碼符號`;
          if (this.state.g) this.state.g.selectAll('*').remove();
          return;
        }

        this.elements.infoBadge.textContent = `星雲節點: ${graphData.nodes.length} 個 | 呼叫鏈: ${graphData.edges.length} 條 (解析耗時: ${graphData.execution_time_ms.toFixed(1)}ms)`;
        this.renderForceGraph(graphData);
      } catch (e) {
        this.elements.infoBadge.textContent = `載入星雲失敗: ${e.message}`;
      }
    },

    renderForceGraph(graphData) {
      const g = this.state.g;
      g.selectAll('*').remove();

      const centerId = graphData.center_id;
      const nodes = graphData.nodes.map((d) => Object.assign({}, d));
      const edges = graphData.edges.map((d) => Object.assign({}, d));

      // 建立 D3 力導向物理模擬器
      const simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(edges).id((d) => d.id).distance((d) => {
          return d.source.id === centerId || d.target.id === centerId ? 140 : 100;
        }))
        .force('charge', d3.forceManyBody().strength((d) => (d.id === centerId ? -600 : -280)))
        .force('collide', d3.forceCollide().radius(40))
        .force('center', d3.forceCenter(this.state.width / 2, this.state.height / 2));

      this.state.simulation = simulation;

      // 繪製連線層
      const link = g.append('g')
        .attr('class', 'nebula-links')
        .selectAll('line')
        .data(edges)
        .join('line')
        .attr('class', (d) => `nebula-link link-${d.relation.toLowerCase()}`)
        .attr('marker-end', (d) => (d.relation === 'INHERITS' ? 'url(#arrow-inherits)' : 'url(#arrow-calls)'));

      // 繪製節點群組
      const node = g.append('g')
        .attr('class', 'nebula-nodes')
        .selectAll('g')
        .data(nodes)
        .join('g')
        .attr('class', (d) => {
          const isCenter = d.id === centerId ? 'center-node' : '';
          return `nebula-node group-${d.module_group} type-${d.symbol_type} ${isCenter}`;
        })
        .call(d3.drag()
          .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on('drag', (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
        );

      // 中心節點脈衝發光環
      node.filter((d) => d.id === centerId)
        .append('circle')
        .attr('class', 'pulse-halo')
        .attr('r', 28);

      // 節點主體圓圈
      node.append('circle')
        .attr('class', 'node-circle')
        .attr('r', (d) => (d.id === centerId ? 22 : 14))
        .attr('fill', (d) => this.getNodeColor(d.module_group, d.is_external));

      // 節點文字標籤
      node.append('text')
        .attr('class', 'node-label')
        .attr('dy', (d) => (d.id === centerId ? 34 : 24))
        .attr('text-anchor', 'middle')
        .text((d) => d.name);

      // 節點副標 (類型與檔案)
      node.append('text')
        .attr('class', 'node-sublabel')
        .attr('dy', (d) => (d.id === centerId ? 46 : 34))
        .attr('text-anchor', 'middle')
        .text((d) => {
          if (d.file_path) {
            const fileName = d.file_path.split('/').pop();
            return `${d.symbol_type} · ${fileName}`;
          }
          return d.symbol_type;
        });

      // 懸停高亮關聯脈絡 (Incident Highlighting)
      node.on('mouseenter', (event, hoveredNode) => {
        const connectedNodeIds = new Set([hoveredNode.id]);

        link.each(function (l) {
          const isOut = l.source.id === hoveredNode.id;
          const isIn = l.target.id === hoveredNode.id;
          if (isOut) {
            connectedNodeIds.add(l.target.id);
            d3.select(this).classed('highlighted-out', true).classed('dimmed', false);
          } else if (isIn) {
            connectedNodeIds.add(l.source.id);
            d3.select(this).classed('highlighted-in', true).classed('dimmed', false);
          } else {
            d3.select(this).classed('dimmed', true).classed('highlighted-out', false).classed('highlighted-in', false);
          }
        });

        node.each(function (n) {
          if (connectedNodeIds.has(n.id)) {
            d3.select(this).classed('highlighted', true).classed('dimmed', false);
          } else {
            d3.select(this).classed('dimmed', true).classed('highlighted', false);
          }
        });
      });

      node.on('mouseleave', () => {
        link.classed('dimmed', false).classed('highlighted-out', false).classed('highlighted-in', false);
        node.classed('dimmed', false).classed('highlighted', false);
      });

      // 節點點擊事件 -> 開啟自省抽屜
      node.on('click', (event, d) => {
        event.stopPropagation();
        this.selectNode(d, true);
      });

      // 物理模擬每幀運算
      simulation.on('tick', () => {
        link
          .attr('x1', (d) => d.source.x)
          .attr('y1', (d) => d.source.y)
          .attr('x2', (d) => d.target.x)
          .attr('y2', (d) => d.target.y);

        node.attr('transform', (d) => `translate(${d.x},${d.y})`);
      });

      this.resetCamera();
    },

    getNodeColor(group, isExternal) {
      if (isExternal) return '#64748b';
      switch (group) {
        case 'core': return '#06b6d4';
        case 'api': return '#3b82f6';
        case 'tasks': return '#a855f7';
        case 'tools': return '#10b981';
        case 'tests': return '#f59e0b';
        default: return '#38bdf8';
      }
    },

    resetCamera() {
      if (!this.state.svg || !this.state.zoom) return;
      this.state.svg.transition().duration(750).call(
        this.state.zoom.transform,
        d3.zoomIdentity.translate(0, 0).scale(1)
      );
    },

    async selectNode(nodeData, pushHistory = true) {
      if (!nodeData) return;
      this.state.selectedNode = nodeData;
      this.elements.inspector.classList.remove('hidden');

      if (pushHistory) {
        if (this.state.historyIndex < this.state.historyStack.length - 1) {
          this.state.historyStack = this.state.historyStack.slice(0, this.state.historyIndex + 1);
        }
        this.state.historyStack.push(nodeData);
        this.state.historyIndex = this.state.historyStack.length - 1;
      }
      this.updateHistoryButtons();

      this.elements.inspectorTypeBadge.textContent = nodeData.symbol_type.toUpperCase();
      this.elements.inspectorName.textContent = nodeData.display_name || nodeData.name;
      this.elements.inspectorPath.textContent = nodeData.file_path
        ? `${nodeData.file_path}:${nodeData.line_start || 1}-${nodeData.line_end || 1}`
        : '外部符號 (External/Builtins)';

      this.elements.inspectorSig.textContent = nodeData.signature || '()';
      this.elements.inspectorDoc.textContent = nodeData.docstring || '無說明文件註解';
      this.elements.inspectorCode.textContent = '# 正在載入原始碼...';

      try {
        const res = await fetch(`/api/v1/nebula/code?symbol_id=${encodeURIComponent(nodeData.id)}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const codeData = await res.json();

        this.elements.inspectorCode.innerHTML = this.highlightPythonCode(codeData.code || '# 無法取得原始碼');
        this.renderRelationChips(codeData.callers, this.elements.inspectorCallersList, this.elements.inspectorCallersCount);
        this.renderRelationChips(codeData.callees, this.elements.inspectorCalleesList, this.elements.inspectorCalleesCount);
      } catch (e) {
        this.elements.inspectorCode.textContent = `# 載入自省資料失敗: ${e.message}`;
      }
    },

    navigateHistory(step) {
      const newIndex = this.state.historyIndex + step;
      if (newIndex >= 0 && newIndex < this.state.historyStack.length) {
        this.state.historyIndex = newIndex;
        this.selectNode(this.state.historyStack[newIndex], false);
      }
    },

    updateHistoryButtons() {
      if (this.elements.inspectorBackBtn) {
        this.elements.inspectorBackBtn.disabled = this.state.historyIndex <= 0;
      }
      if (this.elements.inspectorFwdBtn) {
        this.elements.inspectorFwdBtn.disabled = this.state.historyIndex >= this.state.historyStack.length - 1;
      }
    },

    highlightPythonCode(rawCode) {
      if (!rawCode) return '';
      let escaped = rawCode
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

      // 註解
      escaped = escaped.replace(/(#.*$)/gm, '<span class="token-comment">$1</span>');
      // 字串
      escaped = escaped.replace(/(".*?"|'.*?'|""".*?"""|'''.*?''')/g, '<span class="token-str">$1</span>');
      // 裝飾器
      escaped = escaped.replace(/(@\w+[\w.]*)/g, '<span class="token-decorator">$1</span>');
      // 關鍵字
      escaped = escaped.replace(/\b(def|class|async|await|return|import|from|if|elif|else|try|except|finally|for|while|with|as|in|is|not|and|or|lambda|yield|raise|pass|break|continue)\b/g, '<span class="token-kw">$1</span>');

      return escaped;
    },

    renderRelationChips(items, container, countEl) {
      countEl.textContent = items ? items.length : 0;
      container.innerHTML = '';
      if (!items || items.length === 0) {
        container.innerHTML = '<span class="text-muted" style="font-size:0.75rem;">無</span>';
        return;
      }

      items.forEach((item) => {
        const chip = document.createElement('button');
        chip.className = `rel-chip group-${item.module_group}`;
        chip.title = `${item.symbol_type}: ${item.id}`;
        chip.textContent = item.name;
        chip.addEventListener('click', () => {
          this.loadGraph(item.id);
        });
        container.appendChild(chip);
      });
    },

    exportGraphImage() {
      if (!this.elements.svg) return;
      const serializer = new XMLSerializer();
      const svgStr = serializer.serializeToString(this.elements.svg);
      const blob = new Blob([svgStr], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `code-nebula-${this.state.centerId || 'graph'}.svg`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    },

    closeInspector() {
      this.elements.inspector.classList.add('hidden');
      this.state.selectedNode = null;
    },
  };

  window.NebulaApp = Nebula;
})();
