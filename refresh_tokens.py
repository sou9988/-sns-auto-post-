"""Threads・Instagram のアクセストークン（有効期限60日）を延長して、GitHub の Secrets を更新する"""
import base64
import os
import sys

import requests
from nacl import encoding, public

REFRESH = {
    "THREADS_ACCESS_TOKEN": ("https://graph.threads.net/refresh_access_token", "th_refresh_token"),
    "IG_ACCESS_TOKEN": ("https://graph.instagram.com/refresh_access_token", "ig_refresh_token"),
}


def update_secret(name: str, value: str) -> None:
    repo, pat = os.environ["GITHUB_REPOSITORY"], os.environ["GH_PAT"]
    headers = {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"}
    key = requests.get(f"https://api.github.com/repos/{repo}/actions/secrets/public-key", headers=headers).json()
    box = public.SealedBox(public.PublicKey(key["key"].encode(), encoding.Base64Encoder()))
    encrypted = base64.b64encode(box.encrypt(value.encode())).decode()
    r = requests.put(f"https://api.github.com/repos/{repo}/actions/secrets/{name}", headers=headers,
                     json={"encrypted_value": encrypted, "key_id": key["key_id"]})
    r.raise_for_status()


def main() -> None:
    failed = False
    for name, (url, grant) in REFRESH.items():
        token = os.environ.get(name)
        if not token:
            continue
        r = requests.get(url, params={"grant_type": grant, "access_token": token}, timeout=30)
        if not r.ok:
            print(f"{name}: 延長に失敗 {r.status_code} {r.text[:300]}")
            failed = True
            continue
        update_secret(name, r.json()["access_token"])
        print(f"{name}: 延長しました（あと約{r.json().get('expires_in', 0) // 86400}日）")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
