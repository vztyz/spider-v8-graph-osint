let currentStep = 1;
let selectedProfile = "";
let selectedProfileStatus = "";
let aiDorks = [];
let profilesLoaded = false;
let settingsLoaded = false;
let availableProxies = []; 

window.setStep = function(step) {
    document.querySelectorAll('.step-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.step-box').forEach((el, index) => {
        el.classList.remove('active');
        if (index + 1 < step) el.classList.add('completed');
        else el.classList.remove('completed');
    });
    
    document.getElementById(`step-${step}`).classList.add('active');
    document.getElementById(`ind-${step}`).classList.add('active');
    currentStep = step;

    if (step === 2 && !profilesLoaded) loadProfilesForWizard();
    if (step === 3 && !settingsLoaded) loadGlobalSettingsForWizard();
    if (step === 4) updateChecklist();
};

document.getElementById('btn-analyze').addEventListener('click', async () => {
    const query = document.getElementById('wiz-niche').value;
    if (!query) return;

    const btn = document.getElementById('btn-analyze');
    const resBox = document.getElementById('wiz-ai-result');
    btn.disabled = true; btn.innerText = "🧠 Анализирую..."; resBox.style.display = "block";
    resBox.innerHTML = '<span style="color:#a78bfa;">Идет оценка ЦА и поиск каналов в БД...</span>';

    try {
        const response = await fetch('/api/ai_helper', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: query, min_subs: 100, max_subs: 999999 })
        });
        const data = await response.json();
        if (data.error) { resBox.innerHTML = `<span style="color:#ef4444;">Ошибка: ${data.error}</span>`; return; }

        let html = `<b>📊 Анализ ЦА:</b><br/>${data.analysis.replace(/\n/g, '<br/>')}<br/><br/>`;
        if (data.channels && data.channels.length > 0) {
            html += `<span style="color:#10b981; font-weight:bold;">✅ Найдено ${data.channels.length} целевых каналов с открытыми комментами.</span>`;
        } else {
            html += `<span style="color:#f59e0b; font-weight:bold;">⚠️ В локальной БД мало каналов.</span><br/>`;
            aiDorks = data.dorks || [];
            if (aiDorks.length > 0) html += `<button id="btn-auto-sniper" class="glass-btn primary" style="margin-top:10px; display:block; width:100%; font-size:12px;">🎯 Запустить Google Sniper (Фоновый сбор)</button>`;
        }
        resBox.innerHTML = html;

        const sniperBtn = document.getElementById('btn-auto-sniper');
        if (sniperBtn) {
            sniperBtn.addEventListener('click', async () => {
                sniperBtn.disabled = true; sniperBtn.innerText = "🚀 Снайпер работает в фоне...";
                await fetch('/api/sniper/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ queries: aiDorks }) });
            });
        }
    } catch (e) { resBox.innerHTML = `<span style="color:#ef4444;">Ошибка сети.</span>`; } 
    finally { btn.disabled = false; btn.innerText = "🧠 Обновить подборку"; }
});

function parseProxyString(raw) {
    const parts = raw.split(':');
    let addr = parts[0] || "";
    let port = parts[1] || "";
    let user = parts[2] || "";
    let pass = parts[3] || "";
    let fullAddr = (addr && port) ? `${addr}:${port}` : addr;
    return { addr: fullAddr, user, pass };
}

window.toggleImportForm = async function() {
    const form = document.getElementById('inline-import-form');
    const selectArea = document.getElementById('select-account-area');
    if (form.style.display === 'none') {
        await populateSmartDefaults();
        form.style.display = 'block'; selectArea.style.display = 'none';
    } else {
        form.style.display = 'none'; selectArea.style.display = 'block';
    }
};

document.getElementById('imp-file').addEventListener('change', function(e) {
    if (e.target.files[0]) {
        let name = e.target.files[0].name;
        name = name.replace(/\.session$/i, '').replace(/\.zip$/i, '');
        document.getElementById('imp-name').value = name;
    }
});

async function populateSmartDefaults() {
    try {
        const res = await fetch('/api/wizard_defaults');
        const data = await res.json();
        if (data.api_id) document.getElementById('imp-id').value = data.api_id;
        if (data.api_hash) document.getElementById('imp-hash').value = data.api_hash;

        const proxySelect = document.getElementById('imp-proxy-select');
        proxySelect.innerHTML = '';
        availableProxies = data.proxies || [];

        if (availableProxies.length > 0) {
            const group = document.createElement('optgroup');
            group.label = "♻️ Использовать сохраненный прокси";
            availableProxies.forEach((p, index) => {
                group.appendChild(new Option(`✅ [${p.type}] ${p.addr}`, index));
            });
            proxySelect.appendChild(group);
        }

        proxySelect.options.add(new Option('➕ Добавить НОВЫЙ прокси...', 'new'));
        proxySelect.options.add(new Option('❌ Без прокси (Опасно)', 'none'));
        proxySelect.dispatchEvent(new Event('change'));
    } catch (e) { console.error(e); }
}

document.getElementById('imp-proxy-select').addEventListener('change', function(e) {
    document.getElementById('new-proxy-block').style.display = e.target.value === 'new' ? 'block' : 'none';
    document.getElementById('proxy-test-result').innerHTML = '';
});

window.testProxyHTTP = async function() {
    const pType = document.getElementById('imp-proxy-type').value;
    const rawAddr = document.getElementById('imp-proxy-addr').value;
    const pData = parseProxyString(rawAddr);
    
    const pUser = pData.user || document.getElementById('imp-proxy-user').value;
    const pPass = pData.pass || document.getElementById('imp-proxy-pass').value;

    const resBox = document.getElementById('proxy-test-result');
    resBox.innerHTML = '<span style="color:#f59e0b;">⏳ Пингуем прокси...</span>';
    
    try {
        const response = await fetch('/api/wizard/test_proxy', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ proxy_type: pType, proxy_addr: pData.addr, proxy_user: pUser, proxy_pass: pPass })
        });
        const data = await response.json();
        resBox.innerHTML = `<span style="color:${data.status === 'ok' ? '#10b981' : '#ef4444'};">${data.message}</span>`;
    } catch(e) {
        resBox.innerHTML = `<span style="color:#ef4444;">❌ Сетевая ошибка</span>`;
    }
};

window.submitInlineImport = async function() {
    const name = document.getElementById('imp-name').value;
    const apiId = document.getElementById('imp-id').value;
    const apiHash = document.getElementById('imp-hash').value;
    const fileInput = document.getElementById('imp-file');
    const proxySelectVal = document.getElementById('imp-proxy-select').value;
    
    if (!name || !apiId || !apiHash || !fileInput.files[0]) {
        alert("Заполните API данные и выберите файл!"); return;
    }

    let pType = 'None', pAddr = '', pUser = '', pPass = '';
    
    if (proxySelectVal === 'new') {
        pType = document.getElementById('imp-proxy-type').value;
        const pData = parseProxyString(document.getElementById('imp-proxy-addr').value);
        pAddr = pData.addr;
        pUser = pData.user || document.getElementById('imp-proxy-user').value;
        pPass = pData.pass || document.getElementById('imp-proxy-pass').value;
    } else if (proxySelectVal !== 'none') {
        const pInfo = availableProxies[parseInt(proxySelectVal)];
        if (pInfo) { pType = pInfo.type; pAddr = pInfo.addr; pUser = pInfo.user; pPass = pInfo.pass; }
    }

    const formData = new FormData();
    formData.append('name', name); 
    formData.append('api_id', apiId); 
    formData.append('api_hash', apiHash);
    formData.append('session_file', fileInput.files[0]);
    formData.append('proxy_type', pType); 
    formData.append('proxy_addr', pAddr);
    formData.append('proxy_user', pUser); 
    formData.append('proxy_pass', pPass);

    try {
        const res = await fetch('/api/profiles/import', { method: 'POST', body: formData });
        const text = await res.text();
        let data;
        try { data = JSON.parse(text); } catch (e) { alert("🚨 Критический сбой сервера: " + text); return; }
        
        if (res.ok && data.status === "ok") {
            selectedProfile = name;
            await loadProfilesForWizard(); 
            document.getElementById('inline-import-form').style.display = 'none';
            document.getElementById('select-account-area').style.display = 'block';
        } else {
            alert("Ошибка импорта: " + (data.detail || data.message || "Неизвестная ошибка"));
        }
    } catch (e) { alert("Сбой загрузки: " + e.message); }
};

async function loadProfilesForWizard() {
    profilesLoaded = true;
    const res = await fetch('/api/profiles');
    const profiles = await res.json();
    
    const tbody = document.getElementById('accounts-tbody');
    tbody.innerHTML = '';
    
    if (profiles.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#a8b8d0;">Нет добавленных аккаунтов. Загрузите .session</td></tr>';
        selectedProfile = "";
        document.getElementById('btn-check-proxy').disabled = true;
        document.getElementById('btn-check-spambot').disabled = true;
        return;
    }

    const fullProfiles = await Promise.all(profiles.map(async p => {
        const pRes = await fetch(`/api/profiles/${p.name}`);
        const data = await pRes.json();
        data.status = p.status;
        data.target = p.target;
        data.bridge = p.bridge;
        return data;
    }));

    // Сохраняем глобально для доступа из других функций
    window.fullProfilesData = fullProfiles;

    fullProfiles.forEach(p => {
        const tr = document.createElement('tr');
        if (selectedProfile === p.name) {
            tr.classList.add('selected');
            document.getElementById('btn-check-proxy').disabled = false;
            document.getElementById('btn-check-spambot').disabled = false;
        }
        
        let proxyHtml = p.proxy_type !== 'None' && p.proxy_addr ? `<span style="color:#10b981;">${p.proxy_type}</span>` : `<span style="color:#ef4444;">Нет прокси</span>`;
        let statusHtml = p.status === 'error' ? `<span style="color:#ef4444;">Ошибка</span>` : `<span style="color:#10b981;">Idle</span>`;
        
        let targetHtml = p.target ? `<a href="${p.target}" target="_blank" style="color:#4da6ff;">Основной</a>` : `<span style="color:#666;">-</span>`;
        let bridgeHtml = p.bridge ? `<a href="${p.bridge}" target="_blank" style="color:#a78bfa;">Прокладка</a>` : `<span style="color:#666;">-</span>`;

        let isSelected = (selectedProfile === p.name);
        let btnStyle = isSelected 
            ? "background: rgba(16,185,129,0.2); color: #10b981; border: 1px solid #10b981;" 
            : "border-color: #a8b8d0; color: #a8b8d0;";
        let btnText = isSelected ? "✅ Выбран" : "Выбрать";

        tr.innerHTML = `
            <td style="font-weight:bold;">${p.name}</td>
            <td>${statusHtml}</td>
            <td>${proxyHtml}</td>
            <td>${targetHtml}</td>
            <td>${bridgeHtml}</td>
            <td style="text-align:center; display: flex; gap: 5px; justify-content: center;">
                <button class="glass-btn outline" style="padding: 2px 8px; font-size: 11px; ${btnStyle}" onclick="window.selectProfileInWizard(event, '${p.name}')">${btnText}</button>
                <button class="del-btn" onclick="deleteProfileFromWizard(event, '${p.name}')">✖</button>
            </td>
        `;
        
        tr.onclick = (e) => window.selectProfileInWizard(e, p.name);

        tbody.appendChild(tr);
    });
}

window.deleteProfileFromWizard = async function(event, name) {
    event.stopPropagation();
    if (!confirm(`Точно удалить аккаунт ${name} из базы?`)) return;
    
    await fetch(`/api/profiles/${name}`, { method: 'DELETE' });
    if (selectedProfile === name) selectedProfile = "";
    await loadProfilesForWizard();
};

document.getElementById('btn-check-proxy').addEventListener('click', async () => {
    if (!selectedProfile) return;
    const btn = document.getElementById('btn-check-proxy');
    const resBox = document.getElementById('proxy-result');
    btn.disabled = true; btn.innerText = "⏳ Подключение к Telegram..."; resBox.innerHTML = "";

    try {
        const response = await fetch('/api/wizard/validate_account', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: selectedProfile })
        });
        const data = await response.json();
        resBox.innerHTML = `<span style="color:${data.status === 'ok' ? '#10b981' : '#ef4444'};">${data.message}</span>`;
    } catch (e) { resBox.innerHTML = `<span style="color:#ef4444;">Ошибка связи с сервером.</span>`; } 
    finally { btn.disabled = false; btn.innerText = "🛡️ Подключение (Связка)"; }
});

document.getElementById('btn-check-spambot').addEventListener('click', async () => {
    if (!selectedProfile) return;
    const btn = document.getElementById('btn-check-spambot');
    const resBox = document.getElementById('proxy-result');
    btn.disabled = true; btn.innerText = "⏳ Опрос @spambot..."; resBox.innerHTML = "";

    try {
        const response = await fetch('/api/wizard/check_spambot', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: selectedProfile })
        });
        const data = await response.json();
        if (data.status === 'ok') {
            resBox.innerHTML = `<span style="color:#10b981;">✅ @spambot: ${data.message}</span>`;
        } else {
            resBox.innerHTML = `<span style="color:#ef4444;">❌ @spambot: ${data.message}</span>`;
        }
    } catch (e) { resBox.innerHTML = `<span style="color:#ef4444;">Ошибка связи с сервером.</span>`; } 
    finally { btn.disabled = false; btn.innerText = "🤖 Проверить @spambot"; }
});

window.toggleFunnelMode = function() {
    const mode = document.querySelector('input[name="funnel_type"]:checked').value;
    if (mode === 'direct') {
        document.getElementById('wiz-bridge-settings').style.display = 'none';
        document.getElementById('wiz-direct-settings').style.display = 'block';
        if(document.getElementById('wiz-channel-title-wrapper')) document.getElementById('wiz-channel-title-wrapper').style.display = 'none';
    } else {
        document.getElementById('wiz-bridge-settings').style.display = 'block';
        document.getElementById('wiz-direct-settings').style.display = 'none';
        if(document.getElementById('wiz-channel-title-wrapper')) document.getElementById('wiz-channel-title-wrapper').style.display = 'block';
    }
};

let croppedFiles = { acc: null, chan: null, post: null };
let cropper = null;
let currentCropKey = null;
let currentThumbId = null;
let currentInputId = null;

function setupImagePreview(inputId, thumbId, key) {
    const input = document.getElementById(inputId);
    const thumb = document.getElementById(thumbId);
    if (input && thumb) {
        input.addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = function(event) {
                    openCropModal(event.target.result, key, thumbId, inputId);
                }
                reader.readAsDataURL(file);
            } else {
                thumb.style.backgroundImage = 'none';
                croppedFiles[key] = null;
            }
        });
    }
}

function openCropModal(imgSrc, key, thumbId, inputId) {
    currentCropKey = key;
    currentThumbId = thumbId;
    currentInputId = inputId;
    
    const modal = document.getElementById('crop-modal');
    const img = document.getElementById('crop-image');
    
    img.src = imgSrc;
    modal.style.display = 'flex';
    
    if (cropper) cropper.destroy();
    
    const ratio = (key === 'acc' || key === 'chan') ? 1 : NaN;
    
    cropper = new Cropper(img, {
        aspectRatio: ratio,
        viewMode: 1,
        autoCropArea: 0.9,
        background: false
    });
}

window.closeCropModal = function() {
    document.getElementById('crop-modal').style.display = 'none';
    if (cropper) { cropper.destroy(); cropper = null; }
    document.getElementById(currentInputId).value = ''; 
};

window.applyCrop = function() {
    if (!cropper) return;
    const canvas = cropper.getCroppedCanvas({ maxWidth: 800, maxHeight: 800 });
    canvas.toBlob(function(blob) {
        croppedFiles[currentCropKey] = blob;
        const thumb = document.getElementById(currentThumbId);
        thumb.style.backgroundImage = `url(${canvas.toDataURL()})`;
        thumb.innerText = '';
        document.getElementById('crop-modal').style.display = 'none';
        cropper.destroy();
        cropper = null;
    }, 'image/jpeg', 0.9);
};

setupImagePreview('wiz-acc-avatar', 'thumb-acc', 'acc');
setupImagePreview('wiz-chan-avatar', 'thumb-chan', 'chan');
setupImagePreview('wiz-post-image', 'thumb-post', 'post');

document.getElementById('btn-generate-names').addEventListener('click', async () => {
    const niche = document.getElementById('wiz-niche').value || "Бизнес";
    const lang = document.getElementById('wiz-ai-lang').value || "RU";
    const gender = document.getElementById('wiz-ai-gender').value || "Женский";
    const ageMin = document.getElementById('wiz-ai-age-min').value || "20";
    const ageMax = document.getElementById('wiz-ai-age-max').value || "25";
    const country = document.getElementById('wiz-ai-country').value || "";
    const profession = document.getElementById('wiz-ai-profession').value || "";
    const interests = document.getElementById('wiz-ai-interests').value || "";

    const btn = document.getElementById('btn-generate-names');
    const suggDiv = document.getElementById('ai-name-suggestions');
    btn.innerText = "⏳ Думаю...";
    
    try {
        const res = await fetch('/api/wizard/generate_names', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ 
                niche: niche,
                language: lang,
                gender: gender,
                age_min: ageMin,
                age_max: ageMax,
                country: country,
                profession: profession,
                interests: interests
            })
        });
        const data = await res.json();
        btn.innerText = "🪄 Придумать ИИ";
        
        if (data.error) { alert(data.error); return; }
        
        const badge = document.createElement('div');
        badge.className = 'status-badge';
        badge.style.cursor = 'pointer';
        badge.style.background = 'rgba(167, 139, 250, 0.2)';
        badge.style.color = '#a78bfa';
        badge.style.border = '1px solid #a78bfa';
        badge.style.fontSize = '12px';
        badge.style.padding = '6px 12px';
        badge.innerText = `✨ ${data.first_name} ${data.last_name} | ${data.channel_title}`;
        badge.title = "Нажми, чтобы применить";
        
        badge.onclick = () => {
            document.getElementById('wiz-first-name').value = data.first_name;
            document.getElementById('wiz-last-name').value = data.last_name;
            document.getElementById('wiz-channel-title').value = data.channel_title;
            
            // Заполняем БИО и Пост, если ИИ их вернул
            if (data.bio) {
                document.getElementById('wiz-bio').value = data.bio;
            }
            if (data.post) {
                const postBox = document.getElementById('wiz-post');
                if (postBox) postBox.value = data.post;
            }
            
            // Визуальный отклик
            badge.innerText = "✅ Применено!";
            setTimeout(() => badge.innerText = `✨ ${data.first_name} ${data.last_name} | ${data.channel_title}`, 2000);
            saveWizardState();
        };
        suggDiv.appendChild(badge);
    } catch(e) { btn.innerText = "🪄 Придумать ИИ"; }
});

document.getElementById('btn-preview-ai').addEventListener('click', async () => {
    const prompt = document.getElementById('wiz-prompt').value;
    const resBox = document.getElementById('ai-preview-result');
    const btn = document.getElementById('btn-preview-ai');
    
    btn.innerText = "⏳ Ожидание...";
    resBox.style.display = "block"; 
    resBox.innerText = "Генерация тестового коммента...";
    
    try {
        const res = await fetch('/api/wizard/preview_comment', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ prompt: prompt })
        });
        const data = await res.json();
        btn.innerText = "🎲 Тест Промпта";
        if (data.error) { 
            resBox.style.color = "#ef4444"; 
            resBox.innerHTML = data.error; 
        } else { 
            resBox.style.color = "#10b981"; 
            let formatted = data.comment.replace(/\n/g, '<br/>').replace(/\*\*(.*?)\*\*/g, '<b>$1</b>');
            resBox.innerHTML = "<b>💬 ИИ Ответил:</b><br/>" + formatted; 
        }
    } catch(e) { btn.innerText = "🎲 Тест Промпта"; }
});

document.getElementById('wiz-warmed-up').addEventListener('change', function(e) {
    const box = document.getElementById('funnel-setup-box');
    if (e.target.checked) box.classList.add('dimmed'); else box.classList.remove('dimmed');
});

async function loadGlobalSettingsForWizard() {
    settingsLoaded = true;
    const res = await fetch('/api/settings/global');
    const data = await res.json();
    document.getElementById('wiz-prompt').value = data.auto_comment_prompt || "Напиши интригующий комментарий...";
    document.getElementById('wiz-bio').value = data.funnel_bio || "Мой блог и услуги 👉";
    document.getElementById('wiz-post').value = data.funnel_post || "Привет! Подписывайся на мой закрытый канал!";
}

window.saveAndGoToStep4 = async function() {
    const data = {
        auto_comment_prompt: document.getElementById('wiz-prompt').value,
        funnel_bio: document.getElementById('wiz-bio').value,
        funnel_post: document.getElementById('wiz-post').value
    };
    await fetch('/api/settings/global', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    setStep(4);
};

function updateChecklist() {
    const badge = document.getElementById('chk-acc-badge');
    const txt = document.getElementById('chk-acc-text');
    const funnelTxt = document.getElementById('chk-funnel-text');
    
    const prepBtn = document.getElementById('btn-launch-prep');
    const fullBtn = document.getElementById('btn-launch-full');
    
    const skipSetup = document.getElementById('wiz-warmed-up').checked;

    if (skipSetup) {
        funnelTxt.innerHTML = "<b>Оформление пропущено.</b> (Аккаунт уже настроен)";
        prepBtn.innerHTML = `☕ ТОЛЬКО ПРОГРЕВ<br><span style="font-size: 11px; font-weight: normal; color: #a8b8d0;">Читать ленту (Оформление отключено)</span>`;
        fullBtn.innerHTML = `🔥 СРАЗУ В БОЙ<br><span style="font-size: 11px; font-weight: normal; color: rgba(255,255,255,0.7);">Прогреть и начать Лидогенерацию</span>`;
    } else {
        funnelTxt.innerHTML = "Воронка будет создана (Аватарки, БИО, Канал)";
        prepBtn.innerHTML = `🛠️ ТОЛЬКО ПОДГОТОВКА<br><span style="font-size: 11px; font-weight: normal; color: #a8b8d0;">Оформить профиль и прогреть</span>`;
        fullBtn.innerHTML = `🔥 ПОЛНЫЙ ЦИКЛ<br><span style="font-size: 11px; font-weight: normal; color: rgba(255,255,255,0.7);">Оформить, Прогреть и начать Лидогенерацию</span>`;
    }

    const isRunning = (selectedProfileStatus === 'running' || selectedProfileStatus === 'floodwait');
    const step3Card = document.querySelector('#step-3 .wiz-card');
    if (step3Card) {
        step3Card.style.opacity = isRunning ? '0.5' : '1';
        step3Card.style.pointerEvents = isRunning ? 'none' : 'auto';
    }

    if (selectedProfile) {
        badge.style.background = "rgba(16,185,129,0.2)"; badge.style.color = "#10b981"; badge.innerText = "ГОТОВ";
        if (isRunning) {
            txt.innerHTML = `Аккаунт <b>${selectedProfile}</b> сейчас <span style="color:#f59e0b;">РАБОТАЕТ</span>. Настройки заблокированы.`;
            prepBtn.disabled = true; fullBtn.disabled = true;
            fullBtn.classList.remove('ai-btn'); fullBtn.classList.add('secondary');
            fullBtn.innerHTML = "АККАУНТ УЖЕ ЗАПУЩЕН";
        } else {
            txt.innerHTML = `Аккаунт выбран: <b>${selectedProfile}</b>`;
            prepBtn.disabled = false; fullBtn.disabled = false;
            fullBtn.classList.remove('secondary'); fullBtn.classList.add('ai-btn');
        }
    } else {
        badge.style.background = "rgba(239,68,68,0.2)"; badge.style.color = "#ef4444"; badge.innerText = "ОШИБКА";
        txt.innerHTML = `Аккаунт не выбран! <a href="#" onclick="setStep(2)" style="color:#4da6ff;">Вернуться к Шагу 2</a>`;
        prepBtn.disabled = true; fullBtn.disabled = true;
        fullBtn.classList.remove('ai-btn'); fullBtn.classList.add('secondary');
    }
}

const logsContainer = document.getElementById('wizard-logs');
const launchedProfilesInSession = new Set();
let isWizardWsConnected = false;

function connectWizardWebSocket() {
    if (isWizardWsConnected) return;
    isWizardWsConnected = true;
    
    const ws = new WebSocket(`ws://${window.location.host}/ws`);
    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "log" && (launchedProfilesInSession.has(msg.profile) || msg.profile === "AI Tagger")) {
            const div = document.createElement('div');
            if (msg.message.includes("❌")) div.style.color = "#ef4444";
            else if (msg.message.includes("✅")) div.style.color = "#10b981";
            else if (msg.message.includes("🎯") || msg.message.includes("🔥")) div.style.color = "#4da6ff";
            else div.style.color = "#a8b8d0"; 
            
            div.innerText = `[${msg.profile}] ${msg.message}`;
            
            logsContainer.appendChild(div);
            
            if (logsContainer.children.length > 300) {
                logsContainer.removeChild(logsContainer.firstChild);
            }
            logsContainer.scrollTop = logsContainer.scrollHeight;
        }
    };
    ws.onclose = () => { isWizardWsConnected = false; setTimeout(connectWizardWebSocket, 5000); };
}

window.resetWizardForNewAccount = function() {
    selectedProfile = "";
    document.querySelectorAll('#accounts-tbody tr').forEach(row => row.classList.remove('selected'));
    
    document.getElementById('funnel-links-result').style.display = 'none';
    document.getElementById('res-target-link').style.display = 'none';
    document.getElementById('res-bridge-link').style.display = 'none';
    
    document.getElementById('btn-launch-prep').style.display = 'block';
    document.getElementById('btn-launch-full').style.display = 'block';
    document.getElementById('btn-launch-prep').disabled = true;
    document.getElementById('btn-launch-full').disabled = true;
    
    document.getElementById('nav-btn-4').style.display = 'flex';
    
    // Сбрасываем кнопку Экстренной остановки
    const stopBtn = document.getElementById('btn-wizard-stop');
    if (stopBtn) {
        stopBtn.disabled = false;
        stopBtn.innerText = "🛑 Экстренная остановка";
        stopBtn.style.opacity = "1";
    }
    
    updateChecklist();
    setStep(2);
};

window.selectProfileInWizard = function(event, name) {
    if (event) event.stopPropagation();
    
    if (window.fullProfilesData) {
        const profileData = window.fullProfilesData.find(p => p.name === name);
        if(profileData) {
            selectedProfile = name;
            selectedProfileStatus = profileData.status;

            if (profileData.warmup_count !== undefined) document.getElementById('wiz-warmup-count').value = profileData.warmup_count;
            if (profileData.warmup_min !== undefined) document.getElementById('wiz-warmup-min').value = profileData.warmup_min;
            if (profileData.warmup_max !== undefined) document.getElementById('wiz-warmup-max').value = profileData.warmup_max;
            if (profileData.daily_limit !== undefined) document.getElementById('wiz-daily-limit').value = profileData.daily_limit;
            if (profileData.delay_min !== undefined) document.getElementById('wiz-delay-min').value = profileData.delay_min;
            if (profileData.delay_max !== undefined) document.getElementById('wiz-delay-max').value = profileData.delay_max;
            if (profileData.first_name !== undefined && profileData.first_name !== '') document.getElementById('wiz-first-name').value = profileData.first_name;
            if (profileData.last_name !== undefined && profileData.last_name !== '') document.getElementById('wiz-last-name').value = profileData.last_name;
            if (profileData.channel_title !== undefined && profileData.channel_title !== '') document.getElementById('wiz-channel-title').value = profileData.channel_title;
        }
    }

    document.getElementById('btn-check-proxy').disabled = false;
    document.getElementById('btn-check-spambot').disabled = false;
    document.getElementById('proxy-result').innerHTML = "";
    loadProfilesForWizard();
    updateChecklist();
};

// ЕДИНСТВЕННАЯ, ПРАВИЛЬНАЯ ФУНКЦИЯ ЗАПУСКА
async function executeWizardLaunch(taskMode) {
    const skipSetup = document.getElementById('wiz-warmed-up').checked;
    const funnelMode = document.querySelector('input[name="funnel_type"]:checked').value;
    
    if (!skipSetup) {
        if (funnelMode === 'bridge') {
            const chanTitle = document.getElementById('wiz-channel-title').value.trim();
            if (!chanTitle) {
                alert("❌ Ошибка: Вы выбрали создание канала-прокладки, но не указали его название (Шаг 3). Вернитесь и заполните поле.");
                setStep(3);
                return;
            }
        } else if (funnelMode === 'direct') {
            const targetLink = document.getElementById('wiz-target-channel').value.trim();
            if (!targetLink || !targetLink.includes('t.me/')) {
                alert("❌ Ошибка: Укажите корректную ссылку на ваш канал (https://t.me/...) на Шаге 3.");
                setStep(3);
                return;
            }
        }
    }

    document.getElementById('btn-launch-prep').style.display = "none";
    document.getElementById('btn-launch-full').style.display = "none";
    document.getElementById('nav-btn-4').style.display = "none";
    
    document.getElementById('wizard-terminal-box').style.display = "flex";
    document.getElementById('funnel-links-result').style.display = "flex";
    
    launchedProfilesInSession.add(selectedProfile);
    
    const modeName = taskMode === "setup_and_warmup" ? "Режим: Подготовка" : "Режим: Полный боевой цикл";
    logsContainer.innerHTML += `<div style='color:#a78bfa;'>🚀 Инициализация аккаунта [${selectedProfile}] | ${modeName}</div>`;
    connectWizardWebSocket();

    const targetChannel = funnelMode === 'direct' ? document.getElementById('wiz-target-channel').value : "";
    const mainChannel = funnelMode === 'bridge' ? document.getElementById('wiz-bridge-main').value : "";
    const isPrivateRequest = document.getElementById('wiz-bridge-private') ? document.getElementById('wiz-bridge-private').checked : false;

    const formData = new FormData();
    const accFile = croppedFiles.acc || document.getElementById('wiz-acc-avatar').files[0];
    const chanFile = croppedFiles.chan || document.getElementById('wiz-chan-avatar').files[0];
    const postFile = croppedFiles.post || (document.getElementById('wiz-post-image') ? document.getElementById('wiz-post-image').files[0] : null);
    
    if(accFile) formData.append('acc_avatar', accFile, 'acc.jpg');
    if(chanFile) formData.append('chan_avatar', chanFile, 'chan.jpg');
    if(postFile) formData.append('post_image', postFile, 'post.jpg');
    
    try {
        await fetch(`/api/wizard/upload_assets/${selectedProfile}`, { method: 'POST', body: formData });
    } catch(e) { console.error("Ошибка загрузки файлов:", e); }

    await fetch('/api/spider/start_task', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
            profile: selectedProfile, 
            task_mode: taskMode, 
            skip_setup: skipSetup,
            target_channel: targetChannel,
            main_channel: mainChannel,
            first_name: document.getElementById('wiz-first-name').value,
            last_name: document.getElementById('wiz-last-name').value,
            channel_title: document.getElementById('wiz-channel-title').value,
            w_count: parseInt(document.getElementById('wiz-warmup-count').value) || 3,
            w_min: parseInt(document.getElementById('wiz-warmup-min').value) || 5,
            w_max: parseInt(document.getElementById('wiz-warmup-max').value) || 15,
            leadgen_delay_min: parseInt(document.getElementById('wiz-delay-min').value) || 5,
            leadgen_delay_max: parseInt(document.getElementById('wiz-delay-max').value) || 15,
            leadgen_daily_limit: parseInt(document.getElementById('wiz-daily-limit').value) || 15,
            is_private_request: isPrivateRequest
        })
    });

    const linkCheckInterval = setInterval(async () => {
        try {
            const res = await fetch(`/api/profiles/${selectedProfile}`);
            const profileData = await res.json();
            const fullProfiles = await fetch('/api/profiles');
            const allProfiles = await fullProfiles.json();
            const currentFull = allProfiles.find(p => p.name === selectedProfile);

            if (currentFull && (currentFull.target || currentFull.bridge)) {
                document.getElementById('funnel-links-result').style.display = 'flex';
                const targetLnk = document.getElementById('res-target-link');
                const bridgeLnk = document.getElementById('res-bridge-link');
                
                if (currentFull.target) {
                    targetLnk.href = currentFull.target;
                    targetLnk.innerText = "🎯 Основной канал: " + currentFull.target;
                    targetLnk.style.display = 'block';
                }
                if (currentFull.bridge) {
                    bridgeLnk.href = currentFull.bridge;
                    bridgeLnk.innerText = "🔗 Канал-Прокладка: " + currentFull.bridge;
                    bridgeLnk.style.display = 'block';
                }
                clearInterval(linkCheckInterval);
            }
        } catch(e) {}
    }, 3000);
}

document.getElementById('btn-launch-prep').addEventListener('click', () => executeWizardLaunch("setup_and_warmup"));
document.getElementById('btn-launch-full').addEventListener('click', () => executeWizardLaunch("auto_leadgen"));

function saveWizardState() {
    const fields = ['wiz-niche', 'wiz-first-name', 'wiz-last-name', 'wiz-channel-title', 'wiz-target-channel', 'wiz-bridge-main', 'wiz-warmup-count', 'wiz-warmup-min', 'wiz-warmup-max', 'wiz-delay-min', 'wiz-delay-max', 'wiz-daily-limit', 'wiz-ai-lang', 'wiz-ai-gender', 'wiz-ai-age-min', 'wiz-ai-age-max', 'wiz-ai-country', 'wiz-ai-profession', 'wiz-ai-interests'];
    fields.forEach(id => {
        const el = document.getElementById(id);
        if (el) localStorage.setItem(id, el.value);
    });
    const ft = document.querySelector('input[name="funnel_type"]:checked');
    if (ft) localStorage.setItem('wiz-funnel-type', ft.value);
    const wu = document.getElementById('wiz-warmed-up');
    if (wu) localStorage.setItem('wiz-warmed-up', wu.checked);
}

function loadWizardState() {
    const fields = ['wiz-niche', 'wiz-first-name', 'wiz-last-name', 'wiz-channel-title', 'wiz-target-channel', 'wiz-bridge-main', 'wiz-warmup-count', 'wiz-warmup-min', 'wiz-warmup-max', 'wiz-delay-min', 'wiz-delay-max', 'wiz-daily-limit', 'wiz-ai-lang', 'wiz-ai-gender', 'wiz-ai-age-min', 'wiz-ai-age-max', 'wiz-ai-country', 'wiz-ai-profession', 'wiz-ai-interests'];
    fields.forEach(id => {
        const val = localStorage.getItem(id);
        if (val !== null) {
            const el = document.getElementById(id);
            if (el) el.value = val;
        }
    });
    const ft = localStorage.getItem('wiz-funnel-type');
    if (ft) {
        const r = document.querySelector(`input[name="funnel_type"][value="${ft}"]`);
        if (r) { r.checked = true; if(typeof window.toggleFunnelMode === 'function') window.toggleFunnelMode(); }
    }
    const wu = localStorage.getItem('wiz-warmed-up');
    if (wu !== null) {
        const cb = document.getElementById('wiz-warmed-up');
        if (cb) { cb.checked = (wu === 'true'); cb.dispatchEvent(new Event('change')); }
    }
}

document.addEventListener('input', e => {
    if (e.target.id && e.target.id.startsWith('wiz-')) saveWizardState();
});
document.addEventListener('change', e => {
    if (e.target.name === 'funnel_type' || e.target.id === 'wiz-warmed-up') saveWizardState();
});

document.addEventListener('DOMContentLoaded', loadWizardState);
loadWizardState();

window.addEventListener('beforeunload', function (e) {
    if (typeof launchedProfilesInSession !== 'undefined' && launchedProfilesInSession.size > 0) {
        const confirmationMessage = 'У вас запущены аккаунты! Если вы обновите страницу, терминал логов очистится. Вы уверены?';
        e.returnValue = confirmationMessage; 
        return confirmationMessage;
    }
});

// --- ФУНКЦИЯ ЭКСТРЕННОЙ ОСТАНОВКИ В WIZARD ---
window.stopWizardTask = async function() {
    if (!selectedProfile) return;
    
    const btn = document.getElementById('btn-wizard-stop');
    btn.disabled = true;
    btn.innerText = "⏳ Остановка...";
    
    try {
        // Вызываем системный эндпоинт остановки конкретного профиля
        await fetch(`/api/spider/stop_task/${selectedProfile}`, { method: 'POST' });
        
        // Пишем в терминал жирное красное уведомление
        logsContainer.innerHTML += `<div style='color:#ef4444; font-weight:bold;'>[${selectedProfile}] 🛑 Процесс принудительно остановлен пользователем!</div>`;
        logsContainer.scrollTop = logsContainer.scrollHeight;
        
        btn.innerText = "🛑 Остановлено";
        btn.style.opacity = "0.5";
    } catch(e) {
        console.error("Ошибка при остановке:", e);
        btn.innerText = "❌ Ошибка связи";
    }
};