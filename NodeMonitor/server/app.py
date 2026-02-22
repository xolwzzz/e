from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from datetime import datetime
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'changeme123'
socketio = SocketIO(app, cors_allowed_origins="*")

clients = {}

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
        socketio.emit('client_update', {'clients': list(clients.values())})
    return jsonify({'status': 'ok'})

@socketio.on('connect')
def handle_connect():
    emit('client_update', {'clients': list(clients.values())})

@socketio.on('request_clients')
def handle_request():
    emit('client_update', {'clients': list(clients.values())})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)