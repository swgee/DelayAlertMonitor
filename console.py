from flask import Flask, request, jsonify, render_template, redirect, Response
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from monitor import AudioMonitor
import configparser
import threading
import logging

app = Flask(__name__)

config_path='config.ini'
config = configparser.ConfigParser()
config.read(config_path)

users = {
    config['Security']['username']: generate_password_hash(config['Security']['password'])
}

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

monitor = AudioMonitor(True)

def check_auth(username, password):
    return username in users and check_password_hash(users.get(username), password)

def authenticate():
    return Response(
        'Unauthorized', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'}
    )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        config.read(config_path)
        if config['Security']['auth_enabled'] == "false":
            return f(*args, **kwargs)

        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

@app.route('/')
@requires_auth
def home():
    config.read(config_path)
    profiles = ["Night","Morning"]
    phone_numbers = config['PhoneNumbers']['numbers'].split(',')
    current_to_number = monitor.twilio_to

    if not request.args.get('p') or request.args.get('p') not in profiles:
        selected_profile = profiles[0]
    else:
        selected_profile = request.args.get('p')

    error = ""
    if request.args.get('e') == "integers":
        error="Form values must be positive integers greater than zero"

    current_profile = monitor.profile
    testing = monitor.testing

    return render_template('console.html', 
                            profiles=profiles, 
                            selected_profile=selected_profile,
                            enabled=monitor.enabled,
                            threshold=config[selected_profile]['threshold'],
                            window=config[selected_profile]['window_size'],
                            cooldown=config[selected_profile]['cooldown_minutes'],
                            night_start=config['Times']["night_start"],
                            morning_start=config['Times']["morning_start"],
                            morning_end=config['Times']["morning_end"],
                            error=error,
                            current_profile=current_profile,
                            testing=testing,
                            phone_numbers=phone_numbers,
                            current_to_number=current_to_number)

@app.route('/update', methods=['POST'])
@requires_auth
def update_config():
    config.read(config_path)
    form_data = request.form.to_dict()
    try:
        for v in form_data.values():
            if "-" in v or v == "0":
                raise ValueError
        config[form_data['profile']]['threshold'] = str(int(form_data['threshold']))
        config[form_data['profile']]['window_size'] = str(int(form_data['window']))
        config[form_data['profile']]['cooldown_minutes'] = str(int(form_data['cooldown']))
    except ValueError:
        return redirect('/?e=integers&p='+form_data['profile'])
    with open(config_path, 'w') as configfile:
        config.write(configfile)
    monitor.logger.info("Updated "+form_data['profile']+" profile")
    return redirect('/?p='+form_data['profile'])

@app.route('/change-status', methods=['GET'])
@requires_auth
def change_status():
    if monitor.enabled:
        monitor.enabled = False
    else:
        monitor.enabled = True
    monitor.logger.info("Updated status - enabled: "+str(monitor.enabled))
    return redirect('/')

@app.route('/test', methods=['GET'])
@requires_auth
def test_profile():
    if not monitor.testing:
        if request.args.get('profile') == "Night":
            monitor.test_profile("Night")
        if request.args.get('profile') == "Morning":
            monitor.test_profile("Morning")
        monitor.logger.info("Testing "+request.args.get('profile')+" profile")
    else:
        monitor.test_profile("")
        monitor.logger.info("Stopped testing")
    return redirect('/?p='+request.args.get('profile'))

@app.route('/update-number', methods=['POST'])
@requires_auth
def update_number():
    config.read(config_path)
    new_to_number = request.form.get('to_number')
    if new_to_number:
        monitor.twilio_to = new_to_number
        config['Setup']['to_number'] = new_to_number
        with open(config_path, 'w') as configfile:
            config.write(configfile)
        monitor.logger.info(f"Updated Twilio 'to' number to: {new_to_number}")
    return "OK", 200

@app.route('/average', methods=['GET'])
def get_average():
    return jsonify({'average': f"{monitor.get_console_average():.4f}"}), 200

if __name__ == '__main__':
    monitor_thread = threading.Thread(target=monitor.run, daemon=True)
    monitor_thread.start()
    if config['Security']['tls_enabled'] == "true":
        app.run('0.0.0.0',ssl_context=('cert.pem', 'key.pem'))
    else:
        app.run('0.0.0.0')
