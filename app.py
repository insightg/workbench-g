#!/usr/bin/env python3
import os
import pwd
import pam
import libtmux
import socket
import subprocess
import signal
import secrets
import json
from pathlib import Path
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.secret_key = os.urandom(24)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Get hostname for display
HOSTNAME = socket.gethostname()

# Deployment mode detection
DEPLOYMENT_MODE = os.environ.get('DEPLOYMENT_MODE', 'local')  # 'local' or 'remote'
USE_NGINX_PROXY = DEPLOYMENT_MODE == 'remote'

# Configuration based on deployment mode
if USE_NGINX_PROXY:
    TMUX_SOCKET_BASE = '/tmp/tmux-'
    TTYD_BIND_ADDRESS = '127.0.0.1'  # nginx proxies from localhost
    NGINX_TERMINALS_DIR = '/etc/nginx/terminals'
else:
    TMUX_SOCKET_BASE = '/tmp/tmux-'
    TTYD_BIND_ADDRESS = '0.0.0.0'  # direct access via network_mode: host

# Store active ttyd instances - PERSISTENT (not cleared on tab switch)
# Structure: {terminal_id: {'process': subprocess.Popen, 'port': int, 'uid': int, 'session_name': str, 'token': str, 'host': str}}
ttyd_instances = {}
terminal_counter = 0

# Remote hosts configuration file (per-user)
HOSTS_CONFIG_DIR = '/app/data/hosts'
os.makedirs(HOSTS_CONFIG_DIR, exist_ok=True)

# Color palette for different hosts
HOST_COLORS = [
    '#4a9eff',  # Blue (local/default)
    '#10b981',  # Green
    '#f59e0b',  # Orange
    '#8b5cf6',  # Purple
    '#ef4444',  # Red
    '#06b6d4',  # Cyan
    '#ec4899',  # Pink
    '#f97316',  # Deep orange
]

def get_user_hosts_file(username):
    """Get the hosts configuration file path for a user"""
    return os.path.join(HOSTS_CONFIG_DIR, f'{username}_hosts.json')

def load_user_hosts(username):
    """Load remote hosts configuration for a user"""
    hosts_file = get_user_hosts_file(username)
    if not os.path.exists(hosts_file):
        return []

    try:
        with open(hosts_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading hosts for {username}: {e}")
        return []

def save_user_hosts(username, hosts):
    """Save remote hosts configuration for a user"""
    hosts_file = get_user_hosts_file(username)
    try:
        with open(hosts_file, 'w') as f:
            json.dump(hosts, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving hosts for {username}: {e}")
        return False

def get_host_color(host_id):
    """Get a consistent color for a host based on its ID"""
    if host_id == 'local':
        return HOST_COLORS[0]
    # Use hash of host_id to get consistent color
    hash_val = hash(host_id) % (len(HOST_COLORS) - 1)
    return HOST_COLORS[hash_val + 1]  # Skip first color (reserved for local)

def authenticate_user(username, password):
    """Autentica l'utente usando PAM"""
    try:
        p = pam.pam()
        return p.authenticate(username, password)
    except Exception as e:
        print(f"Authentication error: {e}")
        return False

def get_tmux_sessions(username=None):
    """Ottiene tutte le sessioni tmux attive"""
    sessions_list = []

    try:
        if username:
            try:
                user_info = pwd.getpwnam(username)
                uid = user_info.pw_uid
                socket_path = f'{TMUX_SOCKET_BASE}{uid}/default'

                import sys
                sys.stdout.flush()
                sys.stderr.write(f"[DEBUG] Looking for sessions for user {username} (UID: {uid})\n")
                sys.stderr.write(f"[DEBUG] Socket path: {socket_path}\n")
                sys.stderr.write(f"[DEBUG] Socket exists: {os.path.exists(socket_path)}\n")
                sys.stderr.flush()

                if os.path.exists(socket_path):
                    server = libtmux.Server(socket_path=socket_path)
                    print(f"[DEBUG] Server created, sessions: {len(server.sessions)}")

                    for tmux_session in server.sessions:
                        session_info = {
                            'id': tmux_session.id,
                            'name': tmux_session.name,
                            'created': tmux_session.get('session_created'),
                            'windows': len(tmux_session.windows),
                            'attached': tmux_session.get('session_attached') != '0',
                            'host_id': 'local',
                            'host_name': 'Local',
                            'host_color': get_host_color('local')
                        }
                        sessions_list.append(session_info)
            except Exception as e:
                print(f"Error getting sessions for user {username}: {e}")
        else:
            import glob
            for tmux_dir in glob.glob(f'{TMUX_SOCKET_BASE}*'):
                socket_path = os.path.join(tmux_dir, 'default')
                if os.path.exists(socket_path):
                    try:
                        server = libtmux.Server(socket_path=socket_path)
                        for tmux_session in server.sessions:
                            session_info = {
                                'id': tmux_session.id,
                                'name': tmux_session.name,
                                'created': tmux_session.get('session_created'),
                                'windows': len(tmux_session.windows),
                                'attached': tmux_session.get('session_attached') != '0',
                                'host_id': 'local',
                                'host_name': 'Local',
                                'host_color': get_host_color('local')
                            }
                            sessions_list.append(session_info)
                    except Exception as e:
                        print(f"Error reading socket {socket_path}: {e}")

        return sessions_list
    except Exception as e:
        print(f"Error getting tmux sessions: {e}")
        return []

def get_remote_tmux_sessions(host_config, username):
    """Get tmux sessions from a remote host via SSH"""
    sessions_list = []

    try:
        host_id = host_config['id']
        hostname = host_config['hostname']
        ssh_port = host_config.get('port', 22)
        ssh_user = host_config.get('username') or username  # Use same username if not specified

        # Build SSH command to list tmux sessions
        ssh_cmd = [
            'ssh',
            '-p', str(ssh_port),
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'UserKnownHostsFile=/dev/null',
            '-o', 'ConnectTimeout=2',
            '-o', 'ServerAliveInterval=5',
            '-o', 'ServerAliveCountMax=1',
            f'{ssh_user}@{hostname}',
            'tmux list-sessions -F "#{session_id}|#{session_name}|#{session_created}|#{session_windows}|#{session_attached}"'
        ]

        import sys
        import pwd
        sys.stderr.write(f"[SSH] Connecting to {hostname}:{ssh_port} as {ssh_user}\n")
        sys.stderr.flush()

        # Get user info to run SSH as the logged-in user
        user_info = pwd.getpwnam(username)
        uid = user_info.pw_uid
        gid = user_info.pw_gid

        # Execute SSH command as the user (to use their SSH keys)
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=5,
            preexec_fn=demote(uid, gid)
        )

        if result.returncode == 0:
            # Parse tmux output
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue

                parts = line.split('|')
                if len(parts) >= 5:
                    session_info = {
                        'id': parts[0],
                        'name': parts[1],
                        'created': parts[2],
                        'windows': int(parts[3]),
                        'attached': parts[4] != '0',
                        'host_id': host_id,
                        'host_name': host_config.get('name', hostname),
                        'host_color': get_host_color(host_id)
                    }
                    sessions_list.append(session_info)

            sys.stderr.write(f"[SSH] Found {len(sessions_list)} sessions on {hostname}\n")
            sys.stderr.flush()
        else:
            sys.stderr.write(f"[SSH] Error connecting to {hostname}: {result.stderr}\n")
            sys.stderr.flush()

    except Exception as e:
        import sys
        sys.stderr.write(f"[SSH] Exception getting sessions from {host_config.get('hostname', 'unknown')}: {e}\n")
        sys.stderr.flush()

    return sessions_list

def get_all_sessions(username):
    """Get all tmux sessions (local + all configured remote hosts)"""
    all_sessions = []

    # Get local sessions
    local_sessions = get_tmux_sessions(username)
    all_sessions.extend(local_sessions)

    # Get remote sessions from all configured hosts
    hosts = load_user_hosts(username)
    for host in hosts:
        if host.get('enabled', True):  # Only query enabled hosts
            remote_sessions = get_remote_tmux_sessions(host, username)
            all_sessions.extend(remote_sessions)

    return all_sessions

def find_free_port():
    """Trova una porta TCP libera dinamicamente"""
    bind_address = '127.0.0.1' if USE_NGINX_PROXY else ''
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((bind_address, 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port

def demote(uid, gid):
    """Crea una funzione che cambia l'utente del processo"""
    def set_ids():
        os.setgid(gid)
        os.setuid(uid)
    return set_ids

def create_nginx_terminal_config(terminal_id, port):
    """Crea una configurazione nginx per un terminale specifico (solo remote mode)"""
    if not USE_NGINX_PROXY:
        return True

    import sys

    # Crea la directory se non esiste
    os.makedirs(NGINX_TERMINALS_DIR, exist_ok=True)

    config_content = f"""# Terminal {terminal_id} proxy configuration
location /terminal/{terminal_id} {{
    proxy_pass http://127.0.0.1:{port}/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 86400;
}}
"""

    config_file = os.path.join(NGINX_TERMINALS_DIR, f'terminal_{terminal_id}.conf')

    try:
        with open(config_file, 'w') as f:
            f.write(config_content)

        sys.stderr.write(f"[NGINX] Created config {config_file}\n")
        sys.stderr.flush()

        # Reload nginx configuration
        subprocess.run(['nginx', '-s', 'reload'], check=False)
        sys.stderr.write(f"[NGINX] Reloaded configuration\n")
        sys.stderr.flush()

        # Small delay to ensure nginx has fully reloaded before responding to client
        import time
        time.sleep(0.3)

        return True
    except Exception as e:
        sys.stderr.write(f"[NGINX] Error creating config: {e}\n")
        sys.stderr.flush()
        return False

def remove_nginx_terminal_config(terminal_id):
    """Rimuove la configurazione nginx per un terminale (solo remote mode)"""
    if not USE_NGINX_PROXY:
        return

    import sys
    config_file = os.path.join(NGINX_TERMINALS_DIR, f'terminal_{terminal_id}.conf')

    try:
        if os.path.exists(config_file):
            os.remove(config_file)
            sys.stderr.write(f"[NGINX] Removed config {config_file}\n")
            sys.stderr.flush()

            subprocess.run(['nginx', '-s', 'reload'], check=False)
            sys.stderr.write(f"[NGINX] Reloaded configuration\n")
            sys.stderr.flush()

            # Small delay to ensure nginx has fully reloaded
            import time
            time.sleep(0.3)
    except Exception as e:
        sys.stderr.write(f"[NGINX] Error removing config: {e}\n")
        sys.stderr.flush()

def start_ttyd(session_name, username, host_id='local'):
    """
    Avvia un'istanza di ttyd per una sessione tmux specifica (locale o remota via SSH)
    Returns: (terminal_id, port) or (None, None) on error
    """
    global terminal_counter

    try:
        user_info = pwd.getpwnam(username)
        uid = user_info.pw_uid
        gid = user_info.pw_gid

        port = find_free_port()
        token = secrets.token_urlsafe(32)

        import sys

        if host_id == 'local':
            # Local tmux session
            socket_path = f'{TMUX_SOCKET_BASE}{uid}/default'

            cmd = [
                'ttyd',
                '--writable',
                '-p', str(port),
                '-i', TTYD_BIND_ADDRESS,
                '-t', 'fontSize=14',
                '-t', 'fontFamily=Menlo, Monaco, "Courier New", monospace',
                '-t', 'theme={"background": "#0f0f0f", "foreground": "#e0e0e0", "cursor": "#4a9eff"}',
                'bash', '-c',
                f"tmux -S {socket_path} set-option -t {session_name} mouse off 2>/dev/null || true; tmux -S {socket_path} attach -t {session_name}"
            ]

            sys.stderr.write(f"[TTYD] Starting LOCAL ttyd on {TTYD_BIND_ADDRESS}:{port} for session {session_name}\n")
            sys.stderr.flush()

            process = subprocess.Popen(
                cmd,
                preexec_fn=demote(uid, gid),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

        else:
            # Remote tmux session via SSH
            hosts = load_user_hosts(username)
            host_config = None
            for h in hosts:
                if h['id'] == host_id:
                    host_config = h
                    break

            if not host_config:
                sys.stderr.write(f"[TTYD] Host {host_id} not found\n")
                sys.stderr.flush()
                return None, None

            hostname = host_config['hostname']
            ssh_port = host_config.get('port', 22)
            ssh_user = host_config.get('username') or username

            # Build SSH command to attach to remote tmux
            cmd = [
                'ttyd',
                '--writable',
                '-p', str(port),
                '-i', TTYD_BIND_ADDRESS,
                '-t', 'fontSize=14',
                '-t', 'fontFamily=Menlo, Monaco, "Courier New", monospace',
                '-t', 'theme={"background": "#0f0f0f", "foreground": "#e0e0e0", "cursor": "#4a9eff"}',
                'ssh',
                '-tt',
                '-p', str(ssh_port),
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'LogLevel=QUIET',
                f'{ssh_user}@{hostname}',
                'tmux', 'attach', '-t', session_name
            ]

            ssh_cmd = f"ssh -tt -p {ssh_port} {ssh_user}@{hostname} tmux attach -t {session_name}"

            sys.stderr.write(f"[TTYD] Starting REMOTE ttyd on {TTYD_BIND_ADDRESS}:{port} for session {session_name} on {hostname}\n")
            sys.stderr.write(f"[TTYD] SSH command: {ssh_cmd}\n")
            sys.stderr.flush()

            # Run ttyd with demote so SSH uses user's keys
            process = subprocess.Popen(
                cmd,
                preexec_fn=demote(uid, gid),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

        terminal_id = str(terminal_counter)
        terminal_counter += 1

        ttyd_instances[terminal_id] = {
            'process': process,
            'port': port,
            'uid': uid,
            'session_name': session_name,
            'username': username,
            'token': token,
            'host_id': host_id
        }

        # Create nginx config if in remote mode
        if USE_NGINX_PROXY:
            create_nginx_terminal_config(terminal_id, port)

        sys.stderr.write(f"[TTYD] Started with PID {process.pid}, terminal_id={terminal_id}, port={port}\n")
        sys.stderr.flush()

        return terminal_id, port

    except Exception as e:
        import sys
        sys.stderr.write(f"[TTYD] Error starting ttyd: {e}\n")
        sys.stderr.flush()
        return None, None

def stop_ttyd(terminal_id):
    """Termina un'istanza di ttyd"""
    if terminal_id in ttyd_instances:
        instance = ttyd_instances[terminal_id]
        process = instance['process']

        import sys
        sys.stderr.write(f"[TTYD] Stopping terminal_id={terminal_id}, PID={process.pid}\n")
        sys.stderr.flush()

        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

        # Remove nginx config if in remote mode
        if USE_NGINX_PROXY:
            remove_nginx_terminal_config(terminal_id)

        del ttyd_instances[terminal_id]

        sys.stderr.write(f"[TTYD] Stopped terminal_id={terminal_id}\n")
        sys.stderr.flush()

@app.route('/')
def index():
    """Pagina principale - reindirizza al login se non autenticato"""
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('index.html', username=session['username'], hostname=HOSTNAME)

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Gestisce il login"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if authenticate_user(username, password):
            session['username'] = username
            try:
                user_info = pwd.getpwnam(username)
                session['uid'] = user_info.pw_uid
                session['gid'] = user_info.pw_gid
                session['home'] = user_info.pw_dir
            except:
                pass
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Invalid credentials', hostname=HOSTNAME)

    return render_template('login.html', hostname=HOSTNAME)

@app.route('/logout')
def logout():
    """Logout"""
    session.clear()
    return redirect(url_for('login'))

@app.route('/api/sessions')
def api_sessions():
    """API per ottenere le sessioni tmux (locali e remote)"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    sessions = get_all_sessions(session.get('username'))
    return jsonify({'sessions': sessions})

@app.route('/api/session/rename', methods=['POST'])
def api_session_rename():
    """API per rinominare una sessione tmux"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json()
    old_name = data.get('old_name')
    new_name = data.get('new_name')
    host_id = data.get('host_id', 'local')
    username = session.get('username')

    if not old_name or not new_name:
        return jsonify({'error': 'Missing old_name or new_name'}), 400

    try:
        import pwd
        user_info = pwd.getpwnam(username)
        uid = user_info.pw_uid
        gid = user_info.pw_gid

        if host_id == 'local':
            # Rename local tmux session
            socket_path = f'{TMUX_SOCKET_BASE}{uid}/default'
            cmd = ['tmux', '-S', socket_path, 'rename-session', '-t', old_name, new_name]
            result = subprocess.run(cmd, capture_output=True, text=True, preexec_fn=demote(uid, gid))

            if result.returncode == 0:
                return jsonify({'success': True, 'message': 'Session renamed successfully', 'refresh_sessions': True})
            else:
                return jsonify({'error': f'Failed to rename session: {result.stderr}'}), 500
        else:
            # Rename remote tmux session via SSH
            hosts = load_user_hosts(username)
            host_config = next((h for h in hosts if h['id'] == host_id), None)

            if not host_config:
                return jsonify({'error': 'Host not found'}), 404

            hostname = host_config['hostname']
            ssh_port = host_config.get('port', 22)
            ssh_user = host_config.get('username') or username

            ssh_cmd = [
                'ssh',
                '-p', str(ssh_port),
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'ConnectTimeout=5',
                f'{ssh_user}@{hostname}',
                f'tmux rename-session -t {old_name} {new_name}'
            ]

            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=10,
                preexec_fn=demote(uid, gid)
            )

            if result.returncode == 0:
                return jsonify({'success': True, 'message': 'Remote session renamed successfully', 'refresh_sessions': True})
            else:
                return jsonify({'error': f'Failed to rename remote session: {result.stderr}'}), 500

    except Exception as e:
        import sys
        sys.stderr.write(f"[RENAME] Error: {e}\n")
        sys.stderr.flush()
        return jsonify({'error': str(e)}), 500

@app.route('/api/session/create', methods=['POST'])
def api_session_create():
    """API per creare una nuova sessione tmux"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json()
    session_name = data.get('session_name')
    host_id = data.get('host_id', 'local')
    username = session.get('username')

    if not session_name:
        return jsonify({'error': 'Session name is required'}), 400

    try:
        import pwd
        import sys

        user_info = pwd.getpwnam(username)
        uid = user_info.pw_uid
        gid = user_info.pw_gid

        if host_id == 'local':
            # Crea sessione tmux locale
            socket_path = f'{TMUX_SOCKET_BASE}{uid}/default'

            sys.stderr.write(f"[CREATE] Creating local session {session_name} for user {username}\n")
            sys.stderr.flush()

            cmd = [
                'tmux', '-S', socket_path,
                'new-session', '-d', '-s', session_name
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                preexec_fn=demote(uid, gid)
            )

            if result.returncode != 0:
                sys.stderr.write(f"[CREATE] Error: {result.stderr}\n")
                sys.stderr.flush()
                return jsonify({'error': f'Failed to create session: {result.stderr}'}), 500

            sys.stderr.write(f"[CREATE] Session {session_name} created successfully\n")
            sys.stderr.flush()

            return jsonify({
                'success': True,
                'session_name': session_name,
                'host_id': host_id
            })

        else:
            # Crea sessione tmux remota via SSH
            hosts = load_user_hosts(username)
            host_config = next((h for h in hosts if h['id'] == host_id), None)

            if not host_config:
                return jsonify({'error': 'Host not found'}), 404

            hostname = host_config['hostname']
            ssh_port = host_config.get('port', 22)
            ssh_user = host_config.get('username') or username

            sys.stderr.write(f"[CREATE] Creating remote session {session_name} on {hostname}\n")
            sys.stderr.flush()

            ssh_cmd = [
                'ssh',
                '-p', str(ssh_port),
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'ConnectTimeout=5',
                f'{ssh_user}@{hostname}',
                f'tmux new-session -d -s {session_name}'
            ]

            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                preexec_fn=demote(uid, gid)
            )

            if result.returncode != 0:
                sys.stderr.write(f"[CREATE] Error: {result.stderr}\n")
                sys.stderr.flush()
                return jsonify({'error': f'Failed to create session: {result.stderr}'}), 500

            sys.stderr.write(f"[CREATE] Remote session {session_name} created successfully on {hostname}\n")
            sys.stderr.flush()

            return jsonify({
                'success': True,
                'session_name': session_name,
                'host_id': host_id
            })

    except Exception as e:
        import sys
        sys.stderr.write(f"[CREATE] Error: {e}\n")
        sys.stderr.flush()
        return jsonify({'error': str(e)}), 500

@app.route('/api/session/delete', methods=['POST'])
def api_session_delete():
    """API per eliminare una sessione tmux"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json()
    session_name = data.get('session_name')
    host_id = data.get('host_id', 'local')
    username = session.get('username')

    if not session_name:
        return jsonify({'error': 'Session name is required'}), 400

    try:
        import pwd
        import sys

        user_info = pwd.getpwnam(username)
        uid = user_info.pw_uid
        gid = user_info.pw_gid

        if host_id == 'local':
            # Elimina sessione tmux locale
            socket_path = f'{TMUX_SOCKET_BASE}{uid}/default'

            sys.stderr.write(f"[DELETE] Deleting local session {session_name} for user {username}\n")
            sys.stderr.flush()

            cmd = [
                'tmux', '-S', socket_path,
                'kill-session', '-t', session_name
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                preexec_fn=demote(uid, gid)
            )

            if result.returncode != 0:
                sys.stderr.write(f"[DELETE] Error: {result.stderr}\n")
                sys.stderr.flush()
                return jsonify({'error': f'Failed to delete session: {result.stderr}'}), 500

            sys.stderr.write(f"[DELETE] Session {session_name} deleted successfully\n")
            sys.stderr.flush()

            return jsonify({
                'success': True,
                'session_name': session_name,
                'host_id': host_id,
                'refresh_sessions': True
            })

        else:
            # Elimina sessione tmux remota via SSH
            hosts = load_user_hosts(username)
            host_config = next((h for h in hosts if h['id'] == host_id), None)

            if not host_config:
                return jsonify({'error': 'Host not found'}), 404

            hostname = host_config['hostname']
            ssh_port = host_config.get('port', 22)
            ssh_user = host_config.get('username') or username

            sys.stderr.write(f"[DELETE] Deleting remote session {session_name} on {hostname}\n")
            sys.stderr.flush()

            ssh_cmd = [
                'ssh',
                '-p', str(ssh_port),
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'ConnectTimeout=5',
                f'{ssh_user}@{hostname}',
                f'tmux kill-session -t {session_name}'
            ]

            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                preexec_fn=demote(uid, gid)
            )

            if result.returncode != 0:
                sys.stderr.write(f"[DELETE] Error: {result.stderr}\n")
                sys.stderr.flush()
                return jsonify({'error': f'Failed to delete session: {result.stderr}'}), 500

            sys.stderr.write(f"[DELETE] Remote session {session_name} deleted successfully on {hostname}\n")
            sys.stderr.flush()

            return jsonify({
                'success': True,
                'session_name': session_name,
                'host_id': host_id,
                'refresh_sessions': True
            })

    except Exception as e:
        import sys
        sys.stderr.write(f"[DELETE] Error: {e}\n")
        sys.stderr.flush()
        return jsonify({'error': str(e)}), 500

@app.route('/api/hosts', methods=['GET'])
def api_hosts_list():
    """Get list of configured remote hosts"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    hosts = load_user_hosts(session.get('username'))
    return jsonify({'hosts': hosts})

@app.route('/api/hosts', methods=['POST'])
def api_hosts_add():
    """Add a new remote host"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json()
    username = session.get('username')

    # Validate required fields
    if not data.get('hostname'):
        return jsonify({'error': 'Hostname is required'}), 400

    # Load existing hosts
    hosts = load_user_hosts(username)

    # Generate unique ID
    import uuid
    new_host = {
        'id': str(uuid.uuid4())[:8],
        'name': data.get('name', data['hostname']),
        'hostname': data['hostname'],
        'port': data.get('port', 22),
        'username': data.get('username', username),
        'enabled': data.get('enabled', True)
    }

    hosts.append(new_host)

    if save_user_hosts(username, hosts):
        return jsonify({'success': True, 'host': new_host})
    else:
        return jsonify({'error': 'Failed to save host'}), 500

@app.route('/api/hosts/<host_id>', methods=['PUT'])
def api_hosts_update(host_id):
    """Update an existing remote host"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json()
    username = session.get('username')

    hosts = load_user_hosts(username)
    host_found = False

    for i, host in enumerate(hosts):
        if host['id'] == host_id:
            # Update fields
            hosts[i].update({
                'name': data.get('name', host.get('name')),
                'hostname': data.get('hostname', host['hostname']),
                'port': data.get('port', host.get('port', 22)),
                'username': data.get('username', host.get('username')),
                'enabled': data.get('enabled', host.get('enabled', True))
            })
            host_found = True
            break

    if not host_found:
        return jsonify({'error': 'Host not found'}), 404

    if save_user_hosts(username, hosts):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Failed to save host'}), 500

@app.route('/api/hosts/<host_id>', methods=['DELETE'])
def api_hosts_delete(host_id):
    """Delete a remote host"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    username = session.get('username')
    hosts = load_user_hosts(username)

    hosts = [h for h in hosts if h['id'] != host_id]

    if save_user_hosts(username, hosts):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Failed to save host'}), 500

@socketio.on('connect')
def handle_connect():
    """Gestisce la connessione WebSocket"""
    if 'username' not in session:
        return False
    print(f"Client connected: {session.get('username')}")

@socketio.on('disconnect')
def handle_disconnect():
    """Gestisce la disconnessione WebSocket"""
    print(f"Client disconnected: {session.get('username')}")

@socketio.on('attach_session')
def handle_attach_session(data):
    """Avvia ttyd per una sessione tmux o riusa uno esistente"""
    if 'username' not in session:
        emit('error', {'message': 'Not authenticated'})
        return

    session_name = data.get('session_name')
    host_id = data.get('host_id', 'local')  # Default to local

    if not session_name:
        emit('error', {'message': 'No session name provided'})
        return

    try:
        username = session.get('username')

        import sys

        # Check se esiste già un ttyd per questa sessione, host e utente
        for tid, instance in ttyd_instances.items():
            if (instance['session_name'] == session_name and
                instance['username'] == username and
                instance.get('host_id', 'local') == host_id):
                # Riusa l'istanza esistente
                port = instance['port']

                sys.stderr.write(f"[ATTACH] Reusing existing ttyd for session {session_name} on {host_id}, terminal_id={tid}, port={port}\n")
                sys.stderr.flush()

                # Verifica/ricrea configurazione nginx se necessario
                if USE_NGINX_PROXY:
                    create_nginx_terminal_config(tid, port)

                if USE_NGINX_PROXY:
                    emit('terminal_ready', {
                        'terminal_id': tid,
                        'use_nginx_proxy': True,
                        'reused': True
                    })
                else:
                    host = request.host.split(':')[0]
                    emit('terminal_ready', {
                        'terminal_id': tid,
                        'port': port,
                        'host': host,
                        'reused': True
                    })
                return

        # Non esiste, avvia nuovo ttyd
        terminal_id, port = start_ttyd(session_name, username, host_id)

        if terminal_id is None:
            emit('error', {'message': 'Failed to start terminal'})
            return

        sys.stderr.write(f"[ATTACH] Started new ttyd for session {session_name}, terminal_id={terminal_id}, port={port}\n")
        sys.stderr.flush()

        if USE_NGINX_PROXY:
            emit('terminal_ready', {
                'terminal_id': terminal_id,
                'use_nginx_proxy': True,
                'reused': False
            })
        else:
            host = request.host.split(':')[0]
            emit('terminal_ready', {
                'terminal_id': terminal_id,
                'port': port,
                'host': host,
                'reused': False
            })

    except Exception as e:
        import sys
        sys.stderr.write(f"[ATTACH] Error: {e}\n")
        sys.stderr.flush()
        emit('error', {'message': f'Failed to attach session: {str(e)}'})

if __name__ == '__main__':
    if os.geteuid() != 0:
        print("Warning: This application should be run as root to authenticate system users")

    # Initialize nginx terminals directory in remote mode
    if USE_NGINX_PROXY:
        os.makedirs(NGINX_TERMINALS_DIR, exist_ok=True)
        import sys
        sys.stderr.write(f"[INIT] Running in REMOTE mode with nginx proxy\n")
        sys.stderr.flush()
        # In remote mode: listen on 5000, nginx proxies from 80
        socketio.run(app, host='0.0.0.0', port=5000, debug=False)
    else:
        import sys
        sys.stderr.write(f"[INIT] Running in LOCAL mode with direct connections\n")
        sys.stderr.flush()
        # In local mode: listen on 7777 directly
        socketio.run(app, host='0.0.0.0', port=7777, debug=True)
