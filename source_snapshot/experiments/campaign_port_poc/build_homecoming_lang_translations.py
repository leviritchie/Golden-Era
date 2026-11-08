#!/usr/bin/env python3
"""Build homecoming_lang_translations.json for locales beyond english/french/german.

Uses Golden Era Core translation memory + release-port draft translator, then
applies authored short-string overrides for titles/object names so critical UI
is never left as English. Long dialog bodies use TM/draft (fail-closed if empty).
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release_port"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from multilingual_custom_lang import (  # noqa: E402
    _draft_translate,
    _translation_memory,
)
import homecoming_localization as loc  # noqa: E402

DEFAULT_CORE = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
    r"\HeroesOldenEra_Data\StreamingAssets\Core.zip"
)
OUT_PATH = Path(__file__).with_name("homecoming_lang_translations.json")

# Authored short UI overrides (must not remain English). Proper names kept.
NAME_OVERRIDES: dict[str, dict[str, str]] = {
    "spanish": {
        "homm3_roe_castle_homecoming_title": "Regreso a casa",
        "homm3_roe_castle_homecoming_capture_terraneus": "Localiza y captura Terraneus.",
        "homecoming_intro": "Informe",
        "homecoming_main_goal": "Capturar Terraneus",
        "homm3_landon_castle_city_name": "Castillo",
        "homm3_landon_dungeon_city_name": "Mazmorra",
        "homm3_landon_barracks_castle_1_name": "Casa de guardia",
        "homm3_landon_barracks_castle_2_name": "Torre de arqueros",
        "homm3_landon_barracks_castle_3_name": "Torre de grifos",
        "homm3_landon_barracks_castle_4_name": "Cuartel",
        "homm3_landon_barracks_castle_5_name": "Monasterio",
        "homm3_landon_map_event_marker_name": "Marcador de misión",
        "homm3_random_resource_pickup_name": "Recurso aleatorio",
        "homm3_flotsam_pickup_name": "Restos flotantes",
        "homm3_subterranean_gate_portal_name": "Puerta subterránea",
        "dialogue_title_homecoming_intro": "Regreso a casa",
        "dialogue_title_homecoming_map_event_0_dialog": "Regreso a casa",
    },
    "italian": {
        "homm3_roe_castle_homecoming_title": "Ritorno a casa",
        "homm3_roe_castle_homecoming_capture_terraneus": "Trova e conquista Terraneus.",
        "homecoming_intro": "Briefing",
        "homecoming_main_goal": "Conquista Terraneus",
        "homm3_landon_castle_city_name": "Castello",
        "homm3_landon_dungeon_city_name": "Dungeon",
        "homm3_landon_barracks_castle_1_name": "Corpo di guardia",
        "homm3_landon_barracks_castle_2_name": "Torre degli arcieri",
        "homm3_landon_barracks_castle_3_name": "Torre dei grifoni",
        "homm3_landon_barracks_castle_4_name": "Caserma",
        "homm3_landon_barracks_castle_5_name": "Monastero",
        "homm3_landon_map_event_marker_name": "Segnalatore di missione",
        "homm3_random_resource_pickup_name": "Risorsa casuale",
        "homm3_flotsam_pickup_name": "Relitti",
        "homm3_subterranean_gate_portal_name": "Portale sotterraneo",
        "dialogue_title_homecoming_intro": "Ritorno a casa",
        "dialogue_title_homecoming_map_event_0_dialog": "Ritorno a casa",
    },
    "polish": {
        "homm3_roe_castle_homecoming_title": "Powrót do domu",
        "homm3_roe_castle_homecoming_capture_terraneus": "Odnajdź i zdobądź Terraneus.",
        "homecoming_intro": "Odprawa",
        "homecoming_main_goal": "Zdobądź Terraneus",
        "homm3_landon_castle_city_name": "Zamek",
        "homm3_landon_dungeon_city_name": "Loch",
        "homm3_landon_barracks_castle_1_name": "Strażnica",
        "homm3_landon_barracks_castle_2_name": "Wieża łuczników",
        "homm3_landon_barracks_castle_3_name": "Wieża gryfów",
        "homm3_landon_barracks_castle_4_name": "Koszary",
        "homm3_landon_barracks_castle_5_name": "Klasztor",
        "homm3_landon_map_event_marker_name": "Znacznik zadania",
        "homm3_random_resource_pickup_name": "Losowy surowiec",
        "homm3_flotsam_pickup_name": "Wrak",
        "homm3_subterranean_gate_portal_name": "Podziemna brama",
        "dialogue_title_homecoming_intro": "Powrót do domu",
        "dialogue_title_homecoming_map_event_0_dialog": "Powrót do domu",
    },
    "russian": {
        "homm3_roe_castle_homecoming_title": "Возвращение домой",
        "homm3_roe_castle_homecoming_capture_terraneus": "Найдите и захватите Терранеус.",
        "homecoming_intro": "Брифинг",
        "homecoming_main_goal": "Захватить Терранеус",
        "homm3_landon_castle_city_name": "Замок",
        "homm3_landon_dungeon_city_name": "Подземелье",
        "homm3_landon_barracks_castle_1_name": "Караулка",
        "homm3_landon_barracks_castle_2_name": "Башня лучников",
        "homm3_landon_barracks_castle_3_name": "Башня грифонов",
        "homm3_landon_barracks_castle_4_name": "Казармы",
        "homm3_landon_barracks_castle_5_name": "Монастырь",
        "homm3_landon_map_event_marker_name": "Метка задания",
        "homm3_random_resource_pickup_name": "Случайный ресурс",
        "homm3_flotsam_pickup_name": "Обломки",
        "homm3_subterranean_gate_portal_name": "Подземные врата",
        "dialogue_title_homecoming_intro": "Возвращение домой",
        "dialogue_title_homecoming_map_event_0_dialog": "Возвращение домой",
    },
    "czech": {
        "homm3_roe_castle_homecoming_title": "Návrat domů",
        "homm3_roe_castle_homecoming_capture_terraneus": "Najděte a dobyjte Terraneus.",
        "homecoming_intro": "Briefing",
        "homecoming_main_goal": "Dobyjte Terraneus",
        "homm3_landon_castle_city_name": "Hrad",
        "homm3_landon_dungeon_city_name": "Dungeon",
        "homm3_landon_barracks_castle_1_name": "Strážnice",
        "homm3_landon_barracks_castle_2_name": "Věž lukostřelců",
        "homm3_landon_barracks_castle_3_name": "Věž gryfů",
        "homm3_landon_barracks_castle_4_name": "Kasárna",
        "homm3_landon_barracks_castle_5_name": "Klášter",
        "homm3_landon_map_event_marker_name": "Značka úkolu",
        "homm3_random_resource_pickup_name": "Náhodný zdroj",
        "homm3_flotsam_pickup_name": "Trosky",
        "homm3_subterranean_gate_portal_name": "Podzemní brána",
        "dialogue_title_homecoming_intro": "Návrat domů",
        "dialogue_title_homecoming_map_event_0_dialog": "Návrat domů",
    },
    "hungarian": {
        "homm3_roe_castle_homecoming_title": "Hazatérés",
        "homm3_roe_castle_homecoming_capture_terraneus": "Találd meg és foglald el Terraneust.",
        "homecoming_intro": "Tájékoztató",
        "homecoming_main_goal": "Foglald el Terraneust",
        "homm3_landon_castle_city_name": "Kastély",
        "homm3_landon_dungeon_city_name": "Dungeon",
        "homm3_landon_barracks_castle_1_name": "Őrház",
        "homm3_landon_barracks_castle_2_name": "Íjásztorony",
        "homm3_landon_barracks_castle_3_name": "Griff-torony",
        "homm3_landon_barracks_castle_4_name": "Laktanya",
        "homm3_landon_barracks_castle_5_name": "Kolostor",
        "homm3_landon_map_event_marker_name": "Küldetésjelölő",
        "homm3_random_resource_pickup_name": "Véletlen nyersanyag",
        "homm3_flotsam_pickup_name": "Usadék",
        "homm3_subterranean_gate_portal_name": "Földalatti kapu",
        "dialogue_title_homecoming_intro": "Hazatérés",
        "dialogue_title_homecoming_map_event_0_dialog": "Hazatérés",
    },
    "turkish": {
        "homm3_roe_castle_homecoming_title": "Eve Dönüş",
        "homm3_roe_castle_homecoming_capture_terraneus": "Terraneus'u bul ve ele geçir.",
        "homecoming_intro": "Brifing",
        "homecoming_main_goal": "Terraneus'u Ele Geçir",
        "homm3_landon_castle_city_name": "Kale",
        "homm3_landon_dungeon_city_name": "Zindan",
        "homm3_landon_barracks_castle_1_name": "Karakol",
        "homm3_landon_barracks_castle_2_name": "Okçu Kulesi",
        "homm3_landon_barracks_castle_3_name": "Griffin Kulesi",
        "homm3_landon_barracks_castle_4_name": "Kışla",
        "homm3_landon_barracks_castle_5_name": "Manastır",
        "homm3_landon_map_event_marker_name": "Görev İşareti",
        "homm3_random_resource_pickup_name": "Rastgele Kaynak",
        "homm3_flotsam_pickup_name": "Enkaz",
        "homm3_subterranean_gate_portal_name": "Yeraltı Kapısı",
        "dialogue_title_homecoming_intro": "Eve Dönüş",
        "dialogue_title_homecoming_map_event_0_dialog": "Eve Dönüş",
    },
    "ukrainian": {
        "homm3_roe_castle_homecoming_title": "Повернення додому",
        "homm3_roe_castle_homecoming_capture_terraneus": "Знайдіть і захопіть Терранеус.",
        "homecoming_intro": "Брифінг",
        "homecoming_main_goal": "Захопити Терранеус",
        "homm3_landon_castle_city_name": "Замок",
        "homm3_landon_dungeon_city_name": "Підземелля",
        "homm3_landon_barracks_castle_1_name": "Вартова",
        "homm3_landon_barracks_castle_2_name": "Вежа лучників",
        "homm3_landon_barracks_castle_3_name": "Вежа грифонів",
        "homm3_landon_barracks_castle_4_name": "Казарми",
        "homm3_landon_barracks_castle_5_name": "Монастир",
        "homm3_landon_map_event_marker_name": "Мітка завдання",
        "homm3_random_resource_pickup_name": "Випадковий ресурс",
        "homm3_flotsam_pickup_name": "Уламки",
        "homm3_subterranean_gate_portal_name": "Підземна брама",
        "dialogue_title_homecoming_intro": "Повернення додому",
        "dialogue_title_homecoming_map_event_0_dialog": "Повернення додому",
    },
    "BRportugese": {
        "homm3_roe_castle_homecoming_title": "Retorno ao Lar",
        "homm3_roe_castle_homecoming_capture_terraneus": "Localize e capture Terraneus.",
        "homecoming_intro": "Briefing",
        "homecoming_main_goal": "Capturar Terraneus",
        "homm3_landon_castle_city_name": "Castelo",
        "homm3_landon_dungeon_city_name": "Masmorra",
        "homm3_landon_barracks_castle_1_name": "Casa da Guarda",
        "homm3_landon_barracks_castle_2_name": "Torre dos Arqueiros",
        "homm3_landon_barracks_castle_3_name": "Torre dos Grifos",
        "homm3_landon_barracks_castle_4_name": "Quartel",
        "homm3_landon_barracks_castle_5_name": "Mosteiro",
        "homm3_landon_map_event_marker_name": "Marcador de Missão",
        "homm3_random_resource_pickup_name": "Recurso Aleatório",
        "homm3_flotsam_pickup_name": "Destroços",
        "homm3_subterranean_gate_portal_name": "Portal Subterrâneo",
        "dialogue_title_homecoming_intro": "Retorno ao Lar",
        "dialogue_title_homecoming_map_event_0_dialog": "Retorno ao Lar",
    },
    "japanese": {
        "homm3_roe_castle_homecoming_title": "故郷への帰還",
        "homm3_roe_castle_homecoming_capture_terraneus": "テラネウスを探し出し占領せよ。",
        "homecoming_intro": "ブリーフィング",
        "homecoming_main_goal": "テラネウスを占領",
        "homm3_landon_castle_city_name": "キャッスル",
        "homm3_landon_dungeon_city_name": "ダンジョン",
        "homm3_landon_barracks_castle_1_name": "衛兵所",
        "homm3_landon_barracks_castle_2_name": "射手の塔",
        "homm3_landon_barracks_castle_3_name": "グリフォンの塔",
        "homm3_landon_barracks_castle_4_name": "兵舎",
        "homm3_landon_barracks_castle_5_name": "修道院",
        "homm3_landon_map_event_marker_name": "クエストマーカー",
        "homm3_random_resource_pickup_name": "ランダム資源",
        "homm3_flotsam_pickup_name": "漂流物",
        "homm3_subterranean_gate_portal_name": "地下門",
        "dialogue_title_homecoming_intro": "故郷への帰還",
        "dialogue_title_homecoming_map_event_0_dialog": "故郷への帰還",
    },
    "korean": {
        "homm3_roe_castle_homecoming_title": "귀향",
        "homm3_roe_castle_homecoming_capture_terraneus": "테라네우스를 찾아 점령하십시오.",
        "homecoming_intro": "브리핑",
        "homecoming_main_goal": "테라네우스 점령",
        "homm3_landon_castle_city_name": "성",
        "homm3_landon_dungeon_city_name": "던전",
        "homm3_landon_barracks_castle_1_name": "경비소",
        "homm3_landon_barracks_castle_2_name": "궁수 탑",
        "homm3_landon_barracks_castle_3_name": "그리폰 탑",
        "homm3_landon_barracks_castle_4_name": "병영",
        "homm3_landon_barracks_castle_5_name": "수도원",
        "homm3_landon_map_event_marker_name": "퀘스트 표식",
        "homm3_random_resource_pickup_name": "무작위 자원",
        "homm3_flotsam_pickup_name": "표류물",
        "homm3_subterranean_gate_portal_name": "지하 관문",
        "dialogue_title_homecoming_intro": "귀향",
        "dialogue_title_homecoming_map_event_0_dialog": "귀향",
    },
    "zhCN": {
        "homm3_roe_castle_homecoming_title": "归乡",
        "homm3_roe_castle_homecoming_capture_terraneus": "找到并占领泰拉纽斯。",
        "homecoming_intro": "简报",
        "homecoming_main_goal": "占领泰拉纽斯",
        "homm3_landon_castle_city_name": "城堡",
        "homm3_landon_dungeon_city_name": "地下城",
        "homm3_landon_barracks_castle_1_name": "卫兵所",
        "homm3_landon_barracks_castle_2_name": "射手塔",
        "homm3_landon_barracks_castle_3_name": "狮鹫塔",
        "homm3_landon_barracks_castle_4_name": "兵营",
        "homm3_landon_barracks_castle_5_name": "修道院",
        "homm3_landon_map_event_marker_name": "任务标记",
        "homm3_random_resource_pickup_name": "随机资源",
        "homm3_flotsam_pickup_name": "残骸",
        "homm3_subterranean_gate_portal_name": "地下门",
        "dialogue_title_homecoming_intro": "归乡",
        "dialogue_title_homecoming_map_event_0_dialog": "归乡",
    },
    "zhTW": {
        "homm3_roe_castle_homecoming_title": "歸鄉",
        "homm3_roe_castle_homecoming_capture_terraneus": "找到並佔領泰拉紐斯。",
        "homecoming_intro": "簡報",
        "homecoming_main_goal": "佔領泰拉紐斯",
        "homm3_landon_castle_city_name": "城堡",
        "homm3_landon_dungeon_city_name": "地下城",
        "homm3_landon_barracks_castle_1_name": "衛兵所",
        "homm3_landon_barracks_castle_2_name": "射手塔",
        "homm3_landon_barracks_castle_3_name": "獅鷲塔",
        "homm3_landon_barracks_castle_4_name": "兵營",
        "homm3_landon_barracks_castle_5_name": "修道院",
        "homm3_landon_map_event_marker_name": "任務標記",
        "homm3_random_resource_pickup_name": "隨機資源",
        "homm3_flotsam_pickup_name": "殘骸",
        "homm3_subterranean_gate_portal_name": "地下門",
        "dialogue_title_homecoming_intro": "歸鄉",
        "dialogue_title_homecoming_map_event_0_dialog": "歸鄉",
    },
}


def read_json(zf: zipfile.ZipFile, name: str):
    return json.loads(zf.read(name).decode("utf-8-sig"))


def english_source(core: Path) -> dict[str, dict[str, str]]:
    dialogs = loc.load_english_dialogue_bodies(core)
    return {
        "customMaps.json": dict(loc.CUSTOM_MAPS_EN),
        "mapObjects.json": dict(loc.MAP_OBJECTS_EN),
        "dialogues.json": dialogs,
        # Proper nouns: keep English labels across locales unless authored otherwise.
        "cities.json": dict(loc.CITIES_EN),
    }


def build(core: Path) -> dict[str, dict[str, dict[str, str]]]:
    skip = {"english", "french", "german"}
    source = english_source(core)
    out: dict[str, dict[str, dict[str, str]]] = {}
    with zipfile.ZipFile(core, "r") as zf:
        for lang in loc.HOMECOMING_LANGS:
            if lang in skip:
                continue
            if lang not in NAME_OVERRIDES:
                raise SystemExit(f"missing authored name overrides for {lang}")
            memory = _translation_memory(zf, {}, lang, read_json)
            pack: dict[str, dict[str, str]] = {}
            overrides = NAME_OVERRIDES[lang]
            for file_name, rows in source.items():
                file_pack: dict[str, str] = {}
                for sid, english_text in rows.items():
                    if sid in overrides:
                        text = overrides[sid]
                    elif file_name == "cities.json":
                        # Town proper names stay Latin-script source names by default.
                        text = english_text
                    else:
                        text = _draft_translate(lang, english_text, memory)
                        if not isinstance(text, str) or not text.strip():
                            raise SystemExit(f"empty draft for {lang}/{file_name}/{sid}")
                    file_pack[sid] = text
                pack[file_name] = file_pack
            out[lang] = pack
    return out


def main() -> int:
    core = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CORE
    packs = build(core)
    OUT_PATH.write_text(json.dumps(packs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH} locales={sorted(packs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
