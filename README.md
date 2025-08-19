# Nuntius
Terminal-to-terminal Nostr chat with 3D ferrocell visual (nuntius.ooda.wiki).

## Install
```bash
git clone https://github.com/IsidoreLands/nuntius
cd nuntius
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export NUNTIUS_NSEC=nsec1...  # Generate with generate_keys.py
python nuntius_cli.py
```
