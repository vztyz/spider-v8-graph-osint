const btnStart = document.getElementById('btn-start');
const btnStop = document.getElementById('btn-stop');
const logsContainer = document.getElementById('live-logs');

// --- WebSocket для Логов ---
function connectWebSocket() {
    const ws = new WebSocket(`ws://${window.location.host}/ws`);
    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        
        if (msg.type === "log") {
            appendLog(`[${msg.profile}] ${msg.message}`);
            if (msg.profile === "AI Tagger" && msg.message.includes("✅ Все доступные каналы размечены")) {
                if (typeof isTaggerRunning !== 'undefined') {
                    isTaggerRunning = false;
                    const btn = document.getElementById('btn-run-tagger');
                    if (btn) {
                        btn.innerText = "🪄 Auto-Tag";
                        btn.style.borderColor = "#a78bfa";
                        btn.style.color = "#a78bfa";
                    }
                }
            }
        } else if (msg.type === "status" || msg.action === "update_graph") {
            // Обновляем статистику если пришел статус или обновилась база
            fetchStats();
        }
    };
    ws.onclose = () => setTimeout(connectWebSocket, 5000); 
}

function appendLog(text) {
    if (logsContainer.innerText === "Waiting to start...") {
        logsContainer.innerHTML = "";
    }
    const div = document.createElement('div');
    // Раскрашиваем ошибки красным, успехи зеленым
    if (text.includes("❌") || text.includes("ERR:")) div.style.color = "#ef4444";
    else if (text.includes("✅")) div.style.color = "#10b981";
    else if (text.includes("🎯")) div.style.color = "#4da6ff";
    
    div.innerText = text;
    // Добавляем наверх (как в десктопе)
    logsContainer.prepend(div);
    
    // Ограничиваем количество строк
    if (logsContainer.children.length > 500) {
        logsContainer.removeChild(logsContainer.lastChild);
    }
}

// --- API Запросы ---
async function fetchStats() {
    try {
        const res = await fetch('/api/dashboard/stats');
        const data = await res.json();
        
        // Здоровье БД
        document.getElementById('stat-db-size').innerText = `${data.health.db_size_mb} MB`;
        document.getElementById('stat-total').innerText = data.health.total_channels.toLocaleString();
        let percent = data.health.approved_channels > 0 ? (data.health.ai_tagged_channels / data.health.approved_channels * 100).toFixed(1) : 0;
        document.getElementById('stat-tagged').innerText = `${data.health.ai_tagged_channels.toLocaleString()} (${percent}%)`;
        document.getElementById('stat-links').innerText = data.health.total_links.toLocaleString();
        
        // Статистика сессии
        document.getElementById('stat-appr').innerText = data.stats.approved;
        document.getElementById('stat-rej').innerText = data.stats.rejected;
        document.getElementById('stat-queue').innerText = data.stats.queue;
        document.getElementById('stat-leads').innerText = data.stats.comments_found;

        // Отрисовка профилей (пилюли статусов)
        renderProfiles(data.profiles);
        
    } catch (e) {
        console.error("Failed to load stats", e);
    }
}

function renderProfiles(profiles) {
    const container = document.getElementById('task-manager');
    container.innerHTML = "";
    
    let anyRunning = false;
    
    const statusColors = {
        "idle": { bg: "rgba(168,184,208,0.1)", text: "#a8b8d0" },
        "running": { bg: "rgba(16,185,129,0.1)", text: "#10b981" },
        "floodwait": { bg: "rgba(245,158,11,0.1)", text: "#f59e0b" },
        "error": { bg: "rgba(239,68,68,0.1)", text: "#ef4444" }
    };

    profiles.forEach(p => {
        if (p.status === 'running') anyRunning = true;
        const style = statusColors[p.status] || statusColors["idle"];
        
        const row = document.createElement('div');
        row.className = "task-row";
        
        let errorTitle = p.error ? `title="Error: ${p.error}"` : "";
        
        // Левая часть: Имя и статус
        const infoDiv = document.createElement('div');
        infoDiv.style.display = "flex";
        infoDiv.style.alignItems = "center";
        infoDiv.style.gap = "10px";
        infoDiv.innerHTML = `
            <div class="task-name" ${errorTitle}>${p.name}</div>
            <div class="task-status" style="background:${style.bg}; color:${style.text};">${p.status.toUpperCase()}</div>
        `;
        
        // Правая часть: Управление
        const controlsDiv = document.createElement('div');
        controlsDiv.className = "task-controls";
        
        const selectMode = document.createElement('select');
        selectMode.className = "task-select";
        selectMode.id = `mode-${p.name}`;
        selectMode.innerHTML = `
            <option value="warmup">☕ Только Прогрев (Без спама)</option>
            <option value="scout">🕷️ Scout (Парсинг)</option>
            <option value="funnel">🛠️ Setup Funnel</option>
            <option value="leadgen">🔥 LeadGen (Нейро-комментинг)</option>
        `;
        
        const btnAction = document.createElement('button');
        if (p.status === 'idle' || p.status === 'error') {
            btnAction.className = "task-btn start";
            btnAction.innerText = "▶ Run";
            btnAction.onclick = () => runTask(p.name, document.getElementById(`mode-${p.name}`).value);
        } else {
            selectMode.disabled = true;
            btnAction.className = "task-btn stop";
            btnAction.innerText = "■ Stop";
            btnAction.onclick = () => stopTask(p.name);
        }
        
        controlsDiv.appendChild(selectMode);
        controlsDiv.appendChild(btnAction);

        const btnDelete = document.createElement('button');
        btnDelete.className = "task-btn stop";
        btnDelete.style.marginLeft = "5px";
        btnDelete.style.padding = "5px 8px";
        btnDelete.title = "Удалить аккаунт";
        btnDelete.innerHTML = "✖";
        
        if (p.status !== 'idle' && p.status !== 'error') {
            btnDelete.disabled = true;
            btnDelete.style.opacity = "0.3";
            btnDelete.style.cursor = "not-allowed";
        } else {
            btnDelete.onclick = async () => {
                if(confirm(`Точно удалить профиль ${p.name}?`)) {
                    try {
                        await fetch(`/api/profiles/${p.name}`, { method: 'DELETE' });
                        fetchStats();
                    } catch(e) { appendLog("❌ Ошибка удаления: " + e.message); }
                }
            };
        }
        controlsDiv.appendChild(btnDelete);
        
        row.appendChild(infoDiv);
        row.appendChild(controlsDiv);
        container.appendChild(row);
    });

    // Глобальные кнопки (Оставить для обратной совместимости)
    if (anyRunning) {
        btnStart.disabled = true;
        btnStart.classList.replace('primary', 'secondary');
        btnStop.disabled = false;
        btnStop.classList.replace('secondary', 'primary');
    } else {
        btnStart.disabled = false;
        btnStart.classList.replace('secondary', 'primary');
        btnStop.disabled = true;
        btnStop.classList.replace('primary', 'secondary');
    }
}

async function runTask(profileName, mode) {
    appendLog(`🚀 Requesting to start [${profileName}] in ${mode} mode...`);
    try {
        await fetch('/api/spider/start_task', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ profile: profileName, task_mode: mode })
        });
        setTimeout(fetchStats, 500);
    } catch(e) { appendLog("❌ API Error: " + e.message); }
}

async function stopTask(profileName) {
    appendLog(`⏹️ Stopping [${profileName}]...`);
    const select = document.getElementById(`mode-${profileName}`);
    if (select && select.nextElementSibling) {
        select.nextElementSibling.innerText = "⏳ Stopping...";
    }
    try {
        await fetch(`/api/spider/stop_task/${profileName}`, { method: 'POST' });
        setTimeout(fetchStats, 500);
    } catch(e) { appendLog("❌ API Error: " + e.message); }
}

// --- Управление пауками ---
btnStart.addEventListener('click', async () => {
    btnStart.disabled = true;
    appendLog("🚀 Requesting to start spiders...");
    try {
        await fetch('/api/spider/start', { method: 'POST' });
        setTimeout(fetchStats, 500);
    } catch(e) {
        appendLog("❌ API Error: " + e.message);
    }
});

btnStop.addEventListener('click', async () => {
    btnStop.disabled = true;
    appendLog("⏹️ Requesting to stop spiders...");
    try {
        await fetch('/api/spider/stop', { method: 'POST' });
        setTimeout(fetchStats, 1000);
    } catch(e) {
        appendLog("❌ API Error: " + e.message);
    }
});

// Инициализация
connectWebSocket();
fetchStats();
// Обновляем статистику каждые 5 секунд для надежности
setInterval(fetchStats, 5000);

// --- Управление AI Tagger ---
const btnTagger = document.getElementById('btn-run-tagger');
let isTaggerRunning = false;

if (btnTagger) {
    btnTagger.addEventListener('click', async () => {
        if (!isTaggerRunning) {
            btnTagger.innerText = "🛑 Stop";
            btnTagger.style.borderColor = "#ef4444";
            btnTagger.style.color = "#ef4444";
            isTaggerRunning = true;
            appendLog("🪄 Запрос на запуск AI Tagger...");
            try {
                await fetch('/api/tagger/start', { method: 'POST' });
            } catch(e) { appendLog("❌ API Error: " + e.message); }
        } else {
            btnTagger.innerText = "🪄 Auto-Tag";
            btnTagger.style.borderColor = "#a78bfa";
            btnTagger.style.color = "#a78bfa";
            isTaggerRunning = false;
            appendLog("🛑 Остановка AI Tagger...");
            try {
                await fetch('/api/tagger/stop', { method: 'POST' });
            } catch(e) { appendLog("❌ API Error: " + e.message); }
        }
    });
}