# A clean version of generate_keys.py
from pynostr.key import PrivateKey

# 1. Generate ONE key pair and store it
private_key = PrivateKey()
public_key = private_key.public_key

# 2. Print it to the screen
print(f"Nostr public key: {public_key.bech32()}")
print(f"Nostr private key (KEEP SECRET): {private_key.bech32()}")

# 3. Save that SAME key pair to a file
with open("nostr_keys.txt", "w") as f:
    f.write(f"Public key: {public_key.bech32()}\n")
    f.write(f"Private key: {private_key.bech32()}\n")
print("\nKeys also saved to nostr_keys.txt")
