# La Familia — Estadísticas

Proyecto aparte de [`cs2-sudamerica-analytics`](https://github.com/cervetade/cs2-sudamerica-analytics)
(ese es el de portfolio; este es para el grupo de amigos). Cruza el
historial de FACEIT de 12 amigos para encontrar las partidas donde 2 o
más jugaron juntos (mismo equipo), y a partir de eso arma un dashboard
con sinergias del grupo:

- Con qué amigo tenés mejor/peor win rate cuando juegan juntos (el
  "mufa" y el "amuleto" del grupo).
- Rendimiento individual dentro de las partidas compartidas.
- Qué dúos y qué formaciones de 3, 4 o los 5 juntos son las más
  frecuentes, y cómo les va.
- Mapas y horarios favoritos del grupo.

Por ahora solo cuenta partidas donde jugaron de **compañeros de
equipo** (no cuando se enfrentaron como rivales).

## Ver el dashboard

**[cs2-amigos-stats.vercel.app](https://cs2-amigos-stats.vercel.app)** (se
actualiza solo todos los domingos con las partidas nuevas).

## Cómo correr el fetch de datos

1. Necesitás Python 3 y el paquete `requests` (`pip install -r requirements.txt`).
2. Conseguí una API key de FACEIT (server-side) en
   https://developers.faceit.com/ si no tenés una ya (es la misma que se
   usa en `cs2-sudamerica-analytics`, si guardaste esa).
3. Seteala como variable de entorno:

   ```
   # Windows PowerShell
   $env:FACEIT_API_KEY="tu-key-aca"

   # Windows cmd
   set FACEIT_API_KEY=tu-key-aca

   # Linux / macOS
   export FACEIT_API_KEY="tu-key-aca"
   ```

4. Corré:

   ```
   python fetch_amigos_data.py
   python build_familia_dashboard.py
   ```

5. Si el fetch se corta a mitad de camino, corré el mismo comando de
   nuevo — no vuelve a pedir lo que ya bajó (queda guardado en
   `data/raw/*.csv`).

Los nicknames del grupo están hardcodeados arriba del todo en
`fetch_amigos_data.py` (variable `FRIENDS_NICKNAMES`).

## Qué guarda

Todo en `data/raw/`:

- `amigos_friends.csv` — nickname, player_id, país, ELO de cada amigo.
- `amigos_history.csv` — historial completo (match_id) de cada uno.
- `amigos_matches.csv` — detalle (fecha, duración) de las partidas donde
  coincidieron 2+ amigos.
- `amigos_match_stats.csv` — stats de cada amigo en esas partidas
  compartidas (kills, deaths, headshot %, equipo, si ganó).

`build_familia_dashboard.py` lee esos CSV, calcula todas las métricas
(sinergias, formaciones, impacto neto, mapas, horarios) y escribe
`dashboard.html` / `index.html` con los datos embebidos — no hace falta
ninguna base de datos.

## Actualización automática

`.github/workflows/refresh.yml` corre el pipeline completo (fetch +
build) todos los domingos a las 03:00 UTC vía GitHub Actions, y
commitea los cambios de vuelta a `main` si hay partidas nuevas. Eso
dispara el redeploy automático de Vercel. También se puede disparar a
mano desde la pestaña "Actions" del repo (`workflow_dispatch`).

Para que funcione hace falta cargar `FACEIT_API_KEY` como secreto del
repositorio: Settings → Secrets and variables → Actions → New
repository secret.

## Metodología del "impacto neto" (el mufa / el amuleto)

Para cada amigo, y por cada compañero con el que jugó ≥3 partidas
juntos, se compara el win rate de ese compañero CON el amigo vs. SIN
él (usando el resto de su historial dentro del dataset). El promedio
de esos deltas, ponderado por partidas jugadas juntos, da el "impacto
neto" del amigo sobre el grupo.

Los números con pocas partidas de por medio (ver la etiqueta de
confianza en el dashboard: alta/media/baja) son más ruidosos — un
compañero con pocas partidas en total puede tener un impacto que se
mueve mucho con una sola partida más.

## Próximos pasos posibles

- Sumar partidas como rivales (no solo como compañeros) para ver
  matchups dentro del grupo.
- Trackear cómo evoluciona el ranking de impacto semana a semana.
