using System;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json.Linq;

namespace OfflineUnlockMod;

/// <summary>
/// Central registry for HoMM3 custom-faction identity and unit donor mappings.
/// Runtime identity is loaded from deployed <c>custom_factions/*.json</c> files
/// during plugin startup so bad faction data fails before hooks register.
/// </summary>
internal static class Homm3CustomFactionRegistry
{
    private static readonly string[] UnitSuffixes = { "", "_upg", "_upg_alt" };
    // Empty since 2026-09-29: h3_cannon was retired as a bundled unit (d1921a2510). Every sid listed
    // here is a required recruitment-portrait idle clip at main menu, so a sid without a bundled battle
    // import row makes startup fail closed. The Cove cannon billboard keeps its own donor mapping.
    private static readonly KeyValuePair<string, string>[] ExtraUnitDonorMappings =
    {
    };

    private static readonly HashSet<string> ReleaseUiPresentationEnabledFactionSids = new(StringComparer.OrdinalIgnoreCase)
    {
        "homm3_stronghold",
        "homm3_castle",
        "homm3_tower",
        "homm3_fortress",
        "homm3_rampart",
        "homm3_conflux",
        "homm3_inferno",
        "homm3_necropolis",
        "homm3_cove",
        "homm3_dungeon",
    };

    private static FactionDefinition[] Factions =
    {
        new(
            "homm3_stronghold",
            "homm3_stronghold_city",
            "homm3_stronghold_city_icon",
            "homm3_runtime_assets/town_hud_icons/homm3_stronghold/fort_available.png",
            4.5f,
            "barracks_homm3_stronghold_",
            "homm3_runtime_assets/map_object_refs/homm3_stronghold_dwellings",
            new[]
            {
                "avggobl0.dir/00_00.png",
                "avgwolf0.dir/00_00.png",
                "avgorcg0.dir/00_00.png",
                "avgogre0.dir/00_00.png",
                "avgrocs0.dir/00_00.png",
                "avgcycl0.dir/00_00.png",
                "avgbhmt0.dir/00_00.png",
            },
            new[] { "barracks_dungeon_" },
            "Stronghold (HoMM3)",
            "The Strongholds of Krewlod are raised by alliances of warrior tribes in the harsh western wastelands. Barbarians and battle mages lead goblins, orcs, ogres, rocs, cyclopes, and behemoths into battle, trusting strength, endurance, and old tribal oaths over the refinements of high magic.",
            "homm3_stronghold_hero_",
            "hero_homm3_stronghold_",
            "homm3_stronghold_faction_banner",
            "homm3_runtime_assets/faction_icons/homm3_stronghold/Stronghold_H6_banner.png",
            "homm3_stronghold_faction_card",
            "homm3_runtime_assets/town_scene_refs/homm3_stronghold/Stronghold-in-background.png",
            new[]
        {
            new UnitLine("h3_goblin", "dungeon", "trogl", "troglodyte"),
            new UnitLine("h3_wolf_rider", "dungeon", "assassin"),
            new UnitLine("h3_orc", "dungeon", "blade_dancer"),
            new UnitLine("h3_ogre", "dungeon", "minos"),
            new UnitLine("h3_roc", "dungeon", "medusa"),
            new UnitLine("h3_cyclops", "dungeon", "hydra"),
            new UnitLine("h3_behemoth", "dungeon", "black_dragon"),
        }),
        new(
            "homm3_castle",
            "homm3_castle_city",
            "homm3_castle_city_icon",
            "homm3_runtime_assets/town_hud_icons/homm3_castle/fort_available.png",
            4.5f,
            "barracks_homm3_castle_",
            "homm3_runtime_assets/map_object_refs/homm3_castle_dwellings",
            new[]
            {
                "AVGPIKE0.dir/00_00.png",
                "AVGCROS0.dir/00_00.png",
                "AVGgrff0.dir/00_00.png",
                "AVGSWOR0.dir/00_00.png",
                "AVGmonk0.dir/00_00.png",
                "AVGcavl0.dir/00_00.png",
                "AVGangl0.dir/00_00.png",
            },
            new[] { "barracks_human_" },
            "Castle (HoMM3)",
            "The Castle fields the disciplined armies of Erathia: pikemen, archers, griffins, swordsmen, monks, cavalry, and angels. Knights and clerics win through morale, formation, faith, cavalry charges, and the blessing of the heavens.",
            "homm3_castle_hero_",
            "hero_homm3_castle_",
            "homm3_castle_faction_banner",
            "homm3_runtime_assets/faction_icons/homm3_castle/Icon_Faction_Castle.png",
            "homm3_castle_faction_card",
            "homm3_runtime_assets/town_scene_refs/homm3_castle/Castle-in-background.png",
            new[]
        {
            new UnitLine("h3_pikeman", "humans", "esquire"),
            new UnitLine("h3_archer", "humans", "crossbowman"),
            new UnitLine("h3_griffin", "humans", "griffin"),
            new UnitLine("h3_swordsman", "humans", "inquisitor"),
            new UnitLine("h3_monk", "humans", "lightweaver"),
            new UnitLine("h3_cavalier", "humans", "sunlight_cavalry"),
            new UnitLine("h3_angel", "humans", "angel"),
        }),
        new(
            "homm3_tower",
            "homm3_tower_city",
            "homm3_tower_city_icon",
            "homm3_runtime_assets/town_hud_icons/homm3_tower/fort_available.png",
            5.15f,
            "barracks_homm3_tower_",
            "homm3_runtime_assets/map_object_refs/homm3_tower_dwellings",
            new[]
            {
                "avggrem0.dir/00_00.png",
                "avggarg0.dir/00_00.png",
                "avggolm0.dir/00_00.png",
                "avgmage0.dir/00_00.png",
                "avggeni0.dir/00_00.png",
                "avgnaga0.dir/00_00.png",
                "avgtitn0.dir/00_00.png",
            },
            new[] { "barracks_human_", "barracks_dungeon_" },
            "Tower (HoMM3)",
            "The Tower is a city of artificers, alchemists, and wizards who bind stone, steel, and storm into a precise battlefield machine. Expensive constructs, disciplined casters, and Titan-led ranged pressure define its armies.",
            "homm3_tower_hero_",
            "hero_homm3_tower_",
            "homm3_tower_faction_banner",
            "homm3_runtime_assets/faction_icons/homm3_tower/H5-Wizard.png",
            "homm3_tower_faction_card",
            "homm3_runtime_assets/town_scene_refs/homm3_tower/Tower-in-background.png",
            new[]
        {
            new UnitLine("h3_gremlin", "humans", "esquire"),
            new UnitLine("h3_gargoyle", "humans", "crossbowman"),
            new UnitLine("h3_golem", "humans", "griffin"),
            new UnitLine("h3_mage", "humans", "lightweaver"),
            new UnitLine("h3_genie", "humans", "sunlight_cavalry"),
            new UnitLine("h3_naga", "humans", "inquisitor"),
            new UnitLine("h3_giant", "humans", "angel"),
        }),
        new(
            "homm3_fortress",
            "homm3_fortress_city",
            "homm3_fortress_city_icon",
            "homm3_runtime_assets/town_hud_icons/homm3_fortress/fort_available.png",
            4.5f,
            "barracks_homm3_fortress_",
            "homm3_runtime_assets/map_object_refs/homm3_fortress_dwellings",
            new[]
            {
                "AVGGNLL0.dir/00_00.png",
                "AVGlzrd0.dir/00_00.png",
                "AVGdfly0.dir/00_00.png",
                "AVGbasl0.dir/00_00.png",
                "AVGgorg0.dir/00_00.png",
                "AVGwyvn0.dir/00_00.png",
                "AVGhydr0.dir/00_00.png",
            },
            new[] { "barracks_nature_" },
            "Fortress (HoMM3)",
            "The Fortress commands the marsh through durable beasts, fast flyers, and attrition tactics. Beastmasters and witches favor survival, disruption, and Swamp Tactics over high magic.",
            "homm3_fortress_hero_",
            "hero_homm3_fortress_",
            "homm3_fortress_faction_banner",
            "homm3_runtime_assets/faction_icons/homm3_fortress/Icon_Faction_Fortress.png",
            "homm3_fortress_faction_card",
            "homm3_runtime_assets/town_scene_refs/homm3_fortress/Fortress-in-background.png",
            new[]
        {
            new UnitLine("h3_gnoll", "humans", "esquire"),
            new UnitLine("h3_lizardman", "humans", "crossbowman"),
            new UnitLine("h3_serpent_fly", "humans", "griffin"),
            new UnitLine("h3_basilisk", "nature", "qilin"),
            new UnitLine("h3_gorgon", "dungeon", "minos"),
            new UnitLine("h3_wyvern", "humans", "angel"),
            new UnitLine("h3_hydra", "dungeon", "hydra"),
        }),
        new(
            "homm3_rampart",
            "homm3_rampart_city",
            "homm3_rampart_city_icon",
            "homm3_runtime_assets/town_hud_icons/homm3_rampart/fort_available.png",
            4.5f,
            "barracks_homm3_rampart_",
            "homm3_runtime_assets/map_object_refs/homm3_rampart_dwellings",
            new[]
            {
                "AVGCENT0.dir/00_00.png",
                "AVGdwrf0.dir/00_00.png",
                "AVGelf0.dir/00_00.png",
                "AVGpega0.dir/00_00.png",
                "AVGtree0.dir/00_00.png",
                "AVGUNIC0.dir/00_00.png",
                "AVGgdrg0.dir/00_00.png",
            },
            new[] { "barracks_nature_" },
            "Rampart (HoMM3)",
            "The Rampart guards AvLee's ancient forests with centaurs, dwarves, elves, pegasi, dendroids, unicorns, and dragons. Rangers and druids favor luck, resistance, living woods, and swift strikes from creatures at home beneath the green canopy.",
            "homm3_rampart_hero_",
            "hero_homm3_rampart_",
            "homm3_rampart_faction_banner",
            "homm3_runtime_assets/faction_icons/homm3_rampart/Icon_Faction_Rampart.png",
            "homm3_rampart_faction_card",
            "homm3_runtime_assets/town_scene_refs/homm3_rampart/Rampart-in-background.png",
            new[]
        {
            new UnitLine("h3_centaur", "humans", "sunlight_cavalry", upgradeSid: "h3_centaur_captain", alternateUpgradeSid: "h3_centaur_ranger_upg_alt"),
            new UnitLine("h3_dwarf", "humans", "esquire", upgradeSid: "h3_battle_dwarf", alternateUpgradeSid: "h3_dwarf_battlerager_upg_alt"),
            new UnitLine("h3_wood_elf", "nature", "elf_tracker", upgradeSid: "h3_grand_elf", alternateUpgradeSid: "h3_elf_wardancer_upg_alt"),
            new UnitLine("h3_pegasus", "nature", "twinkle", upgradeSid: "h3_silver_pegasus", alternateUpgradeSid: "h3_gold_pegasus_upg_alt"),
            new UnitLine("h3_dendroid_guard", "nature", "ent", upgradeSid: "h3_dendroid_soldier", alternateUpgradeSid: "h3_dendroid_shaman_upg_alt"),
            new UnitLine("h3_unicorn", "nature", "qilin", upgradeSid: "h3_war_unicorn", alternateUpgradeSid: "h3_pristine_unicorn_upg_alt"),
            new UnitLine("h3_green_dragon", "nature", "phoenix", upgradeSid: "h3_gold_dragon", alternateUpgradeSid: "h3_diamond_dragon_upg_alt"),
        }),
        new(
            "homm3_conflux",
            "homm3_conflux_city",
            "homm3_conflux_city_icon",
            "homm3_runtime_assets/town_hud_icons/homm3_conflux/fort_available.png",
            4.5f,
            "barracks_homm3_conflux_",
            "homm3_runtime_assets/map_object_refs/homm3_conflux_dwellings",
            new[]
            {
                "AVGpixie.dir/00_00.png",
                "AVGair0.dir/00_00.png",
                "AVGwatr0.dir/00_00.png",
                "AVGfire0.dir/00_00.png",
                "AVGerth0.dir/00_00.png",
                "AVGelp.dir/00_00.png",
                "AVGfbrd.dir/00_00.png",
            },
            new[] { "barracks_nature_" },
            "Conflux (HoMM3)",
            "The Conflux gathers the elemental planes into one army: pixies, air, water, fire, and earth elementals, psychic and magic elementals, and phoenixes. Elementalists shape battle through raw magic, planar summons, and forces that do not fight like mortal troops.",
            "homm3_conflux_hero_",
            "hero_homm3_conflux_",
            "homm3_conflux_faction_banner",
            "homm3_runtime_assets/faction_icons/homm3_conflux/Icon_Faction_Conflux.png",
            "homm3_conflux_faction_card",
            "homm3_runtime_assets/town_scene_refs/homm3_conflux/Conflux-in-background.png",
            new[]
        {
            new UnitLine("h3_pixie", "nature", "twinkle"),
            new UnitLine("h3_air_elemental", "humans", "crossbowman"),
            new UnitLine("h3_water_elemental", "nature", "aqualotl"),
            new UnitLine("h3_fire_elemental", "nature", "ent"),
            new UnitLine("h3_earth_elemental", "nature", "qilin"),
            new UnitLine("h3_psychic_elemental", "dungeon", "hydra"),
            new UnitLine("h3_firebird", "nature", "phoenix"),
        }),
        new(
            "homm3_inferno",
            "homm3_inferno_city",
            "homm3_inferno_city_icon",
            "homm3_runtime_assets/town_hud_icons/homm3_inferno/fort_available.png",
            4.5f,
            "barracks_homm3_inferno_",
            "homm3_runtime_assets/map_object_refs/homm3_inferno_dwellings",
            new[]
            {
                "avwimp0.dir/00_00.png",
                "avwgog0.dir/00_00.png",
                "avwhoun0.dir/00_00.png",
                "avwdemn0.dir/00_00.png",
                "avwpitf0.dir/00_00.png",
                "avwefre0.dir/00_00.png",
                "avwdevl0.dir/00_00.png",
            },
            new[] { "barracks_demon_" },
            "Inferno (HoMM3)",
            "Inferno armies surge from lava citadels with imps, gogs, cerberi, demons, pit fiends, efreet, and devils. Demoniacs and heretics thrive on fire, sacrifice, gated reinforcements, and relentless pressure from creatures born in the underworld.",
            "homm3_inferno_hero_",
            "hero_homm3_inferno_",
            "homm3_inferno_faction_banner",
            "homm3_runtime_assets/faction_icons/homm3_inferno/Icon_Faction_Inferno.png",
            "homm3_inferno_faction_card",
            "homm3_runtime_assets/town_scene_refs/homm3_inferno/Inferno-in-background.png",
            new[]
        {
            new UnitLine("h3_imp", "demons", "trick_demon", "parasite"),
            new UnitLine("h3_gog", "humans", "crossbowman"),
            new UnitLine("h3_hell_hound", "demons", "jaw", "scorpion"),
            new UnitLine("h3_demon", "demons", "olgoi"),
            new UnitLine("h3_pit_fiend", "demons", "hive_queen"),
            new UnitLine("h3_efreeti", "demons", "wasp"),
            new UnitLine("h3_devil", "demons", "godslayer"),
        }),
        new(
            "homm3_cove",
            "homm3_cove_city",
            "homm3_cove_city_icon",
            "homm3_runtime_assets/town_hud_icons/homm3_cove/fort_available.png",
            4.5f,
            "barracks_homm3_cove_",
            "homm3_runtime_assets/map_object_refs/homm3_cove_dwellings",
            new[]
            {
                "NIMPHFO.dir/00_00.png",
                "SWSHCAMP.dir/00_00.png",
                "FREGAT.dir/00_00.png",
                "NESTAS.dir/00_00.png",
                "TOWERZA.dir/00_00.png",
                "FORTNIX.dir/00_00.png",
                "HASPHTPL.dir/00_00.png",
            },
            new[] { "barracks_human_" },
            "Cove (HoMM3)",
            "The Cove sails from the seas of Horn of the Abyss with nymphs, pirates, sea witches, nix, sea serpents, and haspids. Captains and navigators fight with powder, tide magic, brutal boarding actions, and the hard bargains of a pirate port.",
            "homm3_cove_hero_",
            "hero_homm3_cove_",
            "homm3_cove_faction_banner",
            "homm3_runtime_assets/faction_icons/homm3_cove/Icon_Faction_Cove.png",
            "homm3_cove_faction_card",
            "homm3_runtime_assets/town_scene_refs/homm3_cove/Cove-in-background.png",
            new[]
        {
            new UnitLine("h3_nymph", "nature", "twinkle", upgradeSid: "h3_oceanid", alternateUpgradeSid: "h3_nymph_upg_alt"),
            new UnitLine("h3_crew_mate", "humans", "esquire", upgradeSid: "h3_seaman", alternateUpgradeSid: "h3_crew_mate_upg_alt"),
            new UnitLine("h3_pirate", "humans", "crossbowman", upgradeSid: "h3_corsair", alternateUpgradeSid: "h3_sea_dog"),
            new UnitLine("h3_stormbird", "humans", "griffin", upgradeSid: "h3_ayssid", alternateUpgradeSid: "h3_stormbird_upg_alt"),
            new UnitLine("h3_sea_witch", "humans", "lightweaver", upgradeSid: "h3_sorceress", alternateUpgradeSid: "h3_sea_witch_upg_alt"),
            new UnitLine("h3_nix", "dungeon", "minos", upgradeSid: "h3_nix_warrior", alternateUpgradeSid: "h3_nix_upg_alt"),
            new UnitLine("h3_sea_serpent", "dungeon", "hydra", upgradeSid: "h3_haspid", alternateUpgradeSid: "h3_sea_serpent_upg_alt"),
        }),
        new(
            "homm3_dungeon",
            "homm3_dungeon_city",
            "homm3_dungeon_city_icon",
            "homm3_runtime_assets/town_hud_icons/homm3_dungeon/fort_available.png",
            4.5f,
            "barracks_homm3_dungeon_",
            "homm3_runtime_assets/map_object_refs/homm3_dungeon_dwellings",
            new[]
            {
                "AVGtrog0.dir/00_00.png",
                "AVGharp0.dir/00_00.png",
                "AVGbhld0.dir/00_00.png",
                "AVGmdsa0.dir/00_00.png",
                "AVGmino0.dir/00_00.png",
                "AVGmant0.dir/00_00.png",
                "AVGrdrg0.dir/00_00.png",
            },
            new[] { "barracks_dungeon_" },
            "Dungeon (HoMM3)",
            "The HoMM3 Dungeon rules the underworld through troglodytes, harpies, beholders, medusas, minotaurs, manticores, and dragons. Overlords and warlocks favor intimidation, underground wealth, brutal monsters, and black dragon supremacy.",
            "homm3_dungeon_hero_",
            "hero_homm3_dungeon_",
            "homm3_dungeon_faction_banner",
            "homm3_runtime_assets/faction_icons/homm3_dungeon/Icon_Faction_Dungeon.png",
            "homm3_dungeon_faction_card",
            "homm3_runtime_assets/town_scene_refs/homm3_dungeon/Dungeon-in-background.png",
            new[]
        {
            new UnitLine("h3_troglodyte", "dungeon", "trogl", "troglodyte"),
            new UnitLine("h3_harpy", "dungeon", "assassin"),
            new UnitLine("h3_beholder", "humans", "lightweaver"),
            new UnitLine("h3_medusa", "dungeon", "medusa"),
            new UnitLine("h3_minotaur", "dungeon", "minos"),
            new UnitLine("h3_manticore", "humans", "griffin"),
            new UnitLine("h3_red_dragon", "dungeon", "black_dragon"),
        }),
        new(
            "homm3_necropolis",
            "homm3_necropolis_city",
            "homm3_necropolis_city_icon",
            "homm3_runtime_assets/town_hud_icons/homm3_necropolis/fort_available.png",
            4.5f,
            "barracks_homm3_necropolis_",
            "homm3_runtime_assets/map_object_refs/homm3_necropolis_dwellings",
            new[]
            {
                "avwskel0.dir/00_00.png",
                "avwzomb0.dir/00_00.png",
                "avwwigh.dir/00_00.png",
                "avwvamp0.dir/00_00.png",
                "avwlich0.dir/00_00.png",
                "avwbkni0.dir/00_00.png",
                "avwbone0.dir/00_00.png",
            },
            new[] { "barracks_undead_", "barracks_necropolis_" },
            "Necropolis (HoMM3)",
            "The Necropolis raises tireless undead armies through skeleton growth, death magic, attrition, and late-stack scaling. Death knights and necromancers rely on immunities, drain, death cloud, curse, and dragon terror rather than living morale.",
            "homm3_necropolis_hero_",
            "hero_homm3_necropolis_",
            "homm3_necropolis_faction_banner",
            "homm3_runtime_assets/faction_icons/homm3_necropolis/Icon_Faction_Necropolis.png",
            "homm3_necropolis_faction_card",
            "homm3_runtime_assets/town_scene_refs/homm3_necropolis/Necropolis-in-background.png",
            new[]
        {
            new UnitLine("h3_skeleton", "undead", "skeleton"),
            new UnitLine("h3_walking_dead", "undead", "graverobber"),
            new UnitLine("h3_wight", "undead", "flicker"),
            new UnitLine("h3_vampire", "undead", "vampire"),
            new UnitLine("h3_lich", "undead", "lich"),
            new UnitLine("h3_black_knight", "undead", "avatar_of_war"),
            new UnitLine("h3_bone_dragon", "dungeon", "black_dragon"),
        }),
    };

    private static Dictionary<string, string> CustomToDonor = BuildCustomToDonor();
    private static Dictionary<string, string> StartupAssetPathsByRelativePath = new(StringComparer.OrdinalIgnoreCase);

    internal static int InitializeFromManifestDirectory(string manifestDirectory)
    {
        if (string.IsNullOrWhiteSpace(manifestDirectory))
            throw new InvalidOperationException("HoMM3 custom faction manifest directory was not provided.");

        var fullDirectory = Path.GetFullPath(manifestDirectory);
        if (!Directory.Exists(fullDirectory))
            throw new InvalidOperationException("HoMM3 custom faction manifest directory is missing: " + fullDirectory);

        var manifestPaths = Directory.GetFiles(fullDirectory, "homm3_*.json");
        Array.Sort(manifestPaths, StringComparer.OrdinalIgnoreCase);
        if (manifestPaths.Length == 0)
            throw new InvalidOperationException("HoMM3 custom faction manifest directory has no JSON manifests: " + fullDirectory);

        var definitions = new List<FactionDefinition>();
        var factionSids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var citySids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var nativeBiomes = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var dwellingPrefixes = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var unitSids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var directDwellingSids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var manifestPath in manifestPaths)
        {
            var definition = LoadManifest(manifestPath);
            if (!factionSids.Add(definition.FactionSid))
                throw new InvalidOperationException("Duplicate HoMM3 custom faction SID in manifests: " + definition.FactionSid);
            if (!citySids.Add(definition.CitySid))
                throw new InvalidOperationException("Duplicate HoMM3 custom city SID in manifests: " + definition.CitySid);
            if (!string.IsNullOrWhiteSpace(definition.NativeBiome) && !nativeBiomes.Add(definition.NativeBiome))
                throw new InvalidOperationException("Duplicate HoMM3 custom native biome in manifests: " + definition.NativeBiome);
            if (!dwellingPrefixes.Add(definition.DirectDwellingPrefix))
                throw new InvalidOperationException("Duplicate HoMM3 custom dwelling prefix in manifests: " + definition.DirectDwellingPrefix);
            for (var tier = 1; tier <= definition.UnitLines.Length; tier++)
            {
                var dwellingSid = definition.DirectDwellingPrefix + tier;
                if (!directDwellingSids.Add(dwellingSid))
                    throw new InvalidOperationException("Duplicate HoMM3 custom direct dwelling SID in manifests: " + dwellingSid);
            }
            foreach (var additional in definition.AdditionalRecruitmentLines)
            {
                if (!directDwellingSids.Add(additional.DirectDwellingSid))
                    throw new InvalidOperationException("Duplicate HoMM3 custom direct dwelling SID in manifests: " + additional.DirectDwellingSid);
            }

            foreach (var line in definition.AllUnitLines)
            {
                if (DonorFactionToPrefabFolder(line.DonorFactionSid) == null)
                    throw new InvalidOperationException(
                        manifestPath
                        + ": unit line "
                        + line.BaseSid
                        + " has unsupported donorFactionSid for native prefab resolution: "
                        + line.DonorFactionSid);
                foreach (var suffix in UnitSuffixes)
                {
                    var sid = line.CustomSidForSuffix(suffix);
                    if (!unitSids.Add(sid))
                        throw new InvalidOperationException("Duplicate HoMM3 custom unit SID in manifests: " + sid);
                }
            }

            definitions.Add(definition);
        }

        var pluginRoot = Directory.GetParent(fullDirectory)?.FullName;
        var startupAssetPaths = ValidateStartupAssetContracts(pluginRoot, definitions);

        Factions = definitions.ToArray();
        CustomToDonor = BuildCustomToDonor();
        StartupAssetPathsByRelativePath = startupAssetPaths;
        ReleaseUiPresentationEnabledFactionSids.Clear();
        foreach (var faction in Factions)
            ReleaseUiPresentationEnabledFactionSids.Add(faction.FactionSid);
        return Factions.Length;
    }

    private static FactionDefinition LoadManifest(string manifestPath)
    {
        JObject root;
        try
        {
            root = JObject.Parse(File.ReadAllText(manifestPath));
        }
        catch (Exception ex)
        {
            throw new InvalidOperationException("Failed to parse HoMM3 custom faction manifest " + manifestPath + ": " + ex.Message, ex);
        }

        var schemaVersion = OptionalInt(root, "schemaVersion", manifestPath) ?? 0;
        if (schemaVersion != 1)
            throw new InvalidOperationException(manifestPath + ": schemaVersion must be 1.");

        // Incomplete inventory/concept drafts (missing heroes/runtime/assets) must not live in
        // custom_factions/ — deploy copies every homm3_*.json into the plugin and startup
        // requires a full runtime manifest. Keep drafts under tools/homm3_import/faction_concepts/.
        // Active Factory and Bulwark production manifests belong in custom_factions/.
        if (root["heroes"] == null || root["runtime"] == null || root["assets"] == null)
        {
            throw new InvalidOperationException(
                manifestPath
                + ": not a runtime faction manifest (missing heroes/runtime/assets). "
                + "Move concept drafts out of custom_factions/ "
                + "(use tools/homm3_import/faction_concepts/) so plugin startup does not load them.");
        }

        var identity = RequiredObject(root, "identity", manifestPath);
        var coreOverlay = RequiredObject(root, "coreOverlay", manifestPath);
        var heroes = RequiredObject(root, "heroes", manifestPath);
        var assets = RequiredObject(root, "assets", manifestPath);
        var runtime = RequiredObject(root, "runtime", manifestPath);

        RequireExact(runtime, "customToDonorSource", "manifest", manifestPath);
        RequireExact(runtime, "reverseDonorLookup", "context_required", manifestPath);
        if (OptionalBool(runtime, "allowGlobalDonorReverseLookup", manifestPath) != false)
            throw new InvalidOperationException(manifestPath + ": runtime.allowGlobalDonorReverseLookup must be false.");

        var factionSid = RequiredString(identity, "factionSid", manifestPath);
        var citySid = RequiredString(identity, "citySid", manifestPath);
        var nativeBiome = RequiredString(identity, "nativeBiome", manifestPath);
        var defaultDonorFactionSid = RequiredString(identity, "donorFactionSid", manifestPath);
        var directDwellingPrefix = RequiredString(coreOverlay, "directDwellingPrefix", manifestPath);
        var displayName = RequiredString(runtime, "displayName", manifestPath);
        var description = RequiredString(runtime, "description", manifestPath);
        var heroPrefix = RequiredString(heroes, "heroPrefix", manifestPath);
        var heroIconPrefix = RequiredString(heroes, "iconPrefix", manifestPath);
        var heroNames = OptionalStringArray(heroes, "names", manifestPath);
        var heroCount = OptionalInt(heroes, "count", manifestPath) ?? 18;
        if (heroNames != null && heroNames.Length < heroCount)
            throw new InvalidOperationException(manifestPath + ": heroes.names must cover heroes.count when present.");

        var unitVariants = RequiredArray(root, "unitVariants", manifestPath);
        if (unitVariants.Count != UnitSuffixes.Length)
            throw new InvalidOperationException(manifestPath + ": unitVariants must contain base, upgrade, and alternate upgrade suffixes.");
        for (var i = 0; i < UnitSuffixes.Length; i++)
        {
            if (!string.Equals(unitVariants[i]?.ToString(), UnitSuffixes[i], StringComparison.Ordinal))
                throw new InvalidOperationException(manifestPath + ": unitVariants must be ['', '_upg', '_upg_alt'].");
        }

        var unitLineTokens = RequiredArray(root, "unitLines", manifestPath);
        if (unitLineTokens.Count != 7)
            throw new InvalidOperationException(manifestPath + ": unitLines must contain exactly seven base creature lines.");
        var unitLines = new UnitLine[unitLineTokens.Count];
        for (var i = 0; i < unitLineTokens.Count; i++)
        {
            var line = ParseObjectToken(unitLineTokens[i], "unitLines[" + i + "]", manifestPath);

            var tier = OptionalInt(line, "tier", manifestPath) ?? 0;
            if (tier != i + 1)
                throw new InvalidOperationException(manifestPath + ": unitLines tiers must be 1..7 in order.");

            var baseSid = RequiredString(line, "baseSid", manifestPath);
            var donorFactionSid = OptionalString(line, "donorFactionSid", manifestPath) ?? defaultDonorFactionSid;
            var donorBaseSid = RequiredString(line, "donorBaseSid", manifestPath);
            var donorPrefabBaseSid = OptionalString(line, "donorPrefabBaseSid", manifestPath);
            var variantSids = OptionalObject(line, "variantSids", manifestPath);
            var explicitBase = OptionalString(variantSids, "", manifestPath);
            var branchFamily = OptionalString(line, "branchFamily", manifestPath);
            if (string.Equals(factionSid, "homm3_factory", StringComparison.Ordinal)
                && !string.Equals(branchFamily, "natural", StringComparison.Ordinal)
                && !string.Equals(branchFamily, "industrial", StringComparison.Ordinal))
                throw new InvalidOperationException(manifestPath + ": Factory unit line " + baseSid + " branchFamily must be natural or industrial.");
            if (!string.IsNullOrEmpty(explicitBase) && !string.Equals(explicitBase, baseSid, StringComparison.Ordinal))
                throw new InvalidOperationException(manifestPath + ": unit line " + baseSid + " variantSids[''] must match baseSid.");

            unitLines[i] = new UnitLine(
                baseSid,
                donorFactionSid,
                donorBaseSid,
                donorPrefabBaseSid,
                OptionalString(variantSids, "_upg", manifestPath),
                OptionalString(variantSids, "_upg_alt", manifestPath),
                branchFamily);
        }
        var additionalLineTokens = OptionalArray(root, "additionalRecruitmentLines", manifestPath) ?? new JArray();
        var additionalRecruitmentLines = new AdditionalRecruitmentLine[additionalLineTokens.Count];
        var lineIds = new HashSet<string>(StringComparer.Ordinal);
        var recruitmentSlots = new HashSet<string>(StringComparer.Ordinal);
        var cityBuildingSids = new HashSet<string>(StringComparer.Ordinal);
        var directDwellingSids = new HashSet<string>(StringComparer.Ordinal);
        for (var tier = 1; tier <= unitLines.Length; tier++)
        {
            recruitmentSlots.Add("Tier_" + tier);
            cityBuildingSids.Add("Build_Tier_" + tier);
            directDwellingSids.Add(directDwellingPrefix + tier);
        }
        for (var i = 0; i < additionalLineTokens.Count; i++)
        {
            var label = "additionalRecruitmentLines[" + i + "]";
            var line = ParseObjectToken(additionalLineTokens[i], label, manifestPath);
            var lineId = RequiredString(line, "lineId", manifestPath);
            var tier = OptionalInt(line, "tier", manifestPath) ?? 0;
            var recruitmentSlotSid = RequiredString(line, "recruitmentSlotSid", manifestPath);
            var cityBuildingSid = RequiredString(line, "cityBuildingSid", manifestPath);
            var directDwellingSid = RequiredString(line, "directDwellingSid", manifestPath);
            var donorDwellingSid = RequiredString(line, "donorDwellingSid", manifestPath);
            var dwellingBillboardImage = NormalizePluginRelativePath(
                RequiredString(line, "dwellingBillboardImage", manifestPath),
                manifestPath);
            if (!IsLowerManifestIdentifier(lineId))
                throw new InvalidOperationException(manifestPath + ": " + label + ".lineId must be a lowercase manifest identifier.");
            if (tier < 1 || tier > 7)
                throw new InvalidOperationException(manifestPath + ": " + label + ".tier must be 1..7.");
            if (!IsNativeSid(recruitmentSlotSid))
                throw new InvalidOperationException(manifestPath + ": " + label + ".recruitmentSlotSid must be a native scene-slot identifier.");
            if (!cityBuildingSid.StartsWith("Build_", StringComparison.Ordinal) || !IsNativeSid(cityBuildingSid))
                throw new InvalidOperationException(manifestPath + ": " + label + ".cityBuildingSid must be a Build_* SID.");
            if (!directDwellingSid.StartsWith("barracks_", StringComparison.Ordinal) || !IsNativeSid(directDwellingSid))
                throw new InvalidOperationException(manifestPath + ": " + label + ".directDwellingSid must be a barracks_* SID.");
            if (!donorDwellingSid.StartsWith("barracks_", StringComparison.Ordinal) || !IsNativeSid(donorDwellingSid))
                throw new InvalidOperationException(manifestPath + ": " + label + ".donorDwellingSid must be a barracks_* SID.");
            if (!lineIds.Add(lineId))
                throw new InvalidOperationException(manifestPath + ": duplicate additional recruitment lineId " + lineId + ".");
            if (!recruitmentSlots.Add(recruitmentSlotSid))
                throw new InvalidOperationException(manifestPath + ": duplicate recruitment slot SID " + recruitmentSlotSid + ".");
            if (!cityBuildingSids.Add(cityBuildingSid))
                throw new InvalidOperationException(manifestPath + ": duplicate recruitment building SID " + cityBuildingSid + ".");
            if (!directDwellingSids.Add(directDwellingSid))
                throw new InvalidOperationException(manifestPath + ": duplicate direct dwelling SID " + directDwellingSid + ".");

            var baseSid = RequiredString(line, "baseSid", manifestPath);
            var donorFactionSid = OptionalString(line, "donorFactionSid", manifestPath) ?? defaultDonorFactionSid;
            var donorBaseSid = RequiredString(line, "donorBaseSid", manifestPath);
            var donorPrefabBaseSid = OptionalString(line, "donorPrefabBaseSid", manifestPath);
            var variantSids = OptionalObject(line, "variantSids", manifestPath);
            var explicitBase = OptionalString(variantSids, "", manifestPath);
            var branchFamily = OptionalString(line, "branchFamily", manifestPath);
            if (!string.IsNullOrEmpty(explicitBase) && !string.Equals(explicitBase, baseSid, StringComparison.Ordinal))
                throw new InvalidOperationException(manifestPath + ": unit line " + baseSid + " variantSids[''] must match baseSid.");
            if (string.Equals(factionSid, "homm3_factory", StringComparison.Ordinal)
                && !string.Equals(branchFamily, "natural", StringComparison.Ordinal)
                && !string.Equals(branchFamily, "industrial", StringComparison.Ordinal))
                throw new InvalidOperationException(manifestPath + ": Factory unit line " + baseSid + " branchFamily must be natural or industrial.");
            var unitLine = new UnitLine(
                baseSid,
                donorFactionSid,
                donorBaseSid,
                donorPrefabBaseSid,
                OptionalString(variantSids, "_upg", manifestPath),
                OptionalString(variantSids, "_upg_alt", manifestPath),
                branchFamily);
            additionalRecruitmentLines[i] = new AdditionalRecruitmentLine(
                lineId,
                tier,
                recruitmentSlotSid,
                cityBuildingSid,
                directDwellingSid,
                donorDwellingSid,
                dwellingBillboardImage,
                unitLine);
        }

        var recruitmentBaseSids = OptionalArray(root, "recruitmentBaseSids", manifestPath);
        if (recruitmentBaseSids != null)
        {
            if (recruitmentBaseSids.Count != unitLines.Length)
                throw new InvalidOperationException(manifestPath + ": recruitmentBaseSids must match unit line count.");
            for (var i = 0; i < unitLines.Length; i++)
            {
                if (!string.Equals(recruitmentBaseSids[i]?.ToString(), unitLines[i].BaseSid, StringComparison.Ordinal))
                    throw new InvalidOperationException(manifestPath + ": recruitmentBaseSids must match unitLines baseSid order.");
            }
        }

        var dwellingBillboardImages = RequiredStringArray(runtime, "dwellingBillboardImages", manifestPath);
        if (dwellingBillboardImages.Length != unitLines.Length)
            throw new InvalidOperationException(manifestPath + ": runtime.dwellingBillboardImages must contain seven tier images.");
        for (var i = 0; i < dwellingBillboardImages.Length; i++)
            dwellingBillboardImages[i] = NormalizePluginRelativePath(dwellingBillboardImages[i], manifestPath);
        var dwellingDonorPrefixes = RequiredStringArray(runtime, "dwellingDonorPrefixes", manifestPath);
        if (dwellingDonorPrefixes.Length == 0)
            throw new InvalidOperationException(manifestPath + ": runtime.dwellingDonorPrefixes must not be empty.");

        return new FactionDefinition(
            factionSid,
            citySid,
            nativeBiome,
            defaultDonorFactionSid,
            factionSid + "_city_icon",
            NormalizePluginRelativePath(RequiredString(assets, "cityIcon", manifestPath), manifestPath),
            RequiredFloat(runtime, "cityMapBillboardHeight", manifestPath),
            directDwellingPrefix,
            NormalizePluginRelativePath(RequiredString(assets, "dwellingBillboardFolder", manifestPath), manifestPath).TrimEnd('/'),
            dwellingBillboardImages,
            dwellingDonorPrefixes,
            displayName,
            description,
            heroPrefix,
            heroIconPrefix,
            heroCount,
            heroNames,
            factionSid + "_faction_banner",
            NormalizePluginRelativePath(RequiredString(assets, "factionIcon", manifestPath), manifestPath),
            factionSid + "_faction_card",
            NormalizePluginRelativePath(RequiredString(assets, "factionCard", manifestPath), manifestPath),
            unitLines,
            additionalRecruitmentLines,
            cityMapBillboardRelativePath: NormalizePluginRelativePath(
                OptionalString(assets, "cityBillboard", manifestPath) ?? RequiredString(assets, "cityIcon", manifestPath),
                manifestPath));
    }

    internal static bool TryGetStartupAssetPath(string relativePath, out string fullPath)
    {
        fullPath = null;
        if (string.IsNullOrWhiteSpace(relativePath))
            return false;
        var normalized = NormalizePluginRelativePath(relativePath, "startup asset lookup");
        return StartupAssetPathsByRelativePath.TryGetValue(normalized, out fullPath);
    }

    private static Dictionary<string, string> ValidateStartupAssetContracts(string pluginRoot, List<FactionDefinition> definitions)
    {
        if (string.IsNullOrWhiteSpace(pluginRoot))
            throw new InvalidOperationException("HoMM3 custom faction plugin root could not be resolved from manifest directory.");

        var fullPluginRoot = Path.GetFullPath(pluginRoot);
        if (!Directory.Exists(fullPluginRoot))
            throw new InvalidOperationException("HoMM3 custom faction plugin root is missing: " + fullPluginRoot);

        var assetPaths = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var faction in definitions)
        {
            RequirePluginFile(fullPluginRoot, faction.FactionIconRelativePath, faction.FactionSid + " assets.factionIcon", assetPaths);
            RequirePluginFile(fullPluginRoot, faction.FactionCardRelativePath, faction.FactionSid + " assets.factionCard", assetPaths);
            RequirePluginFile(fullPluginRoot, faction.CityIconRelativePath, faction.FactionSid + " assets.cityIcon", assetPaths);
            RequirePluginFile(fullPluginRoot, faction.CityMapBillboardRelativePath, faction.FactionSid + " assets.cityBillboard", assetPaths);

            if (string.IsNullOrWhiteSpace(faction.DwellingBillboardFolder))
                throw new InvalidOperationException(faction.FactionSid + ": assets.dwellingBillboardFolder must not be empty.");

            for (var i = 0; i < faction.DwellingBillboardImages.Length; i++)
            {
                var tier = i + 1;
                var relativePath = faction.DwellingBillboardFolder + "/" + faction.DwellingBillboardImages[i];
                RequirePluginFile(
                    fullPluginRoot,
                    relativePath,
                    faction.FactionSid + " runtime.dwellingBillboardImages[" + tier + "]",
                    assetPaths);
            }
            foreach (var additional in faction.AdditionalRecruitmentLines)
            {
                var relativePath = faction.DwellingBillboardFolder + "/" + additional.DwellingBillboardImage;
                RequirePluginFile(
                    fullPluginRoot,
                    relativePath,
                    faction.FactionSid + " additionalRecruitmentLines[" + additional.LineId + "].dwellingBillboardImage",
                    assetPaths);
            }
        }
        return assetPaths;
    }

    private static void RequirePluginFile(string pluginRoot, string relativePath, string label, Dictionary<string, string> assetPaths)
    {
        var normalized = NormalizePluginRelativePath(relativePath, label);
        var fullPath = ResolvePluginRelativePath(pluginRoot, normalized, label);
        if (!File.Exists(fullPath))
        {
            throw new InvalidOperationException(
                "HoMM3 custom faction startup asset is missing: "
                + label
                + " ("
                + relativePath
                + ") -> "
                + fullPath);
        }
        assetPaths[normalized] = fullPath;
    }

    private static string ResolvePluginRelativePath(string pluginRoot, string relativePath, string label)
    {
        if (string.IsNullOrWhiteSpace(relativePath))
            throw new InvalidOperationException("HoMM3 custom faction startup asset path is empty: " + label);

        var normalizedRelative = relativePath.Replace('/', Path.DirectorySeparatorChar);
        var fullRoot = Path.GetFullPath(pluginRoot);
        var fullPath = Path.GetFullPath(Path.Combine(fullRoot, normalizedRelative));
        var rootWithSeparator = fullRoot.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        if (!fullPath.StartsWith(rootWithSeparator, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException(
                "HoMM3 custom faction startup asset escapes plugin root: "
                + label
                + " ("
                + relativePath
                + ")");
        return fullPath;
    }

    private static JObject RequiredObject(JObject parent, string name, string manifestPath)
    {
        var token = parent?[name];
        if (token == null)
            throw new InvalidOperationException(manifestPath + ": missing object " + name + ".");
        return ParseObjectToken(token, name, manifestPath);
    }

    private static JObject OptionalObject(JObject parent, string name, string manifestPath)
    {
        var token = parent?[name];
        return token == null ? null : ParseObjectToken(token, name, manifestPath);
    }

    private static JObject ParseObjectToken(JToken token, string name, string manifestPath)
    {
        if (token == null || token.Type != JTokenType.Object)
            throw new InvalidOperationException(manifestPath + ": " + name + " must be an object.");
        return token as JObject ?? JObject.Parse(token.ToString());
    }

    private static JArray RequiredArray(JObject parent, string name, string manifestPath)
    {
        var token = parent?[name];
        if (token == null)
            throw new InvalidOperationException(manifestPath + ": missing array " + name + ".");
        return ParseArrayToken(token, name, manifestPath);
    }

    private static JArray OptionalArray(JObject parent, string name, string manifestPath)
    {
        var token = parent?[name];
        return token == null ? null : ParseArrayToken(token, name, manifestPath);
    }

    private static JArray ParseArrayToken(JToken token, string name, string manifestPath)
    {
        if (token == null || token.Type != JTokenType.Array)
            throw new InvalidOperationException(manifestPath + ": " + name + " must be an array.");
        return token as JArray ?? JArray.Parse(token.ToString());
    }

    private static string RequiredString(JObject parent, string name, string manifestPath)
    {
        var value = OptionalString(parent, name, manifestPath);
        if (string.IsNullOrWhiteSpace(value))
            throw new InvalidOperationException(manifestPath + ": missing string " + name + ".");
        return value;
    }

    private static string OptionalString(JObject parent, string name, string manifestPath)
    {
        var token = parent?[name];
        if (token == null)
            return null;
        if (token.Type != JTokenType.String)
            throw new InvalidOperationException(manifestPath + ": " + name + " must be a string.");
        var value = token.ToString();
        return string.IsNullOrWhiteSpace(value) ? null : value.Trim();
    }

    private static void RequireExact(JObject parent, string name, string expected, string manifestPath)
    {
        var value = RequiredString(parent, name, manifestPath);
        if (!string.Equals(value, expected, StringComparison.Ordinal))
            throw new InvalidOperationException(manifestPath + ": " + name + " must be " + expected + ".");
    }

    private static int? OptionalInt(JObject parent, string name, string manifestPath)
    {
        var value = parent?[name];
        if (value == null)
            return null;
        if (value.Type != JTokenType.Integer)
            throw new InvalidOperationException(manifestPath + ": " + name + " must be an integer.");
        return (int)value;
    }

    private static bool? OptionalBool(JObject parent, string name, string manifestPath)
    {
        var value = parent?[name];
        if (value == null)
            return null;
        if (value.Type != JTokenType.Boolean)
            throw new InvalidOperationException(manifestPath + ": " + name + " must be a boolean.");
        return (bool)value;
    }

    private static float RequiredFloat(JObject parent, string name, string manifestPath)
    {
        var value = OptionalFloat(parent, name, manifestPath);
        if (value == null || value <= 0f)
            throw new InvalidOperationException(manifestPath + ": " + name + " must be a positive number.");
        return value.Value;
    }

    private static float? OptionalFloat(JObject parent, string name, string manifestPath)
    {
        var value = parent?[name];
        if (value == null)
            return null;
        if (value.Type != JTokenType.Float && value.Type != JTokenType.Integer)
            throw new InvalidOperationException(manifestPath + ": " + name + " must be a number.");
        return (float)value;
    }

    private static string[] RequiredStringArray(JObject parent, string name, string manifestPath)
    {
        var array = RequiredArray(parent, name, manifestPath);
        return ParseStringArray(array, name, manifestPath);
    }

    private static string[] OptionalStringArray(JObject parent, string name, string manifestPath)
    {
        var array = OptionalArray(parent, name, manifestPath);
        return array == null ? null : ParseStringArray(array, name, manifestPath);
    }

    private static string[] ParseStringArray(JArray array, string name, string manifestPath)
    {
        var values = new string[array.Count];
        for (var i = 0; i < array.Count; i++)
        {
            var token = array[i];
            if (token == null || token.Type != JTokenType.String)
                throw new InvalidOperationException(manifestPath + ": " + name + "[" + i + "] must be a string.");
            var value = token.ToString();
            if (string.IsNullOrWhiteSpace(value))
                throw new InvalidOperationException(manifestPath + ": " + name + "[" + i + "] must be a non-empty string.");
            values[i] = value.Trim();
        }
        return values;
    }

    private static bool IsNativeSid(string value)
    {
        if (string.IsNullOrWhiteSpace(value) || !char.IsLetter(value[0]))
            return false;
        for (var i = 1; i < value.Length; i++)
        {
            var ch = value[i];
            if (!char.IsLetterOrDigit(ch) && ch != '_')
                return false;
        }
        return true;
    }

    private static bool IsLowerManifestIdentifier(string value)
    {
        if (string.IsNullOrWhiteSpace(value) || value[0] < 'a' || value[0] > 'z')
            return false;
        for (var i = 1; i < value.Length; i++)
        {
            var ch = value[i];
            if ((ch < 'a' || ch > 'z') && (ch < '0' || ch > '9') && ch != '_')
                return false;
        }
        return true;
    }
    private static string NormalizePluginRelativePath(string path, string manifestPath)
    {
        var normalized = path.Replace('\\', '/').Trim();
        const string marker = "OfflineUnlockMod/";
        var markerIndex = normalized.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
        if (markerIndex >= 0)
            normalized = normalized.Substring(markerIndex + marker.Length);
        while (normalized.StartsWith("/", StringComparison.Ordinal))
            normalized = normalized.Substring(1);
        if (string.IsNullOrWhiteSpace(normalized)
            || normalized.IndexOf(':') >= 0
            || normalized.StartsWith("../", StringComparison.Ordinal)
            || normalized.IndexOf("/../", StringComparison.Ordinal) >= 0)
            throw new InvalidOperationException(manifestPath + ": asset path must resolve under OfflineUnlockMod plugin root: " + path);
        return normalized;
    }

    internal static bool TryGetDonorSid(string sid, out string donorSid)
    {
        donorSid = null;
        return !string.IsNullOrWhiteSpace(sid) && CustomToDonor.TryGetValue(sid.Trim(), out donorSid);
    }

    internal static bool TryGetDonorBattlePrefabPath(string sid, out string donorPath)
    {
        donorPath = null;
        if (string.IsNullOrWhiteSpace(sid))
            return false;

        var key = sid.Trim();
        foreach (var faction in Factions)
        {
            foreach (var line in faction.AllUnitLines)
            {
                foreach (var suffix in UnitSuffixes)
                {
                    if (!string.Equals(line.CustomSidForSuffix(suffix), key, StringComparison.OrdinalIgnoreCase))
                        continue;
                    var folder = DonorFactionToPrefabFolder(line.DonorFactionSid);
                    if (folder == null)
                        return false;
                    donorPath = "units/" + folder + "/1Prefabs/" + line.DonorPrefabBaseSid + suffix;
                    return true;
                }
            }
        }

        return false;
    }

    internal static bool IsCustomUnitSid(string sid)
    {
        return !string.IsNullOrWhiteSpace(sid) && CustomToDonor.ContainsKey(sid.Trim());
    }

    internal static IEnumerable<KeyValuePair<string, string>> EnumerateUnitDonorMappings()
    {
        foreach (var pair in CustomToDonor)
            yield return pair;
    }

    internal static IEnumerable<string> EnumerateCustomUnitSids()
    {
        foreach (var pair in CustomToDonor)
            yield return pair.Key;
    }

    internal static IEnumerable<string> EnumerateRequiredHeroPortraitKeys()
    {
        foreach (var faction in Factions)
        {
            for (var i = 1; i <= faction.HeroCount; i++)
                yield return faction.HeroPrefix + i;
        }
    }

    internal static IEnumerable<string> EnumerateFactionSids()
    {
        foreach (var faction in Factions)
            yield return faction.FactionSid;
    }

    internal static IEnumerable<string> EnumerateCitySids()
    {
        foreach (var faction in Factions)
            yield return faction.CitySid;
    }

    internal static IEnumerable<string> EnumerateDirectDwellingSids()
    {
        foreach (var faction in Factions)
        {
            for (var tier = 1; tier <= faction.DwellingBillboardImages.Length; tier++)
                yield return faction.DirectDwellingPrefix + tier;
            foreach (var additional in faction.AdditionalRecruitmentLines)
                yield return additional.DirectDwellingSid;
        }
    }

    internal static bool TryGetDirectDwellingSidForFactionTier(string factionSid, int tier, out string dwellingSid)
    {
        dwellingSid = null;
        if (tier < 1 || !TryGetFaction(factionSid, out var faction))
            return false;
        if (tier > faction.DwellingBillboardImages.Length)
            return false;

        var candidate = faction.DirectDwellingPrefix + tier;
        if (!TryGetDwellingBillboardAsset(candidate, out _))
            return false;

        dwellingSid = candidate;
        return true;
    }

    internal static IEnumerable<string> EnumerateReleaseUiPresentationFactionSids()
    {
        foreach (var faction in Factions)
        {
            if (ReleaseUiPresentationEnabledFactionSids.Contains(faction.FactionSid))
                yield return faction.FactionSid;
        }
    }

    internal static bool IsReleaseUiPresentationEnabledFactionSid(string sid)
    {
        return !string.IsNullOrWhiteSpace(sid)
            && ReleaseUiPresentationEnabledFactionSids.Contains(sid.Trim());
    }

    internal static bool TryGetCustomSidForDonorInFaction(string donorSid, string factionSid, out string customSid)
    {
        customSid = null;
        if (string.IsNullOrWhiteSpace(donorSid) || !TryGetFaction(factionSid, out var faction))
            return false;

        var key = donorSid.Trim();
        foreach (var line in faction.AllUnitLines)
        {
            foreach (var suffix in UnitSuffixes)
            {
                if (string.Equals(line.DonorBaseSid + suffix, key, StringComparison.OrdinalIgnoreCase))
                {
                    customSid = line.CustomSidForSuffix(suffix);
                    return true;
                }
            }
        }
        return false;
    }

    internal static bool TryGetFactionSidForCustomUnitSid(string unitSid, out string factionSid)
    {
        factionSid = null;
        if (string.IsNullOrWhiteSpace(unitSid))
            return false;

        var key = unitSid.Trim();
        foreach (var faction in Factions)
        {
            foreach (var line in faction.AllUnitLines)
            {
                foreach (var suffix in UnitSuffixes)
                {
                    if (!string.Equals(line.CustomSidForSuffix(suffix), key, StringComparison.OrdinalIgnoreCase))
                        continue;
                    factionSid = faction.FactionSid;
                    return true;
                }
            }
        }

        return false;
    }

    internal static bool TryGetManifestUnitBranch(string customUnitSid, out string baseSid, out string branchFamily)
    {
        baseSid = null;
        branchFamily = null;
        if (string.IsNullOrWhiteSpace(customUnitSid))
            return false;

        var key = customUnitSid.Trim();
        foreach (var faction in Factions)
        {
            foreach (var line in faction.AllUnitLines)
            {
                if (!line.MatchesCustomSid(key))
                    continue;
                if (string.IsNullOrWhiteSpace(line.BranchFamily))
                    return false;
                baseSid = line.BaseSid;
                branchFamily = line.BranchFamily;
                return true;
            }
        }
        return false;
    }
    internal static bool IsCustomFactionSid(string sid)
    {
        if (string.IsNullOrWhiteSpace(sid))
            return false;
        var key = sid.Trim();
        foreach (var faction in Factions)
        {
            if (string.Equals(faction.FactionSid, key, StringComparison.OrdinalIgnoreCase))
                return true;
        }
        return false;
    }

    internal static bool IsCustomCitySid(string sid)
    {
        if (string.IsNullOrWhiteSpace(sid))
            return false;
        var key = ResolveMapBillboardSidAlias(sid.Trim());
        foreach (var faction in Factions)
        {
            if (string.Equals(faction.CitySid, key, StringComparison.OrdinalIgnoreCase))
                return true;
        }
        return false;
    }

    internal static bool TryGetFactionSidForCitySid(string citySid, out string factionSid)
    {
        factionSid = null;
        if (string.IsNullOrWhiteSpace(citySid))
            return false;
        var key = ResolveMapBillboardSidAlias(citySid.Trim());
        foreach (var faction in Factions)
        {
            if (!string.Equals(faction.CitySid, key, StringComparison.OrdinalIgnoreCase))
                continue;
            factionSid = faction.FactionSid;
            return true;
        }
        return false;
    }

    internal static bool TryGetFactionSidForNativeBiome(string nativeBiome, out string factionSid)
    {
        factionSid = null;
        if (string.IsNullOrWhiteSpace(nativeBiome))
            return false;
        var normalized = nativeBiome.Trim();
        var matched = false;
        foreach (var faction in Factions)
        {
            if (!string.IsNullOrWhiteSpace(faction.NativeBiome)
                && string.Equals(faction.NativeBiome, normalized, StringComparison.OrdinalIgnoreCase))
            {
                if (matched)
                {
                    factionSid = null;
                    return false;
                }
                factionSid = faction.FactionSid;
                matched = true;
            }
        }
        return matched;
    }

    /// <summary>
    /// Maps donor Core fraction strings (e.g. <c>dungeon</c>) and custom city config ids
    /// (e.g. <c>homm3_stronghold_city</c>) to the manifest HoMM3 faction sid used for town UI.
    /// </summary>
    internal static bool TryResolveTownPresentationFactionSid(string rawFraction, string cityConfigSid, out string presentationFactionSid)
    {
        presentationFactionSid = null;
        if (!string.IsNullOrWhiteSpace(rawFraction)
            && IsReleaseUiPresentationEnabledFactionSid(rawFraction.Trim()))
        {
            presentationFactionSid = rawFraction.Trim();
            return true;
        }

        if (TryGetFactionSidForCitySid(cityConfigSid, out presentationFactionSid)
            && IsReleaseUiPresentationEnabledFactionSid(presentationFactionSid))
            return true;

        return false;
    }

    internal static string[] GetRecruitmentBaseSids(string factionSid)
    {
        return TryGetFaction(factionSid, out var faction) ? faction.RecruitmentBaseSids : null;
    }

    internal static bool TryGetRecruitmentSidsForBuilding(string factionSid, string buildingSid, int level, out string[] unitSids)
    {
        unitSids = null;
        if (!TryGetFaction(factionSid, out var faction))
            return false;
        foreach (var additional in faction.AdditionalRecruitmentLines)
        {
            if (!string.Equals(additional.CityBuildingSid, buildingSid, StringComparison.Ordinal))
                continue;
            var additionalLine = additional.Line;
            if (level <= 1)
            {
                unitSids = new[] { additionalLine.CustomSidForSuffix("") };
                return true;
            }
            var additionalUpgrades = new List<string>(2);
            var upgrade = additionalLine.CustomSidForSuffix("_upg");
            var alternate = additionalLine.CustomSidForSuffix("_upg_alt");
            if (!string.IsNullOrWhiteSpace(upgrade))
                additionalUpgrades.Add(upgrade);
            if (!string.IsNullOrWhiteSpace(alternate) && !string.Equals(alternate, upgrade, StringComparison.OrdinalIgnoreCase))
                additionalUpgrades.Add(alternate);
            unitSids = additionalUpgrades.ToArray();
            return unitSids.Length > 0;
        }
        if (!TryParseTierBuildingSid(buildingSid, out var tier))
            return false;
        var index = tier - 1;
        if (index < 0 || index >= faction.UnitLines.Length)
            return false;

        var line = faction.UnitLines[index];
        if (level <= 1)
        {
            unitSids = new[] { line.CustomSidForSuffix("") };
            return true;
        }

        var upgrades = new List<string>(2);
        var upgradeSid = line.CustomSidForSuffix("_upg");
        if (!string.IsNullOrWhiteSpace(upgradeSid))
            upgrades.Add(upgradeSid);
        var alternateSid = line.CustomSidForSuffix("_upg_alt");
        if (!string.IsNullOrWhiteSpace(alternateSid)
            && !string.Equals(alternateSid, upgradeSid, StringComparison.OrdinalIgnoreCase))
            upgrades.Add(alternateSid);
        unitSids = upgrades.ToArray();
        return unitSids.Length > 0;
    }

    internal static string GetCitySidForFaction(string factionSid)
    {
        return TryGetFaction(factionSid, out var faction) ? faction.CitySid : null;
    }

    internal static string GetBuildingIconKeyPrefix(string factionSid)
    {
        return TryGetFaction(factionSid, out var faction) ? faction.FactionSid + "_building_" : null;
    }

    internal static bool TryGetFactionDisplayText(string factionSid, out string displayName, out string description)
    {
        displayName = null;
        description = null;
        if (!TryGetFaction(factionSid, out var faction))
            return false;
        displayName = faction.DisplayName;
        description = faction.Description;
        return true;
    }

    internal static bool TryGetFactionSpriteAsset(string factionSid, bool card, out string key, out string relativePath)
    {
        key = null;
        relativePath = null;
        if (!TryGetFaction(factionSid, out var faction))
            return false;
        key = card ? faction.FactionCardSpriteKey : faction.FactionIconSpriteKey;
        relativePath = card ? faction.FactionCardRelativePath : faction.FactionIconRelativePath;
        return true;
    }

    internal static bool TryGetFactionSpriteAssetByKey(string spriteKey, out string factionSid, out bool card)
    {
        factionSid = null;
        card = false;
        if (string.IsNullOrWhiteSpace(spriteKey))
            return false;
        var key = spriteKey.Trim();
        foreach (var faction in Factions)
        {
            if (string.Equals(key, faction.FactionIconSpriteKey, StringComparison.Ordinal))
            {
                factionSid = faction.FactionSid;
                return true;
            }
            if (string.Equals(key, faction.FactionCardSpriteKey, StringComparison.Ordinal))
            {
                factionSid = faction.FactionSid;
                card = true;
                return true;
            }
        }
        return false;
    }

    internal static bool TryGetFactionSidForCustomUiIconKey(string iconKey, out string factionSid)
    {
        factionSid = null;
        if (string.IsNullOrWhiteSpace(iconKey))
            return false;
        var key = iconKey.Trim();
        foreach (var faction in Factions)
        {
            if (key.StartsWith("sub_class_" + faction.FactionSid + "_", StringComparison.Ordinal)
                || key.StartsWith("fraction_law_" + faction.FactionSid + "_", StringComparison.Ordinal)
                || (key.StartsWith(faction.HeroPrefix, StringComparison.Ordinal) && key.EndsWith("_specialization_icon", StringComparison.Ordinal)))
            {
                factionSid = faction.FactionSid;
                return true;
            }
        }
        return false;
    }

    internal static bool TryGetCityIconAsset(string sid, out string key, out string relativePath)
    {
        key = null;
        relativePath = null;
        if (string.IsNullOrWhiteSpace(sid))
            return false;
        var candidate = sid.Trim();
        foreach (var faction in Factions)
        {
            if (IsCityIconAlias(candidate, faction))
            {
                key = faction.CityIconSpriteKey;
                relativePath = faction.CityIconRelativePath;
                return true;
            }
        }
        return false;
    }

    internal static bool TryGetFactionSidForCityIconKey(string sid, out string factionSid)
    {
        factionSid = null;
        if (string.IsNullOrWhiteSpace(sid))
            return false;

        var candidate = sid.Trim();
        foreach (var faction in Factions)
        {
            if (!IsCityIconAlias(candidate, faction))
                continue;
            factionSid = faction.FactionSid;
            return true;
        }
        return false;
    }

    // Explicit land-on city clone → canonical city SID map.
    // Barracks land-on clones use the shared prefix rewrite in ResolveMapBillboardSidAlias
    // (homm3_landon_barracks_{rest} → barracks_homm3_{rest}) so every faction/tier/neutral
    // dwelling is covered without a partial hard-coded list.
    private static readonly Dictionary<string, string> LandOnBillboardSidAliases = new(StringComparer.OrdinalIgnoreCase)
    {
        ["homm3_landon_castle_city"] = "homm3_castle_city",
        ["homm3_landon_dungeon_city"] = "homm3_dungeon_city",
    };

    /// <summary>
    /// Land-on visit-gate clones keep donor prefs under <c>homm3_landon_*</c> SIDs.
    /// Billboard assets stay keyed by the canonical custom city/dwelling SID.
    /// Unknown land-on SIDs are returned unchanged (fail closed at asset lookup).
    /// </summary>
    internal static string ResolveMapBillboardSidAlias(string sid)
    {
        if (string.IsNullOrWhiteSpace(sid))
            return sid;
        var candidate = sid.Trim();
        // Shared dwelling rewrite — must run before the city dictionary. Covers
        // homm3_landon_barracks_{faction}_{tier} and homm3_landon_barracks_neutral_{creature}.
        const string landOnBarracksPrefix = "homm3_landon_barracks_";
        if (candidate.StartsWith(landOnBarracksPrefix, StringComparison.OrdinalIgnoreCase))
        {
            var rest = candidate.Substring(landOnBarracksPrefix.Length);
            if (!string.IsNullOrWhiteSpace(rest))
                return "barracks_homm3_" + rest;
        }
        if (LandOnBillboardSidAliases.TryGetValue(candidate, out var mapped))
            return mapped;
        return candidate;
    }

    /// <summary>True when <paramref name="name"/> is the canonical city SID or a land-on alias of it.</summary>
    internal static bool MatchesCitySidOrLandOnAlias(string name, string citySid)
    {
        if (string.IsNullOrWhiteSpace(name) || string.IsNullOrWhiteSpace(citySid))
            return false;
        var candidate = name.Trim();
        var canonical = citySid.Trim();
        if (string.Equals(candidate, canonical, StringComparison.OrdinalIgnoreCase))
            return true;
        return string.Equals(ResolveMapBillboardSidAlias(candidate), canonical, StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>
    /// True when the live root is a land-on visit-gate city clone (homm3_landon_*_city).
    /// Land-on towns use south-center GATE ObjectConfig (nodes index 7). Billboard placement must
    /// sit on the 3x3 footprint center (SW +1 X / +1 north) so HoMM3 full-town art lines up with
    /// the town body; the art's bottom-center entrance then falls on the GATE. Do not use donor
    /// mesh bounds.center or the bare SW root (corner-gate look).
    /// </summary>
    internal static bool IsLandOnCityRootName(string name)
    {
        if (string.IsNullOrWhiteSpace(name))
            return false;
        var candidate = name.Trim();
        if (!LandOnBillboardSidAliases.TryGetValue(candidate, out var canonical))
            return false;
        return canonical.IndexOf("_city", StringComparison.OrdinalIgnoreCase) >= 0;
    }

    internal static IEnumerable<string> EnumerateLandOnAliasesForCitySid(string citySid)
    {
        if (string.IsNullOrWhiteSpace(citySid))
            yield break;
        var canonical = citySid.Trim();
        foreach (var pair in LandOnBillboardSidAliases)
        {
            if (string.Equals(pair.Value, canonical, StringComparison.Ordinal))
                yield return pair.Key;
        }
    }

    private static bool IsCityIconAlias(string candidate, FactionDefinition faction)
    {
        var resolved = ResolveMapBillboardSidAlias(candidate);
        return string.Equals(candidate, faction.CityIconSpriteKey, StringComparison.Ordinal)
               || string.Equals(candidate, faction.CitySid, StringComparison.Ordinal)
               || string.Equals(resolved, faction.CitySid, StringComparison.Ordinal)
               || string.Equals(candidate, faction.CitySid + "_object", StringComparison.Ordinal)
               || string.Equals(candidate, "city_" + faction.FactionSid, StringComparison.Ordinal)
               || string.Equals(candidate, "obj_city_" + faction.FactionSid, StringComparison.Ordinal)
               || string.Equals(candidate, "fraction_" + faction.FactionSid, StringComparison.Ordinal);
    }

    internal static bool TryGetCityMapBillboardAsset(string sid, out string relativePath, out float billboardHeight)
    {
        relativePath = null;
        billboardHeight = 0f;
        if (string.IsNullOrWhiteSpace(sid))
            return false;
        var candidate = ResolveMapBillboardSidAlias(sid);
        foreach (var faction in Factions)
        {
            if (!string.Equals(candidate, faction.CitySid, StringComparison.Ordinal))
                continue;
            relativePath = faction.CityMapBillboardRelativePath;
            billboardHeight = faction.CityMapBillboardHeight;
            return true;
        }
        return false;
    }

    internal static bool TryGetDwellingBillboardAsset(string sid, out string relativePath)
    {
        relativePath = null;
        if (string.IsNullOrWhiteSpace(sid))
            return false;
        var candidate = ResolveMapBillboardSidAlias(sid);
        if (Homm3NeutralDwellingRegistry.TryGetBillboardRelativePath(candidate, out relativePath))
            return true;
        foreach (var faction in Factions)
        {
            foreach (var additional in faction.AdditionalRecruitmentLines)
            {
                if (!string.Equals(candidate, additional.DirectDwellingSid, StringComparison.Ordinal))
                    continue;
                relativePath = faction.DwellingBillboardFolder + "/" + additional.DwellingBillboardImage;
                return true;
            }
            if (!candidate.StartsWith(faction.DirectDwellingPrefix, StringComparison.Ordinal))
                continue;
            var tierText = candidate.Substring(faction.DirectDwellingPrefix.Length);
            if (!int.TryParse(tierText, out var tier) || tier < 1 || tier > faction.DwellingBillboardImages.Length)
                return false;
            relativePath = faction.DwellingBillboardFolder + "/" + faction.DwellingBillboardImages[tier - 1];
            return true;
        }
        return false;
    }

    private static string ResolveDefaultCityMapBillboardRelativePath(string factionSid, string cityIconRelativePath)
    {
        switch (factionSid)
        {
            case "homm3_castle":
                return "homm3_runtime_assets/map_object_refs/homm3_castle_city/capitol.dir/00_00.png";
            case "homm3_conflux":
                return "homm3_runtime_assets/map_object_refs/homm3_conflux_city/capitol.dir/00_00.png";
            case "homm3_cove":
                return "homm3_runtime_assets/map_object_refs/homm3_cove_city/avccovz0.dir/00_00.png";
            case "homm3_dungeon":
                return "homm3_runtime_assets/map_object_refs/homm3_dungeon_city/capitol.dir/00_00.png";
            case "homm3_fortress":
                return "homm3_runtime_assets/map_object_refs/homm3_fortress_city/capitol.dir/00_00.png";
            case "homm3_inferno":
                return "homm3_runtime_assets/map_object_refs/homm3_inferno_city/capitol.dir/00_00.png";
            case "homm3_necropolis":
                return "homm3_runtime_assets/map_object_refs/homm3_necropolis_city/capitol.dir/00_00.png";
            case "homm3_rampart":
                return "homm3_runtime_assets/map_object_refs/homm3_rampart_city/capitol.dir/00_00.png";
            case "homm3_stronghold":
                return "homm3_runtime_assets/map_object_refs/homm3_stronghold_city/avcstrc0.dir/00_00.png";
            case "homm3_tower":
                return "homm3_runtime_assets/map_object_refs/homm3_tower_city/capitol.dir/00_00.png";
            default:
                return cityIconRelativePath;
        }
    }

    internal static bool TryGetDwellingSidForDonorPrefix(string rawSid, string donorPrefix, string factionSid, out string customSid)
    {
        customSid = null;
        if (string.IsNullOrWhiteSpace(rawSid) || string.IsNullOrWhiteSpace(donorPrefix) || !TryGetFaction(factionSid, out var faction))
            return false;
        var candidate = rawSid.Trim();
        if (!candidate.StartsWith(donorPrefix, StringComparison.Ordinal))
            return false;
        var tierText = candidate.Substring(donorPrefix.Length);
        if (!int.TryParse(tierText, out var tier) || tier < 1 || tier > faction.DwellingBillboardImages.Length)
            return false;
        customSid = faction.DirectDwellingPrefix + tier;
        return TryGetDwellingBillboardAsset(customSid, out _);
    }

    internal static bool TryGetDwellingSidForDonorAlias(string rawSid, string factionSid, out string customSid, out string donorPrefix)
    {
        customSid = null;
        donorPrefix = null;
        if (!TryGetFaction(factionSid, out var faction))
            return false;
        if (string.IsNullOrWhiteSpace(rawSid))
            return false;
        var candidate = rawSid.Trim();
        foreach (var additional in faction.AdditionalRecruitmentLines)
        {
            if (!string.Equals(candidate, additional.DonorDwellingSid, StringComparison.Ordinal))
                continue;
            customSid = additional.DirectDwellingSid;
            donorPrefix = additional.DonorDwellingSid;
            return true;
        }
        foreach (var prefix in faction.DwellingDonorPrefixes)
        {
            if (!TryGetDwellingSidForDonorPrefix(rawSid, prefix, factionSid, out customSid))
                continue;
            donorPrefix = prefix;
            return true;
        }
        return false;
    }

    internal static IEnumerable<DwellingDonorAlias> EnumerateDwellingDonorAliases(string rawSid)
    {
        if (string.IsNullOrWhiteSpace(rawSid))
            yield break;
        foreach (var faction in Factions)
        {
            if (!TryGetDwellingSidForDonorAlias(rawSid, faction.FactionSid, out var customSid, out var donorPrefix))
                continue;
            yield return new DwellingDonorAlias(faction.FactionSid, faction.CitySid, faction.DefaultDonorFactionSid, customSid, donorPrefix);
        }
    }

    internal static bool TryGetDwellingSidForUnitSid(string unitSid, out DwellingUnitMatch match)
    {
        match = default;
        if (string.IsNullOrWhiteSpace(unitSid))
            return false;

        var key = unitSid.Trim();
        foreach (var faction in Factions)
        {
            for (var i = 0; i < faction.UnitLines.Length; i++)
            {
                var line = faction.UnitLines[i];
                if (!line.MatchesCustomSid(key))
                    continue;

                var dwellingSid = faction.DirectDwellingPrefix + (i + 1);
                if (!TryGetDwellingBillboardAsset(dwellingSid, out _))
                    return false;

                match = new DwellingUnitMatch(faction.FactionSid, faction.CitySid, dwellingSid, i + 1, key);
                return true;
            }
            foreach (var additional in faction.AdditionalRecruitmentLines)
            {
                if (!additional.Line.MatchesCustomSid(key))
                    continue;
                if (!TryGetDwellingBillboardAsset(additional.DirectDwellingSid, out _))
                    return false;
                match = new DwellingUnitMatch(
                    faction.FactionSid,
                    faction.CitySid,
                    additional.DirectDwellingSid,
                    additional.Tier,
                    key);
                return true;
            }
        }

        return false;
    }

    internal static bool IsCustomFactionNameToken(string sid, out string factionSid)
    {
        factionSid = null;
        if (string.IsNullOrWhiteSpace(sid))
            return false;
        var key = sid.Trim();
        foreach (var faction in Factions)
        {
            if (string.Equals(key, faction.FactionSid, StringComparison.OrdinalIgnoreCase)
                || string.Equals(key, faction.FactionSid + "_name", StringComparison.OrdinalIgnoreCase))
            {
                factionSid = faction.FactionSid;
                return true;
            }
        }
        return false;
    }

    internal static bool IsCustomHeroSid(string sid)
    {
        if (string.IsNullOrWhiteSpace(sid))
            return false;
        var key = sid.Trim();
        foreach (var faction in Factions)
        {
            if (key.StartsWith(faction.HeroPrefix, StringComparison.Ordinal)
                || key.StartsWith(faction.HeroIconPrefix, StringComparison.Ordinal))
                return true;
        }
        return false;
    }

    internal static bool TryNormalizeHeroPortraitKey(string key, out string portraitKey)
    {
        portraitKey = null;
        if (string.IsNullOrWhiteSpace(key))
            return false;

        var sid = key.Trim();
        foreach (var faction in Factions)
        {
            if (TryBuildHeroPortraitKey(sid, faction.HeroPrefix, faction.HeroPrefix, out portraitKey)
                || TryBuildHeroPortraitKey(sid, faction.HeroIconPrefix, faction.HeroPrefix, out portraitKey))
                return true;
        }

        return false;
    }

    internal static bool TryGetHeroSidFromDisplayLabel(string key, out string heroSid)
    {
        heroSid = null;
        if (string.IsNullOrWhiteSpace(key))
            return false;

        var label = key.Trim();
        if (!TryParseHeroDisplayLabel(label, out var factionPrefix, out var index))
            return false;

        foreach (var faction in Factions)
        {
            if (!string.Equals(factionPrefix, faction.DisplayName, StringComparison.OrdinalIgnoreCase)
                && !string.Equals(factionPrefix, StripHomm3Suffix(faction.DisplayName), StringComparison.OrdinalIgnoreCase))
                continue;

            heroSid = faction.HeroPrefix + index;
            return true;
        }

        return false;
    }

    private static bool TryParseHeroDisplayLabel(string label, out string factionName, out int heroIndex)
    {
        factionName = null;
        heroIndex = 0;
        if (string.IsNullOrWhiteSpace(label))
            return false;

        var text = label.Trim();
        if (text.StartsWith("LOC_[", StringComparison.OrdinalIgnoreCase) && text.EndsWith("]", StringComparison.Ordinal))
        {
            text = text.Substring("LOC_[".Length, text.Length - "LOC_[".Length - 1);
        }

        var tokens = text.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (tokens.Length < 3)
            return false;
        if (!string.Equals(tokens[^2], "Hero", StringComparison.OrdinalIgnoreCase))
            return false;
        if (!int.TryParse(tokens[^1], out heroIndex) || heroIndex <= 0)
            return false;

        factionName = string.Join(' ', tokens[..^2]);
        return !string.IsNullOrWhiteSpace(factionName);
    }

    internal static bool TryReverseHeroPortraitKey(string key, out string iconKey)
    {
        iconKey = null;
        if (string.IsNullOrWhiteSpace(key))
            return false;

        var sid = key.Trim();
        foreach (var faction in Factions)
        {
            if (TryBuildHeroPortraitKey(sid, faction.HeroPrefix, faction.HeroIconPrefix, out iconKey))
                return true;
        }

        return false;
    }

    private static bool TryBuildHeroPortraitKey(string sid, string sourcePrefix, string targetPrefix, out string portraitKey)
    {
        portraitKey = null;
        if (!sid.StartsWith(sourcePrefix, StringComparison.Ordinal))
            return false;

        var number = ExtractLeadingDigits(sid.Substring(sourcePrefix.Length));
        if (number == null)
            return false;

        portraitKey = targetPrefix + number;
        return true;
    }

    private static string ExtractLeadingDigits(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return null;

        var end = 0;
        while (end < value.Length && char.IsDigit(value[end]))
            end++;

        return end > 0 ? value.Substring(0, end) : null;
    }

    internal static bool IsCustomBuildingIconKey(string key)
    {
        if (string.IsNullOrWhiteSpace(key))
            return false;
        var trimmed = key.Trim();
        foreach (var faction in Factions)
        {
            if (trimmed.StartsWith(faction.FactionSid + "_building_", StringComparison.Ordinal))
                return true;
        }
        return false;
    }

    internal static bool LooksLikeCustomFactionLabel(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return true;
        var key = text.Trim();
        foreach (var faction in Factions)
        {
            if (string.Equals(key, faction.FactionSid, StringComparison.OrdinalIgnoreCase)
                || string.Equals(key, faction.FactionSid + "_name", StringComparison.OrdinalIgnoreCase)
                || string.Equals(key, faction.DisplayName, StringComparison.OrdinalIgnoreCase)
                || string.Equals(key, StripHomm3Suffix(faction.DisplayName), StringComparison.OrdinalIgnoreCase))
                return true;
        }
        return false;
    }

    private static Dictionary<string, string> BuildCustomToDonor()
    {
        var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var faction in Factions)
        {
            foreach (var line in faction.AllUnitLines)
            {
                foreach (var suffix in UnitSuffixes)
                    map[line.CustomSidForSuffix(suffix)] = line.DonorBaseSid + suffix;
            }
        }
        foreach (var pair in ExtraUnitDonorMappings)
            map[pair.Key] = pair.Value;
        return map;
    }

    private static bool TryGetFaction(string factionSid, out FactionDefinition definition)
    {
        definition = null;
        if (string.IsNullOrWhiteSpace(factionSid))
            return false;
        var key = factionSid.Trim();
        foreach (var faction in Factions)
        {
            if (string.Equals(faction.FactionSid, key, StringComparison.OrdinalIgnoreCase))
            {
                definition = faction;
                return true;
            }
        }
        return false;
    }

    internal static bool TryGetHeroDisplayName(string key, out string displayName)
    {
        displayName = null;
        if (!TryNormalizeHeroPortraitKey(key, out var heroSid))
            return false;

        foreach (var faction in Factions)
        {
            if (!heroSid.StartsWith(faction.HeroPrefix, StringComparison.Ordinal))
                continue;
            var number = ExtractLeadingDigits(heroSid.Substring(faction.HeroPrefix.Length));
            if (number == null || !int.TryParse(number, out var index))
                return false;
            var zeroBased = index - 1;
            if (faction.HeroNames == null || zeroBased < 0 || zeroBased >= faction.HeroNames.Length)
                return false;
            displayName = faction.HeroNames[zeroBased];
            return !string.IsNullOrWhiteSpace(displayName);
        }
        return false;
    }

    private static bool TryParseTierBuildingSid(string buildingSid, out int tier)
    {
        tier = 0;
        const string prefix = "Build_Tier_";
        if (string.IsNullOrWhiteSpace(buildingSid))
            return false;
        var trimmed = buildingSid.Trim();
        if (!trimmed.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            return false;
        return int.TryParse(trimmed.Substring(prefix.Length), out tier) && tier >= 1;
    }

    private static string StripHomm3Suffix(string displayName)
    {
        const string suffix = " (HoMM3)";
        return displayName != null && displayName.EndsWith(suffix, StringComparison.Ordinal)
            ? displayName.Substring(0, displayName.Length - suffix.Length)
            : displayName;
    }

    private static string DonorFactionToPrefabFolder(string donorFactionSid)
    {
        if (string.IsNullOrWhiteSpace(donorFactionSid))
            return null;
        return donorFactionSid.Trim().ToLowerInvariant() switch
        {
            "dungeon" => "Dungeon",
            "humans" => "Humans",
            "nature" => "Nature",
            "demons" => "Demons",
            "undead" => "Undead",
            _ => null,
        };
    }

    private sealed class FactionDefinition
    {
        internal FactionDefinition(
            string factionSid,
            string citySid,
            string cityIconSpriteKey,
            string cityIconRelativePath,
            float cityMapBillboardHeight,
            string directDwellingPrefix,
            string dwellingBillboardFolder,
            string[] dwellingBillboardImages,
            string[] dwellingDonorPrefixes,
            string displayName,
            string description,
            string heroPrefix,
            string heroIconPrefix,
            string factionIconSpriteKey,
            string factionIconRelativePath,
            string factionCardSpriteKey,
            string factionCardRelativePath,
            UnitLine[] unitLines,
            string cityMapBillboardRelativePath = null)
            : this(
                factionSid,
                citySid,
                null,
                InferDefaultDonorFactionSid(factionSid),
                cityIconSpriteKey,
                cityIconRelativePath,
                cityMapBillboardHeight,
                directDwellingPrefix,
                dwellingBillboardFolder,
                dwellingBillboardImages,
                dwellingDonorPrefixes,
                displayName,
                description,
                heroPrefix,
                heroIconPrefix,
                18,
                null,
                factionIconSpriteKey,
                factionIconRelativePath,
                factionCardSpriteKey,
                factionCardRelativePath,
                unitLines,
                Array.Empty<AdditionalRecruitmentLine>(),
                cityMapBillboardRelativePath)
        {
        }

        internal FactionDefinition(
            string factionSid,
            string citySid,
            string nativeBiome,
            string defaultDonorFactionSid,
            string cityIconSpriteKey,
            string cityIconRelativePath,
            float cityMapBillboardHeight,
            string directDwellingPrefix,
            string dwellingBillboardFolder,
            string[] dwellingBillboardImages,
            string[] dwellingDonorPrefixes,
            string displayName,
            string description,
            string heroPrefix,
            string heroIconPrefix,
            int heroCount,
            string[] heroNames,
            string factionIconSpriteKey,
            string factionIconRelativePath,
            string factionCardSpriteKey,
            string factionCardRelativePath,
            UnitLine[] unitLines,
            AdditionalRecruitmentLine[] additionalRecruitmentLines,
            string cityMapBillboardRelativePath = null)
        {
            FactionSid = factionSid;
            CitySid = citySid;
            NativeBiome = string.IsNullOrWhiteSpace(nativeBiome) ? null : nativeBiome.Trim();
            DefaultDonorFactionSid = defaultDonorFactionSid;
            CityIconSpriteKey = cityIconSpriteKey;
            CityIconRelativePath = cityIconRelativePath;
            CityMapBillboardRelativePath = string.IsNullOrWhiteSpace(cityMapBillboardRelativePath)
                ? ResolveDefaultCityMapBillboardRelativePath(factionSid, cityIconRelativePath)
                : cityMapBillboardRelativePath;
            CityMapBillboardHeight = cityMapBillboardHeight;
            DirectDwellingPrefix = directDwellingPrefix;
            DwellingBillboardFolder = dwellingBillboardFolder;
            DwellingBillboardImages = dwellingBillboardImages;
            DwellingDonorPrefixes = dwellingDonorPrefixes;
            DisplayName = displayName;
            Description = description;
            HeroPrefix = heroPrefix;
            HeroIconPrefix = heroIconPrefix;
            HeroCount = heroCount > 0 ? heroCount : 18;
            HeroNames = heroNames;
            FactionIconSpriteKey = factionIconSpriteKey;
            FactionIconRelativePath = factionIconRelativePath;
            FactionCardSpriteKey = factionCardSpriteKey;
            FactionCardRelativePath = factionCardRelativePath;
            UnitLines = unitLines;
            AdditionalRecruitmentLines = additionalRecruitmentLines ?? Array.Empty<AdditionalRecruitmentLine>();
            AllUnitLines = BuildAllUnitLines(UnitLines, AdditionalRecruitmentLines);
            RecruitmentBaseSids = BuildRecruitmentBaseSids(AllUnitLines);
        }

        internal string FactionSid { get; }
        internal string CitySid { get; }
        internal string NativeBiome { get; }
        internal string DefaultDonorFactionSid { get; }
        internal string CityIconSpriteKey { get; }
        internal string CityIconRelativePath { get; }
        internal string CityMapBillboardRelativePath { get; }
        internal float CityMapBillboardHeight { get; }
        internal string DirectDwellingPrefix { get; }
        internal string DwellingBillboardFolder { get; }
        internal string[] DwellingBillboardImages { get; }
        internal string[] DwellingDonorPrefixes { get; }
        internal string DisplayName { get; }
        internal string Description { get; }
        internal string HeroPrefix { get; }
        internal string HeroIconPrefix { get; }
        internal int HeroCount { get; }
        internal string[] HeroNames { get; }
        internal string FactionIconSpriteKey { get; }
        internal string FactionIconRelativePath { get; }
        internal string FactionCardSpriteKey { get; }
        internal string FactionCardRelativePath { get; }
        internal UnitLine[] UnitLines { get; }
        internal AdditionalRecruitmentLine[] AdditionalRecruitmentLines { get; }
        internal UnitLine[] AllUnitLines { get; }
        private static UnitLine[] BuildAllUnitLines(UnitLine[] primary, AdditionalRecruitmentLine[] additional)
        {
            var result = new UnitLine[primary.Length + additional.Length];
            Array.Copy(primary, result, primary.Length);
            for (var i = 0; i < additional.Length; i++)
                result[primary.Length + i] = additional[i].Line;
            return result;
        }
        internal string[] RecruitmentBaseSids { get; }

        private static string[] BuildRecruitmentBaseSids(UnitLine[] unitLines)
        {
            var result = new string[unitLines.Length];
            for (var i = 0; i < unitLines.Length; i++)
                result[i] = unitLines[i].BaseSid;
            return result;
        }

        private static string InferDefaultDonorFactionSid(string factionSid)
        {
            return factionSid switch
            {
                "homm3_castle" => "humans",
                "homm3_cove" => "humans",
                "homm3_tower" => "humans",
                "homm3_dungeon" => "dungeon",
                "homm3_stronghold" => "dungeon",
                "homm3_inferno" => "demons",
                "homm3_necropolis" => "undead",
                "homm3_conflux" => "nature",
                "homm3_fortress" => "nature",
                "homm3_rampart" => "nature",
                _ => null,
            };
        }
    }

    private readonly struct AdditionalRecruitmentLine
    {
        internal AdditionalRecruitmentLine(
            string lineId,
            int tier,
            string recruitmentSlotSid,
            string cityBuildingSid,
            string directDwellingSid,
            string donorDwellingSid,
            string dwellingBillboardImage,
            UnitLine line)
        {
            LineId = lineId;
            Tier = tier;
            RecruitmentSlotSid = recruitmentSlotSid;
            CityBuildingSid = cityBuildingSid;
            DirectDwellingSid = directDwellingSid;
            DonorDwellingSid = donorDwellingSid;
            DwellingBillboardImage = dwellingBillboardImage;
            Line = line;
        }

        internal string LineId { get; }
        internal int Tier { get; }
        internal string RecruitmentSlotSid { get; }
        internal string CityBuildingSid { get; }
        internal string DirectDwellingSid { get; }
        internal string DonorDwellingSid { get; }
        internal string DwellingBillboardImage { get; }
        internal UnitLine Line { get; }
    }
    private readonly struct UnitLine
    {
        internal UnitLine(
            string baseSid,
            string donorFactionSid,
            string donorBaseSid,
            string donorPrefabBaseSid = null,
            string upgradeSid = null,
            string alternateUpgradeSid = null,
            string branchFamily = null)
        {
            BaseSid = baseSid;
            DonorFactionSid = donorFactionSid;
            DonorBaseSid = donorBaseSid;
            DonorPrefabBaseSid = donorPrefabBaseSid ?? donorBaseSid;
            UpgradeSid = upgradeSid;
            AlternateUpgradeSid = alternateUpgradeSid;
            BranchFamily = string.IsNullOrWhiteSpace(branchFamily) ? null : branchFamily.Trim();
        }

        internal string BaseSid { get; }
        internal string DonorFactionSid { get; }
        internal string DonorBaseSid { get; }
        internal string DonorPrefabBaseSid { get; }
        private string UpgradeSid { get; }
        private string AlternateUpgradeSid { get; }
        internal string BranchFamily { get; }

        internal string CustomSidForSuffix(string suffix)
        {
            return suffix switch
            {
                "" => BaseSid,
                "_upg" => UpgradeSid ?? BaseSid + suffix,
                "_upg_alt" => AlternateUpgradeSid ?? BaseSid + suffix,
                _ => BaseSid + suffix,
            };
        }

        internal bool MatchesCustomSid(string sid)
        {
            if (string.IsNullOrWhiteSpace(sid))
                return false;
            foreach (var suffix in UnitSuffixes)
            {
                if (string.Equals(sid, CustomSidForSuffix(suffix), StringComparison.OrdinalIgnoreCase))
                    return true;
            }
            return false;
        }
    }

    internal readonly struct DwellingDonorAlias
    {
        internal DwellingDonorAlias(string factionSid, string citySid, string defaultDonorFactionSid, string customDwellingSid, string donorPrefix)
        {
            FactionSid = factionSid;
            CitySid = citySid;
            DefaultDonorFactionSid = defaultDonorFactionSid;
            CustomDwellingSid = customDwellingSid;
            DonorPrefix = donorPrefix;
        }

        internal string FactionSid { get; }
        internal string CitySid { get; }
        internal string DefaultDonorFactionSid { get; }
        internal string CustomDwellingSid { get; }
        internal string DonorPrefix { get; }
    }

    internal readonly struct DwellingUnitMatch
    {
        internal DwellingUnitMatch(string factionSid, string citySid, string customDwellingSid, int tier, string unitSid)
        {
            FactionSid = factionSid;
            CitySid = citySid;
            CustomDwellingSid = customDwellingSid;
            Tier = tier;
            UnitSid = unitSid;
        }

        internal string FactionSid { get; }
        internal string CitySid { get; }
        internal string CustomDwellingSid { get; }
        internal int Tier { get; }
        internal string UnitSid { get; }
    }
}
