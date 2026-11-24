let currentProfile = null;

// --- Загрузка глобальных настроек ---
async function loadGlobalSettings() {
    const res = await fetch('/api/settings/global');
    const data = await res.json();
    document.getElementById('glob-min-subs').value = data.min_subscribers || 500;
    document.getElementById('glob-max-depth').value = data.max_depth || 15;
    document.getElementById('glob-delay').value = data.delay_sec || 15;
    
    // Ключ и Прокси для Gemini
    document.getElementById('glob-gemini-key').value = data.gemini_api_key || '';
    document.getElementById('glob-gemini-proxy-ip').value = data.gemini_proxy_ip || '';
    document.getElementById('glob-gemini-proxy-port').value = data.gemini_proxy_port || '';
    document.getElementById('glob-gemini-proxy-user').value = data.gemini_proxy_user || '';
    document.getElementById('glob-gemini-proxy-pass').value = data.gemini_proxy_pass || '';
    
    document.getElementById('glob-comment-prompt').value = data.auto_comment_prompt || "Напиши интригующий, слегка дерзкий комментарий (строго от 2 до 5 слов) к этому посту. Задача: заставить людей кликнуть на мой профиль. Без хэштегов и смайликов. Пост: {text}";
    document.getElementById('glob-funnel-bio').value = data.funnel_bio || "Learn more about me:";
    document.getElementById('glob-funnel-post').value = data.funnel_post || "🚀 Join my exclusive private channel to get the best signals and insights! Subscribe now!";
}

async function saveGlobalSettings() {
    const data = {
        min_subscribers: document.getElementById('glob-min-subs').value,
        max_depth: document.getElementById('glob-max-depth').value,
        delay_sec: document.getElementById('glob-delay').value,
        
        // Ключ и Прокси для Gemini
        gemini_api_key: document.getElementById('glob-gemini-key').value,
        gemini_proxy_ip: document.getElementById('glob-gemini-proxy-ip').value,
        gemini_proxy_port: document.getElementById('glob-gemini-proxy-port').value,
        gemini_proxy_user: document.getElementById('glob-gemini-proxy-user').value,
        gemini_proxy_pass: document.getElementById('glob-gemini-proxy-pass').value,
        
        auto_comment_prompt: document.getElementById('glob-comment-prompt').value,
        funnel_bio: document.getElementById('glob-funnel-bio').value,
        funnel_post: document.getElementById('glob-funnel-post').value
    };
    await fetch('/api/settings/global', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    alert("Настройки и доступы к AI успешно сохранены!");
}

// --- Управление профилями ---
async function loadProfiles() {
    const res = await fetch('/api/profiles');
    const profiles = await res.json();
    
    const list = document.getElementById('profile-list');
    list.innerHTML = "";
    
    profiles.forEach(p => {
        const div = document.createElement('div');
        div.className = `profile-item ${currentProfile === p.name ? 'active' : ''}`;
        div.innerText = p.name;
        div.onclick = () => selectProfile(p.name);
        list.appendChild(div);
    });

    if (!currentProfile && profiles.length > 0) {
        selectProfile(profiles[0].name);
    }
}

async function selectProfile(name) {
    currentProfile = name;
    loadProfiles(); // для обновления выделения .active

    const res = await fetch(`/api/profiles/${name}`);
    const data = await res.json();

    document.getElementById('profile-editor').style.display = 'block';
    document.getElementById('editor-title').innerText = `Editing: ${name}`;
    
    document.getElementById('prof-api-id').value = data.api_id || '';
    document.getElementById('prof-api-hash').value = data.api_hash || '';
    document.getElementById('prof-proxy-type').value = data.proxy_type || 'None';
    document.getElementById('prof-proxy-addr').value = data.proxy_addr || '';
    document.getElementById('prof-proxy-user').value = data.proxy_user || '';
    document.getElementById('prof-proxy-pass').value = data.proxy_pass || '';
    document.getElementById('prof-seed').value = data.seed_channel || '@ege_math_100';
}

async function saveCurrentProfile() {
    if (!currentProfile) return;
    const data = {
        api_id: document.getElementById('prof-api-id').value,
        api_hash: document.getElementById('prof-api-hash').value,
        proxy_type: document.getElementById('prof-proxy-type').value,
        proxy_addr: document.getElementById('prof-proxy-addr').value,
        proxy_user: document.getElementById('prof-proxy-user').value,
        proxy_pass: document.getElementById('prof-proxy-pass').value,
        seed_channel: document.getElementById('prof-seed').value
    };

    await fetch(`/api/profiles/${currentProfile}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    alert("Profile saved successfully!");
}

async function deleteCurrentProfile() {
    if (!currentProfile) return;
    if (!confirm(`Are you sure you want to delete ${currentProfile}?`)) return;

    await fetch(`/api/profiles/${currentProfile}`, { method: 'DELETE' });
    currentProfile = null;
    document.getElementById('profile-editor').style.display = 'none';
    loadProfiles();
}

function showNewProfile() {
    const name = prompt("Enter new profile name:");
    if (name) {
        currentProfile = name;
        saveCurrentProfile().then(loadProfiles);
    }
}

// --- Импорт файлов (Upload) ---
function showImportModal() {
    document.getElementById('import-modal').style.display = 'flex';
}

async function submitImport() {
    const name = document.getElementById('imp-name').value;
    const apiId = document.getElementById('imp-id').value;
    const apiHash = document.getElementById('imp-hash').value;
    const fileInput = document.getElementById('imp-file');
    
    if (!name || !apiId || !apiHash || !fileInput.files[0]) {
        alert("Please fill all fields and select a .session file!");
        return;
    }

    const formData = new FormData();
    formData.append('name', name);
    formData.append('api_id', apiId);
    formData.append('api_hash', apiHash);
    formData.append('session_file', fileInput.files[0]);

    try {
        const res = await fetch('/api/profiles/import', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        
        if (res.ok && data.status === "ok") {
            document.getElementById('import-modal').style.display = 'none';
            currentProfile = name;
            loadProfiles();
            alert("Account imported successfully!");
        } else {
            alert("Error: " + (data.detail || data.message || "Unknown error"));
        }
    } catch (e) {
        alert("Upload failed: " + e.message);
    }
}

// Init
loadGlobalSettings();
loadProfiles();