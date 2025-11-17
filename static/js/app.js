// Inizializza Socket.IO
const socket = io();

// Stato dell'applicazione
let currentSessionName = null;
let currentHostId = null;
let sessions = [];
let selectedHostId = null; // Will be set to first available host
let lastActiveSessionByHost = {}; // Track last active session per host: {hostId: {sessionName, hostId}}
let zoomLevel = 1.0; // 100% = 1.0

// Mappa delle sessioni attive: "host_id:session_name" -> {terminal_id, iframe}
let activeTerminals = {};

// Context menu state
let contextMenuSession = null;
let contextMenuHostId = null;

// Inizializza l'applicazione
document.addEventListener('DOMContentLoaded', () => {
    initializeApp();
    setupEventListeners();
    setupKeyboardShortcuts();
    setupContextMenu();
});

function initializeApp() {
    loadSessions();
    setupSocketListeners();
    updateZoomDisplay();
}

function setupEventListeners() {
    // Refresh button
    document.getElementById('refresh-btn').addEventListener('click', () => {
        loadSessions();
    });

    // Zoom controls
    document.getElementById('zoom-in-btn').addEventListener('click', () => {
        zoomIn();
    });

    document.getElementById('zoom-out-btn').addEventListener('click', () => {
        zoomOut();
    });

    document.getElementById('zoom-reset-btn').addEventListener('click', () => {
        resetZoom();
    });
}

function setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && (e.key === '+' || e.key === '=')) {
            e.preventDefault();
            zoomIn();
        }
        else if ((e.ctrlKey || e.metaKey) && e.key === '-') {
            e.preventDefault();
            zoomOut();
        }
        else if ((e.ctrlKey || e.metaKey) && e.key === '0') {
            e.preventDefault();
            resetZoom();
        }
    });
}

function zoomIn() {
    zoomLevel = Math.min(zoomLevel + 0.1, 2.0);
    applyZoomToAllTerminals();
}

function zoomOut() {
    zoomLevel = Math.max(zoomLevel - 0.1, 0.5);
    applyZoomToAllTerminals();
}

function resetZoom() {
    zoomLevel = 1.0;
    applyZoomToAllTerminals();
}

function applyZoomToAllTerminals() {
    // Applica zoom a tutti gli iframe attivi
    Object.values(activeTerminals).forEach(term => {
        if (term.iframe) {
            term.iframe.style.transform = `scale(${zoomLevel})`;
            term.iframe.style.width = `${100 / zoomLevel}%`;
            term.iframe.style.height = `${100 / zoomLevel}%`;
        }
    });
    updateZoomDisplay();
}

function updateZoomDisplay() {
    const zoomDisplay = document.getElementById('zoom-level');
    if (zoomDisplay) {
        zoomDisplay.textContent = `${Math.round(zoomLevel * 100)}%`;
    }
}

function setupSocketListeners() {
    socket.on('connect', () => {
        console.log('Connected to server');
    });

    socket.on('disconnect', () => {
        console.log('Disconnected from server');
    });

    socket.on('terminal_ready', (data) => {
        console.log('Terminal ready:', data);

        const sessionName = currentSessionName;
        const hostId = currentHostId || 'local';
        const sessionKey = `${hostId}:${sessionName}`;
        const terminal_id = data.terminal_id;

        // Determine terminal URL based on deployment mode
        let terminalUrl;
        if (data.use_nginx_proxy) {
            // Remote mode: use nginx proxy path
            terminalUrl = `/terminal/${terminal_id}`;
            console.log(`Using nginx proxy mode: ${terminalUrl}`);
        } else {
            // Local mode: direct connection to ttyd
            const host = data.host || window.location.hostname;
            const port = data.port;
            const protocol = window.location.protocol === 'https:' ? 'https:' : 'http:';
            terminalUrl = `${protocol}//${host}:${port}`;
            console.log(`Using direct connection mode: ${terminalUrl}`);
        }

        if (data.reused) {
            // Ttyd già esistente
            console.log(`Reusing ttyd for ${sessionKey}`);

            // Se non abbiamo ancora l'iframe, crealo
            if (!activeTerminals[sessionKey]) {
                const iframe = createIframeElement(terminalUrl, sessionKey);
                activeTerminals[sessionKey] = {
                    terminal_id: terminal_id,
                    iframe: iframe
                };
            }
        } else {
            // Nuovo ttyd
            console.log(`New ttyd created for ${sessionKey}`);

            const iframe = createIframeElement(terminalUrl, sessionKey);
            activeTerminals[sessionKey] = {
                terminal_id: terminal_id,
                iframe: iframe
            };
        }

        // Mostra questo terminale e nascondi gli altri
        showTerminal(sessionKey);

        // Mantieni il tab evidenziato
        updateActiveTab();
    });

    socket.on('terminal_closed', (data) => {
        console.log('Terminal closed:', data.terminal_id);
        // Non facciamo nulla - teniamo ttyd alive
    });

    socket.on('error', (data) => {
        console.error('Error:', data.message);
        alert('Errore: ' + data.message);
    });
}

function createIframeElement(terminalUrl, sessionKey) {
    const container = document.getElementById('terminal-container');

    // Nascondi empty state se presente
    const emptyState = container.querySelector('.empty-state');
    if (emptyState) {
        emptyState.style.display = 'none';
    }

    console.log(`Creating iframe for ${sessionKey} at ${terminalUrl}`);

    const iframe = document.createElement('iframe');
    iframe.id = `terminal-${sessionKey.replace(':', '-')}`;
    iframe.dataset.sessionKey = sessionKey;
    iframe.src = terminalUrl;  // Usa il path nginx invece di host:port
    iframe.style.width = `${100 / zoomLevel}%`;
    iframe.style.height = `${100 / zoomLevel}%`;
    iframe.style.border = 'none';
    iframe.style.backgroundColor = '#0f0f0f';
    iframe.style.transform = `scale(${zoomLevel})`;
    iframe.style.transformOrigin = 'top left';
    iframe.style.position = 'absolute';
    iframe.style.top = '0';
    iframe.style.left = '0';
    iframe.style.display = 'none'; // Inizialmente nascosto

    iframe.onerror = function() {
        console.error('Failed to load ttyd iframe for', sessionKey);
        alert(`Errore nel caricamento del terminale ${sessionKey}.`);
    };

    container.appendChild(iframe);

    return iframe;
}

function showTerminal(sessionKey) {
    // Nascondi tutti gli iframe
    Object.values(activeTerminals).forEach(term => {
        if (term.iframe) {
            term.iframe.style.display = 'none';
        }
    });

    // Mostra quello richiesto
    if (activeTerminals[sessionKey] && activeTerminals[sessionKey].iframe) {
        activeTerminals[sessionKey].iframe.style.display = 'block';
        console.log(`Showing terminal for ${sessionKey}`);
    }
}

async function loadSessions() {
    try {
        const response = await fetch('/api/sessions');
        const data = await response.json();

        if (data.error) {
            console.error('Error loading sessions:', data.error);
            return;
        }

        sessions = data.sessions;
        renderHostsTabs();
        renderTabs();

        // Mantieni il tab attivo evidenziato
        updateActiveTab();
    } catch (error) {
        console.error('Error fetching sessions:', error);
        showError('Impossibile caricare le sessioni');
    }
}

function renderHostsTabs() {
    const hostsTabsList = document.getElementById('hosts-tabs-list');

    if (sessions.length === 0) {
        hostsTabsList.innerHTML = '';
        return;
    }

    // Group sessions by host to count them
    const sessionsByHost = {};
    sessions.forEach(session => {
        if (!sessionsByHost[session.host_id]) {
            sessionsByHost[session.host_id] = {
                host_name: session.host_name,
                host_color: session.host_color || '#4a9eff',
                count: 0
            };
        }
        sessionsByHost[session.host_id].count++;
    });

    // If selectedHostId is 'all' or not valid, select the first host
    const hostIds = Object.keys(sessionsByHost);
    if (selectedHostId === 'all' || !sessionsByHost[selectedHostId]) {
        selectedHostId = hostIds[0];
    }

    // Create tabs for each host
    let html = '';
    hostIds.forEach(hostId => {
        const hostData = sessionsByHost[hostId];
        const isActive = selectedHostId === hostId;

        html += `
            <div class="host-tab ${isActive ? 'active' : ''}"
                 onclick="selectHost('${hostId}')">
                <span class="host-tab-indicator" style="background: ${hostData.host_color};"></span>
                <span class="host-tab-name">${hostData.host_name}</span>
                <span class="host-tab-count">${hostData.count}</span>
            </div>
        `;
    });

    hostsTabsList.innerHTML = html;
}

function selectHost(hostId) {
    selectedHostId = hostId;
    renderHostsTabs();
    renderTabs();

    // Restore last active session for this host if available
    if (lastActiveSessionByHost[hostId]) {
        const lastSession = lastActiveSessionByHost[hostId];
        attachSession(lastSession.sessionName, lastSession.hostId);
    }
}

function renderTabs() {
    const tabsList = document.getElementById('tabs-list');

    // Filter sessions based on selected host
    const filteredSessions = sessions.filter(s => s.host_id === selectedHostId);

    if (filteredSessions.length === 0) {
        tabsList.innerHTML = '<div class="tabs-empty">Nessuna sessione tmux disponibile</div>';
        return;
    }

    // Group sessions by host
    const sessionsByHost = {};
    filteredSessions.forEach(session => {
        if (!sessionsByHost[session.host_id]) {
            sessionsByHost[session.host_id] = {
                host_name: session.host_name,
                host_color: session.host_color || '#4a9eff',
                sessions: []
            };
        }
        sessionsByHost[session.host_id].sessions.push(session);
    });

    // Render tabs grouped by host with "+" button before each group
    let html = '';
    Object.keys(sessionsByHost).forEach(hostId => {
        const hostData = sessionsByHost[hostId];
        const hostColor = hostData.host_color;

        // Add "+" button for creating new session on this host
        html += `
            <button class="tab-add-button"
                    style="border-left: 3px solid ${hostColor};"
                    title="Crea nuova sessione su ${hostData.host_name}"
                    onclick="createNewSession('${hostId}')">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                    <line x1="12" y1="5" x2="12" y2="19"></line>
                    <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>
            </button>
        `;

        // Add all sessions for this host
        hostData.sessions.forEach(session => {
            const isActive = currentSessionName === session.name && currentHostId === session.host_id;
            const tooltipText = `${session.name} @ ${session.host_name}\n${session.windows} window(s)${session.attached ? ' • Attached' : ''}`;

            html += `
                <div class="tab-item ${isActive ? 'active' : ''}"
                     data-session="${session.name}"
                     data-host="${session.host_id}"
                     style="background: linear-gradient(135deg, ${hostColor}15 0%, ${hostColor}08 100%); border-left: 3px solid ${hostColor};"
                     title="${tooltipText}"
                     onclick="attachSession('${session.name}', '${session.host_id}')"
                     oncontextmenu="showContextMenu(event, '${session.name}', '${session.host_id}')">
                    <div class="tab-name">${session.name}</div>
                </div>
            `;
        });
    });

    tabsList.innerHTML = html;
}

function updateActiveTab() {
    document.querySelectorAll('.tab-item').forEach(item => {
        item.classList.remove('active');
    });

    if (currentSessionName && currentHostId) {
        const activeTab = document.querySelector(`[data-session="${currentSessionName}"][data-host="${currentHostId}"]`);
        if (activeTab) {
            activeTab.classList.add('active');
        }
    }
}

function attachSession(sessionName, hostId) {
    hostId = hostId || 'local';
    console.log(`attachSession called for: ${sessionName} on host ${hostId}`);

    // Imposta la sessione corrente
    currentSessionName = sessionName;
    currentHostId = hostId;

    // Save last active session for this host
    lastActiveSessionByHost[hostId] = {
        sessionName: sessionName,
        hostId: hostId
    };

    // Aggiorna i tab immediatamente
    updateActiveTab();

    const sessionKey = `${hostId}:${sessionName}`;

    // Check se abbiamo già un iframe per questa sessione
    if (activeTerminals[sessionKey]) {
        console.log(`Terminal already exists for ${sessionKey}, showing it`);
        // Switch istantaneo: mostra questo, nascondi gli altri
        showTerminal(sessionKey);
    } else {
        console.log(`Terminal doesn't exist for ${sessionKey}, requesting from server`);
        // Prima volta: richiedi ttyd al server
        socket.emit('attach_session', {
            session_name: sessionName,
            host_id: hostId
        });
    }
}

function showError(message) {
    const tabsList = document.getElementById('tabs-list');
    tabsList.innerHTML = `
        <div class="tabs-empty" style="color: #ff5555;">
            ${message}
        </div>
    `;
}

// ========================================
// Host Management Functions
// ========================================

let hosts = [];

function initHostManagement() {
    const manageHostsBtn = document.getElementById('manage-hosts-btn');
    const closeModalBtn = document.getElementById('close-modal-btn');
    const addHostBtn = document.getElementById('add-host-btn');
    const cancelFormBtn = document.getElementById('cancel-form-btn');
    const hostForm = document.getElementById('host-edit-form');
    const modal = document.getElementById('hosts-modal');

    manageHostsBtn.addEventListener('click', openHostsModal);
    closeModalBtn.addEventListener('click', closeHostsModal);
    addHostBtn.addEventListener('click', showAddHostForm);
    cancelFormBtn.addEventListener('click', hideHostForm);
    hostForm.addEventListener('submit', handleHostFormSubmit);

    // Close modal when clicking outside
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeHostsModal();
        }
    });
}

async function openHostsModal() {
    const modal = document.getElementById('hosts-modal');
    modal.classList.add('active');
    await loadHosts();
    renderHostsList();
}

function closeHostsModal() {
    const modal = document.getElementById('hosts-modal');
    modal.classList.remove('active');
    hideHostForm();
}

async function loadHosts() {
    try {
        const response = await fetch('/api/hosts');
        const data = await response.json();
        hosts = data.hosts || [];
    } catch (error) {
        console.error('Error loading hosts:', error);
        hosts = [];
    }
}

function renderHostsList() {
    const hostsList = document.getElementById('hosts-list');

    if (hosts.length === 0) {
        hostsList.innerHTML = '<div class="hosts-empty">Nessun host remoto configurato</div>';
        return;
    }

    hostsList.innerHTML = hosts.map(host => `
        <div class="host-item ${!host.enabled ? 'disabled' : ''}" data-host-id="${host.id}">
            <div class="host-info">
                <h4>${host.name}</h4>
                <div class="host-details">
                    <div class="host-detail">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="2" y="2" width="20" height="8" rx="2" ry="2"></rect>
                            <rect x="2" y="14" width="20" height="8" rx="2" ry="2"></rect>
                        </svg>
                        ${host.hostname}:${host.port}
                    </div>
                    <div class="host-detail">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                            <circle cx="12" cy="7" r="4"></circle>
                        </svg>
                        ${host.username || 'current user'}
                    </div>
                    <div class="host-detail">
                        ${host.enabled ?
                            '<span style="color: #4ade80;">● Abilitato</span>' :
                            '<span style="color: #888;">○ Disabilitato</span>'
                        }
                    </div>
                </div>
            </div>
            <div class="host-actions">
                <button class="btn-edit" onclick="editHost('${host.id}')" title="Modifica">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                    </svg>
                </button>
                <button class="btn-delete" onclick="deleteHost('${host.id}')" title="Elimina">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>
            </div>
        </div>
    `).join('');
}

function showAddHostForm() {
    const formContainer = document.getElementById('host-form');
    const formTitle = document.getElementById('form-title');
    const form = document.getElementById('host-edit-form');

    formTitle.textContent = 'Aggiungi Nuovo Host';
    form.reset();
    document.getElementById('host-id').value = '';
    document.getElementById('host-enabled').checked = true;

    formContainer.style.display = 'block';
    formContainer.scrollIntoView({ behavior: 'smooth' });
}

function hideHostForm() {
    const formContainer = document.getElementById('host-form');
    formContainer.style.display = 'none';
}

async function editHost(hostId) {
    const host = hosts.find(h => h.id === hostId);
    if (!host) return;

    const formContainer = document.getElementById('host-form');
    const formTitle = document.getElementById('form-title');

    formTitle.textContent = 'Modifica Host';
    document.getElementById('host-id').value = host.id;
    document.getElementById('host-name').value = host.name;
    document.getElementById('host-hostname').value = host.hostname;
    document.getElementById('host-port').value = host.port;
    document.getElementById('host-username').value = host.username || '';
    document.getElementById('host-enabled').checked = host.enabled;

    formContainer.style.display = 'block';
    formContainer.scrollIntoView({ behavior: 'smooth' });
}

async function deleteHost(hostId) {
    const host = hosts.find(h => h.id === hostId);
    if (!host) return;

    if (!confirm(`Sei sicuro di voler eliminare l'host "${host.name}"?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/hosts/${hostId}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            await loadHosts();
            renderHostsList();
            await loadSessions(); // Reload sessions to remove remote ones
        } else {
            const data = await response.json();
            alert('Errore durante l\'eliminazione: ' + (data.error || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error deleting host:', error);
        alert('Errore durante l\'eliminazione dell\'host');
    }
}

async function handleHostFormSubmit(e) {
    e.preventDefault();

    const hostId = document.getElementById('host-id').value;
    const hostData = {
        name: document.getElementById('host-name').value,
        hostname: document.getElementById('host-hostname').value,
        port: parseInt(document.getElementById('host-port').value),
        username: document.getElementById('host-username').value || null,
        enabled: document.getElementById('host-enabled').checked
    };

    try {
        const url = hostId ? `/api/hosts/${hostId}` : '/api/hosts';
        const method = hostId ? 'PUT' : 'POST';

        const response = await fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(hostData)
        });

        if (response.ok) {
            await loadHosts();
            renderHostsList();
            hideHostForm();
            await loadSessions(); // Reload sessions to include new remote ones
        } else {
            const data = await response.json();
            alert('Errore durante il salvataggio: ' + (data.error || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error saving host:', error);
        alert('Errore durante il salvataggio dell\'host');
    }
}

// Initialize host management when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    initHostManagement();
});

// ========================================
// Context Menu for Session Actions
// ========================================

let contextMenuInitialized = false;

function setupContextMenu() {
    if (contextMenuInitialized) return;
    contextMenuInitialized = true;

    const contextMenu = document.getElementById('context-menu');
    const renameItem = document.getElementById('rename-session');
    const deleteItem = document.getElementById('delete-session');

    // Handle rename action
    renameItem.addEventListener('click', (e) => {
        e.stopPropagation();
        contextMenu.style.display = 'none';
        showRenameDialog(contextMenuSession, contextMenuHostId);
    });

    // Handle delete action
    deleteItem.addEventListener('click', (e) => {
        e.stopPropagation();
        contextMenu.style.display = 'none';
        deleteSession(contextMenuSession, contextMenuHostId);
    });

    // Click anywhere to close menu
    document.addEventListener('click', function closeMenuHandler(e) {
        const menu = document.getElementById('context-menu');
        // Check if menu is visible and click is outside
        if (menu && menu.style.display === 'block') {
            // If click is not on the menu itself, close it
            if (!menu.contains(e.target)) {
                menu.style.display = 'none';
            }
        }
    });

    // Close menu when window loses focus (e.g., clicking on iframe)
    window.addEventListener('blur', function() {
        const menu = document.getElementById('context-menu');
        if (menu && menu.style.display === 'block') {
            menu.style.display = 'none';
        }
    });

    // Close menu when clicking on terminal container
    const terminalContainer = document.getElementById('terminal-container');
    if (terminalContainer) {
        terminalContainer.addEventListener('mousedown', function() {
            const menu = document.getElementById('context-menu');
            if (menu && menu.style.display === 'block') {
                menu.style.display = 'none';
            }
        });
    }

    // Prevent menu from closing when clicking inside it
    contextMenu.addEventListener('click', (e) => {
        // Don't stop propagation - let item clicks work
        // e.stopPropagation();
    });
}

function showContextMenu(e, sessionName, hostId) {
    e.preventDefault();

    const contextMenu = document.getElementById('context-menu');
    contextMenuSession = sessionName;
    contextMenuHostId = hostId;

    // Position the menu at cursor
    contextMenu.style.left = e.pageX + 'px';
    contextMenu.style.top = e.pageY + 'px';
    contextMenu.style.display = 'block';
}

function showRenameDialog(sessionName, hostId) {
    const newName = prompt(`Rinomina la sessione "${sessionName}":`, sessionName);

    if (newName && newName !== sessionName && newName.trim() !== '') {
        renameSession(sessionName, newName.trim(), hostId);
    }
}

async function renameSession(oldName, newName, hostId) {
    try {
        const response = await fetch('/api/session/rename', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                old_name: oldName,
                new_name: newName,
                host_id: hostId
            })
        });

        if (response.ok) {
            // Reload sessions to reflect the change
            await loadSessions();

            // If this was the active session, update the current name
            if (currentSessionName === oldName && currentHostId === hostId) {
                currentSessionName = newName;
            }

            // Update saved session name for this host
            if (lastActiveSessionByHost[hostId] &&
                lastActiveSessionByHost[hostId].sessionName === oldName) {
                lastActiveSessionByHost[hostId].sessionName = newName;
            }
        } else {
            const data = await response.json();
            alert('Errore durante il rinomino: ' + (data.error || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error renaming session:', error);
        alert('Errore durante il rinomino della sessione');
    }
}

async function createNewSession(hostId) {
    const sessionName = prompt('Inserisci il nome della nuova sessione tmux:');

    if (!sessionName || sessionName.trim() === '') {
        return;
    }

    try {
        const response = await fetch('/api/session/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_name: sessionName.trim(),
                host_id: hostId
            })
        });

        if (response.ok) {
            const data = await response.json();

            // Reload sessions
            await loadSessions();

            // Attach to the new session automatically
            attachSession(data.session_name, data.host_id);

            // Show confirmation
            alert(`Sessione "${data.session_name}" creata con successo!`);
        } else {
            const errorData = await response.json();
            alert('Errore durante la creazione della sessione: ' + (errorData.error || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error creating session:', error);
        alert('Errore durante la creazione della sessione');
    }
}

async function deleteSession(sessionName, hostId) {
    // Conferma importante prima di eliminare
    const confirmMessage = `ATTENZIONE!\n\nSei sicuro di voler eliminare la sessione "${sessionName}"?\n\nQuesta azione è IRREVERSIBILE e comporterà la chiusura di tutti i processi in esecuzione nella sessione.\n\nConfermi l'eliminazione?`;

    if (!confirm(confirmMessage)) {
        return;
    }

    try {
        const response = await fetch('/api/session/delete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_name: sessionName,
                host_id: hostId
            })
        });

        if (response.ok) {
            // Se la sessione eliminata era quella corrente, resetta lo stato
            if (currentSessionName === sessionName && currentHostId === hostId) {
                currentSessionName = null;
                currentHostId = null;

                // Nascondi il terminale corrente
                Object.keys(activeTerminals).forEach(key => {
                    const iframe = activeTerminals[key];
                    if (iframe && iframe.style) {
                        iframe.style.display = 'none';
                    }
                });
            }

            // Remove from saved sessions for this host
            if (lastActiveSessionByHost[hostId] &&
                lastActiveSessionByHost[hostId].sessionName === sessionName) {
                delete lastActiveSessionByHost[hostId];
            }

            // Reload sessions per rimuovere la tab
            await loadSessions();

            // Show confirmation
            alert(`Sessione "${sessionName}" eliminata con successo.`);
        } else {
            const errorData = await response.json();
            alert('Errore durante l\'eliminazione della sessione: ' + (errorData.error || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error deleting session:', error);
        alert('Errore durante l\'eliminazione della sessione');
    }
}
