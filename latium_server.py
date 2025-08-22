# Save this file as latium_server.py
import sys
import os
import time
from dotenv import load_dotenv
load_dotenv()
import queue
import json
import threading
import asyncio
import websockets
import base64
import numpy as np
from flask import Flask, render_template
from flask_socketio import SocketIO

# Add submodules to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'ferrocella/hyperboloid'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'aether'))

# Import AetherOS and Nostr components
from hyperboloid_aether_os import Contextus
from pynostr.key import PrivateKey
from pynostr.event import Event
from bech32 import bech32_decode, convertbits

# --- CONFIGURATION ---
print("-> Initializing AetherOS Contextus...")
context = Contextus()
print("-> AetherOS Initialized.")

# Nostr Configuration
RELAYS = ['wss://relay.damus.io', 'wss://nos.lol', 'wss://nostr.wine']
private_key_nsec = os.environ.get('NUNTIUS_NSEC', '').strip()
if not private_key_nsec:
    raise ValueError("FATAL: NUNTIUS_NSEC not set in environment.")
try:
    private_key = PrivateKey.from_nsec(private_key_nsec)
    print(f"-> Server running with Nostr pubkey: {private_key.public_key.bech32()}")
except Exception as e:
    raise ValueError(f"Failed to decode NUNTIUS_NSEC: {e}")

command_queue = queue.Queue()


# --- FLASK & SOCKETIO SETUP ---
app = Flask(__name__, template_folder='web/templates', static_folder='web/static')
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

# --- NOSTR BACKGROUND TASKS ---
async def nostr_listener():
    my_pubkey = private_key.public_key.hex()
    dm_filter = {'kinds': [4], '#p': [my_pubkey]}
    subscription_id = os.urandom(8).hex()
    
    while True:
        try:
            async with websockets.connect(RELAYS[0]) as ws:
                print(f"-> Nostr listener connected to {RELAYS[0]}")
                await ws.send(json.dumps(['REQ', subscription_id, dm_filter]))
                while True:
                    response = await ws.recv()
                    data = json.loads(response)
                    if data[0] == 'EVENT':
                        event_data = data[2]
                        try:
                            from pynostr.encrypted_dm import EncryptedDirectMessage
                            dm = EncryptedDirectMessage()
                            dm.decrypt(private_key_bech32=private_key_nsec, encrypted_message=event_data['content'], public_key_hex=event_data['pubkey'])
                            command_data = json.loads(dm.cleartext_content)
                            if 'command' in command_data:
                                print(f"-> Received command via Nostr: {command_data['command']}")
                                command_queue.put(command_data['command'])
                        except Exception as e:
                            print(f"-> Error processing Nostr DM: {e}")
        except Exception as e:
            print(f"-> Nostr listener error: {e}. Reconnecting...")
            await asyncio.sleep(10)

def run_nostr_listener_in_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(nostr_listener())
    loop.close()

async def broadcast_state_to_nostr(sextet_data):
    try:
        content = {
            "source": "latium_server",
            "timestamp": int(time.time()),
            "sextet": sextet_data
        }
        event = Event(
            kind=1,
            pubkey=private_key.public_key.hex(),
            content=json.dumps(content),
            tags=[["t", "ferrocella-v1"]]
        )
        event.sign(private_key.hex())
        message = json.dumps(['EVENT', event.to_dict()])
        for relay in RELAYS:
            try:
                async with websockets.connect(relay, open_timeout=5) as ws:
                    await ws.send(message)
                    break
            except Exception:
                pass # Fail silently on individual relay errors
    except Exception as e:
        # This will now print the specific error if Event() fails
        print(f"-> Error creating/sending Nostr event: {e}")

async def broadcast_identity_beacon():
    try:
        content = {
            "name": "Latium AetherOS Server",
            "about": "A server for the Ferrocella/Nuntius experiment.",
            "npub": private_key.public_key.bech32()
        }
        # Kind 30078 is a replaceable event, good for profiles or statuses
        event = Event(
            kind=30078,
            pubkey=private_key.public_key.hex(),
            content=json.dumps(content),
            tags=[["d", "latium_server_identity_v1"]] # This is the unique, findable ID
        )
        event.sign(private_key.hex())
        message = json.dumps(['EVENT', event.to_dict()])
        for relay in RELAYS:
            try:
                async with websockets.connect(relay, open_timeout=5) as ws:
                    await ws.send(message)
                    print(f"-> Identity beacon broadcasted to {relay}")
                    break
            except Exception:
                pass
    except Exception as e:
        print(f"-> Error broadcasting identity beacon: {e}")

# --- MAIN SIMULATION LOOP ---
def main_simulation_loop():
    print("-> Main simulation loop started.")
    last_broadcast_time = 0
    last_beacon_time = 0
    while True:
        try:
            # Check for and execute commands
            try:
                command = command_queue.get_nowait()
                asyncio.run(context.execute_command(command))
            except queue.Empty:
                pass
            
            # Broadcast state to Nostr clients every second
            if time.time() - last_broadcast_time > 1.0:
                focused_materia = context.get_focused_materia()
                sextet_data = {k: float(v) for k, v in {
                    'resistance': focused_materia.resistance, 'capacitance': focused_materia.capacitance, 'permeability': focused_materia.permeability,
                    'magnetism': focused_materia.magnetism, 'permittivity': focused_materia.permittivity, 'dielectricity': focused_materia.dielectricity
                }.items()}
                asyncio.run(broadcast_state_to_nostr(sextet_data))
                last_broadcast_time = time.time()

            # Broadcast the identity beacon once per hour
            if time.time() - last_beacon_time > 3600:
                asyncio.run(broadcast_identity_beacon())
                last_beacon_time = time.time()
                
        except Exception as e:
            print(f"-> Error in main loop: {e}")
        
        # The web visualizer (if connected) still gets rapid updates
        try:
            focused_materia = context.get_focused_materia()
            sextet_data = {k: float(v) for k, v in {
                'resistance': focused_materia.resistance, 'capacitance': focused_materia.capacitance, 'permeability': focused_materia.permeability,
                'magnetism': focused_materia.magnetism, 'permittivity': focused_materia.permittivity, 'dielectricity': focused_materia.dielectricity
            }.items()}
            image_grid = focused_materia.grid
            min_val, max_val = np.min(image_grid), np.max(image_grid)
            if max_val > min_val:
                image_grid = (image_grid - min_val) / (max_val - min_val)
            pixels = (np.array(image_grid) * 255).astype(np.uint8)
            rgba_image = np.stack([pixels, pixels, pixels, np.full_like(pixels, 255)], axis=-1)
            grid_b64 = base64.b64encode(rgba_image.tobytes()).decode('utf-8')
            
            socketio.emit('simulation_update', {
                'grid': grid_b64, 'width': focused_materia.size, 'height': focused_materia.size,
                'readings': sextet_data, 'focus': context.focus
            })
        except Exception:
            pass

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
    socketio.start_background_task(target=main_simulation_loop)
    socketio.run(app, host='0.0.0.0', port=5001, allow_unsafe_werkzeug=True)
