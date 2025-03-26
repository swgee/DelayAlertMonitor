import numpy as np
from twilio.rest import Client
import time
from collections import deque
import logging
import configparser
from datetime import datetime
import os
import subprocess
import atexit

class AudioMonitor:
    def __init__(self, service):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

        self.config = configparser.ConfigParser()
        self.config.read('config.ini')
        
        self.mean_hertz = int(self.config['Setup']['mean_hertz'])
        self.rtsp_url = self.config['Setup']['rtsp']
        self.fifo_path = '/tmp/audio_monitor_fifo'
        
        self.twilio_client = Client(
            self.config['Setup']['twilio_account_sid'],
            self.config['Setup']['twilio_auth_token']
        )
        logging.getLogger('twilio.http_client').setLevel(logging.WARNING)
        
        self.twilio_from = self.config['Setup']['from_number']
        self.twilio_to = self.config['Setup']['to_number']

        self.console_window_size = 5  # seconds
        self.console_audio_levels = deque(maxlen=self.console_window_size * self.mean_hertz)
        self.logging_window_size = 600  # seconds
        self.logging_audio_levels = deque(maxlen=self.logging_window_size * self.mean_hertz)

        self.last_call_time = 0
        self.profile = ""
        self.enabled = True
        self.testing = ""
        self.check_time()
        
        atexit.register(self.cleanup)
        self.service = service

        if not os.path.exists(self.fifo_path):
            os.mkfifo(self.fifo_path)
        
        self.start_ffmpeg()

    def start_ffmpeg(self):
        cmd = f"""
        ffmpeg -i {self.rtsp_url} \
               -f wav \
               -acodec pcm_s16le \
               -ac 1 \
               -ar 44100 \
               -y \
               {self.fifo_path} > /dev/null 2>&1 &
        """
        subprocess.Popen(cmd, shell=True)
        self.logger.info("Started FFmpeg process")

    def run(self):
        try:
            self.logger.info("Starting audio monitoring...")
            
            with open(self.fifo_path, 'rb') as fifo:
                # Skip WAV header (44 bytes)
                fifo.read(44)
                
                CHUNK_SIZE = int(44100 / self.mean_hertz)
                average_logged = False

                while True:
                    if datetime.now().second == 0 and self.testing == "": # check every minute
                        self.check_time()

                    if datetime.now().minute % 10 == 0:
                        if not average_logged:
                            ten_min_average = f"{(sum(self.logging_audio_levels) / len(self.logging_audio_levels)):.4f}"
                            self.logger.info("Last 10-minute sound average: "+ten_min_average)
                            average_logged = True
                    else:
                        average_logged = False
                    
                    in_bytes = fifo.read(CHUNK_SIZE * 2)  # 16-bit = 2 bytes per sample
                    if not in_bytes:
                        raise Exception("End of stream")
                    
                    audio_chunk = np.frombuffer(in_bytes, np.int16)
                    self.check_audio_levels(audio_chunk)

                    if self.get_console_average() == 0:
                        raise Exception("Zero value chunks")

        except KeyboardInterrupt:
            self.logger.info("Monitoring stopped by user")
        except Exception as e:
            self.logger.error(f"Error in monitoring: {e}")
            if self.service:
                os.system('sudo systemctl restart monitor.service')

    def check_time(self):
        self.config.read('config.ini')
        night_start = int(self.config['Times']['night_start'])
        morning_start = int(self.config['Times']['morning_start'])
        morning_end = int(self.config['Times']['morning_end'])

        current_time = int(datetime.now().strftime("%H%M"))

        # if night_start is past midnight, go to bed earlier
        if current_time >= night_start or current_time < morning_start:
            if self.profile != "Night":
                self.update_config("Night")
        elif current_time >= morning_start and current_time < morning_end:  
            if self.profile != "Morning":
                self.update_config("Morning")
        else:
            self.profile = ""
            

    def update_config(self, profile):
        self.profile = profile
        self.threshold = int(self.config[profile]['threshold'])
        self.prod_window_size = int(self.config[profile]['window_size'])
        self.call_cooldown = int(self.config[profile]['cooldown_minutes']) * 60

        self.prod_audio_levels = deque(maxlen=self.prod_window_size * self.mean_hertz)
        self.logger.info(f"Updated configuration for {self.profile}")

    def check_audio_levels(self, audio_chunk):
        current_rms = self.calculate_rms(audio_chunk)
        self.console_audio_levels.append(current_rms)
        self.logging_audio_levels.append(current_rms)

        # Uncomment below to debug RTSP audio feed
        # self.logger.info(f"RMS: {current_rms}")
        
        if (self.profile != "" and self.enabled) or self.testing != "":
            self.prod_audio_levels.append(current_rms)
            if len(self.prod_audio_levels) == self.prod_audio_levels.maxlen:
                window_avg = sum(self.prod_audio_levels) / len(self.prod_audio_levels)
                if window_avg > self.threshold:
                    self.make_call()

    def calculate_rms(self, audio_chunk):
        try:
            normalized_array = audio_chunk.astype(float) / 32768.0
            return np.sqrt(np.mean(np.square(normalized_array))) * 1000
        except:
            return 0

    def make_call(self):
        current_time = time.time()
        if current_time - self.last_call_time >= self.call_cooldown:
            try:
                call = self.twilio_client.calls.create(
                    url='http://demo.twilio.com/docs/voice.xml',
                    to=self.twilio_to,
                    from_=self.twilio_from
                )
                self.logger.info(f"Alert call made: {call.sid}")
                self.logger.info(f"Beginning cooldown period of {self.call_cooldown} seconds")
                self.last_call_time = current_time
            except Exception as e:
                self.logger.error(f"Error making Twilio call: {e}")

    def cleanup(self):
        subprocess.run(
            f"pkill -f 'ffmpeg.*{self.fifo_path}'",
            shell=True
        )
        
        if os.path.exists(self.fifo_path):
            os.unlink(self.fifo_path)
        
        self.logger.info("Cleanup completed")

    def get_console_average(self):
        if len(self.console_audio_levels) > 0:
            return sum(self.console_audio_levels) / len(self.console_audio_levels)
        else:
            return 0
    
    def test_profile(self, profile):
        self.config.read('config.ini')
        if profile == "":
            self.testing = ""
        else:
            self.testing = profile
            self.threshold = int(self.config[profile]['threshold'])
            self.call_cooldown = int(self.config[profile]['cooldown_minutes']) * 60

            self.prod_window_size = int(self.config[profile]['window_size'])
            self.prod_audio_levels = deque(maxlen=self.prod_window_size * self.mean_hertz)
            

if __name__ == '__main__':
    monitor = AudioMonitor(False)
    monitor.run()