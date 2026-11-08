#!/usr/bin/env python3
"""Build the original single-player scenario The Floodgate Gambit."""
from __future__ import annotations
import argparse, copy, hashlib, json, zipfile
from pathlib import Path
from typing import Any
import port_homecoming_poc as poc

MAP_SID = "h3_floodgate_gambit"
TITLE = "The Floodgate Gambit"
MISSION = "floodgate_gambit"
SCHEMA = "homm3.olden_floodgate_gambit.v1"
POLICY = "three_sigils_56_capture_citadel"
OUT = Path(poc.ROOT) / "artifacts" / "campaign_port_poc" / MISSION
SIZE = 64
GRASS, DIRT = 1, 7
PLAYER_FACTION, PLAYER_HERO = "homm3_castle", "homm3_castle_hero_3"
ENEMY_FACTION, ENEMY_HERO = "homm3_necropolis", "homm3_necropolis_hero_2"
PLAYER_CITY, ENEMY_CITY = 100, 101
PLAYER_XY, ENEMY_XY = (12, 47), (43, 8)
CITADEL = f"{MISSION}_floodgate_citadel"
SIGILS = [("west", (18, 35), 500, 0, "The western seal is cold. Beneath it, a ledger names the dead who once guarded the floodgates."), ("middle", (30, 28), 0, 6, "The middle seal hums with stored power. You recover six ore from the keeper's cache."), ("east", (20, 18), 0, 0, "The eastern seal bears a warning: the necromancer intends to open the gates at the next new moon.")]
MERC_XY = (38, 23)
ENEMY_HERO_XY = (37, 13)
GUARD_SID = f"{MISSION}_mercenary_guard"
GUARD_SQUAD = f"{MISSION}_griffin_x5"
GUARD_UNIT, GUARD_COUNT = "h3_griffin", 5

def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def node(x: int, y: int) -> int: return y * SIZE + x
def dialog(sid: str) -> dict[str, Any]: return {"comment":"", "a":"Dialog", "p":[sid]}
def give(resource: str, amount: int) -> dict[str, Any]: return {"comment":"", "a":"GiveRes", "p":[resource, str(amount)]}
def print_action(text: str) -> dict[str, Any]: return {"comment":"", "a":"Print", "p":[text]}
def set_counter(sid: str, value: int) -> dict[str, Any]: return {"comment":"", "a":"CounterSet", "p":[sid, str(value)]}
def plus_counter(sid: str) -> dict[str, Any]: return {"comment":"", "a":"CounterPlus", "p":[sid, "1"]}
def interaction(sid: str) -> dict[str, Any]: return {"comment":"", "c":"ObjectInteractionAfter", "p":[sid], "counter":1}
def start_day(day: int) -> dict[str, Any]:
    from campaign_event_ir.schedule_encode import start_turn_condition
    return start_turn_condition(day, context=MISSION)
def any_day() -> dict[str, Any]:
    from campaign_event_ir.schedule_encode import any_start_turn_every_day_condition
    return any_start_turn_every_day_condition()
def day_counter(sid: str, value: int) -> dict[str, Any]:
    from campaign_event_ir.schedule_encode import counter_equality_in_days_condition
    return counter_equality_in_days_condition(sid, value)

def dialogs() -> list[dict[str, Any]]:
    return [
        {"id":f"{MISSION}_briefing","title":TITLE,"text":"Commander Elian, the river gates have been sabotaged. Three ancient sigils can expose the hidden controls. Recover them, survive the deadlands, and seize Floodgate Citadel before the necromancer drowns the valley."},
        {"id":f"{MISSION}_sigil_west","title":"The Ledger Seal","text":SIGILS[0][4] + " You find 500 gold in a dry stone niche."},
        {"id":f"{MISSION}_sigil_middle","title":"The Reservoir Seal","text":SIGILS[1][4] + " The ore will help repair the gates."},
        {"id":f"{MISSION}_sigil_east","title":"The Warning Seal","text":SIGILS[2][4]},
        {"id":f"{MISSION}_mercenary","title":"The Floodgate Wardens","text":"Five griffins guard the old sluice. They are not undead, but their keeper is gone. Defeat them and the sluice road is yours."},
        {"id":f"{MISSION}_necromancer","title":"Lord Varaxis","text":"You came for the gates? Excellent. I will use your army to test the flood."},
        {"id":f"{MISSION}_victory","title":"The Gates Hold","text":"Floodgate Citadel falls before the river can be turned. The three seals flare together, locking the valley's water behind safe stone. The dead retreat. Victory."},
    ]

def done_trigger(comment: str, condition: dict[str, Any], actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = list(actions or []) + [{"comment":"", "a":"CurrentSubQuestDone", "p":[]}]
    return {"comment":comment,"repeat":False,"conditions":[condition],"actions":rows,"conditionsLogic":"And"}

def quest_script() -> dict[str, Any]:
    counters = [{"comment":"", "sid":f"{MISSION}_started", "sharing":"Clone", "value":0, "minValue":-2147483648, "maxValue":2147483647}]
    for key, *_ in SIGILS: counters.append({"comment":"", "sid":f"{MISSION}_{key}_done", "sharing":"Clone", "value":0, "minValue":-2147483648, "maxValue":2147483647})
    counters += [{"comment":"", "sid":f"{MISSION}_supply_days", "sharing":"Clone", "value":0, "minValue":-2147483648, "maxValue":2147483647}]
    main_sub = []
    for key, xy, gold, ore, _ in SIGILS:
        reward = []
        if gold: reward.append(give("gold", gold))
        if ore: reward.append(give("ore", ore))
        reward.append(set_counter(f"{MISSION}_{key}_done", 1))
        main_sub.append({"sid":f"{MISSION}_obj_{key}","activeOnStart":True,"hidden":False,"name":f"Recover the {key} seal","desc":f"Investigate the {key} river seal.","comment":"","triggers":[done_trigger(f"{key} seal visited", interaction(f"{MISSION}_sigil_{key}"), reward)]})
    main_sub.append({"sid":f"{MISSION}_obj_guard","activeOnStart":True,"hidden":False,"name":"Break the sluice wardens (optional)","desc":"Defeat the griffins guarding the old sluice.","comment":"","triggers":[done_trigger("warden victory", {"comment":"","c":"SquadKill","p":[GUARD_SID],"counter":1}, [give("gems", 2)])]})
    main_sub.append({"sid":f"{MISSION}_obj_citadel","activeOnStart":True,"hidden":False,"name":"Capture Floodgate Citadel","desc":"Defeat Lord Varaxis and seize the necromancer citadel.","comment":"","triggers":[{"comment":"citadel captured","repeat":False,"conditions":[{"comment":"","c":"ObjectCaptureEntity","p":[CITADEL],"counter":1}],"actions":[dialog(f"{MISSION}_victory"),{"comment":"","a":"CurrentSubQuestDone","p":[]},{"comment":"","a":"GameVictory","p":[]}],"conditionsLogic":"And"}]})
    return {"comment":f"{MISSION} quest script","aiRolesId":f"{MISSION}_ai","interruptions":[{"sid":f"{MISSION}_necromancer_before","comment":"Lord Varaxis pre-battle speech","p":[ENEMY_HERO],"activeOnStart":True,"interruption":"BeforeIamVsHero","actions":[dialog(f"{MISSION}_necromancer"),{"comment":"","a":"DisableInterruption","p":[f"{MISSION}_necromancer_before"]}]}],"counters":counters,"quests":[{"sid":f"{MISSION}_intro","hidden":True,"main":False,"activeOnStart":True,"comment":"briefing","sharing":"Clone","name":"","desc":"","subQuests":[{"sid":f"{MISSION}_intro_body","activeOnStart":True,"hidden":False,"name":"","desc":"","comment":"","triggers":[{"comment":"opening briefing","repeat":False,"conditions":[start_day(1)],"actions":[dialog(f"{MISSION}_briefing"),give("gold",2500),give("wood",5),set_counter(f"{MISSION}_started",1)],"conditionsLogic":"And"}]}],"subQuestGroups":[]},{"sid":f"{MISSION}_supply","hidden":True,"main":False,"activeOnStart":True,"comment":"timed supply","sharing":"Clone","name":"","desc":"","subQuests":[{"sid":f"{MISSION}_supply_body","activeOnStart":True,"hidden":True,"name":"","desc":"","comment":"","triggers":[{"comment":"first supply","repeat":False,"conditions":[start_day(6)],"actions":[give("wood",8),give("ore",4),print_action("A repaired barge delivers supplies.")],"conditionsLogic":"And"},{"comment":"daily timer","repeat":True,"conditions":[any_day()],"actions":[plus_counter(f"{MISSION}_supply_days")],"conditionsLogic":"And"},{"comment":"every sixth day after start","repeat":True,"conditions":[day_counter(f"{MISSION}_supply_days",6)],"actions":[give("wood",8),give("ore",4),set_counter(f"{MISSION}_supply_days",0)],"conditionsLogic":"And"}]}],"subQuestGroups":[]},{"sid":f"{MISSION}_main","hidden":False,"main":True,"activeOnStart":True,"comment":"three seals and citadel","sharing":"Clone","name":TITLE,"desc":"Recover three river seals and capture Floodgate Citadel.","subQuests":main_sub,"subQuestGroups":[]},{"sid":f"{MISSION}_guards","hidden":True,"main":False,"activeOnStart":True,"comment":"optional warden event","sharing":"Clone","name":"","desc":"","subQuests":[{"sid":f"{MISSION}_guards_body","activeOnStart":True,"hidden":True,"name":"","desc":"","comment":"","triggers":[{"comment":"warden approach","repeat":True,"conditions":[{"comment":"","c":"SquadInteraction","p":[GUARD_SID],"counter":1}],"actions":[dialog(f"{MISSION}_mercenary")],"conditionsLogic":"And"},{"comment":"warden reward cleanup","repeat":False,"conditions":[{"comment":"","c":"SquadKill","p":[GUARD_SID],"counter":1}],"actions":[{"comment":"","a":"DeleteEntity","p":[GUARD_SID]}],"conditionsLogic":"And"}]}],"subQuestGroups":[]}]} 

def terrain() -> dict[str, list[int]]:
    total = SIZE * SIZE; tiles = [GRASS] * total
    for y in range(SIZE):
        for x in range(SIZE):
            if x == PLAYER_XY[0] and 8 <= y <= PLAYER_XY[1]: tiles[node(x,y)] = DIRT
            if y == 28 and 12 <= x <= 38: tiles[node(x,y)] = DIRT
            if x == 20 and 18 <= y <= 35: tiles[node(x,y)] = DIRT
            if x == 30 and 18 <= y <= 28: tiles[node(x,y)] = DIRT
            if x == 38 and 13 <= y <= 23: tiles[node(x,y)] = DIRT
    return {"tilesMap":tiles,"waterMap":[0]*total,"roadsMap":[0]*total,"levelsMap":[0]*total,"climbsMap":[0]*total,"customAreasPainting":[0]*total}

def props(properties: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = properties.setdefault(key, [])
    if not isinstance(value, list): raise ValueError(key)
    return value

def object_group(objects: list[dict[str, Any]], sid: str, object_id: int, at: int) -> None:
    objects.append({"sid":sid,"ids":[object_id],"nodes":[at],"rotations":[0],"levels":[0.0]})

def city(objects: list[dict[str, Any]], p: dict[str, Any], cid: int, at: int, owner: int, faction: str, hero: str, entity: str | None) -> None:
    object_group(objects,"city-spawner",cid,at)
    props(p,"propSpawns").append({"type":0,"id":cid,"owner":owner,"spawnType":0 if owner==1 else 1,"spawnPointType":0 if owner==1 else 1,"isLocked":False})
    props(p,"propCities").append({"type":0,"id":cid,"isDefined":True,"factionSid":faction,"spawnHero":True,"buildingsConstructionSid":poc.HOMM3_CUSTOM_TOWN_BUILDINGS_CONSTRUCTION_SID,"buildingsBanSid":"default_buildings_ban","buildingsSettingsSid":"default_buildings_settings","customCityName":"Floodgate Citadel" if entity else ""})
    props(p,"propHeroes").append({"type":0,"id":cid,"isDefined":True,"heroSid":hero})
    props(p,"propGrowthUnits").append({"type":0,"id":cid,"isConstantGrowth":True,"countGrowth":1})
    props(p,"propActivations").append({"type":0,"id":cid,"isActive":True})
    if entity: props(p,"propEntities").append({"type":0,"id":cid,"sid":entity})

def beacon(objects: list[dict[str, Any]], p: dict[str, Any], markers: list[dict[str, Any]], key: str, at: tuple[int,int], next_id: int, marker_id: int) -> tuple[int,int]:
    sid=f"{MISSION}_sigil_{key}"; markers.append({"node":node(*at),"v":"","sid":"Zone 1x1","id":marker_id})
    props(p,"propMarkers").append({"type":1,"id":marker_id,"isDelete":True,"isActivate":True})
    props(p,"propEntities").append({"type":1,"id":marker_id,"sid":sid})
    props(p,"propActionsBefore").append({"type":1,"id":marker_id,"repeat":False,"sides":"","actions":[dialog(sid)]})
    props(p,"propActionsAfter").append({"type":1,"id":marker_id,"repeat":False,"sides":"","actions":[{"comment":"","a":"DeleteEntity","p":[sid]}]})
    object_group(objects,"fx_quest_mark_gold_01",next_id,node(at[0],at[1]-1)); return next_id+1, marker_id+1

def guarded(objects: list[dict[str, Any]], p: dict[str, Any], next_id: int) -> int:
    object_group(objects,"random-squad",next_id,node(*MERC_XY)); props(p,"propEntities").append({"type":0,"id":next_id,"sid":GUARD_SID}); props(p,"propActivations").append({"type":0,"id":next_id,"isActive":True}); props(p,"propRandomSquads").append({"type":0,"id":next_id,"sids":[GUARD_SQUAD],"requestedValue":300.0,"fraction":"","tier":0,"isMainGuard":False,"reactionType":2,"customTopUnit":GUARD_UNIT,"isEscape":False,"isAutobatle":False,"isFreeDiplomacy":False,"isCampaignFreeDiplomacy":False,"isCampaignDiplomacy":False,"isIgnoreMultiply":False,"obstruction":"","customStacks":0}); props(p,"propSquads").append({"type":0,"id":next_id,"isMainGuard":False,"isStartBattleImmediately":False,"reactionType":2,"unitProps":[{"sid":GUARD_UNIT,"count":GUARD_COUNT}]}); return next_id+1

def enemy_hero(objects: list[dict[str, Any]], p: dict[str, Any], next_id: int) -> int:
    object_group(objects,"hero-spawner",next_id,node(*ENEMY_HERO_XY)); props(p,"propEntities").append({"type":0,"id":next_id,"sid":f"{MISSION}_lord_varaxis"}); props(p,"propActivations").append({"type":0,"id":next_id,"isActive":True}); props(p,"propHeroes").append({"type":0,"id":next_id,"isDefined":True,"heroSid":ENEMY_HERO}); props(p,"propSpawns").append({"type":0,"id":next_id,"owner":2,"spawnType":1,"spawnPointType":1,"isLocked":False}); return next_id+1

def build_map() -> tuple[poc.OldenMapContainer, dict[str, Any]]:
    if not poc.PLAYABLE_TEMPLATE_MAP.exists(): raise FileNotFoundError(poc.PLAYABLE_TEMPLATE_MAP)
    source = poc.read_olden_map_container(poc.PLAYABLE_TEMPLATE_MAP); chunks=copy.deepcopy(list(source.chunks)); meta, data=chunks[0], chunks[1]; schema_fields={k:copy.deepcopy(data[k]) for k in ("cliffRandomSeed","generatorChecksum","settings") if k in data}
    t=terrain(); meta.update({"title":TITLE,"template":"","desc":"Recover the three river seals and seize Floodgate Citadel before the valley floods.","displayWinCondition":"Capture Floodgate Citadel.","hashSum":hashlib.md5(MAP_SID.encode()).hexdigest(),"nameFromLocalization":False,"descFromLocalization":False,"isScenario":True,"sizeX":SIZE,"sizeZ":SIZE,"spawns":{"playersCount":2,"spawns":[{"owner":1,"spawnType":0,"playerId":"","spawnPointType":0,"isCityDefined":True,"factionSid":PLAYER_FACTION,"isHeroDefined":True,"heroSid":PLAYER_HERO,"colorId":-1,"isAlive":True,"isLocked":False},{"owner":2,"spawnType":1,"playerId":"","spawnPointType":1,"isCityDefined":True,"factionSid":ENEMY_FACTION,"isHeroDefined":False,"heroSid":"","colorId":-1,"isAlive":True,"isLocked":False}],"takenHeroes":[PLAYER_HERO,ENEMY_HERO]},"campaignInfo":None})
    p={k:[] for k in ["propSpawns","propCities","propHeroes","propGrowthUnits","propRandomSquads","propEntities","propActionsBefore","propActionsAfter","propActivations","propMarkers","propSquads","propAiIntetations"]}
    data.clear(); data.update({"fileMapName":MAP_SID,"mapName":TITLE,"mapNameFromLoc":False,"mapDesc":meta["desc"],"mapDescFromLoc":False,"sizeX_":SIZE,"sizeZ_":SIZE,**t,"haveCustomAreas":True,"areasVersion":1,"objects":[],"objectsFreeId":200,"squads":[],"squadsFreeId":0,"markers":[],"markersFreeId":1,"takenHeroes":[PLAYER_HERO,ENEMY_HERO],"keyObjects":[],"objectValuesOverrides":[],"areas":[{"id":0,"keyObjectId":PLAYER_CITY,"rootNode":node(*PLAYER_XY),"nodes":list(range(SIZE*SIZE))}],"rivers":[],"views":[{"name":"","minSecX":0,"minSecZ":0,"secSizeX":4,"secSizeZ":4,"isUnderground":False,"stack":-1}],"banInfoData":{"bannedMagics":[],"bannedItems":[],"bannedSkills":[],"bannedHeroes":[],"bannedUnits":[]},"objectsProperties":p,**schema_fields})
    city(data["objects"],p,PLAYER_CITY,node(*PLAYER_XY),1,PLAYER_FACTION,PLAYER_HERO,None); city(data["objects"],p,ENEMY_CITY,node(*ENEMY_XY),2,ENEMY_FACTION,ENEMY_HERO,CITADEL)
    oid=200; mid=1
    for key, at, *_ in SIGILS: oid,mid=beacon(data["objects"],p,data["markers"],key,at,oid,mid)
    oid=guarded(data["objects"],p,oid); oid=enemy_hero(data["objects"],p,oid); data["objectsFreeId"]=oid; data["markersFreeId"]=mid
    chunks[2]={"dialogs":{"lines":[]},"quests":{"quests":[]}}; chunks[3]=quest_script()
    return poc.OldenMapContainer(source.version,source.prefix_suffix,chunks), {"sigils":[{"id":k,"xy":list(a)} for k,a,*_ in SIGILS],"guard":{"xy":list(MERC_XY),"squad":GUARD_SQUAD},"enemyHero":{"xy":list(ENEMY_HERO_XY),"hero":ENEMY_HERO},"citadel":{"xy":list(ENEMY_XY),"entity":CITADEL}}

def overlay(out_root: Path) -> dict[str, Any]:
    root=out_root/"core_overlay"; core=poc.OLDEN_CORE_ZIP
    with zipfile.ZipFile(core) as z: lang=json.loads(z.read("Lang/english/texts/dialogues.json").decode("utf-8-sig")); quick=json.loads(z.read("DB/quickStart.json").decode("utf-8-sig"))
    tokens=lang.setdefault("tokens",[]); arrays=lang.setdefault("array",[]); members=[]
    for item in dialogs():
        sid=item["id"]; title_sid=f"dialogue_title_{sid}"; text_sid=f"dialogue_text_{sid}_0"
        for section in (tokens,arrays): section.extend([{"sid":title_sid,"text":item["title"]},{"sid":text_sid,"text":item["text"]}])
        member=f"DB/dialogs/dialogs/custom_maps/FloodgateGambit/{sid}.json"; members.append(member); write_json(root/member,{"array":[{"id":sid,"localization":True,"slides":[{"id":"start","fon":"","avatars":[],"title":{"sid":title_sid,"position":3},"text":text_sid,"next":"ending"},{"id":"ending","fon":"","text":"","invokeOnlyActions":True,"end":True}]}]})
    write_json(root/"Lang/english/texts/dialogues.json",lang)
    sq=f"DB/squads/squads_custom_maps/FloodgateGambit/{GUARD_SQUAD}.json"; write_json(root/sq,{"array":[{"id":GUARD_SQUAD,"squad":[],"useOldSquads":False,"rollChance":0,"canBeMainGuard":True,"baseSquad":{"units":[{"s":GUARD_UNIT,"v":300}]},"dynamicSquad":{"requiredValue":300,"units":[GUARD_UNIT]},"randomSquad":{"maxValue":300,"units":[{"s":GUARD_UNIT,"v":300}]},"tier":0,"fraction":""}]})
    quick.setdefault("scenarios",[])
    if MAP_SID not in quick["scenarios"]: quick["scenarios"].append(MAP_SID)
    write_json(root/"DB/quickStart.json",quick)
    return {"dialogMembers":members,"squadMember":sq,"dialogCount":len(dialogs())}

def build(out_root: Path) -> dict[str, Any]:
    container, world=build_map(); out_root.mkdir(parents=True,exist_ok=True); mp=out_root/"maps"/f"{MAP_SID}.map"; side=out_root/"maps"/f"{MAP_SID}.json"; mp.parent.mkdir(parents=True,exist_ok=True); poc.write_olden_map_container(mp,container,hashlib.md5(MAP_SID.encode()).hexdigest()); write_json(side,{"counters":container.chunks[3]["counters"],"quests":[]}); ov=overlay(out_root); manifest={"schema":SCHEMA,"status":"generated_artifact_runtime_unproven","mapSid":MAP_SID,"title":TITLE,"policyId":POLICY,"output":str(mp),"sidecar":str(side),"installDestinationPolicy":"maps_root_custom_only","coreOverlayRequired":True,"world":world,"coreOverlay":ov,"objectives":["Recover the western, middle, and eastern river seals","Break the sluice wardens (optional)","Capture Floodgate Citadel"],"events":["Day 1 briefing","Three one-shot seal dialogs with rewards","Barge supplies every six days after day 6","Guarded griffin encounter","Lord Varaxis pre-battle dialog","Victory on citadel capture"],"proofBoundary":"generated artifact + Core overlay; runtime remains user-unvalidated"}; write_json(out_root/"install_manifest.json",manifest); return manifest

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--out-root",type=Path,default=OUT); args=ap.parse_args(); m=build(args.out_root.resolve()); print(json.dumps({"ok":True,"mapSid":m["mapSid"],"output":m["output"]},indent=2)); return 0
if __name__ == "__main__": raise SystemExit(main())


