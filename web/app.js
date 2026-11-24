const colorPalette = [
    "#38bdf8", "#34d399", "#fbbf24", "#f87171", 
    "#a78bfa", "#f472b6", "#2dd4bf", "#e879f9",
    "#fb923c", "#a3e635", "#22d3ee", "#c084fc"
];

function getTagColor(tags) {
    if (!tags || tags.trim() === '') return "#475569";
    if (tags.toUpperCase().includes("[МУСОР]")) return "#3f3f46";
    let firstTag = tags.split(',')[0].trim().toLowerCase();
    let hash = 0;
    for (let i = 0; i < firstTag.length; i++) { hash = firstTag.charCodeAt(i) + ((hash << 5) - hash); }
    return colorPalette[Math.abs(hash) % colorPalette.length];
}

function getNodeRadius(subs, isMacro) {
    if (isMacro) return Math.min(80, Math.max(15, Math.log10(subs || 1) * 10));
    if (!subs || subs <= 0) return 4;
    return Math.min(20, Math.max(4, 2 + Math.log10(subs) * 2.5));
}

function getSliderSubsValue(val) {
    if (val === 0) return 0;
    if (val <= 25) return val * 200;
    if (val <= 50) return 5000 + (val - 25) * 1800;
    if (val <= 75) return 50000 + (val - 50) * 6000;
    return 200000 + (val - 75) * 12000;
}

// --- GLOBAL STATE ---
let Graph = null;
let is3D = false;
let isMacro = true; 

let graphData = { nodes: [], links: [] };
let clustersData = {}; 

let hoverNode = null;
const highlightNodes = new Set();
const highlightLinks = new Set();

let aiMatchedIds = new Set(); 
let currentAiLeads = []; 

let searchQuery = "";
let minSubsFilter = 0;
let hideEmpty = false;
let linesAlpha = 45;

const sidebar = document.getElementById('sidebar');
const aiSidebar = document.getElementById('ai-sidebar');
const aiChatArea = document.getElementById('ai-chat-area');
const aiInput = document.getElementById('ai-input');
const btnAiSend = document.getElementById('btn-ai-send');

const aiSettingsPanel = document.getElementById('ai-settings-panel');
const promptTextarea = document.getElementById('ai-system-prompt');
const btnAiSettings = document.getElementById('btn-ai-settings');
const btnClosePrompt = document.getElementById('btn-close-prompt');
const btnSavePrompt = document.getElementById('btn-save-prompt');

const inputMinSubs = document.getElementById('ai-min-subs');
const inputMaxSubs = document.getElementById('ai-max-subs');

// Восстановление локальных фильтров
inputMinSubs.value = localStorage.getItem('spiderAiMinSubs') || '';
inputMaxSubs.value = localStorage.getItem('spiderAiMaxSubs') || '';

inputMinSubs.addEventListener('input', () => localStorage.setItem('spiderAiMinSubs', inputMinSubs.value));
inputMaxSubs.addEventListener('input', () => localStorage.setItem('spiderAiMaxSubs', inputMaxSubs.value));

// --- ЛОГИКА ПРОМПТА ИИ ---
btnAiSettings.addEventListener('click', async () => {
    aiChatArea.style.display = 'none';
    aiSettingsPanel.style.display = 'block';
    try {
        const res = await fetch('/api/ai_settings');
        const data = await res.json();
        promptTextarea.value = data.prompt || '';
    } catch (e) {
        console.error("Failed to load prompt", e);
    }
});

btnClosePrompt.addEventListener('click', () => {
    aiSettingsPanel.style.display = 'none';
    aiChatArea.style.display = 'flex';
});

btnSavePrompt.addEventListener('click', async () => {
    try {
        await fetch('/api/ai_settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: promptTextarea.value })
        });
        aiSettingsPanel.style.display = 'none';
        aiChatArea.style.display = 'flex';
    } catch (e) {
        alert("Ошибка при сохранении промпта!");
    }
});

// --- ЛОГИКА СОХРАНЕНИЯ ЧАТА В БРАУЗЕРЕ ---
let chatHistory = JSON.parse(localStorage.getItem('spiderAiChat')) || [];

function saveChatHistory() {
    localStorage.setItem('spiderAiChat', JSON.stringify(chatHistory));
}

function renderChatHistory() {
    aiChatArea.innerHTML = `
        <div class="chat-msg bot-msg">
            Привет! Я твой ИИ-помощник. Опиши мне, кого ты ищешь (например: "Нужны лиды для репетитора по английскому под рассылку")("мне нужны каналы где я смогу оставить комментарии с аккаунта репетитора - комментарий с помощью - чувак кликнет на мою аву увидет что я репетитор и в случае чего напишет мне или я напишу потенциальным клиетам из комментариев"). Я проанализирую запрос, выдам Google Dorks и отфильтрую идеальные Telegram-каналы с открытыми комментариями из нашей БД.
            <br><button onclick="clearChatHistory()" style="margin-top:10px; background:rgba(239,68,68,0.2); color:#ef4444; border:1px solid #ef4444; padding:5px 10px; border-radius:5px; cursor:pointer;">🗑 Очистить историю</button>
        </div>
    `;
    
    chatHistory.forEach(item => {
        const msg = document.createElement('div');
        msg.className = `chat-msg ${item.type === 'user' ? 'user-msg' : 'bot-msg'}`;
        msg.innerHTML = item.html;
        
        if (item.type === 'bot' && item.hasExport) {
            const exportBtn = document.createElement('button');
            exportBtn.className = 'ai-export-btn';
            exportBtn.innerText = '📥 Скачать эти лиды (CSV)';
            exportBtn.onclick = () => exportAiLeadsCsvData(item.channelsData);
            msg.appendChild(exportBtn);
        }
        
        aiChatArea.appendChild(msg);
    });
    aiChatArea.scrollTop = aiChatArea.scrollHeight;
}

function clearChatHistory() {
    chatHistory = [];
    saveChatHistory();
    aiMatchedIds.clear();
    renderChatHistory();
    forceRedraw();
}

function closeSidebar() { 
    sidebar.classList.remove('open'); 
    setTimeout(() => window.dispatchEvent(new Event('resize')), 450);
}

function toggleAiSidebar() {
    if (aiSidebar.classList.contains('open')) {
        aiSidebar.classList.remove('open');
        aiMatchedIds.clear(); 
        forceRedraw();
    } else {
        sidebar.classList.remove('open'); 
        aiSettingsPanel.style.display = 'none';
        aiChatArea.style.display = 'flex';
        aiSidebar.classList.add('open');
        aiInput.focus();
    }
    setTimeout(() => window.dispatchEvent(new Event('resize')), 450);
}

document.getElementById('btn-ai-helper').addEventListener('click', toggleAiSidebar);
document.getElementById('close-ai-btn').addEventListener('click', toggleAiSidebar);

function forceRedraw() {
    if (!Graph) return;
    if (is3D) {
        Graph.nodeColor(Graph.nodeColor()).linkColor(Graph.linkColor());
    } else {
        Graph.nodeCanvasObject(render2DNode);
    }
}

function updatePhysics() {
    if (!Graph) return;
    const spreadMultiplier = parseInt(document.getElementById('spread-slider').value) / 100;
    const charge = Graph.d3Force('charge');
    const link = Graph.d3Force('link');
    const center = Graph.d3Force('center');

    if (isMacro) {
        // Выкручиваем отталкивание на максимум
        if (charge) charge.strength(-15000 * spreadMultiplier).distanceMax(15000);
        if (link) {
            link.distance(2000);
            // ПОЛНОСТЬЮ ОТКЛЮЧАЕМ стягивание нитей (сила = 0)
            if (typeof link.strength === 'function') link.strength(l => 0);
        }
        // Ослабляем гравитацию к центру (чтобы папки могли разлететься)
        if (center) center.strength(0.02);
    } else {
        if (charge) charge.strength(-200 * spreadMultiplier).distanceMax(1000);
        if (link) {
            link.distance(50);
            if (typeof link.strength === 'function') link.strength(l => 0.3);
        }
        // Возвращаем нормальную гравитацию для микро-режима (каналов)
        if (center) center.strength(1);
    }
    Graph.d3ReheatSimulation();
}

function zoomToMatches(useAiMatches = false) {
    if (!Graph) return;
    let matched = [];
    
    if (useAiMatches && aiMatchedIds.size > 0 && !isMacro) {
        matched = graphData.nodes.filter(n => aiMatchedIds.has(n.id));
    } else if (searchQuery) {
        matched = graphData.nodes.filter(n => {
            const isFilteredOut = (!isMacro && n.subs < minSubsFilter) || (!isMacro && hideEmpty && n.subs === 0);
            if (isFilteredOut) return false;
            return (n.title || "").toLowerCase().includes(searchQuery) ||
                   (n.username || "").toLowerCase().includes(searchQuery) ||
                   (n.tags || "").toLowerCase().includes(searchQuery) ||
                   (n.category || "").toLowerCase().includes(searchQuery);
        });
    }

    if (matched.length === 0) return;

    let cx = 0, cy = 0, cz = 0;
    let validNodes = 0;

    matched.forEach(n => {
        if (n.x !== undefined && !isNaN(n.x)) {
            cx += n.x; cy += n.y;
            if (is3D) cz += (n.z || 0);
            validNodes++;
        }
    });

    if (validNodes === 0) return;
    cx /= validNodes; cy /= validNodes; cz /= validNodes;

    if (is3D) {
        Graph.cameraPosition({ x: cx, y: cy, z: cz + 600 }, { x: cx, y: cy, z: cz }, 1500);
    } else {
        Graph.centerAt(cx, cy, 1500);
        Graph.zoom(isMacro ? 1 : 1.5, 1500);
    }
}

// --- INITIALIZE GRAPH ENGINE ---
function initGraph() {
    if (Graph) {
        if (typeof Graph.pauseAnimation === 'function') Graph.pauseAnimation();
        if (typeof Graph._destructor === 'function') Graph._destructor();
    }

    const elem = document.getElementById('graph-container');
    elem.innerHTML = ''; 
    
    if (is3D) {
        Graph = ForceGraph3D()(elem)
            .backgroundColor('#11141c')
            .nodeRelSize(isMacro ? 8 : 4)
            .nodeVal(n => Math.max(1, Math.log10(n.subs || 1)))
            .nodeColor(n => {
                if (aiMatchedIds.size > 0 && !isMacro) {
                    if (!aiMatchedIds.has(n.id)) return 'rgba(50,50,50,0.05)';
                    return '#a78bfa'; 
                }
                if (searchQuery) {
                    const textMatch = (n.title || "").toLowerCase().includes(searchQuery) ||
                                      (n.username || "").toLowerCase().includes(searchQuery) ||
                                      (n.tags || "").toLowerCase().includes(searchQuery) ||
                                      (n.category || "").toLowerCase().includes(searchQuery);
                    if (!textMatch) return 'rgba(50,50,50,0.1)';
                }
                const isHovered = n === hoverNode;
                const isNeighbor = highlightNodes.has(n);
                if (hoverNode && !isHovered && !isNeighbor) return 'rgba(50,50,50,0.1)';
                
                return getTagColor(n.tags);
            })
            .nodeLabel(n => `${isMacro ? '📁 ' : ''}${n.title}\nSubs: ${n.subs}`)
            .linkWidth(l => highlightLinks.has(l) ? 2 : (isMacro ? l.weight * 0.1 : 0.5))
            .linkOpacity(linesAlpha / 255)
            .linkColor(l => {
                if (highlightLinks.has(l)) return '#4da6ff';
                if (!isMacro && l.type === 'ai_semantic') return '#a78bfa'; 
                return '#64748b'; 
            })
            .linkDirectionalParticles(l => (!isMacro && l.type === 'ai_semantic') ? 2 : 0) 
            .linkDirectionalParticleWidth(1.5)
            .linkDirectionalParticleColor(() => '#a78bfa')
            .onNodeHover(handleNodeHover)
            .onNodeClick(handleNodeClick);
            
    } else {
        Graph = ForceGraph()(elem)
            .backgroundColor('transparent')
            .nodeId('id')
            .linkWidth(l => highlightLinks.has(l) ? 1.5 : (isMacro ? Math.min(5, l.weight * 0.2) : 0.5))
            .linkColor(l => {
                if (highlightLinks.has(l)) return `rgba(77, 166, 255, 0.9)`;
                if (!isMacro && l.type === 'ai_semantic') return `rgba(167, 139, 250, ${(linesAlpha / 255).toFixed(2)})`; 
                return `rgba(100, 116, 139, ${(linesAlpha / 255).toFixed(2)})`;
            })
            .linkLineDash(l => (!isMacro && l.type === 'ai_semantic') ? [4, 4] : null) 
            .onRenderFramePre(renderClusters)
            .nodePointerAreaPaint((node, color, ctx, globalScale) => {
                const drawR = getNodeRadius(node.subs, isMacro);
                const scale = globalScale || 1;
                
                // Делаем хитбокс динамическим: он всегда будет комфортного размера на экране
                const hitR = Math.max(drawR + 10, 15 / scale);
                
                ctx.fillStyle = color;
                ctx.beginPath();
                ctx.arc(node.x, node.y, hitR, 0, 2 * Math.PI, false);
                ctx.fill();
                
                // В макро-режиме добавляем невидимый прямоугольник хитбокса прямо поверх текста
                if (isMacro) {
                    const fontSize = 14 / scale;
                    // Примерная длина текста, чтобы клик срабатывал по всей длине названия
                    const textWidth = 150 / scale; 
                    ctx.fillRect(node.x, node.y - fontSize, textWidth, fontSize * 2);
                }
            })
            .nodeCanvasObject(render2DNode)
            .onNodeHover(handleNodeHover)
            .onNodeClick(handleNodeClick);
    }

    loadData();
}

function loadData() {
    const endpoint = isMacro ? '/api/graph/macro' : '/api/graph/micro';
    fetch(endpoint)
        .then(res => {
            if (!res.ok) throw new Error("Server not ready");
            return res.json();
        })
        .then(data => {
            const loadingEl = document.getElementById('loading');
            if (loadingEl) {
                loadingEl.style.display = 'none';
                loadingEl.innerHTML = "🚀 Загрузка и расчет физики..."; // Возвращаем текст для следующих загрузок
            }
            const validIds = new Set(data.nodes.map(n => n.id));
            const safeLinks = data.links.filter(l => validIds.has(l.source) && validIds.has(l.target));
            
            graphData = { nodes: data.nodes, links: safeLinks };
            const spreadRadius = isMacro ? 4000 : 800;
            
            graphData.nodes.forEach(n => {
                if (n.x === undefined || n.y === undefined) {
                    n.x = (Math.random() - 0.5) * spreadRadius;
                    n.y = (Math.random() - 0.5) * spreadRadius;
                    if (is3D) n.z = (Math.random() - 0.5) * spreadRadius;
                }
            });
            
            clustersData = {};
            if (!isMacro) {
                graphData.nodes.forEach(n => {
                    let cat = (n.category && n.category !== 'Uncategorized') ? n.category : "Без категории";
                    if(!clustersData[cat]) clustersData[cat] = { nodes: [], color: getTagColor(cat) };
                    clustersData[cat].nodes.push(n);
                });
            }

            graphData.links.forEach(link => {
                const a = graphData.nodes.find(n => n.id === link.source);
                const b = graphData.nodes.find(n => n.id === link.target);
                if(a && b) {
                    !a.neighbors && (a.neighbors = []); !b.neighbors && (b.neighbors = []);
                    a.neighbors.push(b); b.neighbors.push(a);
                    !a.links && (a.links = []); !b.links && (b.links = []);
                    a.links.push(link); b.links.push(link);
                }
            });

            Graph.graphData(graphData);
            setTimeout(updatePhysics, 50); 
            
            if (!isMacro && aiMatchedIds.size > 0) {
                setTimeout(() => zoomToMatches(true), 500);
            }
        })
        .catch(err => {
            console.warn("Ожидание сервера...", err);
            const loadingEl = document.getElementById('loading');
            if (loadingEl) {
                loadingEl.style.display = 'block';
                loadingEl.innerHTML = "⏳ Сервер загружается, подождите...";
            }
            // Автоматически пробуем снова через 1.5 секунды
            setTimeout(loadData, 1500);
        });
}

function connectWebSocket() {
    const ws = new WebSocket(`ws://${window.location.host}/ws`);
    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.action === "update_graph") loadData();
    };
    ws.onclose = () => setTimeout(connectWebSocket, 5000); 
}

function handleNodeHover(node) {
    highlightNodes.clear();
    highlightLinks.clear();
    if (node) {
        highlightNodes.add(node);
        if(node.neighbors) node.neighbors.forEach(n => highlightNodes.add(n));
        if(node.links) node.links.forEach(l => highlightLinks.add(l));
    }
    hoverNode = node || null;
    document.getElementById('graph-container').style.cursor = node ? 'pointer' : null;
    forceRedraw();
}

function handleNodeClick(node) {
    if (isMacro) {
        isMacro = false;
        document.getElementById('btn-mode').innerText = "✨ Микро (Каналы)";
        document.getElementById('btn-mode').classList.replace("primary", "secondary");
        
        searchQuery = node.id.toLowerCase();
        document.getElementById('search-box').value = node.id;
        aiMatchedIds.clear(); 
        
        document.getElementById('loading').style.display = 'block';
        initGraph(); 
        setTimeout(() => zoomToMatches(false), 1500);
    } else {
        if (!is3D) {
            Graph.centerAt(node.x, node.y, 800);
            Graph.zoom(2, 800);
        }
        document.getElementById('sb-title').innerText = node.title;
        document.getElementById('sb-username').innerText = node.username || 'No username';
        document.getElementById('sb-stats').innerText = `Subscribers: ${node.subs.toLocaleString()}`;
        document.getElementById('sb-tags').innerText = `Folder: ${node.category || 'None'}\nTags: ${node.tags || 'None'}`;
        document.getElementById('sb-posts').innerText = node.posts || 'No description/posts found.';
        
        const tgLink = document.getElementById('sb-link');
        if (node.username) {
            tgLink.style.display = 'block';
            tgLink.href = `https://t.me/${node.username.replace('@', '')}`;
        } else {
            tgLink.style.display = 'none';
        }
        
        aiSidebar.classList.remove('open');
        sidebar.classList.add('open');
        setTimeout(() => window.dispatchEvent(new Event('resize')), 450);
    }
}

function renderClusters(ctx, globalScale) {
    if (isMacro || globalScale < 0.1) return; 
    Object.values(clustersData).forEach(cluster => {
        if(cluster.nodes.length < 3) return;
        if(cluster.nodes[0].x === undefined || isNaN(cluster.nodes[0].x)) return;

        let cx = 0, cy = 0;
        cluster.nodes.forEach(n => { cx += n.x; cy += n.y; });
        cx /= cluster.nodes.length; cy /= cluster.nodes.length;

        let maxDist = 0;
        cluster.nodes.forEach(n => {
            let d = Math.hypot(n.x - cx, n.y - cy);
            if(d > maxDist) maxDist = d;
        });
        
        let r = Math.max(maxDist * 1.5, 150);
        if(isNaN(cx) || isNaN(cy) || isNaN(r)) return;

        let grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
        grad.addColorStop(0, cluster.color + '22'); 
        grad.addColorStop(0.6, cluster.color + '0A'); 
        grad.addColorStop(1, 'transparent');
        
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, 2*Math.PI);
        ctx.fill();
        
        if(globalScale < 0.8 && r > 200) {
            ctx.font = `bold ${30/globalScale}px Sans-Serif`;
            ctx.textAlign = 'center';
            ctx.fillStyle = 'rgba(255,255,255,0.3)';
            let tagName = cluster.nodes[0].category && cluster.nodes[0].category !== 'Uncategorized' ? cluster.nodes[0].category.toUpperCase() : "БЕЗ КАТЕГОРИИ";
            ctx.fillText("📁 " + tagName, cx, cy - 20);
        }
    });
}

function render2DNode(node, ctx, globalScale) {
    if (node.x === undefined || isNaN(node.x)) return;

    const isHovered = node === hoverNode;
    const isNeighbor = highlightNodes.has(node);
    const isFilteredOut = (!isMacro && node.subs < minSubsFilter) || (!isMacro && hideEmpty && node.subs === 0);
    if (isFilteredOut) return;

    let isAiMatch = false;
    let opacity = 1;

    if (aiMatchedIds.size > 0 && !isMacro) {
        if (!aiMatchedIds.has(node.id)) opacity = 0.05;
        else isAiMatch = true;
    } else if (searchQuery) {
        const textMatch = (node.title || "").toLowerCase().includes(searchQuery) ||
                          (node.username || "").toLowerCase().includes(searchQuery) ||
                          (node.tags || "").toLowerCase().includes(searchQuery) ||
                          (node.category || "").toLowerCase().includes(searchQuery);
        if (!textMatch) opacity = 0.05;
    } else if (hoverNode && !isHovered && !isNeighbor) {
        opacity = 0.15;
    }

    const r = getNodeRadius(node.subs, isMacro);
    const drawR = isHovered || isNeighbor || isAiMatch ? r * 1.5 : r;
    const color = isAiMatch ? '#a78bfa' : getTagColor(node.tags);

    ctx.globalAlpha = opacity;
    
    if (opacity > 0.1) {
        const glow = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, drawR * 3);
        glow.addColorStop(0, color + (isHovered || isAiMatch ? 'AA' : '44')); 
        glow.addColorStop(1, 'transparent');
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(node.x, node.y, drawR * 3, 0, 2 * Math.PI, false);
        ctx.fill();
    }

    ctx.beginPath();
    ctx.arc(node.x, node.y, drawR, 0, 2 * Math.PI, false);
    ctx.fillStyle = color;
    ctx.fill();

    if (isHovered || isNeighbor || isAiMatch) {
        ctx.lineWidth = (isMacro ? 5 : 2) / globalScale;
        ctx.strokeStyle = isAiMatch ? '#ffffff' : 'rgba(255,255,255,0.8)';
        ctx.stroke();
    }

    const showText = isMacro || globalScale > 1.2 || isHovered || isNeighbor || isAiMatch;
    if (showText) {
        const baseSize = isHovered || isAiMatch ? 14 : 11;
        const fontSize = baseSize / globalScale;
        ctx.font = `${isHovered || isAiMatch ? 'bold' : 'normal'} ${fontSize}px "Segoe UI", Sans-Serif`;
        
        if (isMacro) {
            // В макро-режиме: всегда показываем текст справа от папки
            const label = `📁 ${node.title} (${node.ch_count})`;
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            
            const textWidth = ctx.measureText(label).width;
            const pad = fontSize * 0.3;
            const xOffset = node.x + drawR + (8 / globalScale);
            
            ctx.fillStyle = `rgba(17, 20, 28, ${opacity * 0.8})`;
            ctx.fillRect(xOffset - pad, node.y - fontSize/2 - pad, textWidth + pad*2, fontSize + pad*2);
            
            ctx.fillStyle = isAiMatch ? `rgba(167, 139, 250, ${opacity})` : `rgba(240, 240, 240, ${opacity})`;
            ctx.fillText(label, xOffset, node.y);
        } else {
            // В микро-режиме: текст снизу
            const lines = node.title.split('\n');
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            
            lines.forEach((line, i) => {
                const textWidth = ctx.measureText(line).width;
                const bckgDimensions = [textWidth, fontSize].map(n => n + fontSize * 0.2); 
                const yOffset = node.y + drawR + (4 / globalScale) + (i * fontSize * 1.2);

                ctx.fillStyle = `rgba(17, 20, 28, ${opacity * 0.8})`;
                ctx.fillRect(node.x - bckgDimensions[0] / 2, yOffset - (2/globalScale), bckgDimensions[0], bckgDimensions[1]);
                ctx.fillStyle = isAiMatch ? `rgba(167, 139, 250, ${opacity})` : `rgba(240, 240, 240, ${opacity})`;
                ctx.fillText(line, node.x, yOffset);
            });
        }
    }
    ctx.globalAlpha = 1;
}

// --- SEND AI REQUEST ---
aiInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendAiRequest();
    }
});
btnAiSend.addEventListener('click', sendAiRequest);

async function sendAiRequest() {
    const query = aiInput.value.trim();
    if (!query) return;

    const minSubs = parseInt(inputMinSubs.value) || 0;
    const maxSubs = parseInt(inputMaxSubs.value) || 999999999;

    const userHtml = query.replace(/\n/g, '<br/>') + `<br><i style="font-size:10px; color:#a8b8d0;">[Filter: ${minSubs} - ${maxSubs === 999999999 ? '∞' : maxSubs} subs]</i>`;
    chatHistory.push({ type: 'user', html: userHtml });
    saveChatHistory();
    renderChatHistory();
    
    aiInput.value = '';
    
    const loadingMsg = document.createElement('div');
    loadingMsg.className = 'chat-msg bot-msg';
    loadingMsg.innerHTML = '<span style="color:#a78bfa;">🧠 ИИ анализирует базу и генерирует дорки... Ждем...</span>';
    aiChatArea.appendChild(loadingMsg);
    aiChatArea.scrollTop = aiChatArea.scrollHeight;
    
    btnAiSend.disabled = true;

    try {
        const response = await fetch('/api/ai_helper', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: query, min_subs: minSubs, max_subs: maxSubs })
        });
        
        const data = await response.json();
        aiChatArea.removeChild(loadingMsg); 
        
        if (data.error) {
            chatHistory.push({ type: 'bot', html: `❌ <b>Ошибка:</b> ${data.error}`, hasExport: false });
            saveChatHistory();
            renderChatHistory();
            return;
        }

        let botHtml = `<b>📊 Анализ ниши:</b><br/>${data.analysis.replace(/\n/g, '<br/>')}<br/><br/>`;
        if (data.dorks && data.dorks.length > 0) {
            botHtml += `<b>🎯 Google Dorks (для ручного поиска):</b>`;
            botHtml += `<div class="dorks-box">${data.dorks.join('\n')}</div>`;
        }
        
        botHtml += `<br/><b>🗂 Поиск по локальной БД (с открытыми комментами):</b><br/>`;
        botHtml += `<span style="color:#10b981;">Выбраны теги: ${data.selected_tags.length ? data.selected_tags.join(', ') : 'Ничего не подошло'}</span><br/>`;
        
        let hasExport = false;

        if (data.channels && data.channels.length > 0) {
            botHtml += `Найден(о) <b>${data.channels.length}</b> целевых каналов в графе!`;
            
            data.channels.forEach(ch => {
                botHtml += `
                    <div class="lead-card">
                        <div class="lead-title">${ch.title} <a href="https://t.me/${ch.username.replace('@','')}" target="_blank" style="color:#4da6ff;text-decoration:none;font-weight:normal;">${ch.username}</a></div>
                        <div class="lead-meta">
                            <span>Subs: ${ch.subs.toLocaleString()}</span>
                            <span class="lead-score">${ch.match_score}</span>
                        </div>
                    </div>`;
            });
            hasExport = true;
            currentAiLeads = data.channels;
            aiMatchedIds.clear();
            data.channels.forEach(ch => aiMatchedIds.add(ch.id));
            
            if (isMacro) {
                isMacro = false;
                document.getElementById('btn-mode').innerText = "✨ Микро (Каналы)";
                document.getElementById('btn-mode').classList.replace("primary", "secondary");
                document.getElementById('loading').style.display = 'block';
                initGraph(); 
            } else {
                forceRedraw();
                zoomToMatches(true);
            }
        } else {
            botHtml += `<span style="color:#f59e0b;">Увы, в нашей БД пока нет подходящих каналов с открытыми комментами по этим тегам (или они не подходят под фильтры). Спарси новые через Google Sniper!</span>`;
            aiMatchedIds.clear();
            forceRedraw();
        }

        chatHistory.push({ type: 'bot', html: botHtml, hasExport: hasExport, channelsData: data.channels });
        saveChatHistory();
        renderChatHistory();
        
    } catch (err) {
        aiChatArea.removeChild(loadingMsg);
        chatHistory.push({ type: 'bot', html: `❌ <b>Сетевая ошибка:</b> Не удалось связаться с сервером.`, hasExport: false });
        saveChatHistory();
        renderChatHistory();
    } finally {
        btnAiSend.disabled = false;
    }
}

function exportAiLeadsCsvData(channelsData) {
    if (!channelsData || channelsData.length === 0) return;
    
    let csvContent = "\uFEFF"; 
    csvContent += "Channel Title,Username,Subscribers,Category,Tags,Match Score,Link\n";
    
    channelsData.forEach(ch => {
        const title = `"${(ch.title || '').replace(/"/g, '""')}"`;
        const link = `https://t.me/${ch.username.replace('@','')}`;
        const tags = `"${(ch.tags || '').replace(/"/g, '""')}"`;
        const cat = `"${(ch.category || '').replace(/"/g, '""')}"`;
        
        csvContent += `${title},${ch.username},${ch.subs},${cat},${tags},${ch.match_score},${link}\n`;
    });
    
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", "AI_Leads_Export.csv");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// UI listeners
const searchBox = document.getElementById('search-box');
searchBox.addEventListener('input', e => {
    searchQuery = e.target.value.toLowerCase().trim();
    aiMatchedIds.clear(); 
    forceRedraw();
});
searchBox.addEventListener('keydown', e => { if (e.key === 'Enter') zoomToMatches(false); });

document.getElementById('hide-empty-chk').addEventListener('change', e => { hideEmpty = e.target.checked; forceRedraw(); });

const sValEl = document.getElementById('subs-val');
document.getElementById('subs-slider').addEventListener('input', e => {
    let val = parseInt(e.target.value);
    minSubsFilter = getSliderSubsValue(val);
    if(minSubsFilter >= 1000) sValEl.innerText = `Subs: ${Math.floor(minSubsFilter/1000)}k+`;
    else sValEl.innerText = `Subs: ${minSubsFilter}`;
    forceRedraw();
});

const spreadValEl = document.getElementById('spread-val');
document.getElementById('spread-slider').addEventListener('input', e => {
    spreadValEl.innerText = (parseInt(e.target.value) / 100).toFixed(1) + "x";
    updatePhysics();
});

const alphaValEl = document.getElementById('alpha-val');
document.getElementById('alpha-slider').addEventListener('input', e => {
    linesAlpha = parseInt(e.target.value);
    alphaValEl.innerText = linesAlpha;
    forceRedraw();
});

document.getElementById('btn-mode').addEventListener('click', e => {
    isMacro = !isMacro;
    const btn = e.target;
    if (isMacro) {
        btn.innerText = "🌌 Макро (Ниши)";
        btn.classList.replace("secondary", "primary");
        searchQuery = ""; document.getElementById('search-box').value = "";
    } else {
        btn.innerText = "✨ Микро (Каналы)";
        btn.classList.replace("primary", "secondary");
    }
    document.getElementById('loading').style.display = 'block';
    initGraph();
});

document.getElementById('btn-dim').addEventListener('click', e => {
    is3D = !is3D;
    const btn = e.target;
    if (is3D) {
        btn.innerText = "🪐 2D Режим";
        btn.classList.replace("secondary", "primary");
    } else {
        btn.innerText = "🧊 3D Режим";
        btn.classList.replace("primary", "secondary");
    }
    document.getElementById('loading').style.display = 'block';
    initGraph();
});

// START
renderChatHistory();
initGraph();
connectWebSocket();