import json
import os
import re
import secrets
import uuid
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, static_folder='site')

DATA_PATH = os.path.join(os.path.dirname(__file__), 'data', 'data.json')
HANDLE_RE = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9._]*[A-Za-z0-9])?$')


def normalize_handle(value):
    if value is None:
        return ''
    handle = str(value).strip()
    if handle.startswith('@'):
        handle = handle[1:]
    handle = handle.strip().lower()
    return handle


def is_valid_handle(value):
    handle = normalize_handle(value)
    return bool(handle) and bool(HANDLE_RE.fullmatch(handle))


def load_data():
    if not os.path.exists(DATA_PATH):
        return {'users': {}, 'contacts': {}, 'messages': {}, 'sessions': {}, 'ipBindings': {}}
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
    data.setdefault('typing', {})
    data.setdefault('sessions', {})
    data.setdefault('ipBindings', {})

    normalized_users = {}
    for raw_key, info in list(data.get('users', {}).items()):
        if not isinstance(info, dict):
            continue
        canonical = normalize_handle(raw_key)
        if not canonical:
            continue
        if canonical in normalized_users and normalized_users[canonical].get('lastSeen') and info.get('lastSeen'):
            existing_last = normalized_users[canonical].get('lastSeen')
            if info.get('lastSeen') > existing_last:
                normalized_users[canonical] = info
            continue
        normalized_users[canonical] = info
        if 'username' not in info:
            info['username'] = canonical
    data['users'] = normalized_users

    for key in list(data.get('contacts', {}).keys()):
        normalized_key = normalize_handle(key)
        if not normalized_key:
            data['contacts'].pop(key, None)
            continue
        if normalized_key != key:
            data['contacts'][normalized_key] = data['contacts'].pop(key)

    for key in list(data.get('messages', {}).keys()):
        if '|' not in key:
            continue
        first, second = key.split('|', 1)
        normalized_key = '|'.join(sorted([normalize_handle(first), normalize_handle(second)]))
        if normalized_key != key:
            data['messages'][normalized_key] = data['messages'].pop(key)

    if 'koutroufinis' in data['users']:
        try:
            data['users']['koutroufinis'].setdefault('verified', True)
        except Exception:
            pass
    data['sessions'] = {str(token): info for token, info in (data.get('sessions', {}) or {}).items() if isinstance(info, dict)}
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


def create_session(data, username, ip_address=None):
    token = secrets.token_urlsafe(32)
    data.setdefault('sessions', {})[token] = {
        'username': username,
        'ipAddress': ip_address or request.remote_addr,
        'createdAt': datetime.utcnow().isoformat() + 'Z',
        'lastSeen': datetime.utcnow().isoformat() + 'Z',
    }
    if ip_address:
        data.setdefault('ipBindings', {})[ip_address] = username
    return token


def resolve_session_username():
    data = load_data()
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header.split(' ', 1)[1].strip()
        session = data.get('sessions', {}).get(token)
        if isinstance(session, dict):
            username = normalize_handle(session.get('username'))
            if username in data.get('users', {}):
                return username
    try:
        ip = request.remote_addr
        username = data.get('ipBindings', {}).get(ip)
        if username and normalize_handle(username) in data.get('users', {}):
            return normalize_handle(username)
    except Exception:
        pass
    return None


@app.route('/api/signup', methods=['POST'])
def api_signup():
    payload = request.get_json() or {}
    email = (payload.get('email', '') or '').strip().lower()
    username = payload.get('username', '')
    password = payload.get('password', '')
    normalized = normalize_handle(username)

    if not normalized:
        return jsonify({'success': False, 'message': 'Username is required.'}), 400
    if not is_valid_handle(normalized):
        return jsonify({'success': False, 'message': 'Usernames can only use letters, numbers, underscores, and periods.'}), 400
    if not password or len(str(password)) < 8:
        return jsonify({'success': False, 'message': 'Password must be at least 8 characters long.'}), 400
    if email and '@' not in email:
        return jsonify({'success': False, 'message': 'Please enter a valid email address.'}), 400

    data = load_data()
    users = data['users']
    if normalized in users:
        return jsonify({'success': False, 'message': 'This username is already taken.'}), 400

    user_record = {
        'email': email,
        'password': generate_password_hash(str(password)),
        'lastSeen': datetime.utcnow().isoformat() + 'Z',
        'username': normalized,
    }
    users[normalized] = user_record
    data['contacts'].setdefault(normalized, [])
    token = create_session(data, normalized, request.remote_addr)
    save_data(data)
    return jsonify({'success': True, 'message': 'Account created successfully.', 'username': normalized, 'token': token})


@app.route('/api/login', methods=['POST'])
def api_login():
    payload = request.get_json() or {}
    username = payload.get('username', '')
    password = payload.get('password', '')
    normalized = normalize_handle(username)

    if not normalized:
        return jsonify({'success': False, 'message': 'Username is required.'}), 400
    if not is_valid_handle(normalized):
        return jsonify({'success': False, 'message': 'Please enter a valid username or @handle.'}), 400
    if not password:
        return jsonify({'success': False, 'message': 'Password is required.'}), 400

    data = load_data()
    user = data['users'].get(normalized)
    if not user or not check_password_hash(user.get('password', ''), str(password)):
        return jsonify({'success': False, 'message': 'Incorrect username or password.'}), 401

    user['lastSeen'] = datetime.utcnow().isoformat() + 'Z'
    token = create_session(data, normalized, request.remote_addr)
    save_data(data)
    return jsonify({'success': True, 'message': 'Logged in', 'username': normalized, 'email': user.get('email', ''), 'token': token})


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
    username = resolve_session_username()
    if username:
        return jsonify({'success': True, 'username': username})
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
    raw_q = request.args.get('q', '')
    q = normalize_handle(raw_q)
    current_user = normalize_handle(request.args.get('currentUser'))
    data = load_data()
    users = data.get('users', {})

    if not q:
        return jsonify({'success': False, 'message': 'Enter a username or @handle to search.'}), 400
    if not is_valid_handle(q):
        return jsonify({'success': False, 'message': 'Invalid handle. Use letters, numbers, underscores, and periods only.'}), 400

    matches = []
    for username, info in users.items():
        if current_user and username == current_user:
            continue
        if username == q:
            matches.append({'username': username, 'verified': bool(info.get('verified', False))})

    if not matches:
        return jsonify({'success': True, 'users': [], 'message': 'No user found.'})

    return jsonify({'success': True, 'users': matches[:10]})


@app.route('/api/profile', methods=['POST'])
def api_profile():
    payload = request.get_json() or {}
    username = normalize_handle(payload.get('username'))
    if not username:
        return jsonify({'success': False, 'message': 'Missing username'}), 400
    data = load_data()
    user = data['users'].get(username)
    if not user:
        return jsonify({'success': False, 'message': 'Unknown user'}), 404
    email = payload.get('email')
    avatar = payload.get('avatarBase64')
    if email is not None:
        user['email'] = str(email).strip().lower()
    if avatar is not None:
        user['avatar'] = avatar
    save_data(data)
    return jsonify({'success': True})


@app.route('/api/profile', methods=['GET'])
def api_profile_get():
    username = normalize_handle(request.args.get('username'))
    if not username:
        return jsonify({'success': False, 'message': 'Missing username'}), 400
    data = load_data()
    user = data.get('users', {}).get(username)
    if not user:
        return jsonify({'success': False, 'message': 'Unknown user'}), 404
    return jsonify({'success': True, 'user': {'username': username, 'email': user.get('email', ''), 'avatar': user.get('avatar', ''), 'verified': user.get('verified', False)}})


@app.route('/api/contacts/add', methods=['POST'])
def api_contacts_add():
    payload = request.get_json() or {}
    username = normalize_handle(payload.get('username'))
    contact = normalize_handle(payload.get('contact'))
    if not username or not contact:
        return jsonify({'success': False, 'message': 'Missing user or contact'}), 400
    if username == contact:
        return jsonify({'success': False, 'message': 'You cannot add yourself as a contact.'}), 400
    data = load_data()
    users = data.get('users', {})
    if contact not in users:
        return jsonify({'success': False, 'message': 'User not found.'}), 404
    username_list = data['contacts'].setdefault(username, [])
    if not any(normalize_handle(item.get('id')) == contact for item in username_list):
        username_list.append({
            'id': contact,
            'name': contact,
            'avatarUrl': users.get(contact, {}).get('avatar', ''),
            'lastMessage': '',
            'lastTime': datetime.utcnow().isoformat() + 'Z',
            'unread': 0,
            'verified': bool(users.get(contact, {}).get('verified', False))
        })
    other_list = data['contacts'].setdefault(contact, [])
    if not any(normalize_handle(item.get('id')) == username for item in other_list):
        other_list.append({
            'id': username,
            'name': username,
            'avatarUrl': users.get(username, {}).get('avatar', ''),
            'lastMessage': '',
            'lastTime': datetime.utcnow().isoformat() + 'Z',
            'unread': 0,
            'verified': bool(users.get(username, {}).get('verified', False))
        })
    save_data(data)
    return jsonify({'success': True, 'contact': contact})


@app.route('/api/contacts/remove', methods=['POST'])
def api_contacts_remove():
    payload = request.get_json() or {}
    username = normalize_handle(payload.get('username'))
    contact = normalize_handle(payload.get('contact'))
    if not username or not contact:
        return jsonify({'success': False, 'message': 'Missing user or contact'}), 400
    data = load_data()
    if username in data.get('contacts', {}):
        data['contacts'][username] = [
            item for item in data['contacts'].get(username, [])
            if normalize_handle(item.get('id')) != contact
        ]
    if contact in data.get('contacts', {}):
        data['contacts'][contact] = [
            item for item in data['contacts'].get(contact, [])
            if normalize_handle(item.get('id')) != username
        ]
    save_data(data)
    return jsonify({'success': True})


@app.route('/api/forgot-password', methods=['POST'])
def api_forgot_password():
    payload = request.get_json() or {}
    username = normalize_handle(payload.get('username', ''))
    email = (payload.get('email', '') or '').strip().lower()
    new_password = payload.get('newPassword') or payload.get('password')

    if not username:
        return jsonify({'success': False, 'message': 'Username is required.'}), 400
    if not new_password or len(str(new_password)) < 8:
        return jsonify({'success': False, 'message': 'New password must be at least 8 characters long.'}), 400

    data = load_data()
    user = data.get('users', {}).get(username)
    if not user:
        return jsonify({'success': False, 'message': 'No account matches that username.'}), 404
    if email and user.get('email') and user.get('email', '').lower() != email:
        return jsonify({'success': False, 'message': 'The email address does not match this account.'}), 400

    user['password'] = generate_password_hash(str(new_password))
    user['lastSeen'] = datetime.utcnow().isoformat() + 'Z'
    save_data(data)
    return jsonify({'success': True, 'message': 'Password updated successfully.'})


@app.route('/api/typing', methods=['POST', 'GET'])
def api_typing():
    data = load_data()
    if request.method == 'POST':
        payload = request.get_json() or {}
        sender = normalize_handle(payload.get('from'))
        to = normalize_handle(payload.get('to'))
        action = payload.get('action', 'start')
        if not sender or not to:
            return jsonify({'success': False, 'message': 'Missing fields'}), 400
        key = conv_key(sender, to)
        if action == 'stop':
            data.setdefault('typing', {}).pop(key, None)
        else:
            data.setdefault('typing', {})[key] = {'who': sender, 'time': datetime.utcnow().isoformat() + 'Z'}
        u = data.get('users', {}).get(sender)
        if u is not None:
            u['lastSeen'] = datetime.utcnow().isoformat() + 'Z'
        save_data(data)
        return jsonify({'success': True})

    username = normalize_handle(request.args.get('username'))
    contact = normalize_handle(request.args.get('contactId'))
    if not username or not contact:
        return jsonify({'success': False, 'message': 'Missing params'}), 400
    key = conv_key(username, contact)
    info = data.get('typing', {}).get(key)
    if not info:
        return jsonify({'success': True, 'typing': False})
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
    username = normalize_handle(payload.get('username'))
    contact = normalize_handle(payload.get('contactId'))
    if not username or not contact:
        return jsonify({'success': False, 'message': 'Missing fields'}), 400
    data = load_data()
    lst = data['contacts'].get(username, [])
    entry = next((c for c in lst if normalize_handle(c.get('id')) == contact), None)
    if entry:
        entry['unread'] = 0
        save_data(data)
    return jsonify({'success': True})


@app.route('/api/profile/delete', methods=['POST'])
def api_profile_delete():
    payload = request.get_json() or {}
    username = normalize_handle(payload.get('username'))
    if not username:
        return jsonify({'success': False, 'message': 'Missing username'}), 400
    data = load_data()
    data['users'].pop(username, None)
    data['contacts'].pop(username, None)
    to_delete = [k for k in list(data['messages'].keys()) if username in [normalize_handle(part) for part in k.split('|')]]
    for k in to_delete:
        data['messages'].pop(k, None)
    save_data(data)
    return jsonify({'success': True})


@app.route('/api/logout', methods=['POST'])
def api_logout():
    payload = request.get_json(silent=True) or {}
    token = payload.get('token') or request.headers.get('Authorization', '').replace('Bearer ', '', 1).strip()
    username = normalize_handle(payload.get('username'))
    data = load_data()
    if token:
        data.get('sessions', {}).pop(token, None)
    if username:
        for session_token, session in list((data.get('sessions', {}) or {}).items()):
            if isinstance(session, dict) and normalize_handle(session.get('username')) == username:
                data['sessions'].pop(session_token, None)
        if 'ipBindings' in data:
            for ip, bound_username in list(data['ipBindings'].items()):
                if normalize_handle(bound_username) == username:
                    data['ipBindings'].pop(ip, None)
    save_data(data)
    return jsonify({'success': True})


if __name__ == '__main__':
    # Bind to PORT if provided (Render, Heroku, other PaaS)
    port = int(os.environ.get('PORT', os.environ.get('FLASK_RUN_PORT', 5000)))
    debug_env = os.environ.get('FLASK_DEBUG', os.environ.get('DEBUG', '')).lower()
    debug = debug_env in ('1', 'true', 'yes')
    app.run(host='0.0.0.0', port=port, debug=debug)
