/**
 * Exam Simulator Engine (完全還原 AI-103 原生互動架構 + 多科目動態題庫探索)
 * 支援單選/複選/下拉填空(Hotspots)/案例研究、隨機題目與選項、即時對答案持久化、全真模擬交卷
 */

(function () {
  'use strict';

  let rawQuestions = [];
  let activeQuestions = [];
  let currentIndex = 0;
  let userAnswers = {}; // { [questionId]: [selectedOptionIndices / dropdownIndices] }
  let userChecked = {}; // { [questionId]: boolean }
  let shuffledOptionsMap = {}; // { [questionId]: { options: [], mapping: [] } }
  let wrongQuestions = new Set();
  let currentMode = 'practice'; // 'practice' | 'exam' | 'wrong'
  let examSubmitted = false;
  let currentBankId = 'ai-103';
  let availableBanks = [];

  // DOM 快取
  let dom = {};

  function cacheDom() {
    dom = {
      bankSelect: document.getElementById('exam-bank-select'),
      logoTitle: document.getElementById('exam-logo-title'),
      btnPracticeMode: document.getElementById('btn-practice-mode'),
      btnExamMode: document.getElementById('btn-exam-mode'),
      btnWrongMode: document.getElementById('btn-wrong-mode'),
      wrongCountBadge: document.getElementById('wrong-count-badge'),
      btnToggleGrid: document.getElementById('btn-toggle-grid'),
      btnCloseSidebar: document.getElementById('btn-close-sidebar'),
      sidebarDrawer: document.getElementById('sidebar-drawer'),
      topicFilter: document.getElementById('topic-filter'),
      rangeStartInput: document.getElementById('range-start'),
      rangeEndInput: document.getElementById('range-end'),
      btnApplyRange: document.getElementById('btn-apply-range'),
      chkShuffleQ: document.getElementById('chk-shuffle-q'),
      chkShuffleOpt: document.getElementById('chk-shuffle-opt'),
      statCorrect: document.getElementById('stat-correct'),
      statIncorrect: document.getElementById('stat-incorrect'),
      statUnanswered: document.getElementById('stat-unanswered'),
      questionGrid: document.getElementById('question-grid'),
      btnResetQuiz: document.getElementById('btn-reset-quiz'),
      progressText: document.getElementById('progress-text'),
      progressPercent: document.getElementById('progress-percent'),
      progressFill: document.getElementById('progress-fill'),
      qTopic: document.getElementById('q-topic'),
      qType: document.getElementById('q-type'),
      qId: document.getElementById('q-id'),
      qTitle: document.getElementById('q-title'),
      qCaseStudy: document.getElementById('q-case-study'),
      optionsGroup: document.getElementById('options-group'),
      btnPrevQ: document.getElementById('btn-prev-q'),
      btnNextQ: document.getElementById('btn-next-q'),
      btnCheckAnswer: document.getElementById('btn-check-answer'),
      explanationPanel: document.getElementById('explanation-panel'),
      expStatusIcon: document.getElementById('exp-status-icon'),
      expStatusTitle: document.getElementById('exp-status-title'),
      expCorrectAnswerText: document.getElementById('exp-correct-answer-text'),
      expText: document.getElementById('exp-text'),
      backToHubBtn: document.getElementById('exam-back-to-hub-btn'),
    };
  }

  function shuffle(array) {
    const arr = [...array];
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
  }

  function formatQuestionText(text) {
    if (!text) return '';
    return text.replace(/\n/g, '<br>');
  }

  // 初始化與事件綁定
  async function init() {
    cacheDom();
    bindEvents();
    await fetchBanks();
  }

  function bindEvents() {
    // 題庫切換
    dom.bankSelect?.addEventListener('change', (e) => {
      currentBankId = e.target.value;
      loadBankData(currentBankId);
    });

    // 模式切換
    dom.btnPracticeMode?.addEventListener('click', () => switchMode('practice'));
    dom.btnExamMode?.addEventListener('click', () => switchMode('exam'));
    dom.btnWrongMode?.addEventListener('click', () => switchMode('wrong'));

    // 側邊欄抽屜
    dom.btnToggleGrid?.addEventListener('click', () => {
      dom.sidebarDrawer?.classList.toggle('open');
    });
    dom.btnCloseSidebar?.addEventListener('click', () => {
      dom.sidebarDrawer?.classList.remove('open');
    });

    // 篩選與隨機化
    dom.topicFilter?.addEventListener('change', () => applyFilterAndShuffle());
    dom.btnApplyRange?.addEventListener('click', () => applyFilterAndShuffle());
    dom.chkShuffleQ?.addEventListener('change', () => applyFilterAndShuffle());
    dom.chkShuffleOpt?.addEventListener('change', () => applyFilterAndShuffle());

    // 導航與作答
    dom.btnPrevQ?.addEventListener('click', () => navigateQuestion(-1));
    dom.btnNextQ?.addEventListener('click', () => navigateQuestion(1));
    dom.btnCheckAnswer?.addEventListener('click', () => checkAnswer());
    dom.btnResetQuiz?.addEventListener('click', () => resetQuiz());

    // 返回主畫面
    dom.backToHubBtn?.addEventListener('click', () => {
      if (window.AppRouter) window.AppRouter.showMainHub();
    });
  }

  async function fetchBanks() {
    try {
      const res = await fetch('/api/v1/exam/banks');
      if (!res.ok) return;
      availableBanks = await res.json();
      renderBankSelector(availableBanks);

      if (availableBanks.length > 0) {
        currentBankId = availableBanks[0].bank_id;
        await loadBankData(currentBankId);
      }
    } catch (e) {
      console.error('Fetch banks failed:', e);
    }
  }

  function renderBankSelector(banks) {
    if (!dom.bankSelect) return;
    dom.bankSelect.innerHTML = '';
    banks.forEach((b) => {
      const opt = document.createElement('option');
      opt.value = b.bank_id;
      opt.textContent = `📚 ${b.title} (${b.total_questions} 題)`;
      dom.bankSelect.appendChild(opt);
    });
  }

  async function loadBankData(bankId) {
    try {
      const bankMeta = availableBanks.find((b) => b.bank_id === bankId);
      if (dom.logoTitle && bankMeta) {
        dom.logoTitle.textContent = bankMeta.bank_id.toUpperCase();
      }

      // 讀取該題庫全量題目
      const res = await fetch(`/api/v1/exam/banks/${bankId}/questions`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      rawQuestions = await res.json();

      // 同步後端錯題本記錄
      if (bankMeta) {
        // 從中繼資料或篩選中取得錯題
        const wrongRes = await fetch(`/api/v1/exam/banks/${bankId}/questions?mode=wrong`);
        if (wrongRes.ok) {
          const wrongList = await wrongRes.json();
          wrongQuestions = new Set(wrongList.map((q) => q.id));
        }
      }

      populateTopics();
      updateWrongBadge();

      if (dom.rangeStartInput) dom.rangeStartInput.value = 1;
      if (dom.rangeEndInput) dom.rangeEndInput.value = rawQuestions.length;

      applyFilterAndShuffle();
    } catch (e) {
      console.error('Load bank data failed:', e);
      if (dom.qTitle) dom.qTitle.textContent = '載入題庫失敗，請確認後端服務連線。';
    }
  }

  function populateTopics() {
    if (!dom.topicFilter) return;
    const topics = [...new Set(rawQuestions.map((q) => q.topic).filter(Boolean))];
    dom.topicFilter.innerHTML = `<option value="ALL">全部主題 (All Topics - ${rawQuestions.length}題)</option>`;
    topics.forEach((t) => {
      const count = rawQuestions.filter((q) => q.topic === t).length;
      const opt = document.createElement('option');
      opt.value = t;
      opt.textContent = `${t} (${count}題)`;
      dom.topicFilter.appendChild(opt);
    });
  }

  function updateWrongBadge() {
    if (dom.wrongCountBadge) {
      dom.wrongCountBadge.textContent = wrongQuestions.size;
    }
  }

  function switchMode(mode) {
    currentMode = mode;
    [dom.btnPracticeMode, dom.btnExamMode, dom.btnWrongMode].forEach((b) => b?.classList.remove('active'));

    if (mode === 'practice') dom.btnPracticeMode?.classList.add('active');
    if (mode === 'exam') dom.btnExamMode?.classList.add('active');
    if (mode === 'wrong') dom.btnWrongMode?.classList.add('active');

    examSubmitted = false;
    userAnswers = {};
    userChecked = {};

    applyFilterAndShuffle();
  }

  function applyFilterAndShuffle() {
    let list = [];

    if (currentMode === 'wrong') {
      list = rawQuestions.filter((q) => wrongQuestions.has(q.id));
      if (list.length === 0) {
        alert('目前沒有錯題紀錄！切換回即時練習模式。');
        switchMode('practice');
        return;
      }
    } else {
      const selectedTopic = dom.topicFilter?.value || 'ALL';
      if (selectedTopic === 'ALL') {
        list = [...rawQuestions];
      } else {
        list = rawQuestions.filter((q) => q.topic === selectedTopic);
      }
    }

    // 自訂題號範圍過濾
    if (dom.rangeStartInput && dom.rangeEndInput) {
      let startQ = parseInt(dom.rangeStartInput.value, 10);
      let endQ = parseInt(dom.rangeEndInput.value, 10);
      if (isNaN(startQ) || startQ < 1) startQ = 1;
      if (isNaN(endQ) || endQ > rawQuestions.length) endQ = rawQuestions.length;
      if (startQ > endQ) [startQ, endQ] = [endQ, startQ];

      list = list.filter((q) => q.id >= startQ && q.id <= endQ);

      if (list.length === 0) {
        alert(`在第 ${startQ} ~ ${endQ} 題範圍內沒有符合當前條件的題目！`);
        dom.rangeStartInput.value = 1;
        dom.rangeEndInput.value = rawQuestions.length;
        list = [...rawQuestions];
      }
    }

    // 題目順序隨機
    if (dom.chkShuffleQ?.checked) {
      list = shuffle(list);
    }

    activeQuestions = list;
    currentIndex = 0;
    shuffledOptionsMap = {};

    // 選項順序隨機
    activeQuestions.forEach((q) => {
      if (dom.chkShuffleOpt?.checked && q.options && q.options.length > 0) {
        const indexedOpts = q.options.map((optText, origIdx) => ({
          text: optText,
          origIdx: origIdx,
        }));
        const shuffled = shuffle(indexedOpts);
        shuffledOptionsMap[q.id] = {
          options: shuffled.map((o) => o.text),
          mapping: shuffled.map((o) => o.origIdx),
        };
      } else {
        shuffledOptionsMap[q.id] = {
          options: q.options || [],
          mapping: (q.options || []).map((_, i) => i),
        };
      }
    });

    renderQuestionGrid();
    renderCurrentQuestion();
    updateStats();
  }

  function renderQuestionGrid() {
    if (!dom.questionGrid) return;
    dom.questionGrid.innerHTML = '';

    activeQuestions.forEach((q, idx) => {
      const item = document.createElement('div');
      item.className = 'grid-item';
      item.textContent = idx + 1;

      if (idx === currentIndex) {
        item.classList.add('current');
      }

      if (currentMode === 'exam' && !examSubmitted) {
        if (userAnswers[q.id] && userAnswers[q.id].length > 0) {
          item.classList.add('selected');
        }
      } else {
        if (userChecked[q.id]) {
          const selected = userAnswers[q.id] || [];
          const isCorrect = isAnswerCorrect(q, selected);
          item.classList.add(isCorrect ? 'correct' : 'incorrect');
        }
      }

      item.addEventListener('click', () => {
        currentIndex = idx;
        renderCurrentQuestion();
        renderQuestionGrid();

        if (window.innerWidth <= 992) {
          dom.sidebarDrawer?.classList.remove('open');
        }
      });

      dom.questionGrid.appendChild(item);
    });
  }

  function isAnswerCorrect(q, selectedIndices) {
    if (!selectedIndices || selectedIndices.length === 0) return false;

    if (q.dropdowns && q.dropdowns.length > 0) {
      if (selectedIndices.length !== q.dropdowns.length) return false;
      return q.dropdowns.every((drop, dIdx) => selectedIndices[dIdx] === drop.answer);
    }

    const correctAnswers = Array.isArray(q.answer) ? q.answer : [q.answer];
    if (correctAnswers.length !== selectedIndices.length) return false;
    return correctAnswers.every((idx) => selectedIndices.includes(idx));
  }

  function renderCurrentQuestion() {
    if (!activeQuestions.length) return;

    const q = activeQuestions[currentIndex];
    const optionData = shuffledOptionsMap[q.id];
    const letters = ['A', 'B', 'C', 'D', 'E', 'F', 'G'];
    const showResults =
      (currentMode === 'practice' && userChecked[q.id]) ||
      (currentMode === 'wrong' && userChecked[q.id]) ||
      (currentMode === 'exam' && examSubmitted);

    // Meta 標籤
    if (dom.qTopic) dom.qTopic.textContent = q.topic || 'General';
    if (dom.qType) {
      dom.qType.textContent =
        q.type === 'multiple_choice'
          ? 'Multiple Choice (複選題)'
          : q.type === 'drop_down'
          ? 'Drop-down / Hotspot'
          : 'Single Choice (單選題)';
    }
    if (dom.qId) dom.qId.textContent = `Q${q.id} (第 ${currentIndex + 1} / ${activeQuestions.length} 題)`;

    // 情境案例題 (Case Study)
    if (q.case_study_title || q.case_study) {
      dom.qCaseStudy?.classList.remove('hidden');
      if (dom.qCaseStudy) {
        dom.qCaseStudy.innerHTML = `
          <div class="case-study-title">
            <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
            ${q.case_study_title || 'Case Study Scenario'}
          </div>
          <div>${formatQuestionText(q.case_study || '')}</div>
        `;
      }
    } else {
      dom.qCaseStudy?.classList.add('hidden');
      if (dom.qCaseStudy) dom.qCaseStudy.innerHTML = '';
    }

    // 題幹文字與下拉選單填空 (Hotspots)
    let questionHtml = formatQuestionText(q.question);

    if (q.dropdowns && q.dropdowns.length > 0) {
      q.dropdowns.forEach((drop, dIdx) => {
        const userSel = (userAnswers[q.id] || [])[dIdx];

        let selectHtml = `<select class="q-select" data-drop-idx="${dIdx}" ${showResults ? 'disabled' : ''}>`;
        selectHtml += `<option value="" disabled ${userSel === undefined ? 'selected' : ''}>請選擇...</option>`;

        drop.options.forEach((optText, oIdx) => {
          selectHtml += `<option value="${oIdx}" ${userSel === oIdx ? 'selected' : ''}>${optText}</option>`;
        });
        selectHtml += `</select>`;

        if (showResults) {
          const isCorrect = userSel === drop.answer;
          selectHtml = `<span class="inline-select-wrapper" style="border: 2px solid ${isCorrect ? 'var(--color-success)' : 'var(--color-danger)'}; padding: 2px; border-radius: 6px; display: inline-flex; align-items: center; background: ${isCorrect ? 'var(--color-success-bg)' : 'var(--color-danger-bg)'}; margin: 2px;">
            ${selectHtml}
            <span style="font-size: 11px; font-weight: bold; margin-left: 4px; padding-right: 4px; color: ${isCorrect ? 'var(--color-success)' : 'var(--color-danger)'}">
              ${isCorrect ? '✓' : `✗ 正確: ${drop.options[drop.answer]}`}
            </span>
          </span>`;
        }

        questionHtml = questionHtml.replace(drop.placeholder || `[ Box ${dIdx + 1} ]`, selectHtml);
      });
    }

    if (dom.qTitle) dom.qTitle.innerHTML = questionHtml;

    // 綁定下拉格即時選擇
    const dropdownElements = dom.qTitle?.querySelectorAll('.q-select');
    dropdownElements?.forEach((selectEl) => {
      selectEl.addEventListener('change', (e) => {
        const dIdx = parseInt(e.target.getAttribute('data-drop-idx'), 10);
        const val = parseInt(e.target.value, 10);

        if (!userAnswers[q.id]) {
          userAnswers[q.id] = [];
        }
        userAnswers[q.id][dIdx] = val;

        renderQuestionGrid();
        updateStats();
      });
    });

    // 渲染標準選項 (Single / Multi)
    if (dom.optionsGroup) dom.optionsGroup.innerHTML = '';
    const interactiveArea = document.querySelector('.interactive-area');

    if (q.dropdowns && q.dropdowns.length > 0) {
      if (interactiveArea) interactiveArea.style.display = 'none';
    } else {
      if (interactiveArea) interactiveArea.style.display = 'flex';
      if (optionData && optionData.options.length > 0 && dom.optionsGroup) {
        optionData.options.forEach((optText, index) => {
          const origIdx = optionData.mapping[index];
          const isSelected = (userAnswers[q.id] || []).includes(origIdx);
          const correctAnswers = Array.isArray(q.answer) ? q.answer : [q.answer];
          const isCorrect = correctAnswers.includes(origIdx);

          const item = document.createElement('div');
          item.className = 'option-item';
          if (isSelected) {
            item.classList.add('selected');
          }

          if (showResults) {
            if (isCorrect) {
              item.classList.remove('selected');
              item.classList.add('correct-ans');
            } else if (isSelected) {
              item.classList.remove('selected');
              item.classList.add('wrong-ans');
            }
            item.style.pointerEvents = 'none';
          }

          const badge = document.createElement('div');
          badge.className = 'option-badge';
          badge.textContent = letters[index] || index + 1;

          const content = document.createElement('div');
          content.className = 'option-content';

          const optLabel = document.createElement('span');
          optLabel.className = 'option-text';
          optLabel.textContent = optText;

          content.appendChild(optLabel);
          item.appendChild(badge);
          item.appendChild(content);

          item.addEventListener('click', () => {
            if (showResults) return;

            let currentSelections = userAnswers[q.id] || [];
            if (q.type === 'multiple_choice') {
              if (currentSelections.includes(origIdx)) {
                currentSelections = currentSelections.filter((i) => i !== origIdx);
              } else {
                currentSelections.push(origIdx);
              }
            } else {
              currentSelections = [origIdx];
            }
            userAnswers[q.id] = currentSelections;

            renderCurrentQuestion();
            renderQuestionGrid();
            updateStats();
          });

          dom.optionsGroup.appendChild(item);
        });
      }
    }

    // 更新底部導航與按鈕
    if (dom.btnPrevQ) dom.btnPrevQ.disabled = currentIndex === 0;
    if (dom.btnNextQ) dom.btnNextQ.disabled = currentIndex === activeQuestions.length - 1;

    if (currentMode === 'exam') {
      if (examSubmitted) {
        if (dom.btnCheckAnswer) dom.btnCheckAnswer.style.display = 'none';
        showExplanationPanel(q);
      } else {
        if (dom.btnCheckAnswer) {
          dom.btnCheckAnswer.style.display = 'block';
          dom.btnCheckAnswer.innerHTML = `
            <svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/></svg>
            結束模擬考交卷
          `;
        }
        hideExplanationPanel();
      }
    } else {
      if (dom.btnCheckAnswer) {
        dom.btnCheckAnswer.style.display = 'block';
        dom.btnCheckAnswer.innerHTML = `
          <svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
          即時對答案
        `;
      }
      if (userChecked[q.id]) {
        showExplanationPanel(q);
      } else {
        hideExplanationPanel();
      }
    }

    // 進度條更新
    const currentQNum = currentIndex + 1;
    const totalQs = activeQuestions.length;
    if (dom.progressText) dom.progressText.textContent = `第 ${currentQNum} / ${totalQs} 題`;
    const pct = totalQs > 0 ? (currentQNum / totalQs) * 100 : 0;
    if (dom.progressPercent) dom.progressPercent.textContent = `${Math.round(pct)}%`;
    if (dom.progressFill) dom.progressFill.style.width = `${pct}%`;
  }

  // 即時對答案 (Practice Mode) - 同步更新後端持久化錯題本
  async function checkAnswer() {
    if (currentMode === 'exam') {
      if (!examSubmitted) {
        if (confirm('確定要結束模擬考並交卷嗎？')) {
          submitExam();
        }
      }
      return;
    }

    const q = activeQuestions[currentIndex];
    const selections = userAnswers[q.id] || [];

    if (q.dropdowns && q.dropdowns.length > 0) {
      const filledCount = selections.filter((val) => val !== undefined && val !== null).length;
      if (filledCount < q.dropdowns.length) {
        alert('請先填選題目中的所有下拉選單再進行對答案！');
        return;
      }
    } else {
      if (selections.length === 0) {
        alert('請先選擇您的答案再點選對答案！');
        return;
      }
    }

    userChecked[q.id] = true;
    const isCorrect = isAnswerCorrect(q, selections);

    if (isCorrect) {
      wrongQuestions.delete(q.id);
    } else {
      wrongQuestions.add(q.id);
    }

    // 調用後端 API 同步錯題本持久化檔案
    try {
      await fetch(`/api/v1/exam/banks/${currentBankId}/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question_id: q.id,
          selected_options: q.type !== 'drop_down' ? selections : [],
          selected_dropdowns: q.type === 'drop_down' ? selections : [],
        }),
      });
    } catch (e) {
      console.warn('Sync wrong question to backend failed:', e);
    }

    updateWrongBadge();
    renderCurrentQuestion();
    renderQuestionGrid();
    updateStats();
  }

  // 全真模擬考交卷 - 同步結算成績與後端錯題本
  async function submitExam() {
    examSubmitted = true;
    const answersList = [];

    activeQuestions.forEach((q) => {
      const selections = userAnswers[q.id] || [];
      userChecked[q.id] = true;
      const isCorrect = isAnswerCorrect(q, selections);

      if (isCorrect) {
        wrongQuestions.delete(q.id);
      } else {
        wrongQuestions.add(q.id);
      }

      answersList.push({
        question_id: q.id,
        selected_options: q.type !== 'drop_down' ? selections : [],
        selected_dropdowns: q.type === 'drop_down' ? selections : [],
      });
    });

    // 調用後端交卷 API
    try {
      await fetch(`/api/v1/exam/banks/${currentBankId}/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode: 'exam',
          time_spent_seconds: 0,
          answers: answersList,
        }),
      });
    } catch (e) {
      console.warn('Submit exam to backend failed:', e);
    }

    updateWrongBadge();

    let scoreCount = 0;
    activeQuestions.forEach((q) => {
      if (isAnswerCorrect(q, userAnswers[q.id] || [])) {
        scoreCount++;
      }
    });

    const scorePct = Math.round((scoreCount / activeQuestions.length) * 100);
    alert(
      `模擬考交卷完成！\n您的分數：${scorePct}分 (答對 ${scoreCount} 題 / 共 ${activeQuestions.length} 題)\n\n可點選題目導航面板檢視每題解析。`
    );

    renderCurrentQuestion();
    renderQuestionGrid();
    updateStats();
  }

  function showExplanationPanel(q) {
    if (!dom.explanationPanel) return;
    dom.explanationPanel.classList.remove('hidden');
    if (dom.expText) dom.expText.innerHTML = formatQuestionText(q.explanation);

    const isCorrect = isAnswerCorrect(q, userAnswers[q.id] || []);
    if (isCorrect) {
      dom.explanationPanel.className = 'explanation-panel correct-panel';
      if (dom.expStatusIcon) dom.expStatusIcon.textContent = '✓';
      if (dom.expStatusTitle) dom.expStatusTitle.textContent = '解答正確 (Correct)';
    } else {
      dom.explanationPanel.className = 'explanation-panel incorrect-panel';
      if (dom.expStatusIcon) dom.expStatusIcon.textContent = '✗';
      if (dom.expStatusTitle) dom.expStatusTitle.textContent = '解答錯誤 (Incorrect)';
    }

    if (dom.expCorrectAnswerText) {
      if (q.dropdowns && q.dropdowns.length > 0) {
        dom.expCorrectAnswerText.textContent = `正確填空: ${q.dropdowns.map((d, i) => `[Box ${i + 1}]: ${d.options[d.answer]}`).join(' | ')}`;
      } else {
        const letters = ['A', 'B', 'C', 'D', 'E', 'F', 'G'];
        const correctAnswers = Array.isArray(q.answer) ? q.answer : [q.answer];
        dom.expCorrectAnswerText.textContent = `正確答案: ${correctAnswers.map((idx) => letters[idx] || idx + 1).join(', ')}`;
      }
    }
  }

  function hideExplanationPanel() {
    dom.explanationPanel?.classList.add('hidden');
  }

  function updateStats() {
    let correct = 0;
    let incorrect = 0;
    let unanswered = 0;

    activeQuestions.forEach((q) => {
      if (currentMode === 'exam' && !examSubmitted) {
        if (!userAnswers[q.id] || userAnswers[q.id].length === 0) {
          unanswered++;
        }
      } else {
        if (!userChecked[q.id]) {
          unanswered++;
        } else {
          if (isAnswerCorrect(q, userAnswers[q.id])) {
            correct++;
          } else {
            incorrect++;
          }
        }
      }
    });

    if (dom.statCorrect) dom.statCorrect.textContent = correct;
    if (dom.statIncorrect) dom.statIncorrect.textContent = incorrect;
    if (dom.statUnanswered) dom.statUnanswered.textContent = unanswered;
  }

  function navigateQuestion(step) {
    const newIdx = currentIndex + step;
    if (newIdx >= 0 && newIdx < activeQuestions.length) {
      currentIndex = newIdx;
      renderCurrentQuestion();
      renderQuestionGrid();
    }
  }

  function resetQuiz() {
    if (confirm('確定要重新開始測驗嗎？所有作答紀錄將被清空。')) {
      userAnswers = {};
      userChecked = {};
      examSubmitted = false;
      applyFilterAndShuffle();
    }
  }

  window.ExamApp = {
    init,
  };
})();
