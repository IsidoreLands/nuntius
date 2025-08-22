# Final version of nuntius_cli.py
import os
import asyncio
import json
import websockets
from dotenv import load_dotenv
from pynostr.key import PrivateKey, PublicKey
from pynostr.encrypted_dm import EncryptedDirectMessage
from rich.console import Console
from rich.panel import Panel

# --- GLOBAL SETUP ---
console = Console()
RELAYS = ['wss://relay.damus.io', 'wss://nostr.wine', 'wss://nos.lol']
load_dotenv()

# --- FUNCTIONS ---
async def find_server_on_nostr():
    """Finds the server's public key by querying for its beacon event."""
    console.print("[yellow]Searching for Latium server beacon on the Nostr network...[/yellow]")
    beacon_filter = {"kinds": [30078], "#d": ["latium_server_identity_v1"], "limit": 1}
    subscription_id = os.urandom(8).hex()
    
    # NEW: Try multiple relays to be more robust
    for relay in RELAYS:
        try:
            console.print(f"[dim]Checking relay {relay}...[/dim]")
            async with websockets.connect(relay, open_timeout=5) as ws:
                await ws.send(json.dumps(['REQ', subscription_id, beacon_filter]))
                response = await asyncio.wait_for(ws.recv(), timeout=5)
                data = json.loads(response)
                if data[0] == 'EVENT':
                    content = json.loads(data[2]['content'])
                    server_npub = content.get('npub')
                    if server_npub:
                        console.print(f"[green]Server found! Address: {server_npub[:15]}...[/green]")
                        with open('config.json', 'w') as f:
                            json.dump({"server_npub": server_npub}, f)
                        return server_npub
        except Exception:
            # Try the next relay if one fails
            continue
            
    console.print(f"[red]Could not automatically find server beacon on checked relays.[/red]")
    return None

def setup_identity():
    """Checks for a .env file and creates one with a new Nostr key if it doesn't exist."""
    if os.path.exists('.env') and os.environ.get("NUNTIUS_NSEC"):
        try:
            return PrivateKey.from_nsec(os.environ.get("NUNTIUS_NSEC"))
        except Exception:
            pass # Fall through to generate a new key if the existing one is invalid
    
    console.print(Panel("[yellow]First-time setup:[/yellow] No personal Nostr key found.", subtitle="Generating a new identity..."))
    private_key = PrivateKey()
    with open('.env', 'w') as f:
        f.write(f"NUNTIUS_NSEC='{private_key.bech32()}'\n")
    console.print(f"[green]New identity created and saved to `.env` file.[/green]")
    console.print(f"Your new public key is: [bold cyan]{private_key.public_key.bech32()}[/bold cyan]")
    load_dotenv()
    return private_key

def load_configuration():
    """Loads server npub from config or discovers it, then returns all config."""
    my_private_key = setup_identity()
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        server_npub = config.get("server_npub")
        if not server_npub or "PASTE" in server_npub:
            raise FileNotFoundError
    except FileNotFoundError:
        server_npub = asyncio.run(find_server_on_nostr())
        if not server_npub:
            console.print("Error: Could not discover server. Please ensure the Latium server is running.")
            exit(1)
            
    server_pubkey_hex = PublicKey.from_npub(server_npub).hex()
    return my_private_key, server_npub, server_pubkey_hex

# --- GLOBAL CONFIGURATION ---
MY_PRIVATE_KEY, SERVER_NPUB, SERVER_PUBKEY_HEX = load_configuration()

# --- CORE ASYNC FUNCTIONS ---
async def state_listener():
    state_filter = {"kinds": [1], "authors": [SERVER_PUBKEY_HEX], "#t": ["ferrocella-v1"]}
    subscription_id = os.urandom(8).hex()
    while True:
        try:
            async with websockets.connect(RELAYS[0]) as ws:
                console.print(f"[dim]Subscribed to state updates from Latium server ({SERVER_NPUB[:10]}...) via {RELAYS[0]}...[/dim]")
                await ws.send(json.dumps(['REQ', subscription_id, state_filter]))
                while True:
                    response = await ws.recv()
                    data = json.loads(response)
                    if data[0] == 'EVENT':
                        content = json.loads(data[2]['content'])
                        sextet = content.get('sextet', {})
                        panel_content = ""
                        for key, value in sextet.items():
                            panel_content += f"[bold cyan]{key.capitalize()}:[/bold cyan] {value:e}\n"
                        console.print(Panel(panel_content.strip(), title="[yellow]Latium State Update[/yellow]", border_style="dim blue"))
        except Exception as e:
            console.print(f"[red]State listener error: {e}. Reconnecting...[/red]")
            await asyncio.sleep(10)

async def send_command(command_str: str):
    try:
        command_json = json.dumps({"command": command_str})
        dm = EncryptedDirectMessage()
        dm.encrypt(MY_PRIVATE_KEY.hex(), recipient_pubkey=SERVER_PUBKEY_HEX, cleartext_content=command_json)
        event = dm.to_event()
        event.sign(MY_PRIVATE_KEY.hex())
        message = json.dumps(['EVENT', event.to_dict()])
        async with websockets.connect(RELAYS[1]) as ws:
            await ws.send(message)
            console.print(f"[green]>>> Command sent:[/green] {command_str}")
            return True
    except Exception as e:
        console.print(f"[red]Error sending command: {e}[/red]")
        return False

async def main_loop():
    """The main user-facing application loop."""
    console.print(Panel("[bold green]Nuntius AetherOS Client[/bold green]\nEnter AetherOS commands to send to the Latium server.", border_style="green"))
    listener_task = asyncio.create_task(state_listener())
    while True:
        try:
            cmd = await asyncio.to_thread(input, "aetheros> ")
            if cmd.lower() in ["exit", "quit", "vale"]:
                break
            if cmd.strip():
                await send_command(cmd.strip())
        except (KeyboardInterrupt, EOFError):
            break
    listener_task.cancel()
    console.print("[yellow]Disconnecting... Vale.[/yellow]")

if __name__ == "__main__":
    if not os.path.exists('config.example.json'):
        with open('config.example.json', 'w') as f:
            json.dump({"server_npub": "CLIENT_WILL_FIND_THIS_AUTOMATICALLY"}, f)
    asyncio.run(main_loop())
