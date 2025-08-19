import os
import asyncio
import json
import websockets
import secrets
import shlex
from pynostr.event import Event
from pynostr.key import PrivateKey
from pynostr.encrypted_dm import EncryptedDirectMessage
from bech32 import bech32_decode, convertbits
from rich.console import Console

console = Console()

# --- Configuration ---
RELAYS = ['wss://relay.damus.io', 'wss://nos.lol', 'wss://nostr.wine']
CHAT_KIND = 4  # Kind 4 for Encrypted DMs

# --- State ---
timeline = []

# --- Key Loading and Validation ---
def load_private_key():
    """Loads and validates the nsec private key from environment variables."""
    private_key_nsec = os.environ.get('NUNTIUS_NSEC', '').strip()
    if not private_key_nsec:
        console.print("[red]Error: NUNTIUS_NSEC not set in environment. Please set a valid 63-character nsec key.[/red]")
        return None
    try:
        hrp, data = bech32_decode(private_key_nsec)
        if not data or hrp != 'nsec':
            raise ValueError("Invalid nsec prefix or data.")
        privkey_bytes = bytes(convertbits(data, 5, 8, False))
        return PrivateKey(privkey_bytes)
    except Exception as e:
        console.print(f"[red]Error: Failed to decode NUNTIUS_NSEC: {e}. Ensure it is a valid 63-character Bech32 string.[/red]")
        return None

# --- Nostr Communication ---
async def nostr_listener(private_key):
    """Listens for incoming and outgoing DMs and prints them."""
    my_pubkey = private_key.public_key.hex()
    subscription_id = secrets.token_hex(8)
    filters = [
        {'kinds': [CHAT_KIND], '#p': [my_pubkey], 'limit': 50},  # DMs sent TO me
        {'kinds': [CHAT_KIND], 'authors': [my_pubkey], 'limit': 50} # DMs sent BY me
    ]

    while True: # Main reconnection loop
        for relay in RELAYS:
            try:
                console.print(f"[dim]Connecting to {relay}...[/dim]")
                async with websockets.connect(relay) as ws:
                    console.print(f"[green]Connected to {relay}. Subscribing to DMs...[/green]")
                    await ws.send(json.dumps(['REQ', subscription_id, *filters]))
                    while True:
                        response = await ws.recv()
                        data = json.loads(response)
                        if data[0] == 'EVENT':
                            event = Event.from_json(data[2])
                            try:
                                decrypted = EncryptedDirectMessage.from_event(event, private_key)
                                message_text = f"[cyan]{decrypted.sender_pubkey[:8]}...[/cyan]: {decrypted.cleartext_content}"
                                timeline.append(message_text)
                                console.print(message_text)
                            except Exception as e:
                                console.print(f"[red]Error decrypting event: {e}[/red]")
            except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError) as e:
                console.print(f"[yellow]Connection to {relay} lost: {e}. Will retry...[/yellow]")
            except Exception as e:
                console.print(f"[red]An error occurred with {relay}: {e}[/red]")
        
        console.print(f"[yellow]Finished trying all relays. Waiting 10 seconds to reconnect...[/yellow]")
        await asyncio.sleep(10)

async def send_message(private_key, recipient_pubkey, message):
    """Encrypts and sends a message to a recipient via all relays."""
    try:
        dm = EncryptedDirectMessage(
            privkey=private_key,
            recipient_pubkey=recipient_pubkey,
            cleartext_content=message
        )
        event = dm.to_event()
        event.sign(private_key.hex())
        
        message_json = json.dumps(['EVENT', event.to_json()])
        
        # Send to all relays in parallel
        tasks = [asyncio.create_task(publish_to_relay(relay, message_json)) for relay in RELAYS]
        results = await asyncio.gather(*tasks)

        if any(results):
             console.print(f"[green]Message sent to {recipient_pubkey[:8]}...: '{message}'[/green]")
        else:
             console.print(f"[red]Failed to send message to any relay.[/red]")

    except Exception as e:
        console.print(f"[red]Error creating message: {e}[/red]")

async def publish_to_relay(relay, message_json):
    """Connects to a single relay and publishes a message."""
    try:
        async with websockets.connect(relay, open_timeout=5) as ws:
            await ws.send(message_json)
            return True
    except Exception as e:
        console.print(f"[dim]Failed to send to {relay}: {e}[/dim]")
        return False

# --- Main Application Logic ---
async def main():
    """Initializes the application, starts the listener, and handles user input."""
    private_key = load_private_key()
    if not private_key:
        return

    console.print(f"[bold green]Welcome to Nuntius CLI![/bold green]")
    console.print(f"Logged in with npub: [bold yellow]{private_key.public_key.bech32()}[/bold yellow]")

    # Start the listener as a background task
    listener_task = asyncio.create_task(nostr_listener(private_key))

    username = None
    while True:
        try:
            # Run the blocking input in a separate thread to not freeze the event loop
            raw_cmd = await asyncio.to_thread(console.input, "nuntius> ")
            parts = shlex.split(raw_cmd)
            if not parts:
                continue
            
            command = parts[0].upper()

            if command == 'VALE':
                console.print("[bold yellow]Exiting...[/bold yellow]")
                listener_task.cancel()
                break
            
            elif command == 'CREO':
                if len(parts) == 2:
                    username = parts[1]
                    console.print(f"[yellow]Username set: {username}[/yellow]")
                else:
                    console.print("[red]Format: CREO 'your-username'[/red]")

            elif command == 'MITTERE':
                if len(parts) == 3:
                    if not username:
                        console.print("[red]Set a username first with: CREO 'your-username'[/red]")
                        continue
                    recipient_npub, message = parts[1], parts[2]
                    full_message = f"{username}: {message}"
                    await send_message(private_key, recipient_npub, full_message)
                else:
                    console.print("[red]Format: MITTERE 'recipient_npub' 'your message'[/red]")

            elif command == 'LEGERE':
                console.print("\n[bold blue]--- Timeline ---[/bold blue]")
                for msg in timeline:
                    console.print(msg)
                console.print("[bold blue]----------------[/bold blue]\n")
            
            else:
                console.print("[red]Invalid command. Use: CREO, MITTERE, LEGERE, VALE[/red]")

        except Exception as e:
            console.print(f"[bold red]An error occurred in the main loop: {e}[/bold red]")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Exiting Nuntius.[/bold yellow]")
