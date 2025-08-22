# Final version of nuntius_cli.py
import os
import asyncio
import json
import websockets
import time
from datetime import datetime
from dotenv import load_dotenv
from pynostr.key import PrivateKey, PublicKey
from pynostr.encrypted_dm import EncryptedDirectMessage
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# --- GLOBAL SETUP ---
console = Console()
RELAYS = ['wss://relay.damus.io', 'wss://nostr.wine', 'wss://nos.lol']
load_dotenv()
display_sextet = False
command_log = []

# --- FUNCTIONS ---
async def find_server_on_nostr():
    """Finds the server's public key by querying for its beacon event."""
    console.print("[yellow]Searching for Latium server beacon on the Nostr network...[/yellow]")
    beacon_filter = {"kinds": [30078], "#d": ["latium_server_identity_v1"], "limit": 1}
    subscription_id = os.urandom(8).hex()
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
            continue
    console.print(f"[red]Could not automatically find server beacon on checked relays.[/red]")
    return None

def setup_identity():
    """Checks for a .env file and creates one with a new Nostr key if it doesn't exist."""
    if os.path.exists('.env') and os.environ.get("NUNTIUS_NSEC"):
        try:
            return PrivateKey.from_nsec(os.environ.get("NUNTIUS_NSEC"))
        except Exception:
            pass
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

# --- ASYNC LISTENERS ---
async def command_log_listener():
    log_filter = {"kinds": [30078], "authors": [SERVER_PUBKEY_HEX], "#d": ["nuntius_command_log_v1"]}
    subscription_id = os.urandom(8).hex()
    while True:
        try:
            async with websockets.connect(RELAYS[0]) as ws:
                await ws.send(json.dumps(['REQ', subscription_id, log_filter]))
                while True:
                    response = await ws.recv()
                    data = json.loads(response)
                    if data[0] == 'EVENT':
                        new_log = json.loads(data[2]['content'])
                        if len(new_log) > 0 and (len(command_log) == 0 or new_log[-1]['timestamp'] > command_log[-1]['timestamp']):
                            command_log.clear()
                            command_log.extend(new_log)
                            latest_entry = command_log[-1]
                            dt_object = datetime.fromtimestamp(latest_entry['timestamp'])
                            time_str = dt_object.strftime('%H:%M:%S')
                            console.print(f"\n[dim]{time_str}[/dim] [cyan]{latest_entry['sender']}[/cyan]: {latest_entry['command']}")
        except Exception:
            await asyncio.sleep(10)

async def sextet_listener():
    """Listens for the sextet data stream ONLY when toggled on."""
    state_filter = {"kinds": [30078], "authors": [SERVER_PUBKEY_HEX], "#d": ["nuntius_sextet_state_v1"]}
    subscription_id = os.urandom(8).hex()
    while True:
        if display_sextet:
            try:
                async with websockets.connect(RELAYS[1]) as ws:
                    await ws.send(json.dumps(['REQ', subscription_id, state_filter]))
                    while display_sextet:
                        response = await ws.recv()
                        data = json.loads(response)
                        if data[0] == 'EVENT':
                            content = json.loads(data[2]['content'])
                            sextet = content.get('sextet', {})
                            panel_content = ""
                            for key, value in sextet.items():
                                panel_content += f"[bold cyan]{key.capitalize()}:[/bold cyan] {value:e}\n"
                            console.print(Panel(panel_content.strip(), title="[yellow]Live Sextet Data[/yellow]", border_style="dim yellow"))
            except Exception as e:
                console.print(f"[red]Sextet listener error: {e}[/red]")
        await asyncio.sleep(1)

# --- UI & COMMANDS ---
def generate_log_table() -> Table:
    """Generates a Rich Table from the current command log."""
    table = Table(title="AetherOS Command Log")
    table.add_column("Timestamp", style="dim", width=12)
    table.add_column("Sender", style="cyan")
    table.add_column("Command", style="white")
    for entry in reversed(command_log):
        dt_object = datetime.fromtimestamp(entry['timestamp'])
        time_str = dt_object.strftime('%H:%M:%S')
        table.add_row(time_str, entry['sender'], entry['command'])
    return table

async def send_command(command_str: str):
    """Formats and sends a command to the server as an encrypted DM."""
    try:
        command_json = json.dumps({"command": command_str})
        dm = EncryptedDirectMessage()
        dm.encrypt(MY_PRIVATE_KEY.hex(), recipient_pubkey=SERVER_PUBKEY_HEX, cleartext_content=command_json)
        event = dm.to_event()
        event.sign(MY_PRIVATE_KEY.hex())
        message = json.dumps(['EVENT', event.to_dict()])
        async with websockets.connect(RELAYS[1]) as ws:
            await ws.send(message)
            return True
    except Exception as e:
        console.print(f"[red]Error sending command: {e}[/red]")
        return False

# --- MAIN APPLICATION LOOP ---
async def main_loop():
    """The main user-facing application loop."""
    console.print(Panel("[bold green]Nuntius AetherOS Chat[/bold green]\nCommands you send will perturb the shared simulation. See https://ooda.wiki/wiki/Nuntius_(AetherOS) for list of commands.", border_style="green"))

    log_filter = {"kinds": [30078], "authors": [SERVER_PUBKEY_HEX], "#d": ["nuntius_command_log_v1"], "limit": 1}
    subscription_id = f"initial-log-{os.urandom(4).hex()}"
    try:
        async with websockets.connect(RELAYS[2], open_timeout=5) as ws:
            await ws.send(json.dumps(['REQ', subscription_id, log_filter]))
            response = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(response)
            if data[0] == 'EVENT':
                initial_log = json.loads(data[2]['content'])
                command_log.extend(initial_log)
                console.print(generate_log_table())
    except Exception as e:
        console.print(f"[yellow]Could not fetch initial command log: {e}[/yellow]")

    log_listener_task = asyncio.create_task(command_log_listener())
    sextet_listener_task = asyncio.create_task(sextet_listener())

    while True:
        try:
            cmd = await asyncio.to_thread(input, f"aetheros ({MY_PRIVATE_KEY.public_key.bech32()[:10]}...)> ")
            if cmd.upper() == 'OSTENDO':
                console.print(generate_log_table())
                continue
            
            global display_sextet
            if cmd.upper() == 'LEGERE':
                display_sextet = not display_sextet
                status = "ON" if display_sextet else "OFF"
                console.print(f"[bold yellow]Live sextet display is now {status}[/bold yellow]")
                continue

            if cmd.lower() in ["exit", "quit", "vale"]:
                break
            if cmd.strip():
                await send_command(cmd.strip())
        except (KeyboardInterrupt, EOFError):
            break
    
    log_listener_task.cancel()
    sextet_listener_task.cancel()
    console.print("[yellow]Disconnecting... Vale.[/yellow]")

if __name__ == "__main__":
    if not os.path.exists('config.example.json'):
        with open('config.example.json', 'w') as f:
            json.dump({"server_npub": "CLIENT_WILL_FIND_THIS_AUTOMATICALLY"}, f)
    asyncio.run(main_loop())
