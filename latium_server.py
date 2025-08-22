# Final version of latium_server.py
import sys
import os
import time
from dotenv import load_dotenv
load_dotenv()
import queue
import json
import threading
import asyncio
import base64
import numpy as np
from flask import Flask, render_template
from flask_socketio import SocketIO
from collections import deque

# Add submodules to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'ferrocella/hyperboloid'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'aether'))

# Import AetherOS and Nostr components
from hyperboloid_aether_os import Contextus
from pynostr.key import PrivateKey, PublicKey
from pynostr.event import Event
from pynostr.encrypted_dm import EncryptedDirectMessage

# --- CONFIGURATION ---
print("-> Initializing AetherOS Contextus...")
context = Contextus()
print("-> AetherOS Initialized.")

# Nostr Configuration
RELAYS = ['wss://relay.damus.io', 'wss://nos.lol', 'wss://nostr.wine']
private_key_nsec = os.environ.get('NUNTIUS_NSEC', '').strip()
if not private_key_nsec: raise ValueError("FATAL: NUNTIUS_NSEC not set in environment.")
try:
    private_key = PrivateKey.from_nsec(private_key_nsec)
    print(f"-> Server running with Nostr pubkey: {private_key.public_key.bech32()}")
except Exception as e:
    raise ValueError(f"Failed to decode NUNTIUS_NSEC: {e}")

command_queue = queue.Queue()
command_log = deque(maxlen=50)
nostr_event_loop = None

# --- FLASK & SOCKETIO SETUP ---
app = Flask(__name__, template_folder='web/templates', static_folder='web/static')
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

# --- NOSTR BACKGROUND TASKS ---
async def nostr_listener():
    import websockets
    my_pubkey = private_key.public_key.hex()
    dm_filter = {'kinds': [4], '#p': [my_pubkey]}
    subscription_id = os.urandom(8).hex()
    while True:
        for relay in RELAYS:
            try:
                async with websockets.connect(relay, open_timeout=5, ping_interval=20, ping_timeout=10) as ws:
                    print(f"-> Nostr listener connected to {relay}")
                    await ws.send(json.dumps(['REQ', subscription_id, dm_filter]))
                    while True:
                        try:
                            response = await asyncio.wait_for(ws.recv(), timeout=30)
                            data = json.loads(response)
                            if data[0] == 'EVENT':
                                event_data = data[2]
                                try:
                                    dm = EncryptedDirectMessage()
                                    sender_pubkey = event_data['pubkey']
                                    dm.decrypt(private_key_bech32=private_key_nsec, encrypted_message=event_data['content'], public_key_hex=sender_pubkey)
                                    command_data = json.loads(dm.cleartext_content)
                                    if 'command' in command_data:
                                        command_entry = {"sender": sender_pubkey[:8], "command": command_data['command'], "timestamp": int(time.time())}
                                        print(f"-> Received command from {sender_pubkey[:8]}: {command_data['command']}")
                                        command_queue.put(command_entry)
                                except Exception as e:
                                    print(f"-> Error processing Nostr DM: {e}")
                        except asyncio.TimeoutError:
                            print(f"-> Timeout on {relay}, will reconnect.")
                            break
                        except Exception as e:
                            print(f"-> Error in listener on {relay}: {e}")
                            break
            except Exception as e:
                print(f"-> Failed to connect to {relay}: {e}")
            await asyncio.sleep(5)
        await asyncio.sleep(10)

def run_nostr_listener_in_thread():
    global nostr_event_loop
    nostr_event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(nostr_event_loop)
    try:
        nostr_event_loop.run_until_complete(nostr_listener())
    finally:
        nostr_event_loop.close()

async def broadcast_event_async(event):
    import websockets
    message = json.dumps(['EVENT', event.to_dict()])
    for relay in RELAYS:
        try:
            async with websockets.connect(relay, open_timeout=5, ping_interval=20, ping_timeout=10) as ws:
                await ws.send(message)
                return
        except Exception as e:
            print(f"-> Failed to broadcast to {relay}: {e}")
    print("-> Failed to broadcast to any relay")

def broadcast_event_sync(event):
    if nostr_event_loop and not nostr_event_loop.is_closed():
        try:
            future = asyncio.run_coroutine_threadsafe(broadcast_event_async(event), nostr_event_loop)
            future.result(timeout=10)
        except Exception as e:
            print(f"-> Error in broadcast_event_sync: {e}")

async def broadcast_identity_beacon_async():
    try:
        content = {"name": "Latium AetherOS Server", "about": "A server for the Ferrocella/Nuntius experiment.", "npub": private_key.public_key.bech32()}
        event = Event(kind=30078, pubkey=private_key.public_key.hex(), content=json.dumps(content), tags=[["d", "latium_server_identity_v1"]])
        event.sign(private_key.hex())
        await broadcast_event_async(event)
    except Exception as e:
        print(f"-> Error broadcasting identity beacon: {e}")

def main_simulation_loop():
    print("-> Main simulation loop started.")
    last_sextet_broadcast_time = time.time()
    last_log_broadcast_time = time.time()
    last_beacon_time = time.time()

    while True:
        try:
            try:
                command_entry = command_queue.get_nowait()
                def command_runner(entry):
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(context.execute_command(entry['command']))
                        command_log.append(entry)
                        log_event = Event(kind=30078, pubkey=private_key.public_key.hex(), content=json.dumps(list(command_log)), tags=[["d", "nuntius_command_log_v1"]])
                        log_event.sign(private_key.hex())
                        broadcast_event_sync(log_event)
                    finally:
                        loop.close()
                threading.Thread(target=command_runner, args=(command_entry,), daemon=True).start()
            except queue.Empty:
                pass

            if time.time() - last_sextet_broadcast_time > 1.0:
                focused_materia = context.get_focused_materia()
                sextet_data = {k: float(v) for k, v in {'resistance': focused_materia.resistance, 'capacitance': focused_materia.capacitance, 'permeability': focused_materia.permeability, 'magnetism': focused_materia.magnetism, 'permittivity': focused_materia.permittivity, 'dielectricity': focused_materia.dielectricity}.items()}
                state_event = Event(kind=30078, pubkey=private_key.public_key.hex(), content=json.dumps({"sextet": sextet_data}), tags=[["d", "nuntius_sextet_state_v1"]])
                state_event.sign(private_key.hex())
                broadcast_event_sync(state_event)
                last_sextet_broadcast_time = time.time()
            
            if time.time() - last_log_broadcast_time > 30:
                log_event = Event(kind=30078, pubkey=private_key.public_key.hex(), content=json.dumps(list(command_log)), tags=[["d", "nuntius_command_log_v1"]])
                log_event.sign(private_key.hex())
                broadcast_event_sync(log_event)
                last_log_broadcast_time = time.time()

            if time.time() - last_beacon_time > 3600:
                if nostr_event_loop and not nostr_event_loop.is_closed():
                    asyncio.run_coroutine_threadsafe(broadcast_identity_beacon_async(), nostr_event_loop)
                last_beacon_time = time.time()
        except Exception as e:
            print(f"-> Error in main loop: {e}")
        socketio.sleep(0.1)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def h_connect():
    print("-> Visualizer client connected.")

if __name__ == '__main__':
    print("-> Starting Ferrocella Central Server ('Latium')...")
    nostr_thread = threading.Thread(target=run_nostr_listener_in_thread, daemon=True)
    nostr_thread.start()
    time.sleep(2)
    if nostr_event_loop and not nostr_event_loop.is_closed():
        asyncio.run_coroutine_threadsafe(broadcast_identity_beacon_async(), nostr_event_loop)
    socketio.start_background_task(target=main_simulation_loop)
    socketio.run(app, host='0.0.0.0', port=5001, allow_unsafe_werkzeug=True)
