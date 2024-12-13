# Setup
Clone repo into a permanent directory such as `/var/www/html` or `/opt`
```
git clone https://github.com/swgee/DelayAlertMonitor.git
cd DelayAlertMonitor
```
### Configure config.ini
Under the Setup section in `config.ini`:
- Add your camera/microphone RTSP URL (exact path varies depending on the device, consult its documentation)
- Add your Twilio account credentials
- Add your Twilio phone number in the `from_number` setting
- Add the phone number to be called in the `to_number` setting

Under the Times section:
- Under `night_start`, insert approximate bed time in 24-hour format
- Under `morning_start`, add approximate wake up time
- Under `morning_end`, insert the time for sure past wake up 

### Install Python environment
```
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Install additional packages
```
sudo apt install libopenblas0 portaudio19-dev 
```

### Configure security settings (optional)
To enable TLS, change `tls_enabled` to "true" in `config.ini` and generate a self-signed certificate:
```
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -sha256 -days 3650 -nodes
```
To enable HTTP Basic Auth, change `auth_enabled` to "true" in `config.ini` and change username and password

### Create and activate service
Modify `YOUR_USER` and `APP_INSTALL_DIR` in `monitor.service`
```
sudo cp monitor.service /etc/systemd/system/monitor.service
sudo systemctl daemon-reload
sudo systemctl enable monitor
sudo systemctl start monitor
```
Check if the service is running
```
sudo systemctl status monitor
```
Access the settings site in a browser: http(s)://SERVER_IP:5000