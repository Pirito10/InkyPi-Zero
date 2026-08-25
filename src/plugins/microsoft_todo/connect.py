#!/usr/bin/env python3
"""One-time setup for the microsoft_todo plugin: connects a Microsoft account
via the OAuth device code flow and saves the resulting token cache to disk.

Run this once per device (locally to test, then again via SSH on the real Pi
once it's time to connect the recipient's own account). Needs the project's
venv active with PYTHONPATH set to src/ (see install/dev.sh) so `msal` and
the plugins/utils packages are importable.
"""
import sys

from plugins.microsoft_todo.microsoft_todo import (
    SCOPES, TOKEN_CACHE_PATH,
    load_token_cache, save_token_cache, get_msal_app,
)


def main():
    cache = load_token_cache()
    app = get_msal_app(cache)

    accounts = app.get_accounts()
    if accounts:
        print(f"Ya hay una cuenta conectada: {accounts[0].get('username')}")
        answer = input("¿Conectar una cuenta distinta? Esto sustituye la actual. [s/N] ")
        if answer.strip().lower() != "s":
            return

    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        print("No se pudo iniciar la conexión:", flow.get("error_description"))
        sys.exit(1)

    print()
    print(flow["message"])
    print()

    result = app.acquire_token_by_device_flow(flow)  # bloquea hasta que se complete o caduque

    if "access_token" not in result:
        print("No se pudo conectar la cuenta:", result.get("error_description"))
        sys.exit(1)

    save_token_cache(cache)
    username = result.get("id_token_claims", {}).get("preferred_username", "")
    print(f"Cuenta conectada correctamente: {username}")
    print(f"Token guardado en: {TOKEN_CACHE_PATH}")


if __name__ == "__main__":
    main()
