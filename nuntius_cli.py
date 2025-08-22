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

console = Console()
RELAYS = ['wss://relay.damus.io', 'wss://nostr.wine', 'wss://nos.lol']

async def find_server_on_nostr():
    """Finds the server's public key by querying for its beacon event."""
    console.print("[yellow]Searching for Latium server beacon on the Nostr network...[/yellow]")
    # This filter looks for the unique beacon event
    beacon_filter = {"kinds": [30078], "#d": ["latium_server_identity_v1"], "limit": 1}
    subscription_id = os.urandom(8).hex()
    
    try:
        async with websockets.connect(RELAYS[0], open_timeout=10) as ws:
            await ws.send(json.dumps(['REQ', subscription_id, beacon_filter]))
            # Wait up to 10 seconds for a response from the relay
            response = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(response)
            if data[0] == 'EVENT':
                content = json.loads(data[2]['content'])
                server_npub = content.get('npub')
                if server_npub:
                    console.print(f"[green]Server found! Address: {server_npub[:15]}...[/green]")
                    # Save the found npub to the config file
                    with open('config.json', 'w') as f:
                        json.dump({"server_npub": server_npub}, f)
                    return server_npub
    except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
        console.print(f"[red]Could not connect to relay or timed out waiting for beacon.[/red]")
        return None
    except Exception as e:
        console.print(f"[red]Could not automatically find server: {e}[/red]")
        return None
    return None

def setup_identity():
    """Checks for a .env file and creates one with a new Nostr key if it doesn't exist."""
    if os.path.exists('.env') and os.environ.get("NUNTIUS_NSEC"):
        try:
            # If the file exists and the key is valid, we're good.
            return PrivateKey.from_nsec(os.environ.get("NUNTIUS_NSEC"))
        except Exception as e:
            console.print(f"[red]Error loading key from .env: {e}. A new key will be generated.[/red]")

    console.print(Panel("[yellow]First-time setup:[/yellow] No personal Nostr key found.", subtitle="Generating a new identity..."))
    
    private_key = PrivateKey()
    nsec = private_key.bech32()
    npub = private_key.public_key.bech32()

    with open('.env', 'w') as f:
        f.write(f"NUNTIUS_NSEC='{nsec}'\n")
    
    console.print(f"[green]New identity created and saved to `.env` file.[/green]")
    console.print(f"Your new public key is: [bold cyan]{npub}[/bold cyan]")
    
    # Load the newly created variable into the environment for the current session
    load_dotenv()
    return private_key

# --- MAIN ENTRY POINT ---
async def main():
    """Initializes config and runs the main application loop."""
    load_dotenv()
    
    # Automatically set up user's personal identity
    global MY_PRIVATE_KEY
    MY_PRIVATE_KEY = setup_identity()

    # Load server config from config.json or find it on the network
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        SERVER_NPUB = config.get("server_npub")
        if not SERVER_NPUB or "PASTE" in SERVER_NPUB:
            raise FileNotFoundError # Trigger discovery
    except FileNotFoundError:
        SERVER_NPUB = await find_server_on_nostr()
        if not SERVER_NPUB:
            console.print("Error: Could not discover server. Please ensure the Latium server is running.")
            return

    global SERVER_PUBKEY_HEX
    SERVER_PUBKEY_HEX = PublicKey.from_npub(SERVER_NPUB).hex()

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

# --- CORE FUNCTIONS ---
async def state_listener():
    """Listens for the server's public state broadcasts."""
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
            console.print(f"[red]State listener error: {e}. Reconnecting in 10s...[/red]")
            await asyncio.sleep(10)

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
            console.print(f"[green]>>> Command sent:[/green] {command_str}")
            return True
    except Exception as e:
        console.print(f"[red]Error sending command: {e}[/red]")
        return False

if __name__ == "__main__":
    if not os.path.exists('config.example.json'):
        with open('config.example.json', 'w') as f:
            json.dump({"server_npub": "CLIENT_WILL_FIND_THIS_AUTOMATICALLY"}, f)
            
    asyncio.run(main())
