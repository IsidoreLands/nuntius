import os
import time
import asyncio
import json
import websockets
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv
from pynostr.event import Event
from pynostr.key import PrivateKey
from pynostr.encrypted_dm import EncryptedDirectMessage
from bech32 import bech32_decode, convertbits
import numpy as np
import base64
import cv2

# Load environment variables
load_dotenv()

# Nostr Configuration
private_key_nsec = os.environ.get('NUNTIUS_NSEC')
if not private_key_nsec:
    raise ValueError("NUNTIUS_NSEC environment variable not set")
hrp, data = bech32_decode(private_key_nsec)
privkey_bytes = bytes(convertbits(data, 5, 8, False))
private_key = PrivateKey(privkey_bytes)
relays = ['wss://relay.damus.io', 'wss://nos.lol']

# FluxCore Class (from your ferrocella code)
class FluxCore:
    def __init__(self):
        self.size = 1000
        self.grid = np.zeros((self.size, self.size), dtype=np.float32)
        self.energy = 0.0
        self.memory_patterns = []
        self.identity_wave = 0.0
        self.context_embeddings = {}
        self.anomaly = None
        self.resistance = 1e-9
        self.capacitance = 0.0
        self.permeability = 1.0
        self.magnetism = 0.0
        self.permittivity = 1.0
        self.dielectricity = 0.0
        self._ground_with_visual_truth()

    def _ground_with_visual_truth(self):
        self.grid = np.random.uniform(0, 0.15, (self.size, self.size))  # Mock grounding

    def perturb(self, x, y, amp, mod=1.0):
        flux_change = amp * mod
        if 0 <= x < self.size and 0 <= y < self.size:
            self.grid[y, x] += flux_change
        self._update_memory(flux_change)
        self._update_simulated_sextet(flux_change)

    def converge(self):
        kernel = np.ones((3, 3), np.float32) / 9
        self.grid = cv2.filter2D(self.grid, -1, kernel) + self.magnetism
        np.clip(self.grid, 0, None, out=self.grid)
        self._ground_with_visual_truth()
        self._update_simulated_sextet(0)

    def _update_memory(self, change):
        self.memory_patterns.append(change)
        if len(self.memory_patterns) > 100:
            self.memory_patterns.pop(0)

    def _update_simulated_sextet(self, change):
        self.capacitance += self.energy
        self.resistance += np.var(self.grid) * (self.capacitance / 100 if self.capacitance > 0 else 1)
        self.magnetism += np.mean(self.grid)
        self.dielectricity = max(0.1, 1 / (1 + abs(change) if abs(change) > 0 else 1e-9))
        self.permittivity = 1.0 - self.dielectricity
        self.energy = np.sum(self.grid) / (self.resistance if self.resistance > 0 else 1e-9)
        self._synthesize_identity()

    def _synthesize_identity(self):
        if self.memory_patterns:
            self.identity_wave = (self.energy / len(self.memory_patterns)) * self.dielectricity

    def display(self):
        context_str = "\n".join([f" '{k}': {v}" for k, v in self.context_embeddings.items()])
        return (f"FLUXUS: {self.energy:.2f} | IDENTITAS: {self.identity_wave:.2f} | MEMORIA: {len(self.memory_patterns)}\n"
                f"SEXTET: R={self.resistance:.2e}, C={self.capacitance:.2f}, M={self.magnetism:.2f}, P={self.permeability:.2f}, Pt={self.permittivity:.2f}, D={self.dielectricity:.2f}\n"
                f"CONTEXTUS:\n{context_str}")

# FerrocellSensor Class (from your ferrocella code, mock mode)
class FerrocellSensor:
    def __init__(self, mock_mode=True, resolution=(128, 128)):
        self.mock_mode = mock_mode
        self.resolution = resolution
        self.sextet = {'A': {'resistance': 1e-9, 'capacitance': 0.0, 'permeability': 1.0, 'magnetism': 0.0, 'permittivity': 1.0, 'dielectricity': 0.0, 'laser': 0.0},
                       'B': {'resistance': 1e-9, 'capacitance': 0.0, 'permeability': 1.0, 'magnetism': 0.0, 'permittivity': 1.0, 'dielectricity': 0.0, 'laser': 0.0}}
        self.visual_grid = np.random.uniform(0, 0.15, resolution)

    def get_sextet(self, side='A'):
        return self.sextet[side].copy()

    def get_visual_grid(self, paths=['A-B'], grid_size=1000):
        return self.visual_grid.copy()

    def set_laser(self, side, pulse):
        self.sextet[side]['laser'] = pulse

# Initialize simulation
flux_core = FluxCore()
sensor = FerrocellSensor()

# Flask and SocketIO
app = Flask(__name__)
socketio = SocketIO(app)

# Nostr DM Queue for real-time updates
dm_queue = asyncio.Queue()

async def nostr_listener():
    subscription_id = private_key.public_key.hex()[:16]
    filter = {'kinds': [4], 'authors': [private_key.public_key.hex()]}
    for relay in relays:
        try:
            async with websockets.connect(relay) as ws:
                await ws.send(json.dumps(['REQ', subscription_id, filter]))
                while True:
                    response = await ws.recv()
                    data = json.loads(response)
                    if data[0] == 'EVENT':
                        event = Event.from_json(data[2])
                        decrypted = EncryptedDirectMessage.from_event(event, private_key)
                        dm = {'sender': decrypted.sender_pubkey, 'message': decrypted.cleartext_content}
                        await dm_queue.put(dm)
        except Exception as e:
            print(f"Error with {relay}: {e}")

# Background tasks
def run_nostr_background_task():
    asyncio.run(nostr_listener())

def run_dm_update_task():
    asyncio.run(dm_update_task())

def simulation_update_task():
    while True:
        flux_core.converge()
        # Generate base64 image for grid
        grid = flux_core.grid
        min_val, max_val = np.min(grid), np.max(grid)
        if max_val > min_val:
            grid = (grid - min_val) / (max_val - min_val)
        pixels = (grid * 255).astype(np.uint8)
        _, encoded_img = cv2.imencode('.png', pixels)
        base64_img = base64.b64encode(encoded_img).decode('utf-8')
        sextet = sensor.get_sextet('A')  # Example for side A
        socketio.emit('simulation_update', {'grid': base64_img, 'sextet': sextet})
        time.sleep(0.5)

@app.route('/')
def index():
    return render_template('index.html', npub=private_key.public_key.bech32())

@app.route('/send_dm', methods=['POST'])
async def send_dm():
    recipient_npub = request.form['recipient_npub']
    message = request.form['message']
    dm = EncryptedDirectMessage(
        privkey=private_key,
        recipient_pubkey=recipient_npub,
        cleartext_content=message
    )
    event = dm.to_event()
    event.sign(private_key.hex())
    amp = len(message)  # Perturb amp based on message length
    flux_core.perturb(random.randint(0, flux_core.size - 1), random.randint(0, flux_core.size - 1), amp)
    for relay in relays:
        async with websockets.connect(relay) as ws:
            await ws.send(json.dumps(['EVENT', event.to_json()]))
    return 'DM sent'

@socketio.on('connect')
def handle_connect():
    print('Client connected')

async def dm_update_task():
    while True:
        dm = await dm_queue.get()
        amp = len(dm['message'])  # Perturb on receive
        flux_core.perturb(random.randint(0, flux_core.size - 1), random.randint(0, flux_core.size - 1), amp)
        socketio.emit('dm_received', dm)

if __name__ == '__main__':
    socketio.start_background_task(run_nostr_background_task)
    socketio.start_background_task(simulation_update_task)
    socketio.start_background_task(run_dm_update_task)
    socketio.run(app, debug=True, port=5001)
