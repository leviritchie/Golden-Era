# usage: guarded_lab.sh <unit>... : per unit -> wait while game runs, V: check, memgate, game re-check, then the
# spec-driven vanilla-style lab for that one unit (Unity via unitylock inside the lab), raw frames pruned after compose.
cd "/v/games/Olden Era Playtest Tweak"
game_up() { powershell -NoProfile -Command "if (Get-Process HeroesOldenEra -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"; }
for u in "$@"; do
  while :; do
    while game_up; do echo "PAUSE $(date +%T): HeroesOldenEra running, not launching $u"; sleep 60; done
    free=$(df -BG /v | tail -1 | awk '{print $4}' | tr -d G); if [ "$free" -lt 20 ]; then echo "STOP: V: ${free}G"; exit 1; fi
    python tools/homm3_def_retarget/memgate.py --wait 30 || { echo "STOP: memgate failed"; exit 1; }
    game_up || break
    echo "PAUSE: game started during memgate, $u not launched"
  done
  echo "=== $u $(date +%T)"
  python tools/homm3_vfx/vanilla_style_lab.py --units "$u" --prune-renders --timeout 2400 || echo "FAILED $u"
done
echo "lab batch done $(date +%T)"
