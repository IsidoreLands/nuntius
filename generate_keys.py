from ecdsa import SigningKey, SECP256k1
import bech32
import secrets

# Generate private key
privkey = secrets.token_bytes(32)
sk = SigningKey.from_string(privkey, curve=SECP256k1)
pubkey = sk.verifying_key.to_string("compressed").hex()

# Encode to npub and nsec
pubkey_data = bech32.convertbits(bytes.fromhex(pubkey), 8, 5)
npub = bech32.bech32_encode('npub', pubkey_data)
privkey_data = bech32.convertbits(privkey, 8, 5)
nsec = bech32.bech32_encode('nsec', privkey_data)

print(f"Nostr public key: {npub}")
print(f"Nostr private key (KEEP SECRET): {nsec}")
