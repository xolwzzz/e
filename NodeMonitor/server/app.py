from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime
import uuid
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'changeme123'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', max_http_buffer_size=10 * 1024 * 1024)

clients = {}
# Maps client_id -> socket session id (for the agent)
agent_sids = {}
# Maps viewer socket sid -> client_id they're viewing
viewer_watching = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/ping', methods=['POST'])
def ping():
    data = request.json or {}
    client_id = data.get('client_id', str(uuid.uuid4()))
    clients[client_id] = {
        'id': client_id,
        'hostname': data.get('hostname', 'Unknown'),
        'ip': request.remote_addr,
        'username': data.get('username', 'Unknown'),
        'platform': data.get('platform', 'Unknown'),
        'connected_at': data.get('connected_at', datetime.now().isoformat()),
        'last_seen': datetime.now().isoformat(),
        'status': 'online'
    }
    socketio.emit('client_update', {'clients': list(clients.values())})
    return jsonify({'status': 'ok', 'client_id': client_id})

@app.route('/api/disconnect', methods=['POST'])
def client_disconnect():
    data = request.json or {}
    client_id = data.get('client_id')
    if client_id and client_id in clients:
        clients[client_id]['status'] = 'offline'
        agent_sids.pop(client_id, None)
        socketio.emit('client_update', {'clients': list(clients.values())})
    return jsonify({'status': 'ok'})

# ── Socket events ──────────────────────────────────────────────

@socketio.on('connect')
def handle_connect():
    emit('client_update', {'clients': list(clients.values())})

@socketio.on('request_clients')
def handle_request():
    emit('client_update', {'clients': list(clients.values())})

@socketio.on('agent_register')
def agent_register(data):
    """Called by the Python client over WebSocket to register its sid"""
    client_id = data.get('client_id')
    if client_id:
        agent_sids[client_id] = request.sid
        join_room(f'agent_{client_id}')
        if client_id in clients:
            clients[client_id]['status'] = 'online'
            clients[client_id]['last_seen'] = datetime.now().isoformat()
        socketio.emit('client_update', {'clients': list(clients.values())})

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    # Clean up agent
    for cid, asid in list(agent_sids.items()):
        if asid == sid:
            del agent_sids[cid]
            if cid in clients:
                clients[cid]['status'] = 'offline'
            socketio.emit('client_update', {'clients': list(clients.values())})
            break
    # Clean up viewer
    viewer_watching.pop(sid, None)

@socketio.on('viewer_watch')
def viewer_watch(data):
    """Dashboard viewer wants to watch a client"""
    client_id = data.get('client_id')
    viewer_watching[request.sid] = client_id
    join_room(f'viewers_{client_id}')
    # Ask the agent to start streaming
    if client_id in agent_sids:
        socketio.emit('start_stream', {}, room=f'agent_{client_id}')

@socketio.on('viewer_unwatch')
def viewer_unwatch(data):
    client_id = data.get('client_id')
    viewer_watching.pop(request.sid, None)
    leave_room(f'viewers_{client_id}')
    # If no viewers left, tell agent to stop
    # (rough check — room membership not easily queryable, agent handles it gracefully)
    socketio.emit('stop_stream', {}, room=f'agent_{client_id}')

@socketio.on('screen_frame')
def screen_frame(data):
    """Agent sends a JPEG frame as base64, forward to all viewers of that client"""
    client_id = data.get('client_id')
    socketio.emit('screen_frame', {'frame': data.get('frame'), 'client_id': client_id},
                  room=f'viewers_{client_id}')

@socketio.on('mouse_move')
def mouse_move(data):
    """Viewer sends mouse move, forward to agent"""
    client_id = data.get('client_id')
    if client_id in agent_sids:
        socketio.emit('mouse_move', {'x': data['x'], 'y': data['y']}, room=f'agent_{client_id}')

@socketio.on('mouse_click')
def mouse_click(data):
    client_id = data.get('client_id')
    if client_id in agent_sids:
        socketio.emit('mouse_click', {'x': data['x'], 'y': data['y'], 'button': data.get('button','left')}, room=f'agent_{client_id}')

@socketio.on('key_press')
def key_press(data):
    client_id = data.get('client_id')
    if client_id in agent_sids:
        socketio.emit('key_press', {'key': data['key']}, room=f'agent_{client_id}')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
