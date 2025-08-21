# Save this file as latium_server.py
import sys
import os
import time
import queue
import json
import threading
import asyncio
import websockets
import base64
import numpy as np
from flask import Flask, render_template
from flask_socketio import SocketIO

# Import AetherOS and Nostr components
sys.path.append(os.path.join(os.path.dirname(__file__), 'ferrocella/hyperboloid'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'aether'))

from hyperboloid_aether_os import Contextus
from pynostr.key import PrivateKey
from pynostr.event import Event
from bech32 import bech32_decode, convertbits

# --- CONFIGURATION ---
# MODIFIED: Renamed from sim_engine to context for clarity
# This is now the main entry point for all operations.
print("-> Initializing AetherOS Contextus...")
context = Contextus()
print("-> AetherOS Initialized.")

# NEW: Nostr Configuration
RELAYS = ['wss://relay.damus.io', 'wss://nos.lol', 'wss://nostr.wine']
# IMPORTANT: Set your server's private key as an environment variable
# In your terminal: export NUNTIUS_NSEC='nsec1...'
private_key_nsec = os.environ.get('NUNTIUS_NSEC', '').strip()
if not private_key_nsec:
    raise ValueError("FATAL: NUNTIUS_NSEC not set in environment. The server needs its own Nostr identity.")

try:
    hrp, data = bech32_decode(private_key_nsec)
    privkey_bytes = bytes(convertbits(data, 5, 8, False))
    private_key = PrivateKey(privkey_bytes)
    print(f"-> Server running with Nostr pubkey: {private_key.public_key.bech32()}")
except Exception as e:
    raise ValueError(f"Failed to decode NUNTIUS_NSEC: {e}")

# NEW: Thread-safe queue to pass commands from the Nostr listener to the main loop
command_queue = queue.Queue()

# --- FLASK & SOCKETIO SETUP ---
app = Flask(__name__, template_folder='web/templates', static_folder='web/static')
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

# --- NOSTR BACKGROUND TASKS (EARS & MOUTH) ---
async def nostr_listener():
    """The 'Ears': Listens for encrypted DMs and puts commands on the queue."""
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
                            # Note: pynostr's decrypt_dm is not async, so we can call it directly
                            from pynostr.encrypted_dm import EncryptedDirectMessage
                            dm = EncryptedDirectMessage()
                            dm.decrypt(private_key_bech32=private_key_nsec, encrypted_message=event_data['content'], public_key_hex=event_data['pubkey'])
                            message_content = dm.cleartext_content
                            
                            # Assuming the DM content is JSON: {"command": "..."}
                            command_data = json.loads(message_content)
                            if 'command' in command_data:
                                print(f"-> Received command via Nostr: {command_data['command']}")
                                command_queue.put(command_data['command'])
                        except Exception as e:
                            print(f"-> Error processing Nostr DM: {e}")
        except Exception as e:
            print(f"-> Nostr listener error: {e}. Reconnecting in 10 seconds...")
            await asyncio.sleep(10)

def run_nostr_listener_in_thread():
    """Helper to run the async listener in its own thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(nostr_listener())
    loop.close()

async def broadcast_state_to_nostr(sextet_data):
    """The 'Mouth': Publishes the current sextet state to Nostr."""
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

        # Ensure the event object is valid before proceeding
        if not isinstance(event, Event) or not hasattr(event, 'to_json'):
            print("-> Error: Failed to create a valid Nostr event object.")
            return

        message = json.dumps(['EVENT', event.to_json()])

        for relay in RELAYS:
            try:
                async with websockets.connect(relay, open_timeout=5) as ws:
                    await ws.send(message)
                    # Optional: uncomment to see successful broadcasts
                    # print(f"-> Broadcasted state to {relay}") 
                    break 
            except Exception as e:
                print(f"-> Could not broadcast state to {relay}: {e}")
    except Exception as e:
        print(f"-> A critical error occurred in the broadcast function: {e}")

# --- MAIN SIMULATION & WEB VISUALIZER LOOP ---
def main_simulation_loop():
    """Main background task managed by SocketIO."""
    print("-> Main simulation loop started.")
    last_broadcast_time = 0
    
    while True:
        # 1. Check for and execute commands from the Nostr queue
        try:
            command = command_queue.get_nowait()
            # AetherOS command execution is async, so we need to run it in a loop
            asyncio.run(context.execute_command(command))
        except queue.Empty:
            pass # No command, just continue the loop
        except Exception as e:
            print(f"-> Error executing command '{command}': {e}")
            
        # 2. Get the current state from the focused Materia in AetherOS
        # MODIFIED: We get the state from AetherOS, not a separate sim_engine
        try:
            focused_materia = context.get_focused_materia()
            
            # This part is for the WEB VISUALIZER
            # We will use the materia's grid for visualization
            image_grid = focused_materia.grid
            min_val, max_val = np.min(image_grid), np.max(image_grid)
            if max_val > min_val:
                image_grid = (image_grid - min_val) / (max_val - min_val)
            pixels = (np.array(image_grid) * 255).astype(np.uint8)
            # Create a simple grayscale image for the visualizer
            rgba_image = np.stack([pixels, pixels, pixels, np.full_like(pixels, 255)], axis=-1)
            grid_b64 = base64.b64encode(rgba_image.tobytes()).decode('utf-8')
            
            # This part gets the SEXTET data
            sextet_data = {
                'resistance': focused_materia.resistance,
                'capacitance': focused_materia.capacitance,
                'permeability': focused_materia.permeability,
                'magnetism': focused_materia.magnetism,
                'permittivity': focused_materia.permittivity,
                'dielectricity': focused_materia.dielectricity
            }

            # 3. Emit state to the web visualizer via WebSocket
            socketio.emit('simulation_update', {
                'grid': grid_b64, 'width': focused_materia.size, 'height': focused_materia.size,
                'readings': sextet_data,
                'focus': context.focus
            })

            # 4. Broadcast state to Nostr clients (rate-limited to once per second)
            current_time = time.time()
            if current_time - last_broadcast_time > 1.0:
                asyncio.run(broadcast_state_to_nostr(sextet_data))
                last_broadcast_time = current_time

        except ValueError as e: # Handles case where no materia exists
             # print(e) # Can be noisy
             pass
        except Exception as e:
            print(f"-> Error in main loop: {e}")

        # Let other tasks run
        socketio.sleep(0.1) # Update at 10Hz

@app.route('/')
def index():
    """Serves the main page for the visualizer."""
    return render_template('index.html') # Assumes you have an index.html for the visualizer

@socketio.on('connect')
def h_connect():
    print("-> Visualizer client connected.")

if __name__ == '__main__':
    print("-> Starting Ferrocella Central Server ('Latium')...")
    # Start the Nostr listener in its own thread
    nostr_thread = threading.Thread(target=run_nostr_listener_in_thread, daemon=True)
    nostr_thread.start()
    
    # Start the main simulation loop as a background task
    socketio.start_background_task(target=main_simulation_loop)
    
    # Run the Flask-SocketIO server for the visualizer
    socketio.run(app, host='0.0.0.0', port=5001, allow_unsafe_werkzeug=True)
