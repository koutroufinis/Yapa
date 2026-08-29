from flask import Flask, request, jsonify, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
import json
import os
from datetime import datetime
import uuid

app = Flask(__name__, static_folder='site')

DATA_PATH = os.path.join(os.path.dirname(__file__), 'data', 'data.json')


def load_data():
    if not os.path.exists(DATA_PATH):
        return {'users': {}, 'contacts': {}, 'messages': {}}
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault('users', {})
    data.setdefault('contacts', {})
    data.setdefault('messages', {})
    # Ensure typing map exists for transient typing indicators
    data.setdefault('typing', {})
    # map client IP -> last username
    data.setdefault('ipBindings', {})
    # Mark specific known verified users
    if 'koutroufinis' in data['users']:
        try:
            data['users']['koutroufinis'].setdefault('verified', True)
        except Exception:
            pass
    return data


def save_data(data):
    folder = os.path.dirname(DATA_PATH)
    if not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)
    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


@app.route('/', methods=['GET'])
def index():
    return send_from_directory('site', 'website.html')


@app.route('/login', methods=['GET'])
def login_page():
    return send_from_directory('site', 'login.html')


@app.route('/tester', methods=['GET'])
def tester_page():
    return send_from_directory('site', 'tester.html')


@app.route('/chat.html', methods=['GET'])
def chat_page():
    return send_from_directory('site', 'chat.html')


@app.route('/api/signup', methods=['POST'])
def api_signup():
    payload = request.get_json() or {}
    email = payload.get('email', '').strip().lower()
    username = payload.get('username', '').strip()
    password = payload.get('password', '')
    if not username or not password:
        return jsonify({'success': False, 'message': 'Missing username or password'}), 400
    data = load_data()
    users = data['users']
    if username in users:
        return jsonify({'success': False, 'message': 'Username already taken'}), 400
    users[username] = {'email': email, 'password': generate_password_hash(password)}
    users[username]['lastSeen'] = datetime.utcnow().isoformat() + 'Z'
    data['contacts'].setdefault(username, [])
    # bind IP to username for convenience
    try:
        ip = request.remote_addr
        data.setdefault('ipBindings', {})[ip] = username
    except Exception:
        pass
    save_data(data)
    return jsonify({'success': True, 'message': 'Account created', 'username': username})


@app.route('/api/login', methods=['POST'])
def api_login():
    payload = request.get_json() or {}
    username = payload.get('username', '').strip()
    password = payload.get('password', '')
    if not username or not password:
        return jsonify({'success': False, 'message': 'Missing fields'}), 400
    data = load_data()
    user = data['users'].get(username)
    if not user or not check_password_hash(user.get('password', ''), password):
        return jsonify({'success': False, 'message': 'Invalid credentials'}), 401
    # update last seen on login
    user['lastSeen'] = datetime.utcnow().isoformat() + 'Z'
    try:
        ip = request.remote_addr
        data.setdefault('ipBindings', {})[ip] = username
    except Exception:
        pass
    save_data(data)
    return jsonify({'success': True, 'message': 'Logged in', 'username': username, 'email': user.get('email', '')})


def conv_key(a, b):
    return '|'.join(sorted([a, b]))


@app.route('/api/contacts', methods=['GET'])
def api_contacts():
    username = request.args.get('username')
    data = load_data()
    contacts = data['contacts'].get(username, []) if username else []
    # Annotate contacts with known user metadata (e.g., verified)
    users = data.get('users', {})
    annotated = []
    for c in contacts:
        copy = dict(c)
        other = copy.get('id')
        if other and other in users:
            copy['verified'] = users.get(other, {}).get('verified', False)
            copy['lastSeen'] = users.get(other, {}).get('lastSeen')
            # expose avatar url for clients to render
            copy['avatarUrl'] = users.get(other, {}).get('avatar', '')
            # consider online if lastSeen within 30 seconds
            try:
                if copy['lastSeen']:
                    t = datetime.fromisoformat(copy['lastSeen'].replace('Z', ''))
                    copy['online'] = (datetime.utcnow() - t).total_seconds() <= 30
                else:
                    copy['online'] = False
            except Exception:
                copy['online'] = False
        else:
            copy.setdefault('verified', False)
            copy.setdefault('online', False)
        annotated.append(copy)
    return jsonify({'success': True, 'contacts': annotated})


@app.route('/api/remember', methods=['GET'])
def api_remember():
    data = load_data()
    try:
        ip = request.remote_addr
        username = data.get('ipBindings', {}).get(ip)
        if username:
            return jsonify({'success': True, 'username': username})
    except Exception:
        pass
    return jsonify({'success': True, 'username': None})


@app.route('/api/messages', methods=['GET', 'POST'])
def api_messages():
    data = load_data()
    if request.method == 'GET':
        username = request.args.get('username')
        contact = request.args.get('contactId')
        if not username or not contact:
            return jsonify({'success': False, 'message': 'Missing params'}), 400
        key = conv_key(username, contact)
        msgs = data['messages'].get(key, [])
        return jsonify({'success': True, 'messages': msgs})
    payload = request.get_json() or {}
    sender = payload.get('from')
    to = payload.get('to')
    text = payload.get('text', '')
    if not sender or not to or not text:
        return jsonify({'success': False, 'message': 'Missing fields'}), 400
    key = conv_key(sender, to)
    msg = {'id': str(uuid.uuid4()), 'from': sender, 'to': to, 'text': text, 'isoTime': datetime.utcnow().isoformat() + 'Z'}
    data['messages'].setdefault(key, []).append(msg)
    # update contacts
    for user, other in [(sender, to), (to, sender)]:
        lst = data['contacts'].setdefault(user, [])
        entry = next((c for c in lst if c.get('id') == other), None)
        if not entry:
            entry = {'id': other, 'name': other, 'avatarUrl': '', 'lastMessage': text, 'lastTime': msg['isoTime'], 'unread': 0, 'verified': data.get('users', {}).get(other, {}).get('verified', False)}
            lst.append(entry)
        else:
            entry['lastMessage'] = text
            entry['lastTime'] = msg['isoTime']
        if user == to:
            entry['unread'] = entry.get('unread', 0) + 1
    # update lastSeen for sender
    u = data.get('users', {}).get(sender)
    if u is not None:
        u['lastSeen'] = datetime.utcnow().isoformat() + 'Z'
    save_data(data)
    return jsonify({'success': True, 'message': msg})


@app.route('/api/users/search', methods=['GET'])
def api_users_search():
    q = (request.args.get('q') or '').strip().lower()
    data = load_data()
    users = data.get('users', {})
    if not q:
        # return a short list of usernames
        result = [{'username': u, 'verified': users[u].get('verified', False)} for u in list(users.keys())[:20]]
        return jsonify({'success': True, 'users': result})
    matches = []
    for u, info in users.items():
        if q in u.lower():
            matches.append({'username': u, 'verified': info.get('verified', False)})
    return jsonify({'success': True, 'users': matches})


@app.route('/api/profile', methods=['POST'])
def api_profile():
    payload = request.get_json() or {}
    username = payload.get('username')
    if not username:
        return jsonify({'success': False, 'message': 'Missing username'}), 400
    data = load_data()
    user = data['users'].get(username)
    if not user:
        return jsonify({'success': False, 'message': 'Unknown user'}), 404
    email = payload.get('email')
    avatar = payload.get('avatarBase64')
    if email is not None:
        user['email'] = email
    if avatar is not None:
        user['avatar'] = avatar
    save_data(data)
    return jsonify({'success': True})


@app.route('/api/profile', methods=['GET'])
def api_profile_get():
    username = request.args.get('username')
    if not username:
        return jsonify({'success': False, 'message': 'Missing username'}), 400
    data = load_data()
    user = data.get('users', {}).get(username)
    if not user:
        return jsonify({'success': False, 'message': 'Unknown user'}), 404
    # Return public-safe profile (no password)
    return jsonify({'success': True, 'user': {'username': username, 'email': user.get('email', ''), 'avatar': user.get('avatar', ''), 'verified': user.get('verified', False)}})


@app.route('/api/typing', methods=['POST', 'GET'])
def api_typing():
    data = load_data()
    if request.method == 'POST':
        payload = request.get_json() or {}
        sender = payload.get('from')
        to = payload.get('to')
        action = payload.get('action', 'start')
        if not sender or not to:
            return jsonify({'success': False, 'message': 'Missing fields'}), 400
        key = conv_key(sender, to)
        if action == 'stop':
            data.setdefault('typing', {}).pop(key, None)
        else:
            data.setdefault('typing', {})[key] = {'who': sender, 'time': datetime.utcnow().isoformat() + 'Z'}
        # update lastSeen for sender as typing indicates activity
        u = data.get('users', {}).get(sender)
        if u is not None:
            u['lastSeen'] = datetime.utcnow().isoformat() + 'Z'
        save_data(data)
        return jsonify({'success': True})

    # GET: check typing state for a conversation
    username = request.args.get('username')
    contact = request.args.get('contactId')
    if not username or not contact:
        return jsonify({'success': False, 'message': 'Missing params'}), 400
    key = conv_key(username, contact)
    info = data.get('typing', {}).get(key)
    if not info:
        return jsonify({'success': True, 'typing': False})
    # If last typing within 5 seconds and from other user, report typing
    try:
        t = datetime.fromisoformat(info.get('time').replace('Z', ''))
        delta = datetime.utcnow() - t
        if delta.total_seconds() <= 5 and info.get('who') != username:
            return jsonify({'success': True, 'typing': True, 'who': info.get('who')})
    except Exception:
        pass
    return jsonify({'success': True, 'typing': False})


@app.route('/api/contacts/mark_read', methods=['POST'])
def api_contacts_mark_read():
    payload = request.get_json() or {}
    username = payload.get('username')
    contact = payload.get('contactId')
    if not username or not contact:
        return jsonify({'success': False, 'message': 'Missing fields'}), 400
    data = load_data()
    lst = data['contacts'].get(username, [])
    entry = next((c for c in lst if c.get('id') == contact), None)
    if entry:
        entry['unread'] = 0
        save_data(data)
    return jsonify({'success': True})


@app.route('/api/profile/delete', methods=['POST'])
def api_profile_delete():
    payload = request.get_json() or {}
    username = payload.get('username')
    if not username:
        return jsonify({'success': False, 'message': 'Missing username'}), 400
    data = load_data()
    data['users'].pop(username, None)
    data['contacts'].pop(username, None)
    to_delete = [k for k in list(data['messages'].keys()) if username in k.split('|')]
    for k in to_delete:
        data['messages'].pop(k, None)
    save_data(data)
    return jsonify({'success': True})


@app.route('/api/logout', methods=['POST'])
def api_logout():
    return jsonify({'success': True})


if __name__ == '__main__':
    # Bind to PORT if provided (Render, Heroku, other PaaS)
    port = int(os.environ.get('PORT', os.environ.get('FLASK_RUN_PORT', 5000)))
    debug_env = os.environ.get('FLASK_DEBUG', os.environ.get('DEBUG', '')).lower()
    debug = debug_env in ('1', 'true', 'yes')
    app.run(host='0.0.0.0', port=port, debug=debug)
