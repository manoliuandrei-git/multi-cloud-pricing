"""
Run this script once to split your Oracle wallet zip into Railway-safe chunks.

Usage:
    python split_wallet.py Wallet_yourdb.zip

It will print the environment variables to set in Railway.
"""
import base64
import sys

CHUNK_SIZE = 30_000  # safely under Railway's 32,768-char limit

def split_wallet(zip_path: str):
    with open(zip_path, "rb") as f:
        raw = f.read()

    b64 = base64.b64encode(raw).decode("ascii")
    total = len(b64)
    chunks = [b64[i:i+CHUNK_SIZE] for i in range(0, total, CHUNK_SIZE)]

    print(f"\n✅  Wallet: {zip_path}  ({total} base64 chars → {len(chunks)} chunk(s))\n")
    print("Add these variables in Railway → service → Variables:\n")
    for idx, chunk in enumerate(chunks, start=1):
        print(f"ATP_WALLET_B64_{idx}={chunk}\n")

    if len(chunks) == 1:
        print("(Only 1 chunk — you can also just use ATP_WALLET_B64 directly if it fits.)")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python split_wallet.py <path-to-wallet.zip>")
        sys.exit(1)
    split_wallet(sys.argv[1])
