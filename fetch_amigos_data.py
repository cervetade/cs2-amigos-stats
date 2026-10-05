"""
Baja el historial de partidas de un grupo de amigos en FACEIT y cruza sus
match_id para encontrar en cuales jugaron juntos (mismo equipo). Se puede
correr a mano, pero tambien es el primer paso del pipeline automatico
semanal (.github/workflows/refresh.yml) -- por eso es resumible: cada
corrida solo baja lo nuevo desde la ultima vez.

COMO CORRERLO (necesitas tu API key de FACEIT -- la misma que ya usaste
para cs2-sudamerica-analytics si tenes una, o sacate una gratis en
https://developers.faceit.com/ -- "Server-side API key"):

    export FACEIT_API_KEY="tu-key-aca"          (Windows PowerShell: $env:FACEIT_API_KEY="tu-key-aca")
    python fetch_amigos_data.py

Si se corta a mitad de camino (corte de luz, se cierra la terminal, etc.),
correlo de nuevo: no vuelve a pedir el historial de un jugador si ya lo
tiene guardado en data/raw/amigos_history.csv, y no vuelve a pedir detalle
de una partida que ya este en data/raw/amigos_matches.csv.

QUE HACE, PASO A PASO:
  1. Resuelve cada nickname de FRIENDS (abajo) a su player_id de FACEIT.
  2. Baja el historial COMPLETO de partidas de cada uno (paginando).
  3. Cruza esos historiales: encuentra los match_id que aparecen en el
     historial de 2 o mas amigos -- esas son las partidas "compartidas".
  4. Para cada partida compartida (y SOLO esas, no todo el historial),
     pide el detalle + las stats por jugador, para saber en que equipo
     jugo cada amigo y si ese equipo gano.
  5. Guarda todo en CSVs -- build_familia_dashboard.py arma el
     dashboard.html/index.html a partir de esos CSVs.

Nota: esto NO cuenta partidas donde dos amigos se enfrentaron como
rivales -- por ahora solo interesa "jugamos juntos" (mismo team_id en la
misma partida). Si despues quieren sumar el caso de rivales, es un
cambio chico sobre el mismo cruce de datos.
"""

import csv
import os
import sys
import time
from pathlib import Path

import requests

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------

API_KEY = os.environ.get("FACEIT_API_KEY")
if not API_KEY:
    sys.exit(
        "Falta la API key. Seteala como variable de entorno FACEIT_API_KEY antes de correr esto "
        "(mismo paso que para cs2-sudamerica-analytics)."
    )

BASE_URL = "https://open.faceit.com/data/v4"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}
GAME_ID = "cs2"

# Los 12 nicknames que pasaste (sacados de los links de faceit.com/en/players/...).
# Si alguno esta mal escrito o cambio de nick, el script lo va a avisar al
# resolverlo (paso 1) -- se puede corregir esta lista y volver a correr.
FRIENDS_NICKNAMES = [
    "agb-_-",
    "ELGERENTE",
    "Fakabot",
    "frantarasco",
    "gordotiverso",
    "hhmero",
    "monzooo",
    "n0xinho",
    "polski-",
    "santibest10",
    "santutu_",
    "flacotiverso",
]

HISTORY_PAGE_SIZE = 100  # maximo permitido por la API para /history
# Techo de seguridad para no quedar en un loop infinito si algun jugador
# tiene un historial gigante -- 3000 partidas por persona ya es MUCHO mas
# de lo que cualquiera de ustedes probablemente jugo, asi que en la
# practica esto no debería recortar nada real.
MAX_OFFSET_SAFETY = 3000
REQUEST_DELAY_SECONDS = 0.6

RAW_DIR = Path(__file__).parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# ----------------------------------------------------------------------------
# HELPERS (mismo patron de reintento que el proyecto cs2-sudamerica-analytics)
# ----------------------------------------------------------------------------


def api_get(path, params=None, max_retries=5):
    url = f"{BASE_URL}{path}"
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=HEADERS, params=params or {}, timeout=20)
        except requests.exceptions.RequestException as exc:
            wait = min(2 ** attempt, 30)
            print(f"  [red] {exc.__class__.__name__}, espero {wait}s y reintento... ({path})")
            time.sleep(wait)
            continue
        if resp.status_code == 404:
            return None
        if resp.status_code == 429:
            wait = min(2 ** attempt, 30)
            print(f"  [429 rate limit] esperando {wait}s y reintentando... ({path})")
            time.sleep(wait)
            continue
        if resp.status_code >= 500:
            wait = min(2 ** attempt, 30)
            print(f"  [{resp.status_code} server] esperando {wait}s y reintentando... ({path})")
            time.sleep(wait)
            continue
        if resp.status_code >= 400:
            print(f"  [ERROR {resp.status_code}] {url} params={params}")
            print(f"  body: {resp.text[:300]}")
            return None
        time.sleep(REQUEST_DELAY_SECONDS)
        return resp.json()
    print(f"  [FALLO tras {max_retries} intentos] {url}")
    return None


def resolve_player(nickname):
    """nickname -> dict con player_id, country, elo -- o None si no se encontro."""
    data = api_get("/players", params={"nickname": nickname, "game": GAME_ID})
    if not data:
        return None
    games = data.get("games", {}) or {}
    cs2 = games.get(GAME_ID, {}) or {}
    return {
        "nickname": data.get("nickname"),
        "player_id": data.get("player_id"),
        "country": data.get("country"),
        "faceit_elo": cs2.get("faceit_elo"),
    }


def get_player_history_page(player_id, offset):
    return api_get(
        f"/players/{player_id}/history",
        params={"game": GAME_ID, "offset": offset, "limit": HISTORY_PAGE_SIZE},
    )


def get_match_stats(match_id):
    return api_get(f"/matches/{match_id}/stats")


def get_match_details(match_id):
    return api_get(f"/matches/{match_id}")


def read_csv_rows(name):
    path = RAW_DIR / name
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(name, rows, fieldnames):
    path = RAW_DIR / name
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  guardado: {path} ({len(rows)} filas)")


def parse_rounds_total(score_str):
    if not score_str:
        return None
    for sep in ("/", "-", ":"):
        if sep in score_str:
            parts = [p.strip() for p in score_str.split(sep)]
            try:
                return sum(int(p) for p in parts)
            except ValueError:
                return None
    return None


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------


def main():
    print(f"== Amigos: {len(FRIENDS_NICKNAMES)} nicknames a resolver ==\n")

    # ------------------------------------------------------------------
    # Paso 0: nicknames -> player_id (se guarda para no volver a pedirlo).
    # ------------------------------------------------------------------
    existing_friends = {f["nickname"]: f for f in read_csv_rows("amigos_friends.csv")}
    friends = []
    any_missing = False
    for nick in FRIENDS_NICKNAMES:
        if nick in existing_friends:
            friends.append(existing_friends[nick])
            continue
        info = resolve_player(nick)
        if not info or not info.get("player_id"):
            print(f"  [OJO] no encontre a '{nick}' en FACEIT -- revisa que el nickname este bien escrito "
                  f"(mayusculas/minusculas no importan, pero el nickname exacto si). Lo salteo por ahora.")
            any_missing = True
            continue
        print(f"  {nick} -> player_id {info['player_id']} ({info['country']}, ELO {info['faceit_elo']})")
        friends.append(info)

    write_csv("amigos_friends.csv", friends, ["nickname", "player_id", "country", "faceit_elo"])
    if any_missing:
        print("\n  Corregi los nicknames que fallaron arriba y volve a correr el script -- los que si se")
        print("  resolvieron ya quedaron guardados, no se vuelven a pedir.\n")
    if len(friends) < 2:
        sys.exit("Necesito al menos 2 jugadores resueltos para poder cruzar partidas. Revisa los nicknames.")

    player_ids = {f["player_id"] for f in friends}
    nick_by_pid = {f["player_id"]: f["nickname"] for f in friends}

    # ------------------------------------------------------------------
    # Paso 1: historial completo de cada amigo (paginando).
    # ------------------------------------------------------------------
    print(f"\n== Paso 1: historial completo de {len(friends)} jugadores ==")
    existing_history = read_csv_rows("amigos_history.csv")
    existing_history_keys = {(h["player_id"], h["match_id"]) for h in existing_history}
    already_have_by_player = {}
    for h in existing_history:
        already_have_by_player[h["player_id"]] = already_have_by_player.get(h["player_id"], 0) + 1

    new_history_rows = []
    for i, f in enumerate(friends, 1):
        pid = f["player_id"]
        # Si ya hay historial guardado de este jugador, se pide desde lo mas
        # nuevo y se corta apenas aparece una partida que ya tenemos (FACEIT
        # devuelve el historial de la mas reciente a la mas vieja), asi cada
        # corrida solo baja lo nuevo en vez de saltearse al jugador entero.
        had_history = already_have_by_player.get(pid, 0) > 0
        offset = 0
        count = 0
        while offset < MAX_OFFSET_SAFETY:
            page = get_player_history_page(pid, offset)
            if not page:
                break
            items = page.get("items", [])
            if not items:
                break
            hit_known = False
            for m in items:
                match_id = m.get("match_id")
                if not match_id:
                    continue
                key = (pid, match_id)
                if key in existing_history_keys:
                    hit_known = True
                    continue
                existing_history_keys.add(key)
                new_history_rows.append({
                    "player_id": pid,
                    "match_id": match_id,
                    "finished_at": m.get("finished_at"),
                })
                count += 1
            if len(items) < HISTORY_PAGE_SIZE:
                break  # ultima pagina
            if had_history and hit_known:
                break  # de aca para atras ya lo tenemos todo
            offset += HISTORY_PAGE_SIZE
        print(f"  [{i}/{len(friends)}] {f['nickname']}: {count} partidas nuevas de historial")

    all_history = existing_history + new_history_rows
    write_csv("amigos_history.csv", all_history, ["player_id", "match_id", "finished_at"])

    # ------------------------------------------------------------------
    # Paso 2: cruzar -- match_id que aparecen en el historial de 2+ amigos.
    # ------------------------------------------------------------------
    print("\n== Paso 2: cruzando historiales ==")
    friends_by_match = {}
    for h in all_history:
        if h["player_id"] not in player_ids:
            continue
        friends_by_match.setdefault(h["match_id"], set()).add(h["player_id"])

    shared_match_ids = {mid: pids for mid, pids in friends_by_match.items() if len(pids) >= 2}
    print(f"  Partidas compartidas por 2 o mas amigos: {len(shared_match_ids)}")
    for size in range(2, len(friends) + 1):
        n = sum(1 for pids in shared_match_ids.values() if len(pids) == size)
        if n:
            print(f"    con exactamente {size} amigos presentes: {n} partidas")

    if not shared_match_ids:
        print("\n  No encontre ninguna partida compartida. Si esto no tiene sentido (seguro jugaron juntos),")
        print("  puede ser que el historial de FACEIT no llegue tan atras para alguno -- avisame y lo revisamos.")
        return

    # ------------------------------------------------------------------
    # Paso 3: detalle + stats SOLO de las partidas compartidas.
    # ------------------------------------------------------------------
    print(f"\n== Paso 3: detalle de {len(shared_match_ids)} partidas compartidas ==")
    existing_matches = read_csv_rows("amigos_matches.csv")
    existing_match_ids = {m["match_id"] for m in existing_matches}
    existing_stats = read_csv_rows("amigos_match_stats.csv")
    existing_stats_keys = {(s["match_id"], s["player_id"]) for s in existing_stats}

    new_matches_rows = []
    new_stats_rows = []
    to_fetch = sorted(mid for mid in shared_match_ids if mid not in existing_match_ids)
    print(f"  Ya tengo detalle de {len(existing_match_ids & set(shared_match_ids))}, faltan {len(to_fetch)}.")

    def save_progress():
        write_csv("amigos_matches.csv", existing_matches + new_matches_rows,
                  ["match_id", "competition_name", "started_at", "finished_at", "duration_minutes"])
        write_csv("amigos_match_stats.csv", existing_stats + new_stats_rows,
                  ["match_id", "map", "team_id", "player_id", "nickname", "kills", "deaths",
                   "assists", "headshots_percent", "winning_team_id", "team_won"])

    try:
        for i, match_id in enumerate(to_fetch, 1):
            if i % 10 == 0 or i == len(to_fetch):
                print(f"  [{i}/{len(to_fetch)}] {match_id}")
            details = get_match_details(match_id)
            stats = get_match_stats(match_id)

            if details:
                started_at = details.get("started_at")
                finished_at = details.get("finished_at")
                duration_minutes = round((finished_at - started_at) / 60, 1) if started_at and finished_at else None
                new_matches_rows.append({
                    "match_id": match_id,
                    "competition_name": details.get("competition_name"),
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "duration_minutes": duration_minutes,
                })

            if not stats:
                continue
            for round_data in stats.get("rounds", []):
                round_stats = round_data.get("round_stats", {})
                map_name = round_stats.get("Map")
                winning_team_id = round_stats.get("Winner")
                for team in round_data.get("teams", []):
                    team_id = team.get("team_id")
                    for player in team.get("players", []):
                        pid = player.get("player_id")
                        if pid not in player_ids:
                            continue  # solo nos importan las filas de nuestros amigos
                        key = (match_id, pid)
                        if key in existing_stats_keys:
                            continue
                        existing_stats_keys.add(key)
                        ps = player.get("player_stats", {})
                        new_stats_rows.append({
                            "match_id": match_id,
                            "map": map_name,
                            "team_id": team_id,
                            "player_id": pid,
                            "nickname": nick_by_pid.get(pid, player.get("nickname")),
                            "kills": ps.get("Kills"),
                            "deaths": ps.get("Deaths"),
                            "assists": ps.get("Assists"),
                            "headshots_percent": ps.get("Headshots %"),
                            "winning_team_id": winning_team_id,
                            "team_won": int(team_id == winning_team_id),
                        })
            if i % 100 == 0:
                print(f"  -- checkpoint: guardando progreso parcial ({i}/{len(to_fetch)}) --")
                save_progress()
    except KeyboardInterrupt:
        print("\n[interrumpido manualmente] guardando lo que se llego a bajar...")
    except Exception as exc:
        print(f"\n[error inesperado: {exc}] guardando lo que se llego a bajar antes de cortar...")
        save_progress()
        raise

    save_progress()
    print("\nListo. Con estos CSVs en data/raw/ ya se puede armar el dashboard de sinergias.")
    print("Si esto se corto antes de terminar, corre el mismo comando de nuevo -- retoma justo donde quedo.")


if __name__ == "__main__":
    main()
