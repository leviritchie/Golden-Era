using System;

namespace OfflineUnlockMod;

// Semantic registry for hotfix-sensitive obfuscated game symbols. If a Steam
// hotfix only renames obfuscated members, update this file first instead of
// scattering find/replace edits across hook implementations.
//
// Every literal here is a Golden Era pin. Every nested class is partial: GameSymbolsCurrent.g.cs,
// generated from the P1 remap, adds static constructors that swap in the live names on the current
// build only (GameSymbolScope). After editing a hint declaration, regenerate the remap and then
// run tools/port_current/generate_current_symbol_scopes.py; the build fails while it is stale.
internal static partial class GameSymbols
{
	internal readonly struct MethodSymbol
	{
		internal readonly string Id;
		internal readonly string[] NameHints;

		internal MethodSymbol(string id, params string[] nameHints)
		{
			Id = id;
			NameHints = nameHints ?? System.Array.Empty<string>();
		}
	}

	/// <summary>
	/// Expected shape of a hint-resolved type on one build: generic-definition full name of the base
	/// type (nested types joined with '+'), declared field count, and declared non-constructor method
	/// count, both over Public|NonPublic|Instance|Static|DeclaredOnly. Pinned from that build's interop
	/// by tools/validate_game_symbols_hint_contract.py (tools/port_current/interop_shape_index counts
	/// the same way GameMember.ObserveTypeShape does at runtime).
	/// </summary>
	internal readonly struct TypeShape
	{
		internal readonly string BaseType;
		internal readonly int Fields;
		internal readonly int Methods;

		internal TypeShape(string baseType, int fields, int methods)
		{
			BaseType = baseType ?? "";
			Fields = fields;
			Methods = methods;
		}

		public override string ToString() => BaseType + "|f" + Fields + "|m" + Methods;
	}

	/// <summary>Hints plus expected shape for one build. <see cref="None"/> means "not pinned for this build".</summary>
	internal sealed class TypeHintScope
	{
		internal static readonly TypeHintScope None = new(System.Array.Empty<string>(), default);

		/// <summary>
		/// "Filled from the remap": GameSymbolsCurrent.g.cs (tools/port_current/generate_current_symbol_scopes.py)
		/// replaces it with the live hint and shape when the remap resolves the group's golden hints; if it
		/// stays, the scope is empty and the group is refused on that build.
		/// </summary>
		internal static readonly TypeHintScope Generated = new(System.Array.Empty<string>(), default);

		internal readonly string[] Hints;
		internal readonly TypeShape Shape;

		internal TypeHintScope(string[] hints, TypeShape shape)
		{
			Hints = hints ?? System.Array.Empty<string>();
			Shape = shape;
		}

		internal bool IsEmpty => Hints.Length == 0;
	}

	/// <summary>
	/// A build-scoped type hint group: { golden: [...], current: [...] }. GameMember.ResolveTypeGroup
	/// picks the scope for GameBuild.Kind, requires exactly one shape-matching type across the scope's
	/// hints, and refuses (null, logged) otherwise, including for an empty scope or an unknown build.
	/// A <c>current: TypeHintScope.Generated</c> scope is filled by GameSymbolsCurrent.g.cs from the remap.
	/// Populate <c>current</c> only from a group of the P1 remap (tools/port_current/remap/
	/// game_symbols_remap_&lt;buildid&gt;.json, schema game_symbols_remap.v1) whose entries are all mapped.
	/// </summary>
	internal sealed class TypeHintGroup
	{
		internal readonly string Id;
		internal readonly TypeHintScope Golden;
		internal readonly TypeHintScope Current;

		internal TypeHintGroup(string id, TypeHintScope golden, TypeHintScope current)
		{
			Id = id;
			Golden = golden ?? TypeHintScope.None;
			Current = current ?? TypeHintScope.None;
		}

		internal TypeHintScope ScopeFor(GameBuildKind kind)
		{
			switch (kind)
			{
				case GameBuildKind.Golden: return Golden;
				case GameBuildKind.Current: return Current;
				default: return null;
			}
		}
	}

	/// <summary>Known game builds, keyed by GameAssembly.dll SHA-256 (see GameBuild).</summary>
	internal static partial class Builds
	{
		// Golden Era frozen copy (depot 3105441 manifest 3222242645517655127), 95,480,832 B, 2026-06-04.
		internal const string GoldenGameAssemblySha256 = "D47706EB0FFEDBDA0EC07EDE47ABC778E6022ED820AE1A1FD23522D3ACDB8416";
		// The current live build is the target of the generated scopes (GameSymbolsCurrent.g.cs, see
		// GameSymbolScope): Steam buildid 25672315 (manifest 7750145598966689713), 98,075,648 B, 2026-10-02.
		// Its hash comes from the generated remap target so it cannot drift from the scopes.
		internal const string CurrentGameAssemblySha256 = CurrentScopes.GameAssemblySha256;
	}

	internal readonly struct FieldSymbol
	{
		internal readonly string Id;
		internal readonly string NativeFieldInfoName;
		internal readonly string FieldName;

		internal FieldSymbol(string id, string nativeFieldInfoName, string fieldName)
		{
			Id = id;
			NativeFieldInfoName = nativeFieldInfoName;
			FieldName = fieldName;
		}
	}

	internal static partial class BattleForecast
	{
		internal const string CalculatorTypeId = "battle.forecast.calculator";
		internal static readonly string[] CalculatorTypeHints = { "ell", "elj", "eky", "elc" };
	}

	internal static partial class Minimap
	{
		internal const string RendererTypeId = "minimap.renderer";
		// Golden Era live type leads; short bcu is legacy-only (beg→beh / bcu→bcv era).
		internal static readonly string[] RendererTypeHints =
			{ "ObjectPublicInbrStInbrCoStMaInbrUnique", "bcv", "bcu", "bbff", "nma" };

		internal static readonly MethodSymbol RendererBuildMapCurrent = new(
			"minimap.renderer.buildMap.current",
			"Method_Public_Void_ObjectPublicRebrRebrUnique_Map_SoMinimapConfig_4",
			"Method_Public_Void_ObjectPublicRebrRebrUnique_Map_SoMinimapConfig_3",
			"Method_Public_Void_ObjectPublicRebrRebrUnique_Map_SoMinimapConfig_2",
			"Method_Public_Void_ObjectPublicRebrRebrUnique_Map_SoMinimapConfig_1",
			"Method_Public_Void_ObjectPublicRebrRebrUnique_Map_SoMinimapConfig_0",
			"hbi", "hev", "kcn", "klt", "kym");

		internal static readonly MethodSymbol RendererBuildMap = new(
			"minimap.renderer.buildMap",
			"Method_Public_Void_ObjectPublicRebrRebrUnique_Map_SoMinimapConfig_4",
			"Method_Public_Void_ObjectPublicRebrRebrUnique_Map_SoMinimapConfig_3",
			"Method_Public_Void_ObjectPublicRebrRebrUnique_Map_SoMinimapConfig_2",
			"Method_Public_Void_ObjectPublicRebrRebrUnique_Map_SoMinimapConfig_1",
			"Method_Public_Void_ObjectPublicRebrRebrUnique_Map_SoMinimapConfig_0",
			"hbi", "hev", "kcn", "klt", "kym",
			"kln", "kkx", "klo", "kac");

		internal static readonly MethodSymbol RendererRenderMapData = new(
			"minimap.renderer.renderMapData",
			"Method_Private_Void_RenderTexture_MapData_RectInt_SoMinimapConfig_Boolean_0",
			"klu");

		internal static readonly FieldSymbol[] WorldConfigFields =
		{
			new("minimap.world.config.may21", "NativeFieldInfoPtr_ciji", "ciji"),
			new("minimap.world.config", "NativeFieldInfoPtr_cihn", "cihn"),
		};
	}

	/// <summary>
	/// Golden Era SpawnsCreator (obfuscated <c>czr</c>) surfaces for StoryHub campaign
	/// hero/city spawn parity. Keep obfuscated names here.
	/// </summary>
	internal static partial class CampaignSpawnParity
	{
		internal const string SpawnsCreatorTypeId = "campaign.spawnParity.spawnsCreator";
		internal static readonly string SpawnsCreatorTypeHint = "czr";

		internal static readonly string[] ObjectsPropertiesFieldHints =
			{ "care", "objectsProperties", "get_care", "field_Private_Static_ObjectsProperties_0", "NativeFieldInfoPtr_care" };

		internal static readonly string[] MapFieldHints =
			{ "cara", "map", "get_cara", "field_Private_Static_Map_0", "NativeFieldInfoPtr_cara" };

		// FractionConfig.city (DiffableCs offset 0x60). Prefer the exact name; do not use
		// ConfigElementBase id aliases — those collide with generated field_Public_String_0.
		internal static readonly string[] FractionConfigCityFields =
			{ "city", "<city>k__BackingField", "_city" };

		internal static readonly string[] SideFractionConfigFields =
			{ "cnzk", "chty", "cnvq", "fractionConfig", "<fractionConfig>k__BackingField", "_fractionConfig" };

		internal static readonly string[] PropHeroesMemberHints =
			{ "cmuq", "get_cmuq", "oua", "PropHeroes", "propHeroes", "get_propHeroes", "Method_Public_get_List_1_PropHero_0" };

		internal static readonly string[] MapObjectsMemberHints =
			{ "objects", "ogc", "cmwh", "field_Public_MapObjects_0", "get_objects" };

		internal static readonly string[] MapObjectsByIdMethodHints =
			{ "ById", "byId", "Get", "get_Item" };

		// MapData.objects is List<MapDataObjects> with per-row sid + ids[].
		internal static readonly string[] MapDataObjectsListMemberHints =
			{ "objects", "get_objects", "field_Public_List_1_MapDataObjects_0", "field_Public_List_1_0" };

		internal static readonly string[] MapDataObjectsSidFields =
			{ "sid", "field_Public_String_0" };

		internal static readonly string[] MapDataObjectsIdsFields =
			{ "ids", "field_Public_Il2CppStructArray_1_Int32_0", "field_Public_ArrayOf_Int32_0" };

		// Parallel to ids[] on MapDataObjects (dump: public int[] nodes).
		internal static readonly string[] MapDataObjectsNodesFields =
			{ "nodes", "field_Public_Il2CppStructArray_1_Int32_1", "field_Public_ArrayOf_Int32_1" };
	}

	/// <summary>
	/// Native prison initialization surfaces. ObjPrison.heroSid must be populated before
	/// the prison logic selects its Hero; writing it after Init only changes serialized
	/// identity and leaves the already-selected random Hero in place.
	/// </summary>
	internal static partial class PrisonHeroBinding
	{
		internal const string LogicTypeId = "map.prison.heroBinding.logic";
		// Golden Era live interop exposes the prison logic as native type `fav`,
		// represented by this generated managed name. `fcj` is retained only as
		// the older dump-era alias and must not be the sole live pin.
		internal static readonly string[] LogicTypeHints =
			{ "Object1PublicObcjHeObcjObcjcjObcjUnique", "fcj" };
		internal static readonly MethodSymbol LogicInit = new(
			"map.prison.heroBinding.logic.init",
			"Init_Public_Virtual_Void_0",
			"Init");
		internal static readonly string[] LogicPrisonFieldHints =
			{ "cjjm", "field_Private_ObjPrison_0", "field_Private_ObjPrison_1" };
		internal static readonly string[] PrisonIdFields =
			{ "idMapObject", "field_Public_Int32_0", "field_Public_Int32_1" };
		internal static readonly string[] PrisonHeroSidFields =
			{ "heroSid", "field_Public_String_0", "field_Public_String_1" };
	}

	/// <summary>
	/// Adventure-map screen_dump catalog member hints. Keep obfuscated names here.
	/// LocKit display names and fog visibility remain unproven.
	/// Node→world projection: Hex.Map.Map.oaq/oar (live may be Method_Public_Vector3_Int32_*).
	/// </summary>
	internal static partial class AiDriverScreenDump
	{
		internal const float MapWorldPointRectSize = 32f;

		internal static readonly string[] MapDataMarkersMemberHints =
			{ "markers", "Markers", "<markers>k__BackingField", "get_markers", "Method_Public_get_List_1_Marker_0", "Method_Public_get_List_1_MapDataMarker_0" };

		// MapDataMarker layout (dump): node@0x10, id@0x28 — prefer named node; obfuscated first int is node.
		internal static readonly string[] MarkerIdFields =
			{ "id", "Id", "field_Public_Int32_1" };

		internal static readonly string[] MarkerNodeFields =
			{ "node", "Node", "field_Public_Int32_0", "<node>k__BackingField" };

		internal static readonly string[] MarkerSidFields =
			{ "sid", "Sid", "field_Public_String_0", "field_Public_String_1", "get_sid" };

		internal static readonly string[] PropHeroIdFields =
			{ "id", "Id", "objectId", "ObjectId", "field_Public_Int32_0", "field_Public_Int32_1" };

		internal static readonly string[] PropHeroSidFields =
			{ "heroSid", "field_Public_String_0", "field_Public_String_1", "sid", "configSid" };

		internal static readonly string[] PropHeroDefinedFields =
			{ "isDefined", "IsDefined", "field_Public_Boolean_0" };

		internal static readonly string[] PropHeroNodeFields =
			{ "node", "Node", "mapNode", "nodeId", "field_Public_Int32_1" };

		// esd/eta are Il2Cpp plain objects (not UnityEngine.Object); session logic-world walk is primary.
		// FindObjectsOfTypeAll remains a cold fallback for legacy etc MonoBehaviour shapes only.
		internal static readonly string[] WorldHeroScanTypeHints =
		{
			"eta",
			"etc",
			"ObjectPublicHeObInObciSiObVeSeObUnique",
		};

		// eta world position when drawer root GameObject is not yet attached.
		internal static readonly string[] WorldHeroPositionFields =
			{ "_cicq_k__BackingField", "<cicq>k__BackingField", "cicq" };

		internal static readonly string[] LogicWorldHeroListMembers =
		{
			"ccns", "_ccns_k__BackingField", "_ccjn_k__BackingField", "_cclg_k__BackingField",
			"heroes", "get_heroes", "bhud", "bhxe", "Method_Public_get_List_1_Hero_0",
		};

		internal static readonly string[] DataHeroConfigSidFields =
		{
			"configSid", "heroSid", "sid",
			"field_Public_String_0", "field_Public_String_1", "field_Private_String_0",
			"chsm", "bfuz", "chqr", "chno", "<bqep>k__BackingField", "_bqep_k__BackingField", "bqep",
		};

		// Dump: Map.oaq(int)/oar(int). Live Hex.dll retains oar + Method_Public_Vector3_Int32_0/1 (oaq string absent).
		internal static readonly MethodSymbol MapNodeToWorld = new(
			"ai.dump.map.nodeToWorld",
			"oar",
			"oaq",
			"Method_Public_Vector3_Int32_0",
			"Method_Public_Vector3_Int32_1");

		// BhWorldCamera.targetCamera_ / clhv / hfq (dump).
		internal static readonly string[] WorldCameraUnityCameraMembers =
			{ "targetCamera_", "clhv", "get_clhv", "hfq", "Method_Public_get_Camera_0", "<targetCamera>k__BackingField" };
	}

	/// <summary>
	/// Native StoryHub / CampaignInfo symbols for RoE Castle continuity.
	/// Keep obfuscated names here; do not scatter them through feature code.
	/// Runtime session→hub writeback remains unvalidated.
	/// </summary>
	internal static partial class CampaignContinuity
	{
		internal const string CampaignInfoTypeId = "campaign.continuity.campaignInfo";
		internal static readonly string[] CampaignInfoTypeHints = { "CampaignInfo", "Hex.Session.CampaignInfo" };

		internal const string StoryHubConfigTypeId = "campaign.continuity.storyHub.config";
		internal static readonly string[] StoryHubConfigTypeHints = { "StoryHub", "Hex.StoryHub.DB.Config.StoryHub" };

		internal const string StoryHubSaveTypeId = "campaign.continuity.storyHubSave";
		internal static readonly string[] StoryHubSaveTypeHints = { "StoryHubSave", "Hex.StoryHub.Data.StoryHubSave" };

		internal const string StoryHubHeroTypeId = "campaign.continuity.storyHub.hero";
		internal static readonly string[] StoryHubHeroTypeHints = { "Hero", "Hex.StoryHub.Data.Hero" };

		internal static readonly FieldSymbol StoryHubTransferHeroProgressFromSession = new(
			"campaign.continuity.storyHub.transferHeroProgressFromSession",
			"NativeFieldInfoPtr_transferHeroProgressFromSession",
			"transferHeroProgressFromSession");

		internal static readonly FieldSymbol CampaignInfoTransferHeroProgressFromSession = new(
			"campaign.continuity.campaignInfo.transferHeroProgressFromSession_",
			"NativeFieldInfoPtr_transferHeroProgressFromSession_",
			"transferHeroProgressFromSession_");

		internal static readonly FieldSymbol StoryHubSaveHeroesSaves = new(
			"campaign.continuity.storyHubSave.heroesSaves",
			"NativeFieldInfoPtr_heroesSaves",
			"heroesSaves");

		internal static readonly FieldSymbol StoryHubHeroLevel = new(
			"campaign.continuity.storyHub.hero.level",
			"NativeFieldInfoPtr_level",
			"level");

		internal static readonly FieldSymbol StoryHubHeroExperience = new(
			"campaign.continuity.storyHub.hero.experience",
			"NativeFieldInfoPtr_experience",
			"experience");

		internal static readonly MethodSymbol CampaignInfoPopulate = new(
			"campaign.continuity.campaignInfo.vop",
			"vop");

		internal static readonly MethodSymbol OpenMissionsPrologue = new(
			"campaign.continuity.openMissionsPrologue",
			"OpenMissionsPrologue");
	}

	/// <summary>
	/// QuestsSystem (<c>ddq</c>) re-Init guard: deactivate orphaned SubQuest listeners when
	/// a failed map load retries OnScenesLoaded without disposing the first QuestSystem.
	/// </summary>
	internal static partial class QuestsSystemReinit
	{
		internal const string QuestsSystemTypeId = "quests.system.reinit.questsSystem";
		internal static readonly string QuestsSystemTypeHint = "ddq";

		internal static readonly string[] StaticMePropertyHints =
		{
			"me",
			"cbiz",
		};

		internal static readonly string[] LogicQuestsMemberHints =
		{
			"quests",
			"cbjb",
			"<cbjb>k__BackingField",
		};

		internal static readonly string[] QuestArrayMemberHints =
		{
			"array",
			"cbkb",
			"<cbkb>k__BackingField",
		};

		internal static readonly string[] SubQuestArrayMemberHints =
		{
			"arraySubQuests",
			"cbjz",
			"<cbjz>k__BackingField",
		};

		internal static readonly string[] SubQuestDictMemberHints =
		{
			"subQuests",
			"cbjy",
			"<cbjy>k__BackingField",
		};

		internal static readonly string[] SubQuestDeactivateHints =
		{
			"Deactivate",
			"wqd",
			"mds",
		};
	}

	/// <summary>
	/// StoryHub canvas MapImage swap (G*_BG → NewMap-sized sprite). Keep obfuscated
	/// BhStoryHub Init / config accessor names here.
	/// </summary>
	internal static partial class StoryHubMapBackground
	{
		internal const string BhStoryHubTypeId = "storyHub.mapBackground.bhStoryHub";
		internal static readonly string[] BhStoryHubTypeHints =
		{
			"Hex.StoryHub.BhStoryHub",
			"BhStoryHub",
		};

		internal static readonly MethodSymbol BhStoryHubInit = new(
			"storyHub.mapBackground.bhStoryHub.init",
			"Init");

		internal static readonly MethodSymbol BhStoryHubConfigAccessor = new(
			"storyHub.mapBackground.bhStoryHub.configAccessor",
			"iek",
			"get_StoryHub");

		/// <summary>
		/// <c>BhStoryHub.Init(StoryHubSave)</c> argument → <c>storyHubData.activeProfile.campaignSid</c>.
		/// Live Golden Era drops obfuscated <c>iek</c>; prefer this path.
		/// </summary>
		internal static readonly string[] StoryHubSaveDataFieldHints =
		{
			"storyHubData",
			"field_Public_StoryHub_0",
		};

		internal static readonly string[] StoryHubActiveProfileFieldHints =
		{
			"activeProfile",
			"field_Public_Profile_0",
		};

		internal static readonly string[] ProfileCampaignSidFieldHints =
		{
			"campaignSid",
			"field_Public_String_0",
			"field_Public_String_1",
		};

		internal static readonly string[] StoryHubConfigSidFieldHints =
		{
			"sid",
			"field_Public_String_0",
			"field_Public_String_1",
		};
	}

	internal static partial class HomecomingPlayableShell
	{
		internal static readonly FieldSymbol MapDataNestedData = new(
			"homecoming.playableShell.mapData.nestedData",
			"NativeFieldInfoPtr_bvjr",
			"bvjr");

		internal static readonly FieldSymbol QuickStartSingleton = new(
			"homecoming.playableShell.quickStart.singleton",
			"NativeFieldInfoPtr_field_Private_Static_ScQuickStart_0",
			"bsmu");

		internal static readonly MethodSymbol QuickStartSingletonGetter = new(
			"homecoming.playableShell.quickStart.singleton.getter",
			"get_field_Private_Static_ScQuickStart_0");

		internal static readonly FieldSymbol QuickStartSettings = new(
			"homecoming.playableShell.quickStart.settings",
			"NativeFieldInfoPtr_field_Private_GameStartInfo_0",
			"bsmx");

		internal static readonly MethodSymbol QuickStartSettingsGetter = new(
			"homecoming.playableShell.quickStart.settings.getter",
			"get_field_Private_GameStartInfo_0");

		internal static readonly FieldSymbol QuickStartConfig = new(
			"homecoming.playableShell.quickStart.config",
			"NativeFieldInfoPtr_field_Private_QuickStartConfig_0",
			"bsmy");

		internal static readonly MethodSymbol QuickStartConfigGetter = new(
			"homecoming.playableShell.quickStart.config.getter",
			"get_field_Private_QuickStartConfig_0");

		internal static readonly FieldSymbol QuickStartMode = new(
			"homecoming.playableShell.quickStart.mode",
			"NativeFieldInfoPtr_field_Private_QuickGameMode_0",
			"bsne");

		internal static readonly MethodSymbol QuickStartModeGetter = new(
			"homecoming.playableShell.quickStart.mode.getter",
			"get_field_Private_QuickGameMode_0");

		internal static readonly FieldSymbol QuickStartSelectedMap = new(
			"homecoming.playableShell.quickStart.selectedMap",
			"NativeFieldInfoPtr_field_Private_ObjectPublicAbstractVo0_0",
			"bsnf");

		internal static readonly MethodSymbol QuickStartSelectedMapGetter = new(
			"homecoming.playableShell.quickStart.selectedMap.getter",
			"get_field_Private_ObjectPublicAbstractVo0_0");

		internal static readonly FieldSymbol QuickStartDifficultySelector = new(
			"homecoming.playableShell.quickStart.difficultySelector",
			"NativeFieldInfoPtr_field_Private_BhSummarySelector_0",
			"bsnw");

		internal static readonly MethodSymbol QuickStartDifficultySelectorGetter = new(
			"homecoming.playableShell.quickStart.difficultySelector.getter",
			"get_field_Private_BhSummarySelector_0");

		internal const string QuickStartConfigScenariosField = "scenarios";
		internal const string QuickStartConfigClassicMapsField = "classicMaps";
		internal const string QuickStartConfigSingleHeroMapsField = "singleHeroMaps";
		internal const string QuickStartConfigDifficultiesField = "difficulties";

		// Source/static/build/deployed/runtime-start validated 2026-07-01:
		// dad.vki resolves StartInfo.fileHashSum through qc.ixs. The Homecoming
		// launcher must therefore resolve the installed map's catalog hash from
		// qc at main-menu runtime instead of pinning a stale source literal.
		internal const string MapCatalogTypeId = "homecoming.playableShell.mapCatalog";
		internal static readonly string[] MapCatalogTypeHints = { "qc", "ObjectPublicIDisposableObbqObQuThbq1QuWrBoUnique" };
		internal static readonly string[] MapCatalogSingletonMethods = { "iwx", "get__bqnu_k__BackingField", "Method_Public_Static_get_ObjectPublicIDisposableObbqObQuThbq1QuWrBoUnique_PDM_0" };
	}

	/// <summary>
	/// RMG → .map capture surface. Decomp names: ql (container), qc.ixu (catalog write),
	/// Map.ogz (sync before serialize), Map.Init (post-generate hook). Static-only until runtime proof.
	/// </summary>
	internal static partial class RmgMapCapture
	{
		internal const string GeneratorTypeId = "rmg.mapCapture.generator";
		internal static readonly string[] GeneratorTypeHints = { "blc" };

		internal static readonly MethodSymbol GenerateMap = new(
			"rmg.mapCapture.generator.generateMap",
			"GenerateMap",
			"Method_Public_Static_MapData_String_Int32_Il2CppStringArray_0",
			"Method_Public_Static_MapData_String_Int32_Il2CppStringArray_PDM_0",
			"Method_Public_Static_Void_String_Int32_Il2CppStringArray_0");

		internal const string MapContainerTypeId = "rmg.mapCapture.container";
		internal static readonly string[] MapContainerTypeHints =
		{
			"ql",
			"ObjectPublicObbqMaSebqMaDaNobqQuUnique",
		};

		internal static readonly MethodSymbol MapContainerSave = new(
			"rmg.mapCapture.container.save",
			"Save",
			"Method_Public_Il2CppStructArray_1_Byte_PDM_0",
			"Method_Public_Il2CppStructArray_1_Byte_PDM_1",
			"Method_Public_Il2CppStructArray_1_Byte_0");

		internal static readonly FieldSymbol MapContainerMap = new(
			"rmg.mapCapture.container.map",
			"NativeFieldInfoPtr_field_Public_Map_0",
			"bqpp");

		internal static readonly FieldSymbol MapContainerMapData = new(
			"rmg.mapCapture.container.mapData",
			"NativeFieldInfoPtr_field_Public_MapData_0",
			"bqpr");

		internal static readonly FieldSymbol MapContainerMeta = new(
			"rmg.mapCapture.container.meta",
			"NativeFieldInfoPtr_field_Public_MapMetaInfo_0",
			"bqpo");

		internal static readonly FieldSymbol MapContainerHeader = new(
			"rmg.mapCapture.container.header",
			"NativeFieldInfoPtr_field_Public_qk_0",
			"bqpn");

		internal static readonly MethodSymbol MapSyncToMapData = new(
			"rmg.mapCapture.map.syncToMapData",
			"ogz",
			"Method_Public_Void_PDM_0",
			"Method_Public_Void_0");

		internal static readonly MethodSymbol MapInit = new(
			"rmg.mapCapture.map.init",
			"Init",
			"Method_Public_Void_bud_0",
			"Method_Public_Void_bud_PDM_0");

		internal const string MapCatalogWriteTypeId = "rmg.mapCapture.catalog";
		internal static readonly string[] MapCatalogWriteTypeHints =
		{
			"qc",
			"ObjectPublicIDisposableObbqObQuThbq1QuWrBoUnique",
		};

		internal static readonly MethodSymbol CatalogWriteMap = new(
			"rmg.mapCapture.catalog.writeMap",
			"ixu",
			"Method_Public_Void_String_Boolean_FileType_MetaInfo_Il2CppStructArray_1_Byte_PDM_0",
			"Method_Public_Void_String_Boolean_FileType_MetaInfo_Il2CppStructArray_1_Byte_0");
	}

	internal static partial class HomecomingBoatTravel
	{
		internal const string BoatObjectSid = "homm3_boat";
		internal const string MapSid = "h3_roe_castle_homecoming_layered_atlas";
		internal const string LayeredAtlasMapSid = "h3_roe_castle_homecoming_layered_atlas";
		internal const string ApproachCellMapSid = "h3_roe_castle_homecoming_approach_cell";
		internal const string RawTranslationMapSid = "h3_roe_castle_homecoming_raw_translation";
		internal const string DeprecatedSingleLayerMapSid = "h3_roe_castle_homecoming_single_layer";
		/// <summary>
		/// Standalone maps/-root exact-72 minimap bounds probe. Not a HomecomingMapProfile
		/// entry and not a boat-travel enablement SID.
		/// </summary>
		internal const string Exact72ProbeMapSid = "h3_roe_castle_homecoming_exact72_probe";
		// Campaign ocean is the native basin: Sand seabed tile 2 + waterMap 2 ("water sand") at
		// levelsMap -1 (experiments/campaign_port_poc/campaign_ocean.py). Tile 2 alone is also
		// land Sand, and a Sand river channel is tile 2 + waterMap 2 at land level, so the ocean
		// identity is the (tile, water, level) triple.
		internal const int OceanSeabedTileCode = 2;
		internal const int OceanWaterMapId = 2;
		internal const int OceanBasinLevel = -1;

		internal static bool IsOceanCell(int tileCode, int waterId, int level)
		{
			return tileCode == OceanSeabedTileCode && waterId == OceanWaterMapId && level == OceanBasinLevel;
		}

		// Golden Era-only ocean tile ids (Water, Water Shore N/S/W/E). Retired: no campaign map
		// emits them. Only the terrain-visual hooks that recognise them on a loaded map use this.
		internal static readonly int[] RetiredGoldenEraWaterTileCodes = { 18, 19, 20, 21, 22 };

		internal static bool IsRetiredGoldenEraWaterTileCode(int tileCode)
		{
			return Array.IndexOf(RetiredGoldenEraWaterTileCodes, tileCode) >= 0;
		}

		internal const int MapWidth = 96;
		internal const int MapHeight = 96;
		internal const string WorldRootName = "WORLD";

		// Retired 2026-07-02 after user-visible runtime regression; retained only as historical symbol evidence:
		// The retired ocean-travel reset previously hooked the Loader StartInfo entry used by the launcher,
		// not Loader.lqo(cee[]), because runtime logs showed lqo continues native session loading afterward.
		internal const string SessionLoaderTypeId = "homecoming.boatTravel.sessionLoader";
		internal static readonly string[] SessionLoaderTypeHints =
			{ "Hex.Session.Loader" };


		// Retired 2026-07-02 after user-visible runtime regression; retained only as historical symbol evidence:
		// cyp.hsg() returns ECmd.WorldPath (20 / 0x14). It consumed a hero id during the retired water experiment,
		// path array, and destination node after fao/fcz path calculation.
		internal const string WorldPathCommandTypeId = "homecoming.boatTravel.worldPathCommand";
		internal static readonly string[] WorldPathCommandTypeHints =
			{ "cyp", "Object1PublicIncahsIncaIl2CppStructArray_1_InInInVo19" };

		internal static readonly MethodSymbol WorldPathCommandApply = new(
			"homecoming.boatTravel.worldPathCommand.apply",
			"hsg",
			"Method_Public_Virtual_Boolean_0");

		internal static readonly string[] WorldPathHeroIdFields =
			{ "cara", "field_Public_Int32_0", "get_field_Public_Int32_0" };

		internal static readonly string[] WorldPathNodesFields =
			{ "carb", "field_Public_Il2CppStructArray_1_Int32_0", "get_field_Public_Il2CppStructArray_1_Int32_0" };

		internal static readonly string[] WorldPathDestinationNodeFields =
			{ "carc", "field_Public_Int32_1", "get_field_Public_Int32_1" };


		internal const string MovementTypeId = "homecoming.boatTravel.movement";
		internal static readonly string[] MovementTypeHints =
			{ "fda", "ObjectPublicObBhcjObIncjSiObIncoUnique" };

		internal const string MapInteractableTypeId = "homecoming.boatTravel.mapInteractable";
		internal static readonly string[] MapInteractableTypeHints =
			{ "ets", "ObjectPublicBhciInBociSeEIcociEIUnique" };

		internal static readonly string[] MovementWorldHeroMembers =
			{ "cjme", "<cjme>k__BackingField", "get__cjme_k__BackingField" };
		// Retired 2026-07-02 after user-visible runtime regression; retained only as historical symbol evidence:
		// fcz.bjbi is the public native path request used by fao click handlers before
		// movement command creation. The attempted Homecoming tile-18 pathability
		// bridge was retired; tile 18 is currently terrain-only.
		internal const string PathCalculatorTypeId = "homecoming.boatTravel.pathCalculator";
		internal static readonly string[] PathCalculatorTypeHints =
			{ "fcz", "ObjectPublicObcjUnique" };

		internal static readonly MethodSymbol PathCalculatorFindPath = new(
			"homecoming.boatTravel.pathCalculator.findPath",
			"Method_Public_Il2CppStructArray_1_Int32_ObjectPublicHeObInObciSiObVeSeObUnique_Int32_ObjectPublicBhciInBociSeEIcociEIUnique_ObjectPublicBociBociBociBociBociUnique_0",
			"bjbi");

		internal static readonly MethodSymbol WorldHeroId = new(
			"homecoming.boatTravel.worldHero.id",
			"bgzw",
			"Method_Public_get_Int32_0");

		internal const string WorldHeroTypeId = "homecoming.boatTravel.worldHero";
		internal static readonly string[] WorldHeroTypeHints =
			{ "etc", "ObjectPublicHeObInObciSiObVeSeObUnique" };

		internal const string WorldHeroStartDayName = "OnStartDay";

		// etc.bhcd(int) is the native accepted-node transition seam. It carries the moving hero and
		// target node together, unlike terrain footstep sound lookup, which only resolves node sound data.
		internal static readonly MethodSymbol WorldHeroEnterNode = new(
			"homecoming.boatTravel.worldHero.enterNode",
			"bhcd",
			"Method_Public_EEnterNodeResult_Int32_0");

		// Retired Homecoming direct-state traversal used this native node-commit transaction; the active water path is native tile penalty data.
		// The retired automatic boat/path hook remains disabled; do not reintroduce in_boat terrain state around this symbol.
		internal static readonly MethodSymbol WorldHeroSetNode = new(
			"homecoming.boatTravel.worldHero.setNode",
			"Method_Public_Void_Int32_0",
			"ecn");

		// Retired Homecoming direct-state traversal resolved Hex.Session.Data.Hero through Logic.Hero.ccez; keep these symbols centralized if future diagnostics need them.
		// The retired automatic experiment's in_boat state handling remains disabled.
		internal static readonly string[] WorldHeroLogicHeroMembers =
			{ "ciez", "<ciez>k__BackingField", "bgzu", "get__ciez_k__BackingField", "Method_Public_get_Hero_0" };

		internal static readonly string[] LogicHeroDataHeroMembers =
			{ "ccez", "<ccez>k__BackingField", "xpv", "get__ccez_k__BackingField", "Method_Public_get_Hero_0" };

		internal static readonly string[] DataHeroNodeMembers =
			{ "node", "get_node" };

		internal static readonly string[] DataHeroWorldMovePointsMembers =
			{ "worldMovePoints", "get_worldMovePoints" };

		// Retired Homecoming direct-state traversal used etc.cife/etj.bhfs(int); do not use it to bypass native terrain penalty movement.
		// etj.bhfs(int) writes Hero.worldMovePoints and triggers the native refresh path; do not bypass it by
		// mutating Hex.Session.Data.Hero.worldMovePoints directly.
		internal static readonly string[] WorldHeroMovePointControllerMembers =
			{ "cife", "<cife>k__BackingField", "bhag", "get__cife_k__BackingField" };

		internal const string MovePointControllerTypeId = "homecoming.boatTravel.movePointController";
		internal static readonly string[] MovePointControllerTypeHints =
			{ "etj", "ObjectPublic85ciInVo_hii85BoaoqUnique" };

		internal static readonly MethodSymbol MovePointControllerSetWorldMovePoints = new(
			"homecoming.boatTravel.movePointController.setWorldMovePoints",
			"Method_Public_Void_Int32_2",
			"bhfs");

		// Retired 2026-07-02 after user-visible runtime regression; retained only as historical symbol evidence:
		// etj.bhfc(float) refills worldMovePoints to a fraction of the native max movement stat.
		// The active Homecoming water traversal bridge does not use these move-point controller symbols.
		internal static readonly MethodSymbol MovePointControllerSetWorldMovePointsFraction = new(
			"homecoming.boatTravel.movePointController.setWorldMovePointsFraction",
			"Method_Public_Void_Single_0",
			"bhfc");

		internal const string SideLogicTypeId = "homecoming.boatTravel.sideLogic";
		internal static readonly string[] SideLogicTypeHints =
			{ "Hex.Session.Logic.SideLogic", "dtj" };

		internal const string SideStartDayName = "OnStartDay";
		// Current Official dtj side logic exposes side data at ccng, hero list at ccns,
		// and session manager at ccnw/cclk/ccjr. Homecoming water-start relief now patches the per-hero etc.OnStartDay prefix; the
		// previous dtj side-level hook lagged one morning because native hero movement
		// materialization had already run. It does not use the retired move-point controller
		// symbols or HeroStat.chvk/fly motion.
		internal static readonly string[] SideDataProperties =
			{ "ccng", "_ccng_k__BackingField", "_ccjb_k__BackingField", "_ccku_k__BackingField" };

		internal static readonly string[] SideHeroListProperties =
			{ "ccns", "_ccns_k__BackingField", "_ccjn_k__BackingField", "_cclg_k__BackingField" };

		internal static readonly string[] SideSessionManagerMembers =
		{
			"ccnw",
			"field_Private_ObjectPublicObDaObSeEvccObccDaSeUnique_0",
			"cclk",
			"ccjr",
		};

		internal static readonly string[] SessionDataMembers =
			{ "cclb", "prop_Data_0", "_cclb_k__BackingField", "Data", "_ccgw_k__BackingField", "_ccip_k__BackingField" };

		internal static readonly string[] SessionDayMembers =
			{ "daysInGameCount", "day", "field_Public_Int32_0", "field_Public_Int32_1" };

		internal static readonly string[] DataHeroAdditionalStatsMembers =
			{ "additionalStats", "get_additionalStats" };

		internal static readonly string[] HeroStatLandscapePenaltyPerBonusMembers =
			{ "landscapePenaltyPerBonus" };

		// Source/static validated 2026-06-28. Historical boat-object removal evidence; not used by the active tile/stat baseline.
		// fcs.bjam(int) removes an object through the native object manager, including dictionary removal
		// and downstream notifications. Keep this explicit; bjan(int) only queues removal.
		internal const string WorldTypeId = "homecoming.boatTravel.world";

		internal static readonly string[] WorldTypeHints =
			{ "Hex.BhWorld", "erj" };

		internal static readonly string[] WorldSingletonMembers =
			{ "me", "Method_Public_Static_get_BhWorld_0" };


		// Retired 2026-07-02 after user-visible runtime regression; retained only as map/tile read symbol evidence:
		// The scene WORLD owner exposes the current Hex.Map.Map, and Hex.Map.Map exposes MapData.
		internal const string WorldOwnerTypeId = "homecoming.boatTravel.worldOwner";
		internal static readonly string[] WorldOwnerTypeHints =
			{ "MonoBehaviourPublicObmeGarenoGareObarchUnique", "erj" };

		internal static readonly MethodSymbol WorldMap = new(
			"homecoming.boatTravel.world.map",
			"get__chyo_k__BackingField",
			"Method_Public_get_Map_0",
			"get_map");

		internal static readonly MethodSymbol MapData = new(
			"homecoming.boatTravel.map.mapData",
			"Method_Public_get_MapData_0",
			"get__bvjr_k__BackingField",
			"get_mapData");

		internal static readonly string[] MapDataFileNameMembers =
			{ "fileMapName", "get_fileMapName" };

		internal static readonly string[] MapDataTilesMapMembers =
			{ "tilesMap" };

		internal static readonly string[] MapDataWaterMapMembers =
			{ "waterMap", "waterMap_" };

		// MapData.levelsMap is Il2CppStructArray<sbyte> (ocean basin cells are -1).
		internal static readonly string[] MapDataLevelsMapMembers =
			{ "levelsMap" };

		internal static readonly MethodSymbol MapSetWaterNode = new(
			"homecoming.boatTravel.map.setWaterNode",
			"ohl",
			"ncv",
			"iwt",
			"Method_Public_Void_Int32_Byte_0");

		internal static readonly string[] MapDataSizeXMembers =
			{ "sizeX_" };

		internal static readonly string[] MapDataSizeZMembers =
			{ "sizeZ_" };
	}

	internal static partial class HomecomingWaterPresentation
	{
		internal const string PathDrawerTypeId = "homecoming.waterPresentation.pathDrawer";
		// Full name resolves on Golden Era; short BhPathDrawer alone misses via GameMember.
		internal static readonly string[] PathDrawerTypeHints =
			{ "Hex.Session.World.BhPathDrawer", "BhPathDrawer" };

		internal static readonly string[] PathDrawerRefreshMethodHints =
		{
			"Method_Public_Void_0",
			"Method_Public_Void_1",
			"Method_Public_Void_2",
			"Method_Private_Void_PDM_0",
			"Method_Private_Void_0",
			"Method_Private_Void_1",
		};

		internal static readonly string[] PathDrawerShowMethodHints =
			{ "Show" };

		internal static readonly string[] PathDrawerExcludedRefreshMethodHints =
			{ "Update", "LateUpdate", "FixedUpdate", "Awake", "Start", "OnEnable", "OnDisable", "Clear" };

		internal static readonly string[] PathDrawerClearMethodHints =
			{ "Clear", "bhkk", "bhja" };

		// Live-bridge validated 2026-07-06 against Golden Era adventure hover controller.
		internal const string HoverContextTypeId = "homecoming.waterPresentation.hoverContext";
		internal static readonly string[] HoverContextTypeHints =
			{ "ObjectPublicBoInVeObMacjObcjInBoUnique" };

		internal static readonly string[] HoverContextNodeMembers =
			{ "Method_Public_get_Int32_0", "_cjcz_k__BackingField", "get__cjcz_k__BackingField" };

		// Live Golden Era software cursor manager. The native/decomp name is cip, while
		// the generated Golden Era interop type is shape-named. Unity Cursor.visible
		// does not hide this software cursor.
		internal const string CursorManagerTypeId = "homecoming.waterPresentation.cursorManager";
		internal static readonly string[] CursorManagerTypeHints =
		{
			"MonoBehaviourPublicSocomaSobaedObSobxInUnique",
			"cip",
		};

		internal static readonly MethodSymbol CursorManagerSingleton = new(
			"homecoming.waterPresentation.cursorManager.singleton",
			"rjw",
			"Method_Public_Static_get_cip_0",
			"Method_Public_Static_get_MonoBehaviourPublicSocomaSobaedObSobxInUnique_PDM_0");

		internal static readonly string[] CursorApplyTextureMethodHints =
			{ "rkc", "rkb", "cig", "fhz", "hmt", "Method_Private_Void_Texture2D_0" };

		internal static readonly string[] CursorSetMethodHints =
		{
			"rjy", "oar", "mru",
			"Method_Public_Void_ECursor_Int32_0",
			"Method_Public_Void_ECursor_Int32_1",
			"Method_Public_Void_ECursor_Int32_2",
		};

		// Live-bridge validated 2026-07-06: adventure hover returns ECursor from move/interact controllers.
		internal const string HoverCursorProviderTypeId = "homecoming.waterPresentation.hoverCursorProvider";
		internal static readonly string[] HoverCursorProviderTypeHints =
		{
			"ObjectPublicBhciInBociSeEIcociEIUnique",
			"eti",
			"etj",
		};

		// Empty-terrain cursor owner (dump erq). rmi() → bgud() when hover has no interactable.
		// Live pin 2026-07-21: GameAssembly erq$$bgud RVA 0x2133900 emits ECursor 0x17..0x1a.
		internal const string EmptyTerrainCursorOwnerTypeId = "homecoming.waterPresentation.emptyTerrainCursorOwner";
		internal static readonly string[] EmptyTerrainCursorOwnerTypeHints =
		{
			"erq",
			"ObjectPrivateObciBoObciECciciUnique",
		};

		// WORLD owner -> cursor-state container -> empty-terrain cursor service.
		// Golden Era index: erj._ciae -> ero._cial -> erq. Current 25672315 live read:
		// fbu._cnnj -> fbz._cnnp -> fcb. That chain read is positive; this source
		// implementation is built/installed in the isolated copy; automatic WORLD/node hover remains runtime-unproven.
		internal static readonly string[] MapHoverOwnerStateContainerMembers =
			{ "_ciae_k__BackingField", "_cnnj_k__BackingField" };

		internal static readonly string[] MapHoverStateCursorOwnerMembers =
			{ "_cial_k__BackingField", "_cnnp_k__BackingField" };

		// Private void() candidates; bgud is pinned by IL (ValidPath/ValidPathRed/Gray/InvalidTarget immediates), not name alone.
		internal static readonly string[] EmptyTerrainCursorMapperMethodHints =
		{
			"bgud",
			"Method_Private_Void_0",
			"Method_Private_Void_PDM_0",
			"Method_Private_Void_PDM_1",
			"Method_Private_Void_PDM_2",
			"Method_Private_Void_PDM_3",
		};

		internal static readonly string[] EmptyTerrainCursorHoverContextMembers =
		{
			"field_Private_ObjectPublicBoInVeObMacjObcjInBoUnique_0",
			"get_field_Private_ObjectPublicBoInVeObMacjObcjInBoUnique_0",
			"ciao",
		};

		// cir stack (dump cir.byv/rmc/mte) — applies ECursor into ciq software cursor.
		internal const string CursorStackTypeId = "homecoming.waterPresentation.cursorStack";
		internal static readonly string[] CursorStackTypeHints =
		{
			"ObjectPublicObbxLiOb1cnObbxbxObUnique",
			"cir",
		};

		internal static readonly MethodSymbol CursorStackSingleton = new(
			"homecoming.waterPresentation.cursorStack.singleton",
			"cnct",
			"Method_Public_Static_get_ObjectPublicObbxLiOb1cnObbxbxObUnique_0",
			"get_field_Private_Static_ObjectPublicObbxLiOb1cnObbxbxObUnique_0");

		internal static readonly string[] CursorStackApplyMethodHints =
		{
			"byv", "rmc", "mte",
			"Method_Public_Boolean_ECursor_Int32_0",
			"Method_Public_Boolean_ECursor_Int32_1",
			"Method_Public_Boolean_ECursor_Int32_2",
		};

		// Owned cityFactory map-city-interact suppress: see Homm3OwnedCityMapCursorSuppress.
		// Live-positive 2026-07-31: PlayerInteractCity (and HeroInteractCity*) rewrite under cityFactory.

		// Nested ets.CursorColor — interactable path only (etr.bhij). NOT empty-water ValidPathRed.
		internal const string CursorColorEnumTypeId = "homecoming.waterPresentation.cursorColor";
		internal static readonly string[] CursorColorEnumTypeHints =
		{
			"ObjectPublicBhciInBociSeEIcociEIUnique+CursorColor",
			"ObjectPublicBhciInBociSeEIcociEIUnique.CursorColor",
		};

		internal const string CursorColorProviderTypeId = "homecoming.waterPresentation.cursorColorProvider";
		internal static readonly string[] CursorColorProviderTypeHints =
		{
			"Object1PublicStciSi85cico85bh80ciUnique",
			"Object1PublicStciSi35cico35bhCuciUnique",
			"etr",
			"etv",
		};

		internal static readonly string[] CursorColorMethodHints =
		{
			"bhij",
			"hxo",
			"bhjc",
			"eiv",
			"ohh",
			"Method_Private_CursorColor_ObjectPublicHeObInObciSiObVeSeObUnique_Int32_0",
			"Method_Private_CursorColor_ObjectPublicHeObInObciSiObVeSeObUnique_Int32_PDM_0",
			"Method_Private_CursorColor_ObjectPublicHeObInObciSiObVeSeObUnique_Int32_PDM_1",
			"Method_Private_CursorColor_ObjectPublicHeObInObciSiObVeSeObUnique_Int32_PDM_2",
		};

		internal static readonly string[] WorldHeroTypeHintsForCursorColor =
		{
			"ObjectPublicHeObInObciSiObVeSeObUnique",
			"etc",
		};
	}

	/// <summary>
	/// StoryHub-playable continuity-weave map SIDs installed under Story_maps/.
	/// Authoritative install list: tools/install_roe_castle_continuity_weave.py HUB_CONFIGS[*].mapInstalls
	/// (RoE + AB/SoD). Keep this array in sync when adding hubs.
	/// </summary>
	internal static partial class RoeCastleCampaignMaps
	{
		internal static readonly string[] StoryHubPlayableMapSids =
		{
			// RoE Good1 / Good2
			"h3_roe_castle_homecoming_raw_translation",
			"h3_roe_castle_guardian_angels_raw_translation",
			"h3_roe_castle_griffin_cliff_raw_translation",
			"h3_roe_castle_steadwick_liberation_raw_translation",
			"h3_roe_castle_deal_with_the_devil_raw_translation",
			"h3_roe_castle_neutral_affairs_raw_translation",
			"h3_roe_castle_tunnels_and_troglodytes_raw_translation",
			// RoE Good3
			"h3_roe_castle_safe_passage_raw_translation",
			"h3_roe_castle_united_front_raw_translation",
			"h3_roe_castle_for_king_and_country_raw_translation",
			// RoE Evil1 / Evil2
			"h3_roe_dungeon_a_devilish_plan_raw_translation",
			"h3_roe_dungeon_groundbreaking_raw_translation",
			"h3_roe_dungeon_steadwicks_fall_raw_translation",
			"h3_roe_necropolis_a_gryphons_heart_raw_translation",
			"h3_roe_necropolis_season_of_harvest_raw_translation",
			"h3_roe_necropolis_corporeal_punishment_raw_translation",
			"h3_roe_necropolis_from_day_to_night_raw_translation",
			// RoE Specter / Seeds / Spoils
			"h3_roe_necropolis_poison_fit_for_a_king_raw_translation",
			"h3_roe_necropolis_to_build_a_tunnel_raw_translation",
			"h3_roe_necropolis_kreegan_alliance_raw_translation",
			"h3_roe_necropolis_with_blinders_on_raw_translation",
			"h3_roe_neutral_the_grail_raw_translation",
			"h3_roe_neutral_independence_raw_translation",
			"h3_roe_neutral_the_road_home_raw_translation",
			"h3_roe_neutral_1a_raw_translation",
			"h3_roe_neutral_1b_raw_translation",
			"h3_roe_neutral_1c_raw_translation",
			// AB Armageddon's Blade
			"h3_conflux_catherines_charge_raw_translation",
			"h3_conflux_seeking_armageddon_raw_translation",
			"h3_conflux_shadows_of_the_forest_raw_translation",
			"h3_conflux_maker_of_sorrows_raw_translation",
			"h3_conflux_return_of_the_king_raw_translation",
			"h3_conflux_a_blade_in_the_back_raw_translation",
			"h3_conflux_to_kill_a_hero_raw_translation",
			"h3_conflux_oblivions_edge_raw_translation",
			// AB Dragon's Blood
			"h3_dungeon_culling_the_weak_raw_translation",
			"h3_dungeon_savaging_the_scavengers_raw_translation",
			"h3_dungeon_blood_of_the_dragon_father_raw_translation",
			"h3_dungeon_blood_thirsty_raw_translation",
			// AB Dragon Slayer
			"h3_tower_rust_dragons_raw_translation",
			"h3_tower_faerie_dragons_raw_translation",
			"h3_tower_azure_dragons_raw_translation",
			"h3_tower_crystal_dragons_raw_translation",
			// AB Festival of Life
			"h3_stronghold_for_the_throne_raw_translation",
			"h3_stronghold_clan_war_raw_translation",
			"h3_stronghold_taming_of_the_wild_raw_translation",
			"h3_stronghold_razor_claw_raw_translation",
			// AB Playing with Fire
			"h3_fortress_farming_towns_raw_translation",
			"h3_fortress_march_of_the_undead_raw_translation",
			"h3_fortress_burning_of_tatalia_raw_translation",
			// AB Foolhardy Waywardness
			"h3_castle_lost_at_sea_raw_translation",
			"h3_castle_here_there_be_pirates_raw_translation",
			"h3_castle_hurry_up_and_wait_raw_translation",
			"h3_castle_their_end_of_the_bargain_raw_translation",
			// SoD Rise of the Necromancer
			"h3_necropolis_target_raw_translation",
			"h3_necropolis_master_raw_translation",
			"h3_necropolis_finneas_vilmar_raw_translation",
			"h3_necropolis_duke_alarice_raw_translation",
			// SoD Hack and Slash
			"h3_stronghold_bashing_skulls_raw_translation",
			"h3_stronghold_black_sheep_raw_translation",
			"h3_stronghold_a_cage_in_the_hand_raw_translation",
			"h3_stronghold_grave_robber_raw_translation",
			// SoD Birth of a Barbarian
			"h3_stronghold_on_the_run_raw_translation",
			"h3_stronghold_the_meeting_raw_translation",
			"h3_stronghold_a_tough_start_raw_translation",
			"h3_stronghold_falor_and_terwen_raw_translation",
			"h3_stronghold_returning_to_bracada_raw_translation",
			// SoD New Beginning
			"h3_rampart_clearing_the_border_raw_translation",
			"h3_rampart_after_the_amulet_raw_translation",
			"h3_rampart_retrieving_the_cowl_raw_translation",
			"h3_rampart_driving_for_the_boots_raw_translation",
			// SoD Elixir of Life
			"h3_rampart_graduation_exercise_raw_translation",
			"h3_rampart_cutthroats_raw_translation",
			"h3_rampart_valley_of_the_dragon_lords_raw_translation",
			"h3_rampart_a_thief_in_the_night_raw_translation",
			// SoD Unholy Alliance
			"h3_necropolis_harvest_raw_translation",
			"h3_necropolis_gathering_the_legion_raw_translation",
			"h3_necropolis_search_for_a_killer_raw_translation",
			"h3_necropolis_final_peace_raw_translation",
			"h3_necropolis_secrets_revealed_raw_translation",
			"h3_necropolis_agents_of_vengeance_raw_translation",
			"h3_necropolis_wrath_of_sandro_raw_translation",
			"h3_necropolis_invasion_raw_translation",
			"h3_necropolis_to_strive_to_seek_raw_translation",
			"h3_necropolis_barbarian_brothers_raw_translation",
			"h3_necropolis_union_raw_translation",
			"h3_necropolis_fall_of_sandro_raw_translation",
		};
	}

	internal static partial class HomecomingLayerViewToggle
	{
		internal const string WorldCameraTypeId = "homecoming.layerViewToggle.worldCamera";
		internal static readonly string[] WorldCameraTypeHints = { "Hex.BhWorldCamera" };

		// Live-metadata and live-probe validated 2026-07-04 against Golden Era. The
		// native layer transition sequence is: write the target view index, then
		// call BhWorldCamera.hju(oldViewIndex, targetViewIndex) to reframe the camera.
		internal static readonly MethodSymbol WorldCameraSingleton = new(
			"homecoming.layerViewToggle.worldCamera.singleton",
			"Method_Public_Static_get_BhWorldCamera_PDM_0",
			"hfm",
			"get_bork");

		internal static readonly MethodSymbol WorldCameraCurrentMap = new(
			"homecoming.layerViewToggle.worldCamera.currentMap",
			"Method_Public_Map_0");

		internal static readonly MethodSymbol WorldCameraMoveBetweenViews = new(
			"homecoming.layerViewToggle.worldCamera.moveBetweenViews",
			"Method_Public_Void_Int32_Int32_0");

		internal static readonly MethodSymbol MapData = new(
			"homecoming.layerViewToggle.map.mapData",
			"Method_Public_get_MapData_0");

		internal static readonly MethodSymbol MapViewState = new(
			"homecoming.layerViewToggle.map.viewState",
			"Method_Public_get_ObjectPublicLi1MabvInbvInbvInbvUnique_0");

		internal static readonly MethodSymbol CurrentViewIndexGetter = new(
			"homecoming.layerViewToggle.viewState.currentIndex.getter",
			"Method_Public_Int32_0");

		internal static readonly MethodSymbol ViewCountGetter = new(
			"homecoming.layerViewToggle.viewState.viewCount.getter",
			"Method_Public_Int32_1");

		internal static readonly MethodSymbol CurrentViewIndexSetter = new(
			"homecoming.layerViewToggle.viewState.currentIndex.setter",
			"Method_Public_Void_Int32_1");

		internal static readonly string[] MapDataFileNameMembers =
			{ "fileMapName" };

		internal static readonly string[] MapDataViewsMembers =
			{ "views" };
	}

	internal static partial class TerrainMaterial
	{
		internal static readonly MethodSymbol InstanceGetter = new(
			"terrain.material.instance.getter",
			"kwf", "Method_Public_Static_SoTerrainMaterial_0",
			"kwa", "kvm", "kuz", "krb");

		internal static readonly MethodSymbol MaterialGetter = new(
			"terrain.material.material.getter",
			"kwg", "Method_Public_Material_0",
			"kwb", "kvn", "kva", "krc");

		internal const string RendererTypeId = "terrain.material.renderer";
		// Golden Era live interop name; short beg is legacy-only (beg→beh).
		internal static readonly string RendererTypeHint = "ObjectPublicInbsTeInbsCoReVebsInUnique";
		internal static readonly string[] RendererTypeHints =
		{
			"ObjectPublicInbsTeInbsCoReVebsInUnique", "beh", "bei", "beg", "MonoBehaviourPublicStbsCaRebsLi1RabsNuUnique"
		};

		internal static readonly MethodSymbol RendererPrepareMap = new(
			"terrain.material.renderer.prepareMap",
			"kwc", "jmr", "kvo", "Method_Public_Void_Map_Boolean_Boolean_0", "Method_Public_Void_Map_Boolean_Boolean_1");

		internal static readonly MethodSymbol RendererRebuildMaterialArrays = new(
			"terrain.material.renderer.rebuildMaterialArrays",
			"Method_Private_Void_PDM_5", "nac", "ivz", "kwe", "bbd", "hpm", "ne");
		// Golden Era audit 2026-07-05: Hex.beh.kwm uploads packed terrain color layers
		// into the visible _TextureNodes/mask2 texture. Runtime interop exposes it as
		// ObjectPublicInbsTeInbsCoReVebsInUnique.Method_Private_Void_Map_0.
		internal static readonly MethodSymbol RendererUploadTextureNodes = new(
			"terrain.material.renderer.uploadTextureNodes",
			"kwm", "Method_Private_Void_Map_0");
		// Golden Era audit 2026-06-07: ObjectPublicInbsTeInbsCoReVebsInUnique.Method_Private_Void_PDM_0
		// and Method_Private_Void_PDM_1 are rejected generated candidates on the current Golden Era renderer.
		// Keep postcondition validation mandatory before marking any rebuild success.
		internal static readonly string[] RejectedRendererRebuildMethodNames =
			{ "Method_Private_Void_PDM_0", "Method_Private_Void_PDM_1", "Method_Private_Void_0" };

		internal static readonly MethodSymbol RendererPackMaterialTextures = new(
			"terrain.material.renderer.packMaterialTextures",
			"hd", "kvq");

		internal static readonly MethodSymbol RendererApplyMaterialGlobals = new(
			"terrain.material.renderer.applyMaterialGlobals",
			"lqt", "kvr");

		internal static readonly MethodSymbol RendererPackedBuildNaturalCallProbe = new(
			"terrain.material.renderer.packedBuildNaturalCallProbe",
			"Method_Private_Void_PDM_0",
			"Method_Private_Void_PDM_1",
			"Method_Private_Void_PDM_2",
			"Method_Private_Void_PDM_3",
			"Method_Private_Void_PDM_4",
			"Method_Private_Void_PDM_5",
			"Method_Private_Void_PDM_6",
			"Method_Private_Void_PDM_7",
			"Method_Private_Void_PDM_8",
			"Method_Private_Void_1",
			"Method_Private_Void_PDM_9",
			"Method_Private_Void_2",
			"Method_Public_Void_PDM_0",
			"Method_Public_Void_PDM_1",
			"Method_Public_Void_PDM_2",
			"Method_Public_Void_PDM_3",
			"Method_Public_Void_PDM_4",
			"bbd", "fdp", "hd", "ioj", "kwe", "kwi", "lqt", "lty", "nxb", "wu");

		internal static readonly string[] RendererPackedBuildStatePrepMethodNames =
			{ "Method_Private_Void_PDM_5" };

		internal static readonly MethodSymbol RendererTextureArrayBuildNaturalCallProbe = new(
			"terrain.material.renderer.textureArrayBuildNaturalCallProbe",
			"Method_Private_Void_Int32_Int32_0",
			"Method_Private_Void_Int32_Int32_PDM_0",
			"Method_Private_Void_Int32_Int32_PDM_1",
			"Method_Private_Void_Int32_Int32_PDM_2",
			"ewp", "imr", "kwj", "kzh", "lzo");

		internal static readonly MethodSymbol RendererMapNaturalCallProbe = new(
			"terrain.material.renderer.mapNaturalCallProbe",
			"Method_Private_Void_Map_0",
			"Method_Private_Void_Map_1",
			"Method_Private_Void_Map_PDM_0",
			"Method_Private_Void_Map_PDM_1",
			"fuv", "ilg", "kwg", "kwh");

		internal static readonly MethodSymbol RendererPrepareNaturalCallProbe = new(
			"terrain.material.renderer.prepareNaturalCallProbe",
			"Method_Public_Void_Map_Boolean_Boolean_0",
			"Method_Public_Void_Map_Boolean_Boolean_1",
			"Method_Public_Void_Map_Boolean_Boolean_2",
			"Method_Public_Void_Map_Boolean_Boolean_3",
			"kwc");

		internal static readonly FieldSymbol[] RendererPackedTextureArrays =
		{
			new("terrain.material.renderer.packedTextureArray.deobf", "NativeFieldInfoPtr_field_Private_Texture2DArray_0", "field_Private_Texture2DArray_0"),
			new("terrain.material.renderer.packedTextureArray.deobfNative", "NativeFieldInfoPtr_bshu", "bshu"),
			new("terrain.material.renderer.packedTextureArray.oldMay", "NativeFieldInfoPtr_bsdk", "bsdk"),
			new("terrain.material.renderer.packedTextureArray.old", "NativeFieldInfoPtr_bsce", "bsce")
		};

		// Adjacent packed terrain renderer state on current Golden Era. These are diagnostics for the
		// native packed material path, not rebuild candidates.
		internal static readonly FieldSymbol[] RendererPackedStateFields =
		{
			new("terrain.material.renderer.packedState.materialIndices.deobf", "NativeFieldInfoPtr_field_Private_Il2CppReferenceArray_1_Il2CppStructArray_1_Int32_0", "field_Private_Il2CppReferenceArray_1_Il2CppStructArray_1_Int32_0"),
			new("terrain.material.renderer.packedState.materialIndices.deobfNative", "NativeFieldInfoPtr_bshv", "bshv"),
			new("terrain.material.renderer.packedState.tileIndices.deobf", "NativeFieldInfoPtr_field_Private_Il2CppStructArray_1_Int32_0", "field_Private_Il2CppStructArray_1_Int32_0"),
			new("terrain.material.renderer.packedState.tileIndices.deobfNative", "NativeFieldInfoPtr_bshw", "bshw"),
			new("terrain.material.renderer.packedState.colors.deobf", "NativeFieldInfoPtr_field_Private_Il2CppReferenceArray_1_Il2CppStructArray_1_Color_0", "field_Private_Il2CppReferenceArray_1_Il2CppStructArray_1_Color_0"),
			new("terrain.material.renderer.packedState.colors.deobfNative", "NativeFieldInfoPtr_bshx", "bshx"),
			new("terrain.material.renderer.packedState.nodes.deobf", "NativeFieldInfoPtr_field_Private_Il2CppStructArray_1_Vector4_0", "field_Private_Il2CppStructArray_1_Vector4_0"),
			new("terrain.material.renderer.packedState.nodes.deobfNative", "NativeFieldInfoPtr_bsia", "bsia"),
			new("terrain.material.renderer.packedState.splat0.deobf", "NativeFieldInfoPtr_field_Private_Il2CppStructArray_1_Vector4_1", "field_Private_Il2CppStructArray_1_Vector4_1"),
			new("terrain.material.renderer.packedState.splat0.deobfNative", "NativeFieldInfoPtr_bsib", "bsib"),
			new("terrain.material.renderer.packedState.splat1.deobf", "NativeFieldInfoPtr_field_Private_Il2CppStructArray_1_Vector4_2", "field_Private_Il2CppStructArray_1_Vector4_2"),
			new("terrain.material.renderer.packedState.splat1.deobfNative", "NativeFieldInfoPtr_bsic", "bsic")
		};

		// Hex/TerrainMap shader strings in current Golden Era resources show the packed terrain texture
		// array as _Textures. Keep this exact and centralized; do not guess broad _MainTexArray-style fallbacks.
		internal static readonly string[] TerrainMapPackedTextureArrayProperties =
			{ "_Textures" };

		internal static readonly string[] TerrainMapTextureNodeProperties =
			{ "_TextureNodes" };

		internal const int NativePackedMaterialSlotLimit = 16;

		// Covers custom land tiles through Permafrost (30) plus one spare; 24-28 remain retired display-water ids.
		internal const int CustomBiomePackedSlotCapacity = 32;

		internal static readonly string[] TerrainMapPackedVectorArrayProperties =
		{
			"Terrain_BiomParams",
			"Terrain_Tilings",
			"Terrain_HeightmapScales"
		};

		internal static readonly FieldSymbol[] RendererMaterialLookups =
		{
			new("terrain.material.renderer.materialLookup.deobf", "NativeFieldInfoPtr_field_Private_Dictionary_2_Int32_Int32_0", "field_Private_Dictionary_2_Int32_Int32_0"),
			new("terrain.material.renderer.roadLookup.deobf", "NativeFieldInfoPtr_field_Private_Dictionary_2_Int32_Int32_1", "field_Private_Dictionary_2_Int32_Int32_1"),
			new("terrain.material.renderer.materialLookup.may21", "NativeFieldInfoPtr_bsge", "bsge"),
			new("terrain.material.renderer.roadLookup.may21", "NativeFieldInfoPtr_bsgi", "bsgi"),
			new("terrain.material.renderer.materialLookup.deobfBacking", "NativeFieldInfoPtr__bseu_k__BackingField", "_bseu_k__BackingField"),
			new("terrain.material.renderer.roadLookup.deobfBacking", "NativeFieldInfoPtr__bsck_k__BackingField", "_bsck_k__BackingField"),
			new("terrain.material.renderer.materialLookup", "NativeFieldInfoPtr_bseu", "bseu"),
			new("terrain.material.renderer.roadLookup", "NativeFieldInfoPtr_bsey", "bsey"),
			new("terrain.material.renderer.materialLookup.oldMay", "NativeFieldInfoPtr_bsdu", "bsdu"),
			new("terrain.material.renderer.roadLookup.oldMay", "NativeFieldInfoPtr_bsdy", "bsdy"),
			new("terrain.material.renderer.materialLookup.old", "NativeFieldInfoPtr_bscg", "bscg"),
			new("terrain.material.renderer.roadLookup.old", "NativeFieldInfoPtr_bsck", "bsck")
		};

	}

	/// <summary>
	/// ELang/font static bootstrap helper (static void (ELang, Dictionary&lt;string, FontByLang&gt;)) that
	/// <see cref="ElangHjsNreWorkaround"/> wraps with an NRE finalizer. Owner and method are resolved only
	/// through these hints; on a build where they are refused the workaround is skipped (no type scan).
	/// </summary>
	internal static partial class ElangFontBootstrap
	{
		internal const string OwnerTypeId = "ui.elang.fontBootstrap.owner";
		internal static readonly string[] OwnerTypeHints =
			{ "ObjectPublicAbstractSealedDi2StFobpTMDi2StbpUnique", "ip" };

		internal static readonly MethodSymbol Bootstrap = new(
			"ui.elang.fontBootstrap.method",
			"Method_Private_Static_Void_ELang_Dictionary_2_String_FontByLang_0", "hmn", "hjs");
	}

	internal static partial class TerrainSound
	{
		internal const string HeroBiomeSoundTypeId = "terrain.sound.heroBiome";
		internal static readonly string HeroBiomeSoundTypeHint = "eza";

		internal static readonly MethodSymbol HeroBiomeBuildMap = new(
			"terrain.sound.heroBiome.buildMap",
			"bias", "bhzp", "Method_Public_Void_Map_0", "Method_Public_Void_Map_PDM_0", "Method_Public_Void_Map_PDM_1");

		internal static readonly MethodSymbol HeroBiomeLookupByTileCode = new(
			"terrain.sound.heroBiome.lookupByTileCode",
			"biat", "bhzq", "get_Item", "fvl", "mij",
			"Method_Private_EHeroSoundType_Int32_0", "Method_Private_EHeroSoundType_Int32_PDM_0");

		internal static readonly FieldSymbol HeroBiomeSoundByTileCode = new(
			"terrain.sound.heroBiome.soundByTileCode",
			"NativeFieldInfoPtr_ciwe",
			"ciwe");

		internal static readonly FieldSymbol[] HeroBiomeStaticArrays =
		{
			new("terrain.sound.heroBiome.staticByTileCode.deobf", "field_Private_Static_Il2CppStructArray_1_EHeroSoundType_0", "field_Private_Static_Il2CppStructArray_1_EHeroSoundType_0"),
			new("terrain.sound.heroBiome.soundByTileCode", "NativeFieldInfoPtr_ciwe", "ciwe"),
			new("terrain.sound.heroBiome.selector.soundByTileCode", "NativeFieldInfoPtr_civj", "civj")
		};

		internal static readonly FieldSymbol[] HeroBiomeInstanceArrays =
		{
			new("terrain.sound.heroBiome.instanceByTileCode.deobf", "field_Private_Il2CppStructArray_1_EHeroSoundType_0", "field_Private_Il2CppStructArray_1_EHeroSoundType_0"),
			new("terrain.sound.heroBiome.instanceByTileCode", "NativeFieldInfoPtr_ciwc", "ciwc"),
			new("terrain.sound.heroBiome.instanceByTileCode.oldMay", "NativeFieldInfoPtr_civh", "civh")
		};

		internal static readonly FieldSymbol[] HeroBiomeSelectorFields =
		{
			new("terrain.sound.heroBiome.selector", "NativeFieldInfoPtr_ciws", "ciws")
		};

		internal const string HeroBiomeControllerTypeId = "terrain.sound.heroBiome.controller";
		internal static readonly string HeroBiomeControllerTypeHint = "ezh";

		internal static readonly MethodSymbol HeroBiomeControllerLifecycle = new(
			"terrain.sound.heroBiome.controller.lifecycle",
			"Init", "hva", "huz");

		internal static readonly FieldSymbol[] HeroBiomeControllerSelectorFields =
		{
			new("terrain.sound.heroBiome.controller.selector", "NativeFieldInfoPtr_cixn", "cixn")
		};

		// Live Golden Era Player.log pins GetSoundsVolume on ezd (older dumps used eyu; ezb is a different type).
		internal const string AmbientBiomeSoundTypeId = "terrain.sound.ambientBiome";
		internal static readonly string AmbientBiomeSoundTypeHint = "ezd";

		internal static readonly MethodSymbol AmbientBiomeBuild = new(
			"terrain.sound.ambientBiome.build",
			"Method_Private_Void_0", "Method_Private_Void_PDM_0", "Method_Private_Void_PDM_1",
			"biav", "bhzs", "bict", "Method_Public_Void_PDM_0");

		internal static readonly MethodSymbol AmbientBiomeGetVolumes = new(
			"terrain.sound.ambientBiome.getVolumes",
			"GetSoundsVolume", "iwv", "ch", "fiw");

		// Live Golden Era dump pin: ezd.cizf (static EAmbientSoundType[]), tile-code → ambient type.
		// Interop exposes it as property field_Private_Static_Il2CppStructArray_1_EAmbientSoundType_0;
		// NativeFieldInfoPtr_* is IntPtr metadata only — do not GetValue it as the array.
		// Only this static map is tile-code-indexed. Do NOT treat ezd instance arrays as tile maps:
		// cizb/cizc are EAmbientSoundType.NUM-sized (8) working counts/volumes; cizd is per-cell.
		// Extending volumes by tileCode makes GetSoundsVolume return len>8 while ezi.cjab stays bool[8]
		// → ezi.bidt IndexOutOfRange (Player.log / BhWorldCamera / ModeBattle.Activate path).
		internal static readonly FieldSymbol AmbientSoundByTileCode = new(
			"terrain.sound.ambientBiome.soundByTileCode",
			"NativeFieldInfoPtr_field_Private_Static_Il2CppStructArray_1_EAmbientSoundType_0",
			"field_Private_Static_Il2CppStructArray_1_EAmbientSoundType_0");

		// Historical / stale names only — not tile-code maps on Golden Era ezd. Kept for audit grep;
		// EnsureBiomeSoundMappings must not extend these by custom tileCode.
		internal static readonly FieldSymbol[] AmbientInstanceArrays =
		{
			new("terrain.sound.ambientBiome.counts.deobf", "NativeFieldInfoPtr_field_Private_Il2CppStructArray_1_Int32_0", "field_Private_Il2CppStructArray_1_Int32_0"),
			new("terrain.sound.ambientBiome.counts", "NativeFieldInfoPtr_civl", "civl"),
			new("terrain.sound.ambientBiome.volumes.deobf", "NativeFieldInfoPtr_field_Private_Il2CppStructArray_1_Single_0", "field_Private_Il2CppStructArray_1_Single_0"),
			new("terrain.sound.ambientBiome.volumes", "NativeFieldInfoPtr_civm", "civm"),
			new("terrain.sound.ambientBiome.perCellTypes.deobf", "NativeFieldInfoPtr_field_Private_Il2CppStructArray_1_EAmbientSoundType_0", "field_Private_Il2CppStructArray_1_EAmbientSoundType_0"),
			new("terrain.sound.ambientBiome.perCellTypes", "NativeFieldInfoPtr_civn", "civn")
		};

		internal const string AmbientFogControllerTypeId = "terrain.sound.ambientFogController";
		internal static readonly string AmbientFogControllerTypeHint = "ezg";

		internal static readonly MethodSymbol AmbientFogControllerRefresh = new(
			"terrain.sound.ambientFogController.refresh",
			"bibv");

		internal static readonly MethodSymbol AmbientFogControllerEarlyRefresh = new(
			"terrain.sound.ambientFogController.earlyRefresh",
			"Init", "hva", "huz");

		internal static readonly FieldSymbol AmbientFogControllerActiveByTileCode = new(
			"terrain.sound.ambientFogController.activeByTileCode",
			"NativeFieldInfoPtr_cixg",
			"cixg");
	}

	internal static partial class DamageKill
	{
		internal static readonly string[] UnitDataFields =
			{ "chgw", "<chgw>k__BackingField", "_chgw_k__BackingField", "chfb", "<chfb>k__BackingField", "_chfb_k__BackingField", "cghc", "chgb" };

		internal static readonly MethodSymbol UnitStatsGetter = new(
			"battle.damageKill.unitStats.getter",
			"bbay", "bbax", "bewo", "bewq", "bcst", "bajp", "bcbb");

		internal static readonly MethodSymbol UnitDataGetter = new(
			"battle.damageKill.unitData.getter",
			"bewm", "beuq", "bevn");

		internal static readonly MethodSymbol StackCountGetter = new(
			"battle.damageKill.stackCount.getter",
			"bbaz", "bbcg", "bajq", "bayd", "ish", "crf", "bbak");

		internal static readonly MethodSymbol KilledStackGetter = new(
			"battle.damageKill.killedStack.getter",
			"bbfj", "bbel");

		internal static readonly MethodSymbol AliveStackCountGetter = new(
			"battle.damageKill.aliveStackCount.getter",
			"bfbe", "beic");

		internal static readonly string[] HpLastUnitFields =
			{ "chmd", "cgmp" };

		internal static readonly string[] AllStacksFields =
			{ "cnxs", "cmxs" };

		internal static readonly string[] FullStacksFields =
			{ "fullStacks" };

		internal static readonly string[] TempFullStacksFields =
			{ "chme", "cgmq" };

		internal static readonly string[] HpPerFallbackFields =
			{ "chmd", "cgmp" };
	}

	internal static partial class DamageForecast
	{
		internal const string ParamsCaster = "caster";
		internal const string ParamsCastSource = "castSource";
		internal const string ParamsTarget = "target";
		internal const string ParamsDmgMult = "dmgMult";
		internal const string ParamsSideCastType = "sideCastType";
		internal const string ParamsPathLength = "pathLength";

		internal static readonly string[][] FieldGroups =
		{
			new[] { "chdd", "chde", "chdi", "chdj" },
			new[] { "chai", "chaj", "chan", "chao" },
			new[] { "cgau", "cgav", "cgaz", "cgba" },
			new[] { "cgwy", "cgwz", "cgxd", "cgxe" }
		};
	}

	internal static partial class DamageForecastPanel
	{
		internal static readonly string[] CounterIndicatorFields =
			{ "isCounter" };

		internal static readonly MethodSymbol PanelRectGetter = new(
			"battle.damageForecastPanel.rectTransform.getter",
			"bepb", "bdxa", "nmp");
	}

	/// <summary>
	/// Audit B5 (2026-09-27): members the OfficialDeobf compile interop exposes under semantic names
	/// but the live Golden Era interop renames, so a direct reference throws MissingMethodException
	/// on the live game (they were allow-listed in tools/verify_plugin_live_interop_refs). Live names
	/// were read from the live wrappers' IL2CPP.GetIl2CppField(..., "native") strings. Read these by
	/// reflection (DeobfInteropCompat); the semantic name comes first for the deobf build.
	/// </summary>
	internal static partial class LiveRenamedMembers
	{
		/// <summary>BhSelectedUnitView.pic (Image); live field_Private_Image_0 = native "pic".</summary>
		internal static readonly string[] SelectedUnitViewPic = { "pic", "field_Private_Image_0" };

		/// <summary>UnitStat.crit (float); live field_Public_Single_0 = native "crit".</summary>
		internal static readonly string[] UnitStatCrit = { "crit", "field_Public_Single_0" };

		/// <summary>UnitStat.hp (int); live field_Public_Int32_0 = native "hp".</summary>
		internal static readonly string[] UnitStatHp = { "hp", "field_Public_Int32_0" };

		/// <summary>Static BhHeroHUDPanel.me; live field_Public_Static_BhHeroHUDPanel_0 = native "me".</summary>
		internal static readonly string[] HeroHudPanelStaticMe = { "me", "field_Public_Static_BhHeroHUDPanel_0" };

		/// <summary>
		/// DamageUiParams caster/castSource/target keep their names live, but their types are
		/// different obfuscated interfaces (deobf dyt/dyu/dyx), so the typed getters do not bind.
		/// </summary>
		internal static readonly string[] DamageUiParamsCaster = { "caster" };
		internal static readonly string[] DamageUiParamsCastSource = { "castSource" };
		internal static readonly string[] DamageUiParamsTarget = { "target" };
	}

	internal static partial class DamageRetaliation
	{
		internal static readonly MethodSymbol CasterSourceGetter = new(
			"battle.damageRetaliation.casterSource.getter",
			"bbbb", "bajs");
	}

	internal static partial class CounterstrokeDoctrine
	{
		internal const string AbilityExecutionTypeId = "battle.counterstroke.abilityExecution";
		internal static readonly string[] AbilityExecutionTypeHints = { "dxy" };

		internal static readonly string[] TriggeringAbilityExecuteMethods =
			{ "bate", "ldn", "cec" };

		internal const string EventDispatcherTypeId = "battle.counterstroke.eventDispatcher";
		internal static readonly string[] EventDispatcherTypeHints = { "edb" };

		internal static readonly MethodSymbol TriggerCounterDispatcher = new(
			"battle.counterstroke.triggerCounter.dispatcher",
			"bcry");

		internal const string DamageCalculatorTypeId = "battle.counterstroke.damageCalculator";
		internal static readonly string[] DamageCalculatorTypeHints = { "ell" };

		internal static readonly string[] DamageCandidateMethods =
			{ "bert", "hem" };
	}

	/// <summary>
	/// Bulwark Runes committed attack/cast surface. Static DiffableCs/ISIL pin of
	/// <c>dxy.bate</c> resolved by metadata token / RVA into Golden Era interop
	/// (do not resolve by short names <c>bate</c>/<c>ldn</c>/<c>cec</c>):
	/// runtime type <c>ObjectPublicObceInBoInceAbObELInUnique</c>, generated
	/// wrapper <c>Method_Private_Void_Il2CppStructArray_1_Int32_HashSet_1_FieldObject_0</c>,
	/// token <c>0x6009067</c> (100700263), RVA <c>0x2EA7710</c> / VA <c>0x182EA7710</c>,
	/// params <c>Il2CppStructArray&lt;int&gt;</c> + <c>HashSet&lt;FieldObject&gt;</c>,
	/// return void. Void success: failure paths throw (null → <c>int 3</c>);
	/// normal return follows CastAbilityEventArgs construction/publication, so a
	/// Harmony postfix after successful invoke means committed. Award +1 in that
	/// postfix — do not stash into ActionEnded.
	/// LIVE-NEGATIVE: do not Harmony-patch <c>eda</c> CastAbility Method_34.
	/// </summary>
	internal static partial class BulwarkRunesLaws
	{
		internal const string AbilityRuntimeTypeId = "battle.bulwarkRunes.abilityRuntime";
		internal static readonly string[] AbilityRuntimeTypeHints =
			{ "ObjectPublicObceInBoInceAbObELInUnique" };

		internal const int AbilityCommitExecuteMetadataToken = 100700263;
		internal const string AbilityCommitExecuteRvaHex = "0x2EA7710";
		internal const string AbilityCommitExecuteVaHex = "0x182EA7710";

		internal static readonly MethodSymbol AbilityCommitExecute = new(
			"battle.bulwarkRunes.abilityCommitExecute",
			"Method_Private_Void_Il2CppStructArray_1_Int32_HashSet_1_FieldObject_0");

		internal static readonly string[] AbilityRuntimeCasterMembers =
			{ "ceis", "field_Public_ede_0", "field_Public_FieldObjectPublicAbstractObUnObcfcnObstcnUnHeUnique_0" };

		internal static readonly string[] AbilityRuntimeLogicConfigMembers =
			{ "cejb", "field_Public_AbilityLogicConfig_0" };

		internal static readonly string[] AbilityLogicMoveTypeMembers =
			{ "moveType", "get_moveType" };

		internal static readonly string[] AbilityLogicAttackTypeMembers =
			{ "attackType_", "get_attackType_", "attackType" };

		internal static readonly string[] AbilityLogicCastTypeMembers =
			{ "castType_", "get_castType_", "castType" };
	}

	internal static partial class DamageCastSource
	{
		internal static readonly string[] PrimaryDamageDealerGetters =
			{ "baqr", "zzs" };

		internal static readonly string[] SecondaryDamageDealerGetters =
			{ "baqs", "zzt" };

		internal static readonly string[] CastSourceIdGetters =
			{ "baqq", "zzr", "banu" };

		internal static readonly string[] RuntimeDealerMembers =
			{ "data", "config" };

		internal const string AttackPatternSidMember = "attackPatternSid";
		internal const string TriggerCounterMember = "triggerCounter";
	}

	internal static partial class SelectedUnitHud
	{
		internal static readonly MethodSymbol HudEventBind = new(
			"battle.selectedUnit.hud.eventBind",
			"bejn", "behr", "begs", "befw", "beeu", "begr", "befv", "beet",
			"Method_Private_Void_Object_BattleEventArgs_0", "Method_Private_Void_Object_BattleEventArgs_PDM_0");

		internal static readonly MethodSymbol HudDirectBind = new(
			"battle.selectedUnit.hud.directBind",
			"bejo", "behs", "begt", "begs", "befw", "beia",
			"Method_Public_Void_Boolean_Unit_0", "Method_Public_Void_Boolean_Unit_PDM_0");

		internal static readonly MethodSymbol ControlsClick = new(
			"battle.selectedUnit.controls.click",
			"belo", "Method_Public_Void_BhUnitAbilityView_0",
			"bejs", "beit", "beis", "behw");

		internal static readonly MethodSymbol ControlsHotkey = new(
			"battle.selectedUnit.controls.hotkey",
			"beme", "bdrf", "beki", "bejj", "beji", "beim", "Method_Private_Void_Object_HotkeyAbilityArgs_PDM_0");

		internal static readonly MethodSymbol AbilityViewBind = new(
			"battle.selectedUnit.abilityView.bind",
			"beky", "Method_Public_Void_ObjectPublicObBochBoObchBochBoUnique_Boolean_PDM_0", "bejc");

		internal static readonly MethodSymbol AbilityViewBaseFocusMarkers = new(
			"battle.selectedUnit.abilityViewBase.focusMarkers",
			"uga", "ucx", "ufi");

		internal static readonly string[] AbilityWrapperTypeNames =
			{ "ObjectPublicObceInBoInceAbObELInUnique", "dxy", "dwr" };

		internal static readonly string[] AbilityViewWrapperTypeNames =
			{ "ObjectPublicObBochBoObchBochBoUnique", "emb", "elz", "els", "ekn" };

		internal static readonly string[] ControlsAbilityViewTypeNames =
			{ "Hex.Session.Battle.BhUnitAbilityView", "BhUnitAbilityView" };

		internal static readonly string[] BasicCommandsTypeNames =
			{ "Hex.UI.BhUnitBasicCommands", "BhUnitBasicCommands" };

		internal static readonly string[] AbilityManagerTypeNames =
			{ "dxx", "ObjectPublicObceDiObce2EAInBoInUnique" };

		internal static readonly MethodSymbol AbilityWrapperTryGetAbility = new(
			"battle.selectedUnit.abilityWrapper.tryGetAbility",
			"beue", "oku",
			"Method_Public_Boolean_byref_ObjectPublicObceInBoInceAbObELInUnique_PDM_0",
			"Method_Public_Boolean_byref_ObjectPublicObceInBoInceAbObELInUnique_PDM_1",
			"besi", "beri", "flz", "eca", "berj", "lqt", "hgc", "jdi", "kvk", "mll", "fd", "mzp", "beqo", "gfs", "zp");

		internal static readonly MethodSymbol ControlsBind = new(
			"battle.selectedUnit.controls.bindAbilities",
			"beln",
			"Method_Public_Void_Il2CppReferenceArray_1_ObjectPublicObceInBoInceAbObELInUnique_ObjectPublicObceInBoInceAbObELInUnique_Boolean_PDM_0",
			"bejr", "beis", "beir", "behv");

		internal static readonly MethodSymbol ControlsClickEnabled = new(
			"battle.selectedUnit.controls.setClickEnabled",
			"belz", "bekd", "beje", "beii", "bejd", "beih", "Method_Private_Void_Boolean_PDM_0");

		internal static readonly MethodSymbol ControlsSelect = new(
			"battle.selectedUnit.controls.selectAbility",
			"belt", "bejx", "beiy", "beic", "beix", "beib",
			"Method_Private_Void_ObjectPublicObceInBoInceAbObELInUnique_PDM_0");

		internal static readonly MethodSymbol ControlsSyncAbilityView = new(
			"battle.selectedUnit.controls.syncAbilityView",
			"belq", "Method_Private_Void_BhUnitAbilityView_PDM_0");

		// Source-prepared/static-proven 2026-06-22, runtime-unvalidated:
		// BhUnitBasicCommands.smf(Unit) refreshes waitDefault/waitAlt, and
		// smg(Unit) refreshes skipDefault/skipAlt. Keep these split so a
		// partial refresh cannot leave the wait-alt GameObject stale.
		internal static readonly MethodSymbol BasicCommandsWaitRefresh = new(
			"battle.selectedUnit.basicCommands.waitRefresh",
			"Method_Public_Void_Unit_PDM_0");

		internal static readonly MethodSymbol BasicCommandsSkipRefresh = new(
			"battle.selectedUnit.basicCommands.skipRefresh",
			"Method_Public_Void_Unit_PDM_1");

		internal static readonly MethodSymbol AbilityBucket = new(
			"battle.selectedUnit.abilityManager.bucket",
			"baql", "baox", "jus", "itp", "mpy", "bana", "bama", "baoa", "banz", "klu", "ihh", "fnd", "fsk", "bar", "drf",
			"Method_Public_Il2CppReferenceArray_1_ObjectPublicObceInBoInceAbObELInUnique_EAbilityType_0");

		internal static readonly MethodSymbol UnitLogicAbilityBucket = new(
			"battle.selectedUnit.unitLogicConfig.abilityBucket",
			"Method_Public_Il2CppReferenceArray_1_AbilityLogicConfig_EAbilityType_0", "scu");

		internal static readonly MethodSymbol UnitViewAbilityBucket = new(
			"battle.selectedUnit.unitViewConfig.abilityBucket",
			"Method_Public_Il2CppReferenceArray_1_AbilityViewConfig_EAbilityType_0", "sem");

		internal static readonly MethodSymbol UnitViewAbilityAt = new(
			"battle.selectedUnit.unitViewConfig.abilityAt",
			"Method_Public_AbilityViewConfig_EAbilityType_Int32_PDM_0", "sel");

		internal static readonly MethodSymbol AbilityWrapperInit = new(
			"battle.selectedUnit.abilityWrapper.init",
			"Init", "ius",
			"Method_Public_Void_AbilityLogicConfig_AbilityViewConfig_AbilityID_PDM_0",
			"Method_Public_Void_AbilityLogicConfig_AbilityViewConfig_AbilityID_PDM_1");

		internal static readonly string[] UnitLogicConfigFields =
			{ "chgu", "bewi", "<chgu>k__BackingField", "_chgu_k__BackingField", "chfz", "bevj", "<chfz>k__BackingField", "_chfz_k__BackingField", "chjp", "<chjp>k__BackingField", "_chjp_k__BackingField", "chez", "chbv", "cgha" };

		internal static readonly string[] UnitViewConfigFields =
			{ "chgv", "bewk", "<chgv>k__BackingField", "_chgv_k__BackingField", "chga", "bevl", "<chga>k__BackingField", "_chga_k__BackingField", "chjq", "<chjq>k__BackingField", "_chjq_k__BackingField", "chfa", "chbw" };

		internal static readonly string[] HireAbilityWrapperLogicFields =
			{ "bwhq", "field_Public_AbilityLogicConfig_0" };

		internal static readonly string[] UnitSidTransferFields =
			{ "chey", "_chdi_k__BackingField", "_chjo_k__BackingField", "<chjo>k__BackingField", "chjo", "cggz" };

		internal static readonly string[] UnitSidConfigIdFields =
			{ "cgha" };

		internal static readonly string[] UnitReleaseAliasConfigFields =
			{ "chfa", "chez", "chfb", "cgha" };

		internal static readonly MethodSymbol UnitLogicConfigGetter = new(
			"battle.selectedUnit.unit.logicConfigGetter",
			"Method_Public_get_UnitLogicConfig_0");

		internal static readonly MethodSymbol UnitViewConfigGetter = new(
			"battle.selectedUnit.unit.viewConfigGetter",
			"Method_Public_get_UnitViewConfig_0");

		internal static readonly string[] AbilityManagerFields =
			{ "cfng", "<cfng>k__BackingField", "_cfng_k__BackingField", "cfkv", "<cfkv>k__BackingField", "_cfkv_k__BackingField", "cfkb", "<cfkb>k__BackingField", "_cfkb_k__BackingField", "cfjy", "<cfjy>k__BackingField", "_cfjy_k__BackingField", "cfjb", "<cfjb>k__BackingField", "_cfjb_k__BackingField" };

		internal static readonly MethodSymbol AbilityManagerGetter = new(
			"battle.selectedUnit.abilityManager.getter",
			"bcud", "bcsn", "bcrm", "bcrn", "bcqo");

		internal static readonly MethodSymbol AbilityManagerFieldObjectInit = new(
			"battle.selectedUnit.abilityManager.initFieldObject",
			"Init",
			"Method_Public_Void_FieldObjectPublicAbstractObUnObcfcnObstcnUnHeUnique_PDM_0",
			"Method_Public_Void_FieldObjectPublicAbstractObUnObcfcnObstcnUnHeUnique_PDM_1",
			"Method_Public_Void_FieldObjectPublicAbstractObUnObcfcnObstcnUnHeUnique_PDM_2",
			"Method_Public_Void_FieldObjectPublicAbstractObUnObcfcnObstcnUnHeUnique_PDM_3");

		internal static readonly string[] AbilityLogicFields =
			{ "field_Public_AbilityLogicConfig_0", "cejb", "cegq", "ceex", "<ceex>k__BackingField", "ceeu", "<ceeu>k__BackingField", "cech", "cedw", "cdgt" };

		internal static readonly string[] AbilityViewFields =
			{ "field_Public_AbilityViewConfig_0", "cejc", "cegr", "ceey", "<ceey>k__BackingField", "ceev", "<ceev>k__BackingField", "ceci", "cedx", "cdgu" };

		internal static readonly string[] AbilityViewAbilityFields =
			{ "chaf", "field_Private_ObjectPublicObceInBoInceAbObELInUnique_0", "cgxk", "cgwp", "cgwm", "cgvp", "cnvi", "cgua" };

		internal static readonly string[] AbilityViewWrapperFields =
			{ "chae", "field_Private_ObjectPublicObBochBoObchBochBoUnique_0", "cgxj", "cgwo", "cgvr", "cgwl", "cgvo", "cgtz" };

		internal static readonly string[] ControlsSelectedViewFields =
			{ "field_Private_BhUnitAbilityView_0", "chao", "cgxt", "cgwy", "cgwv", "cgvy", "cguj" };

		internal static readonly string[] ControlsCurrentAbilityArrayFields =
			{ "field_Private_Il2CppReferenceArray_1_ObjectPublicObceInBoInceAbObELInUnique_0", "chap", "cgxu", "cgwz", "cgvz", "cguk" };

		internal static readonly string[] ControlsAbilityViewByAbilityFields =
			{ "field_Private_Dictionary_2_ObjectPublicObceInBoInceAbObELInUnique_ObjectPublicObBochBoObchBochBoUnique_0" };
	}

	internal static partial class AiDriverCombatSetup
	{
		// Source-prepared 2026-06-20: static DiffableCs/ISIL evidence only.
		// These symbols document the current `ai_start_combat` investigation surface;
		// they must not be treated as a proven command route until live metadata,
		// owner discovery, battle transition, and post-observation proof succeed.
		internal static readonly string[] WorldCheatControllerTypeNames =
			{ "eys", "ObjectPublicInciObInciBoObStInciUnique" };

		internal static readonly string[] WorldCheatCommandTypeNames =
			{ "cux", "Object1PublicIncaStIncaBoStcaInStUnique" };

		// Source-prepared 2026-06-20: generated interop metadata shows these
		// cheat UI windows expose get_sideCheats()/set_sideCheats() returning
		// the eys runtime type. This is owner-discovery evidence only; do not
		// use it as command authorization without fresh live owner proof.
		internal static readonly string[] WorldCheatUiOwnerTypeNames =
			{ "Hex.Cheat.UI.BhWindowWorld", "Hex.Cheat.UI.BhWindowHero", "Hex.Cheat.UI.BhWindowMagic" };

		internal static readonly string[] WorldCheatSessionRootTypeNames =
			{ "ObjectPublicObBhcjObIncjSiObIncoUnique", "fda" };

		internal static readonly MethodSymbol UiOwnerSideCheatsGetter = new(
			"aiDriver.startCombat.cheatUiOwner.sideCheatsGetter",
			"get_sideCheats");

		internal static readonly MethodSymbol SessionRootSideCheatsGetter = new(
			"aiDriver.startCombat.sessionRoot.sideCheatsGetter",
			"get_field_Public_ObjectPublicInciObInciBoObStInciUnique_0");

		internal static readonly MethodSymbol DispatchClickState = new(
			"aiDriver.startCombat.worldCheatController.dispatchClickState",
			"dvf");

		internal static readonly MethodSymbol BuildCreateSquadCommand = new(
			"aiDriver.startCombat.worldCheatController.buildCreateSquadCommand",
			"bhzm");

		internal static readonly MethodSymbol BuildCreateRandomSquadCommand = new(
			"aiDriver.startCombat.worldCheatController.buildCreateRandomSquadCommand",
			"bhzo");

		internal static readonly MethodSymbol BuildBattleAutoWinCommand = new(
			"aiDriver.startCombat.worldCheatController.buildBattleAutoWinCommand",
			"bhzj");

		internal static readonly MethodSymbol WorldCheatCommandTypeGetter = new(
			"aiDriver.startCombat.worldCheatCommand.outerCommandType",
			"hsf");

		internal static readonly FieldSymbol CheatClickStateField = new(
			"aiDriver.startCombat.worldCheatController.clickState",
			"NativeFieldInfoPtr_cixc",
			"cixc");

		internal static readonly FieldSymbol CommandSelectorField = new(
			"aiDriver.startCombat.worldCheatCommand.selector",
			"NativeFieldInfoPtr_cafe",
			"cafe");

		internal static readonly FieldSymbol CommandContextField = new(
			"aiDriver.startCombat.worldCheatCommand.context",
			"NativeFieldInfoPtr_caff",
			"caff");

		internal static readonly FieldSymbol CommandBoolField = new(
			"aiDriver.startCombat.worldCheatCommand.boolArg",
			"NativeFieldInfoPtr_cafi",
			"cafi");

		internal static readonly FieldSymbol CommandXField = new(
			"aiDriver.startCombat.worldCheatCommand.x",
			"NativeFieldInfoPtr_cafp",
			"cafp");

		internal static readonly FieldSymbol CommandYField = new(
			"aiDriver.startCombat.worldCheatCommand.y",
			"NativeFieldInfoPtr_cafq",
			"cafq");

		internal static readonly FieldSymbol CommandZField = new(
			"aiDriver.startCombat.worldCheatCommand.z",
			"NativeFieldInfoPtr_cafr",
			"cafr");

		internal const int StateCheatClickNodeCreateSquad = 1;
		internal const int StateCheatClickNodeCreateRandomSquad = 2;
		internal const int TypeCmdWorldCheatsBattleAutoWin = 12;
		internal const int TypeCmdWorldCheatsCreateSquad = 16;
		internal const int TypeCmdWorldCheatsCreateRandomSquad = 17;
		internal const int WorldCheatOuterCommandType = 0x71;

		internal const int CheatClickStateFieldOffset = 0x3C;
		internal const int CommandSelectorFieldOffset = 0x20;
		internal const int CommandBoolFieldOffset = 0x34;
		internal const int CommandXFieldOffset = 0x64;
		internal const int CommandYFieldOffset = 0x68;
		internal const int CommandZFieldOffset = 0x6C;
	}

	/// <summary>
	/// Battle AI decision loop (computer / auto-battle). Current Golden Era DummyDll
	/// owns the brain on <c>dyt</c>; scorers on <c>dye</c>; execution on <c>ecv</c>.
	/// Do not use May-2026 CSV names <c>dyn</c>/<c>eco</c>/<c>dxy</c>-as-scorer.
	/// Resolve methods by signature; short names drift across builds.
	/// Evidence: docs/ai_decision_logic_surface.md (source/static).
	/// </summary>
	internal static partial class BattleAiDecision
	{
		internal const string BrainTypeId = "battle.ai.decision.brain";
		internal static readonly string[] BrainTypeHints =
			{ "dyt" };

		internal const string ScorerTypeId = "battle.ai.decision.scorer";
		internal static readonly string[] ScorerTypeHints =
			{ "dye" };

		internal const string ExecutorTypeId = "battle.ai.decision.executor";
		internal static readonly string[] ExecutorTypeHints =
			{ "ecv" };

		internal const string ActionTypeId = "battle.ai.decision.action";
		internal static readonly string[] ActionTypeHints =
			{ "Hex.Session.Battle.BattleAiAction", "BattleAiAction" };

		internal const string ParamsTypeId = "battle.ai.decision.params";
		internal static readonly string[] ParamsTypeHints =
			{ "Hex.Configs.BattleAiParams", "BattleAiParams" };

		internal const string UnitTypeId = "battle.ai.decision.unit";
		internal static readonly string[] UnitTypeHints =
			{ "Hex.Session.Battle.Unit", "Unit" };

		// Final pick: (Unit, List&lt;Unit&gt;, List&lt;Unit&gt;, List&lt;BattleAiAction&gt;) → BattleAiAction
		internal static readonly MethodSymbol PickAction = new(
			"battle.ai.decision.pickAction",
			"Method_Private_BattleAiAction_Unit_List_1_Unit_List_1_Unit_List_1_BattleAiAction_0",
			"Method_Private_BattleAiAction_Unit_List_1_Unit_List_1_Unit_List_1_BattleAiAction_PDM_0",
			"Method_Private_BattleAiAction_Unit_List_1_Unit_List_1_Unit_List_1_BattleAiAction_PDM_1",
			"bavi",
			"mla",
			"kkj");

		// Turn score: (Unit, BattleAiParams, List&lt;Unit&gt;, List&lt;Unit&gt;, Dict, Dict) → int
		internal static readonly MethodSymbol ScoreUnitTurn = new(
			"battle.ai.decision.scoreUnitTurn",
			"bavn");

		// Params load: (Unit, ESideCastType) → BattleAiParams
		internal static readonly MethodSymbol LoadParams = new(
			"battle.ai.decision.loadParams",
			"bavl",
			"fpr",
			"lpl",
			"cmt",
			"ic");

		// Execute: (BattleAiAction, int) → void
		internal static readonly MethodSymbol ExecuteAction = new(
			"battle.ai.decision.executeAction",
			"bcau",
			"bcav");

		internal static readonly string[] ActionValueFieldHints =
			{ "value", "NativeFieldInfoPtr_value" };

		internal static readonly string[] ActionTypeFieldHints =
			{ "actionType", "NativeFieldInfoPtr_actionType" };

		internal static readonly string[] ActionCasterFieldHints =
			{ "caster", "NativeFieldInfoPtr_caster" };

		internal static readonly string[] ActionHexAttackFieldHints =
			{ "hexToAttack", "NativeFieldInfoPtr_hexToAttack" };

		internal static readonly string[] ActionHexRunFieldHints =
			{ "hexToRun", "NativeFieldInfoPtr_hexToRun" };

		internal static readonly string[] ActionAbilityFieldHints =
			{ "ability", "NativeFieldInfoPtr_ability" };
	}

	/// <summary>
	/// Adventure/world computer-player AI (mark-centric lookahead surface).
	/// Day entry is <c>fjl.OnStartDay</c>; intent lives in <c>Side.aiData</c>.
	/// Evidence: docs/ai_lookahead_requirements.md, docs/ai_decision_logic_surface.md (source/static).
	/// </summary>
	internal static partial class AdventureAiDecision
	{
		internal const string DayControllerTypeId = "adventure.ai.decision.dayController";
		internal static readonly string[] DayControllerTypeHints =
			{ "fjl" };

		// DummyDll aliases share RVA with OnStartDay (hvs/bro) — prefer readable name.
		internal static readonly MethodSymbol OnStartDay = new(
			"adventure.ai.decision.onStartDay",
			"OnStartDay",
			"hvs",
			"bro");

		internal const string LocatorTypeId = "adventure.ai.decision.locator";
		internal static readonly string[] LocatorTypeHints =
			{ "fhk" };

		internal const string LocatorFieldOnDayControllerId = "adventure.ai.decision.dayController.locatorField";
		internal static readonly string[] LocatorFieldOnDayControllerHints =
			{ "cjwl" };

		internal const string SideRuntimeTypeId = "adventure.ai.decision.sideRuntime";
		internal static readonly string[] SideRuntimeTypeHints =
			{ "fcy" };

		internal const string SideRuntimeOnLocatorId = "adventure.ai.decision.locator.sideRuntime";
		internal static readonly string[] SideRuntimeOnLocatorHints =
			{ "cofk" };

		internal const string SideTypeId = "adventure.ai.decision.side";
		internal static readonly string[] SideTypeHints =
			{ "Hex.Session.Data.Side", "Side" };

		internal const string SideOnRuntimeId = "adventure.ai.decision.sideRuntime.side";
		internal static readonly string[] SideOnRuntimeHints =
			{ "codp" };

		internal const string SideAiDataTypeId = "adventure.ai.decision.sideAiData";
		internal static readonly string[] SideAiDataTypeHints =
			{ "Hex.Session.Data.SideAiData", "SideAiData" };

		internal const string SideAiDataFieldId = "adventure.ai.decision.side.aiData";
		internal static readonly string[] SideAiDataFieldHints =
			{ "aiData" };

		internal const string SideResFieldId = "adventure.ai.decision.side.res";
		internal static readonly string[] SideResFieldHints =
			{ "res" };

		internal const string SideHeroesFieldId = "adventure.ai.decision.side.sideHeroes";
		internal static readonly string[] SideHeroesFieldHints =
			{ "sideHeroes" };

		// SideHeroes container exposes hero id list or hero entry objects via heroes / obfuscated getters.
		internal static readonly string[] SideHeroesListMembers =
			{ "heroes", "get_heroes", "bhud", "bhxe", "Method_Public_get_List_1_Hero_0" };

		internal const string SideIndexFieldId = "adventure.ai.decision.side.index";
		internal static readonly string[] SideIndexFieldHints =
			{ "index" };

		internal const string SideNameFieldId = "adventure.ai.decision.side.name";
		internal static readonly string[] SideNameFieldHints =
			{ "name" };

		// SideAiData mark / memory fields (mark-centric fork).
		internal static readonly string[] MarkedCityFieldHints = { "markedCity" };
		internal static readonly string[] MarkedHeroFieldHints = { "markedHero" };
		internal static readonly string[] MarkedObjectFieldHints = { "markedObject" };
		internal static readonly string[] MarkedNodeFieldHints = { "markedNode" };
		internal static readonly string[] MarkedSquadsFieldHints = { "markedSquads" };
		internal static readonly string[] MarkedEnemyCityFieldHints = { "makredEnemyCity", "markedEnemyCity" };
		internal static readonly string[] MarkedCityToCourierFieldHints = { "markedCityToCourier" };
		internal static readonly string[] MarkedCityToUnitUpgradeFieldHints = { "markedCityToUnitUpgrade" };
		internal static readonly string[] MarkedAreaGuardFieldHints = { "markedAreaGuard" };
		internal static readonly string[] HardStrategyFieldHints = { "hardStrategy" };
		internal static readonly string[] BuildingCooldownFieldHints = { "buildingColdown", "buildingCooldown" };
		internal static readonly string[] HeroesHiredTodayFieldHints = { "heroesHiredToday" };
		internal static readonly string[] AreasReachableFieldHints = { "areasReachable" };
		internal static readonly string[] AreasLastOpenFieldHints = { "areasLastOpen" };

		internal const string DayIndexOnDayControllerId = "adventure.ai.decision.dayController.dayIndex";
		internal static readonly string[] DayIndexOnDayControllerHints =
			{ "cjwk" };

		// Active strategy runner on day controller (optional observe).
		internal const string ActiveStrategyFieldId = "adventure.ai.decision.dayController.activeStrategy";
		internal static readonly string[] ActiveStrategyFieldHints =
			{ "cjwj" };

		internal const string StrategyConfigOnRunnerId = "adventure.ai.decision.strategyRunner.config";
		internal static readonly string[] StrategyConfigOnRunnerHints =
			{ "cjwo" };

		internal const string AiConfigStrategyTypeId = "adventure.ai.decision.aiConfigStrategy";
		internal static readonly string[] AiConfigStrategyTypeHints =
			{ "Hex.Configs.AiConfigStrategy", "AiConfigStrategy" };

		// Task scorer: int bjsj(HeroAiPriority, int, float, float, int, int, float, float, int, int)
		internal const string TaskScorerTypeId = "adventure.ai.decision.taskScorer";
		internal static readonly string[] TaskScorerTypeHints =
			{ "ffe" };

		internal static readonly MethodSymbol ScoreTask = new(
			"adventure.ai.decision.scoreTask",
			"bjsj");

		internal const string HeroAiPriorityTypeId = "adventure.ai.decision.heroAiPriority";
		internal static readonly string[] HeroAiPriorityTypeHints =
			{ "Hex.Configs.HeroAiPriority", "HeroAiPriority" };

		internal static readonly string[] TaskTargetWorldObjectFieldHints =
			{ "cjqw" };

		internal static readonly string[] TaskTargetIdFieldHints =
			{ "cjqs", "cjqt", "cjqu", "cjqz" };

		internal static readonly string[] WorldObjectDataObjectFieldHints =
			{ "cjhx" };

		internal static readonly string[] DataObjectIdFieldHints =
			{ "id" };

		internal static readonly string[] DataHeroNodeFieldHints =
			{ "node" };

		internal static readonly string[] DataHeroMovePointsFieldHints =
			{ "worldMovePoints" };

		internal static readonly string[] DataHeroManaFieldHints =
			{ "mana" };

		internal static readonly string[] DataHeroIdFieldHints =
			{ "id" };

		internal static readonly string[] DataHeroPartyFieldHints =
			{ "party" };

		internal static readonly string[] DataPartyUnitsFieldHints =
			{ "units" };

		internal static readonly string[] DataUnitSidFieldHints =
			{ "field_Public_String_0", "get_field_Public_String_0", "sid" };

		internal static readonly string[] DataUnitStacksFieldHints =
			{ "stacks" };

		internal static readonly string[] SideObjectsFieldHints =
			{ "sideObjects" };

		internal static readonly string[] DataSquadIdFieldHints =
			{ "id" };

		internal static readonly string[] DataSquadNodeFieldHints =
			{ "node" };

		internal static readonly string[] DataSquadStartValueFieldHints =
			{ "startValue" };

		internal static readonly string[] DataSquadReleasedFieldHints =
			{ "released" };
		// MapData is the native world-grid source used by the live AI capture adapter.
		// Keep these names here so capture code does not scatter generated aliases.
		internal const int LiveMapVoidTerrainTileCode = 23;
		internal const int MaxLiveMapCells = 65536;
		internal static readonly string[] LiveMapSizeXMembers =
			{ "sizeX", "get_sizeX" };
		internal static readonly string[] LiveMapSizeZMembers =
			{ "sizeZ", "get_sizeZ" };
		internal static readonly string[] LiveMapTilesMembers =
			{ "tilesMap", "get_tilesMap" };
		internal static readonly string[] LiveMapRoadsMembers =
			{ "roadsMap", "get_roadsMap" };
		internal static readonly string[] LiveMapWaterMembers =
			{ "waterMap", "get_waterMap" };
		internal static readonly string[] LiveMapObjectsMembers =
			{ "objects", "get_objects" };

		internal static readonly string[] DataRootObjectsMembers =
			{ "objects", "get_objects" };
		internal static readonly string[] DataRootHeroesMembers =
			{ "heroes", "get_heroes" };
		internal static readonly string[] DataRootSquadsMembers =
			{ "squads", "get_squads" };
		internal static readonly string[] DataObjectsAllMembers =
			{ "cocf", "get_cocf", "bgfi" };
		internal static readonly string[] DataHeroesAllMembers =
			{ "coba", "get_coba" };
		internal static readonly string[] DataSquadsAllMembers =
			{ "list", "get_list" };
		internal static readonly string[] DataObjectMapIdMembers =
			{ "idMapObject" };
		internal static readonly string[] DataObjectConfigSidMembers =
			{ "sidConfig" };
		internal static readonly string[] DataObjectReleasedMembers =
			{ "released" };
		internal static readonly string[] DataObjectAiValueMembers =
			{ "aiValue" };
		internal static readonly string[] DataObjectNeutralMembers =
			{ "isNeutralObj" };
		internal static readonly string[] DataSquadConfigSidMembers =
			{ "configSid" };
		internal static readonly string[] DataSquadNpcMembers =
			{ "isNPC" };
	}

	internal static partial class UnitPreviewAbilityIcons
	{
		internal static readonly string[] HireAbilityWrapperTypeNames =
			{ "bzd", "ObjectPublicAbbwObBubwObItUnbwObUnique" };

		// Current ISIL evidence: bzd ejl/pna/idu/ecn all call the same clone helper (183373F90) and return bzd.
		internal static readonly MethodSymbol HireAbilityWrapperClone = new(
			"unit.preview.hireAbilityWrapper.clone",
			"Method_Public_ObjectPublicAbbwObBubwObItUnbwObUnique_PDM_0",
			"Method_Public_ObjectPublicAbbwObBubwObItUnbwObUnique_0",
			"Method_Public_ObjectPublicAbbwObBubwObItUnbwObUnique_PDM_1",
			"Method_Public_ObjectPublicAbbwObBubwObItUnbwObUnique_PDM_2",
			"pna");

		internal static readonly string[] HireAbilityWrapperLogicFields = SelectedUnitHud.HireAbilityWrapperLogicFields;

		internal static readonly MethodSymbol AbilityItemPrimaryBind = new(
			"unit.preview.abilityItem.primaryBind",
			"banl", "Method_Public_Void_ObjectPublicAbbwObBubwObItUnbwObUnique_AbilityViewConfig_0", "baly");

		internal static readonly MethodSymbol AbilityItemSecondaryBind = new(
			"unit.preview.abilityItem.secondaryBind",
			"banm", "Method_Public_Void_ObjectPublicAbbwObBubwObItUnbwObUnique_AbilityViewConfig_1", "balz");

		internal static readonly MethodSymbol AbilityViewPrimaryBind = new(
			"unit.preview.abilityView.primaryBind",
			"bann", "Method_Public_Void_AbilityViewConfig_ObjectPublicAbbwObBubwObItUnbwObUnique_0", "bama");

		internal static readonly MethodSymbol AbilityViewSecondaryBind = new(
			"unit.preview.abilityView.secondaryBind",
			"bano", "Method_Public_Void_ObjectPublicAbbwObBubwObItUnbwObUnique_AbilityViewConfig_0", "bamb");

		internal static readonly string[] HireAbilityItemViewConfigFields =
			{ "cege", "field_Private_AbilityViewConfig_0" };

		internal static readonly string[] HireAbilityItemViewWrapperFields =
			{ "cegf", "field_Private_ObjectPublicAbbwObBubwObItUnbwObUnique_0" };

		internal static readonly MethodSymbol HireUnitAbilitiesBind = new(
			"unit.preview.hireUnitAbilities.bind",
			"hun", "hto", "Method_Public_Void_Unit_0", "hue");

		internal static readonly string[] HireUnitItemAbilityFields =
			{ "abilities" };

		internal static readonly string[] HireUnitItemNativePreviewRawImageFields =
			{ "raw", "cnju", "tvg", "field_Private_RawImage_0", "Method_Public_get_RawImage_0" };

		internal static readonly string[] HireUnitItemPreviewFields =
			{ "bzic", "field_Private_BhUnitPreview_0", "get_field_Private_BhUnitPreview_0" };

		internal static readonly string[] HireUnitPreviewRootFields =
			{ "root", "cnhw", "sre", "Method_Public_get_GameObject_0" };

		internal static readonly string[] AbilityViewIconFields =
			{ "pic", "field_Private_Image_0" };

		internal static readonly string[] ConfigRootTypeNames =
			{ "ObjectPublicObbxDaRebxBiUIMebxMaUnique", "cjw", "cjv" };

		internal static readonly string[] ConfigRootMembers =
			{ "field_Private_Static_ObjectPublicObbxDaRebxBiUIMebxMaUnique_0", "prop_ObjectPublicObbxDaRebxBiUIMebxMaUnique_0", "cmxw", "bxij", "cnbn", "cnaq" };

		internal static readonly string[] UnitLogicConfigTables =
			{ "bxpw", "field_Public_cjv_2_UnitLogicConfig_String_0", "bxjv", "bxnu", "bxmk" };

		internal static readonly string[] UnitViewConfigTables =
			{ "bxpx", "field_Public_cjv_2_UnitViewConfig_String_0", "bxjw", "bxnv", "bxml" };

		internal static readonly MethodSymbol ConfigTableTryGet = new(
			"unit.preview.configTable.tryGet",
			"Method_Public_Boolean_b_byref_a_PDM_0", "run", "rub", "rto");

		internal static readonly string[] UnitLogicConfigFields =
			{ "chgu", "<chgu>k__BackingField", "_chgu_k__BackingField", "bewi", "chfz", "<chfz>k__BackingField", "_chfz_k__BackingField", "bevj", "chjp", "<chjp>k__BackingField", "_chjp_k__BackingField", "chez", "chbv", "cgha" };

		internal static readonly string[] UnitViewConfigFields =
			{ "chgv", "<chgv>k__BackingField", "_chgv_k__BackingField", "bewk", "chga", "<chga>k__BackingField", "_chga_k__BackingField", "bevl", "chjq", "<chjq>k__BackingField", "_chjq_k__BackingField", "chfa", "chbw" };

	}

	internal static partial class UnitAbilityNative
	{
		internal static readonly MethodSymbol UnitAbilityAvailability = new(
			"unitAbility.native.unitAbility.availability",
			"lis");

		internal static readonly MethodSymbol ControlsNativeUnitBind = new(
			"unitAbility.native.controls.unitBind",
			"dng");
	}

	internal static partial class BattleUi
	{
		internal static readonly MethodSymbol SelectedHudEventBind = new(
			"battle.ui.selectedHud.eventBind",
			"bejn", "behr", "begs", "beic", "begr", "beib", "befv", "beet",
			"Method_Private_Void_Object_BattleEventArgs_0", "Method_Private_Void_Object_BattleEventArgs_PDM_0");

		internal static readonly MethodSymbol SelectedHudDirectBind = new(
			"battle.ui.selectedHud.directBind",
			"bejo", "behs", "begt", "beib", "begs", "beia",
			"Method_Public_Void_Boolean_Unit_0", "Method_Public_Void_Boolean_Unit_PDM_0");

		internal static readonly MethodSymbol SelectedUnitViewBind = new(
			"battle.ui.selectedUnitView.bind",
			"behx", "begy", "begc", "befa", "beig", "begx", "begb", "beez", "beif",
			"Method_Public_Void_String_0", "Method_Public_Void_String_PDM_0");

		internal static readonly MethodSymbol QueueLayout = new(
			"battle.ui.queue.layout",
			"beef", "bede", "becg", "bedf", "bech", "jnk", "bebg",
			"Method_Private_Void_List_1_ObjectPublicUnchInBhchTuTuchchUnique_0",
			"Method_Private_Void_List_1_ObjectPublicUnchInBhchTuTuchchUnique_PDM_0");

		internal static readonly string[] TurnItemTypeNames =
			{ "elx", "elq", "elm", "ObjectPublicUnchInBhchTuTuchchUnique" };

		internal static readonly string[] TurnItemUnitFields =
			{ "chbr", "chaw", "chat", "cgzw", "cgyh", "cgwt", "cgxm", "unit", "_unit" };

		internal static readonly string[] TurnItemViewFields =
			{ "chbt", "chay", "chav", "cgzy", "cgyj", "cgwv", "view", "turnView" };

		internal static readonly string[] TurnItemKnownUnitFields =
			{ "chbr", "chaw", "chat", "cgzw", "cgyh" };

		internal static readonly string[] TurnItemKnownViewFields =
			{ "chbt", "chay", "chav", "cgzy", "cgyj" };

		internal static readonly string[] TurnViewUnitFields =
			{ "field_Private_Unit_0", "cgzn", "cgva", "cgvu", "_cgvu_k__BackingField", "<cgvu>k__BackingField", "cgux", "cgti", "cgru", "unit", "_unit", "cgyh" };

		internal static readonly string[] UnitTransferFields =
			{ "chgt", "bewg", "<chgt>k__BackingField", "chfy", "bevh", "<chfy>k__BackingField", "chfv", "<chfv>k__BackingField", "chcp", "<chcp>k__BackingField", "chbu", "<chbu>k__BackingField", "_chjo_k__BackingField", "<chjo>k__BackingField", "chjo", "cggz" };

		internal static readonly string[] UnitConfigIdFields =
			{ "chgu", "bewi", "<chgu>k__BackingField", "_chgu_k__BackingField", "chgv", "bewk", "<chgv>k__BackingField", "_chgv_k__BackingField", "chgw", "bewm", "<chgw>k__BackingField", "_chgw_k__BackingField", "chgt", "bewg", "<chgt>k__BackingField", "_chgt_k__BackingField", "chfz", "bevj", "<chfz>k__BackingField", "_chfz_k__BackingField", "chga", "bevl", "<chga>k__BackingField", "_chga_k__BackingField", "chgb", "bevn", "<chgb>k__BackingField", "_chgb_k__BackingField", "<chjp>k__BackingField", "_chjp_k__BackingField", "<chjq>k__BackingField", "_chjq_k__BackingField", "<chjr>k__BackingField", "_chjr_k__BackingField", "chfw", "<chfw>k__BackingField", "chfx", "<chfx>k__BackingField", "chfy", "bevh", "<chfy>k__BackingField", "chbv", "<chbv>k__BackingField", "chbw", "<chbw>k__BackingField", "cgha" };

		internal static readonly string[] UnitShapeNestedFields =
			{ "chgt", "chgu", "chgv", "chgw", "<chgt>k__BackingField", "<chgu>k__BackingField", "<chgv>k__BackingField", "<chgw>k__BackingField", "_chgt_k__BackingField", "_chgu_k__BackingField", "_chgv_k__BackingField", "_chgw_k__BackingField", "chfy", "chfz", "chga", "chgb", "<chfy>k__BackingField", "<chfz>k__BackingField", "<chga>k__BackingField", "<chgb>k__BackingField", "_chfy_k__BackingField", "_chfz_k__BackingField", "_chga_k__BackingField", "_chgb_k__BackingField", "<chjp>k__BackingField", "<chjq>k__BackingField", "<chjr>k__BackingField", "_chjp_k__BackingField", "_chjq_k__BackingField", "_chjr_k__BackingField", "chfv", "chfw", "chfx", "chfy", "<chfv>k__BackingField", "<chfw>k__BackingField", "<chfx>k__BackingField", "<chfy>k__BackingField", "chcp", "chcq", "chcr", "_chcp_k__BackingField", "_chcq_k__BackingField", "_chcr_k__BackingField", "<chcp>k__BackingField", "<chcq>k__BackingField", "<chcr>k__BackingField", "chbu", "chbv", "chbw", "_chbu_k__BackingField", "_chbv_k__BackingField", "_chbw_k__BackingField", "<chbu>k__BackingField", "<chbv>k__BackingField", "<chbw>k__BackingField", "chey", "chez", "chfa", "chfb", "_chdi_k__BackingField", "_chdj_k__BackingField", "_chdk_k__BackingField", "_chdl_k__BackingField", "<chey>k__BackingField", "<chez>k__BackingField", "<chfa>k__BackingField", "<chfb>k__BackingField", "cggz", "cgha" };

		internal static readonly string[] HeroNestedFields =
			{ "cguy", "cgsm", "cgfa", "hero", "logicHero", "cbye", "<cbye>k__BackingField", "_cbye_k__BackingField", "cbzt", "<cbzt>k__BackingField", "chyt", "_chyt_k__BackingField", "<chyt>k__BackingField", "chys", "_chys_k__BackingField", "<chys>k__BackingField", "cbzu", "_cbyf_k__BackingField", "<cbzu>k__BackingField", "chpd", "cnva", "cmgf", "bqax", "ciaj", "<ciaj>k__BackingField", "cnxy", "heroConfig", "config" };

		internal static readonly MethodSymbol ResultHeroPortraitRefresh = new(
			"battle.ui.resultHeroPortrait.refresh",
			"vpm", "vnu", "von", "vom");
	}

	internal static partial class BattleUnitInit
	{
		internal const string UnitTypeId = "Hex.Session.Battle.Unit";
		internal const string HexTypeId = "Hex.Session.Battle.Hex";

		// Source-prepared/runtime-unproven June 19: generated interop metadata exposes
		// Hex.Session.Battle.Unit.Init(..., System.Boolean _isSummon,
		// System.Boolean _spawnedInBattle). These names are intentionally exact
		// summon-identity candidates for Inferno gated-entry laws. If the current
		// runtime does not retain them as readable members, gated-entry laws fail
		// closed rather than falling back to Inferno faction or unit SID.
		internal static readonly string[] BattleUnitIsSummonMembers =
			{ "isSummon", "get_isSummon", "<isSummon>k__BackingField", "_isSummon", "_isSummon_k__BackingField" };

		internal static readonly string[] BattleUnitSpawnedInBattleMembers =
			{ "spawnedInBattle", "get_spawnedInBattle", "<spawnedInBattle>k__BackingField", "_spawnedInBattle", "_spawnedInBattle_k__BackingField" };

		// Live Golden Era interop regenerated BattleLogic as
		// ObjectPublicPrcfInPrcfSiBoPrcfInUnique (legacy short names eep/eeh/eeo).
		internal static readonly string[] BattleLogicTypeHints =
			{ "ObjectPublicPrcfInPrcfSiBoPrcfInUnique", "eep", "eeh", "eeo" };

		// Live Unit.Init param[2] is ObjectPublicPrcgObPrcgInTrPrcgInUnique
		// (battle-side wrapper with field_Public_TransferSide_0). Legacy short
		// names ehh/eir/eii/eip are absent from current Hex.dll — keep them last
		// as historical aliases only. Pin via SideTypeHints gate in
		// Homm3BattleUnitInitSurface; do not treat TransferSide as the Init arg.
		internal static readonly string[] SideTypeHints =
			{
				"ObjectPublicPrcgObPrcgInTrPrcgInUnique",
				"ehh",
				"eir",
				"eii",
				"eip"
			};

		internal static readonly MethodSymbol Init = new(
			"battle.unit.init",
			"Init");
	}

	internal static partial class SkeletalNecromancy
	{
		internal static readonly string[] BattlesManagerTypeHints =
			{
				"ObjectPublicDi2InObcfLi1cnObcfUnique",
				"eff"
			};

		internal static readonly MethodSymbol ApplyBattleResult = new(
			"battle.skeletalNecromancy.applyBattleResult",
			"Method_Public_Void_ObjectPublicPrcfInPrcfSiBoPrcfInUnique_Boolean_0",
			"bdol",
			"ApplyResult");

		internal static readonly string[] BattleLogicTypeHints =
			{ "ObjectPublicPrcfInPrcfSiBoPrcfInUnique", "eep", "Hex.Session.Battle.Logic" };

		internal static readonly string[] BattleLogicAlreadyAppliedFields =
			{ "get__cfwf_k__BackingField", "cfwf", "<cfwf>k__BackingField", "_cfwf_k__BackingField", "appliedToWorld" };

		internal static readonly string[] BattleLogicIdFields =
			{ "get__cfuz_k__BackingField", "cfuz", "<cfuz>k__BackingField", "_cfuz_k__BackingField", "id" };

		internal static readonly string[] BattleLogicTransferBattleFields =
			{ "get__cfvh_k__BackingField", "Method_Public_get_TransferBattle_0", "cfvh", "<cfvh>k__BackingField", "_cfvh_k__BackingField", "transferBattle" };

		internal static readonly string[] BattleLogicStartedTransferBattleFields =
			{ "get__cfvi_k__BackingField", "Method_Public_get_TransferBattle_1", "cfvi", "<cfvi>k__BackingField", "_cfvi_k__BackingField", "startedTransferBattle" };

		internal static readonly string[] BattleLogicBattleResultInfoFields =
			{ "get_field_Public_BattleResultInfo_0", "cfvb", "field_Public_BattleResultInfo_0", "battleResultInfo" };

		internal static readonly string[] BattleResultLosersFields =
			{ "get_losers", "losers", "field_Public_List_1_BattleResultLoserInfo_0" };

		internal static readonly string[] BattleResultLoserIndexFields =
			{ "get_loserIndex", "loserIndex", "field_Public_Int32_0" };

		internal static readonly MethodSymbol TransferSideAddSpawnedUnit = new(
			"battle.skeletalNecromancy.transferSide.addSpawnedUnit",
			"Method_Public_Void_TransferUnit_Boolean_0",
			"bech",
			"AddUnitSpawnedInBattle");

		internal static readonly MethodSymbol TransferSideSortBySlot = new(
			"battle.skeletalNecromancy.transferSide.sortBySlot",
			"Method_Public_Void_0",
			"becl",
			"SortUnitsBySlotPos");

		internal static readonly string[] TransferSideHeroMembers =
			{ "get_hero", "hero" };

		internal static readonly string[] TransferSideLogicHeroMembers =
			{ "get_logicHero", "logicHero" };

		internal static readonly string[] TransferHeroStatMembers =
			{ "get_heroStat", "heroStat", "get_heroStatUnclamped", "heroStatUnclamped" };

		internal static readonly string[] LogicHeroDataHeroMembers =
			{ "get__cbfh_k__BackingField", "get_cbfh", "xal", "cbfh", "_cbfh_k__BackingField" };

		internal static readonly string[] LogicHeroStatMembers =
			{ "get_cbfz", "cbfz", "get_cbga", "cbga" };

		internal static readonly string[] DataHeroStatMembers =
			{ "get_statsByLevel", "statsByLevel", "get_additionalStats", "additionalStats" };

		internal static readonly string[] DataHeroSkillsMembers =
			{ "get_skills", "skills" };

		internal static readonly string[] HeroSkillsListMembers =
			{ "get_list", "list" };

		internal static readonly string[] HeroSkillSubSkillsMembers =
			{ "get_subSkills", "subSkills" };

		internal static readonly string[] HeroSubSkillSidMembers =
			{ "get_sid", "sid" };

		internal static readonly string[] HeroStatNecromancyPerBonusMembers =
			{ "get_necromancyPerBonus", "necromancyPerBonus" };

		internal static readonly MethodSymbol TransferUnitLogicConfigGetter = new(
			"battle.skeletalNecromancy.transferUnit.logicConfig.getter",
			"Method_Public_UnitLogicConfig_0",
			"becr",
			"get_cnzz",
			"cnzz");

		internal static readonly string[] TransferUnitLogicConfigFields =
			{ "cgtg", "field_Private_UnitLogicConfig_0" };
	}

	internal static partial class BattleResultLaws
	{
		internal static readonly string[] BattlesManagerTypeHints =
		{
			"ObjectPublicDi2InObcfLi1cnObcfUnique",
			"eff"
		};

		internal static readonly MethodSymbol ApplyBattleResult = new(
			"law.battleResult.applyBattleResult",
			"Method_Public_Void_ObjectPublicPrcfInPrcfSiBoPrcfInUnique_Boolean_0",
			"bdol",
			"ApplyResult");

		internal static readonly string[] BattleLogicTypeHints =
			{ "ObjectPublicPrcfInPrcfSiBoPrcfInUnique", "eep", "Hex.Session.Battle.Logic" };

		internal static readonly string[] BattleLogicAlreadyAppliedFields =
			{ "get__cfwf_k__BackingField", "cfwf", "<cfwf>k__BackingField", "_cfwf_k__BackingField", "appliedToWorld" };

		internal static readonly string[] BattleLogicIdFields =
			{ "get__cfuz_k__BackingField", "cfuz", "<cfuz>k__BackingField", "_cfuz_k__BackingField", "id" };

		internal static readonly string[] BattleLogicTransferBattleFields =
			{ "get__cfvh_k__BackingField", "Method_Public_get_TransferBattle_0", "cfvh", "<cfvh>k__BackingField", "_cfvh_k__BackingField", "transferBattle" };

		internal static readonly string[] BattleLogicStartedTransferBattleFields =
			{ "get__cfvi_k__BackingField", "Method_Public_get_TransferBattle_1", "cfvi", "<cfvi>k__BackingField", "_cfvi_k__BackingField", "startedTransferBattle" };

		internal static readonly string[] BattleLogicBattleResultInfoFields =
			{ "get_field_Public_BattleResultInfo_0", "cfvb", "field_Public_BattleResultInfo_0", "battleResultInfo" };

		internal static readonly string[] BattleResultLosersFields =
			{ "get_losers", "losers", "field_Public_List_1_BattleResultLoserInfo_0" };

		internal static readonly string[] BattleResultLoserIndexFields =
			{ "get_loserIndex", "loserIndex", "field_Public_Int32_0" };
	}

	internal static partial class SwashbucklerGold
	{
		internal const string SideLogicTypeId = "homm3.swashbuckler.gold.sideLogic";
		internal static readonly string SideLogicTypeHint = "dtj";
		internal const string SessionManagerTypeId = "homm3.swashbuckler.gold.sessionManager";
		internal static readonly string SessionManagerTypeHint = "dsu";
		internal const string ResourceWrapperTypeId = "homm3.swashbuckler.gold.resourceWrapper";
		internal static readonly string ResourceWrapperTypeHint = "dti";

		internal const string SideStartDayName = "OnStartDay";

		// Current Official dtj side logic: Side ccng, hero list ccns, session mgr field ccnw.
		internal static readonly string[] SideDataProperties = { "ccng", "_ccng_k__BackingField", "_ccjb_k__BackingField", "_ccku_k__BackingField" };
		internal static readonly string[] SideResourceMembers = { "field_Public_ResHeap_0", "res" };
		internal static readonly string[] SideHeroListProperties = { "ccns", "_ccns_k__BackingField", "_ccjn_k__BackingField", "_cclg_k__BackingField" };
		internal static readonly string[] SessionManagerMembers =
		{
			"ccnw",
			"field_Private_ObjectPublicObDaObSeEvccObccDaSeUnique_0",
			"cclk",
			"ccjr",
		};
		internal static readonly string[] SessionDataProperties = { "cclb", "prop_Data_0", "_cclb_k__BackingField", "Data", "_ccgw_k__BackingField", "_ccip_k__BackingField" };
		internal static readonly string[] SessionDayMembers = { "daysInGameCount", "day", "field_Public_Int32_0", "field_Public_Int32_1" };
		internal static readonly string[] LogicHeroDataProperties = { "ccez", "_ccez_k__BackingField", "prop_Hero_0", "_cccn_k__BackingField", "cbyf", "Hero", "Data" };
		// Audit B1 (2026-09-27), live Golden Era GameAssembly disasm via MethodAddressToToken.db:
		// dti (ObjectPublicReccDi2StReccUnique).Method_Public_Void_String_Int32_0 at rva 2dbc380 does
		// "if known(sid) resources[sid].Method_Public_Void_Int32_1(value)", and that Resource method
		// is "add dword [rcx+0x18], edx" (amount += value): an ADD. Method_Public_Void_String_Int32_1
		// at rva 2dbc300 does "mov [rax+0x18], esi" (amount = value): a SET. The PDM_0..3 copies also
		// add. Before this, the add was bound only by the lowest-ordinal signature fallback, because
		// none of the obfuscated hints exist on the live interop. It is now pinned by exact name, and
		// the hook resolves by name only (fail closed).
		internal static readonly MethodSymbol AddResource = new(
			"homm3.swashbuckler.gold.addResource",
			"Method_Public_Void_String_Int32_0",
			"ymj",
			"nbg",
			"cpw",
			"mjn",
			"exi");
	}

	internal static partial class EconomyLaws
	{
		internal const string SideLogicTypeId = "law.economy.sideLogic";
		internal static readonly string SideLogicTypeHint = "dtj";
		internal const string ResourceWrapperTypeId = "law.economy.resourceWrapper";
		internal static readonly string ResourceWrapperTypeHint = "dti";

		internal const string SideStartDayName = "OnStartDay";

		internal static readonly MethodSymbol AddResource = new(
			"law.economy.addResource",
			// June 18 refreshed law-surface dossier maps dti.ymj/nbg to this
			// generated method with type-callable ordinal + signature shape.
			// Registration only; reward/economy gameplay remains packet-gated.
			"Method_Public_Void_String_Int32_PDM_0",
			"ymj",
			"nbg",
			"cpw",
			"mjn",
			"exi");

		internal static readonly MethodSymbol SpendResourceIfAvailable = new(
			"law.economy.spendResourceIfAvailable",
			// June 20 construction-crash evidence: native city construction reaches
			// dti.ymk(string,int), which resolves a named Resource and jumps into
			// Resource.bggw(int). Diagnostic-only until a successful construction
			// runtime proves ordering and owner context.
			"ymk");

		internal const string ResourceDataTypeId = "law.economy.resourceData";
		internal static readonly string[] ResourceDataTypeHints =
			{ "Hex.Session.Data.Resource", "Resource" };

		internal static readonly MethodSymbol ResourceSetValue = new(
			"law.economy.resourceData.setValue",
			"bggu",
			"Method_Public_Void_Int32_0");

		internal static readonly MethodSymbol ResourceAddValue = new(
			"law.economy.resourceData.addValue",
			"bggv",
			"Method_Public_Void_Int32_1");

		internal static readonly MethodSymbol ResourceSubtractIfAvailable = new(
			"law.economy.resourceData.subtractIfAvailable",
			"bggw",
			"Method_Public_Boolean_Int32_0");

		internal static readonly MethodSymbol ResourceHasAtLeast = new(
			"law.economy.resourceData.hasAtLeast",
			"bggx",
			"Method_Public_Boolean_Int32_1");

		internal static readonly string[] ResourceNameMembers =
			{ "name" };

		internal static readonly string[] ResourceValueMembers =
			{ "value" };

		internal const string GoldResourceName = "gold";

		internal static readonly string[] SideResourceMembers =
			{ "field_Public_ResHeap_0", "res" };

		internal const string ResHeapDataTypeId = "law.economy.resHeapData";
		internal static readonly string[] ResHeapDataTypeHints =
			{ "Hex.Session.Data.ResHeap", "ResHeap" };

		internal static readonly string[] ResHeapGoldMembers =
			{ "gold" };
		internal static readonly string[] ResHeapWoodMembers =
			{ "wood" };
		internal static readonly string[] ResHeapOreMembers =
			{ "ore" };
		internal static readonly string[] ResHeapGemstonesMembers =
			{ "gemstones" };
		internal static readonly string[] ResHeapCrystalsMembers =
			{ "crystals" };
		internal static readonly string[] ResHeapMercuryMembers =
			{ "mercury" };
		internal static readonly string[] ResHeapDustMembers =
			{ "dust" };
		internal static readonly string[] ResHeapGraalMembers =
			{ "graal" };
		internal static readonly string[] ResHeapStarDustMembers =
			{ "starDust" };

		internal static readonly MethodSymbol ResHeapApply = new(
			"law.economy.resHeapData.apply",
			"bggt");
	}

	internal static partial class RewardCommitLaws
	{
		internal const string RewardApplierTypeId = "law.rewardCommit.rewardApplier";
		internal static readonly string[] RewardApplierTypeHints =
			{ "czy", "ObjectPrivateviVoaAc172b8058viUnique" };

		internal static readonly MethodSymbol RewardSetApply = new(
			"law.rewardCommit.rewardSetApply",
			// June 18 refreshed dossier still has no ordinal+signature runtime
			// candidate for czy.vji(Hero,DataRewardSet). Keep only the exact
			// decomp name; do not bind shape-only generated reward-applier
			// methods as diagnostics or gameplay.
			"vji");

		internal const string DataRewardSetsTypeId = "law.rewardCommit.dataRewardSets";
		internal static readonly string[] DataRewardSetsTypeHints =
			{ "Hex.Session.Data.DataRewardSets", "DataRewardSets" };

		internal static readonly MethodSymbol RewardSetQueued = new(
			"law.rewardCommit.rewardSetQueued",
			"bfus",
			"Method_Public_Void_DataRewardSet_0");

		internal static readonly MethodSymbol RewardSetRemoved = new(
			"law.rewardCommit.rewardSetRemoved",
			"bfut",
			"Method_Public_Void_DataRewardSet_1");

		internal static readonly string[] RewardSetIdMembers =
			{ "id" };

		internal static readonly string[] RewardSetHeroIdMembers =
			{ "heroId" };

		internal static readonly string[] RewardSetObjectIdMembers =
			{ "objectId" };

		internal static readonly string[] RewardSetLabelMembers =
			{ "label" };

		internal static readonly string[] RewardSetShowTypeMembers =
			{ "showType" };

		internal static readonly string[] RewardSetApplyTypeMembers =
			{ "applyType" };

		internal static readonly string[] RewardSetCancelTypeMembers =
			{ "cancelType" };

		internal static readonly string[] RewardSetRewardsMembers =
			{ "rewards" };

		internal static readonly string[] RewardItemStringTypeMembers =
			{ "stringRewardType" };

		internal static readonly string[] RewardItemTypeMembers =
			{ "rewardType" };

		internal static readonly string[] RewardItemNameMembers =
			{ "rewardName" };

		internal static readonly string[] RewardItemDescriptionMembers =
			{ "rewardDesc" };

		internal static readonly string[] RewardItemIconMembers =
			{ "rewardIcon" };

		internal static readonly string[] RewardItemParametersMembers =
			{ "parameters" };
	}

	internal static partial class ConstructionLaws
	{
		internal const string BuildingsManagerTypeId = "law.construction.buildingsManager";
		internal static readonly string[] BuildingsManagerTypeHints =
			{ "Hex.Session.City.BhBuildingsManager", "BhBuildingsManager" };

		internal static readonly MethodSymbol BuildingsManagerStateCandidate = new(
			"law.construction.buildingsManager.stateCandidate",
			"bajs",
			"Method_Private_Void_ObjectPublicBuObcdStObcdcnInBocnUnique_Boolean_PDM_0");

		internal static readonly MethodSymbol BuildingsManagerLookupCandidate = new(
			"law.construction.buildingsManager.lookupCandidate",
			"bajt",
			"Method_Private_MonoBehaviourPublicStBhbuceBhInceStBhceUnique_String_PDM_0");

		internal static readonly MethodSymbol BuildingsManagerRefreshCandidate = new(
			"law.construction.buildingsManager.refreshCandidate",
			"baju",
			"Method_Public_Void_0");

		internal const string BuildingSessionTypeId = "law.construction.buildingSession";
		internal static readonly string[] BuildingSessionTypeHints =
			{ "Hex.UI.City.BhUIBuildingSession", "BhUIBuildingSession" };

		internal static readonly MethodSymbol BuildingSessionCostCandidate = new(
			"law.construction.buildingSession.costCandidate",
			"tuc",
			"Method_Private_Int32_Int32_Int32_PDM_0");

		internal static readonly MethodSymbol BuildingSessionSelectCandidate = new(
			"law.construction.buildingSession.selectCandidate",
			"tud",
			"Method_Public_Void_ObjectPublicAbstractByInbsInbsByInbsbsUnique_PDM_0");

		internal const string BuildingViewTypeId = "law.construction.buildingView";
		internal static readonly string[] BuildingViewTypeHints =
			{ "Hex.UI.City.BhBuildingView", "BhBuildingView" };

		internal static readonly MethodSymbol BuildingViewBindCandidate = new(
			"law.construction.buildingView.bindCandidate",
			"trr",
			"Method_Public_Void_Object1PublicObInObcjcoObcjInObcjUnique_ObjectPublicBuObcdStObcdcnInBocnUnique_Int32_0");

		internal static readonly MethodSymbol BuildingViewUpdateCandidate = new(
			"law.construction.buildingView.updateCandidate",
			"UpdateView");

		internal static readonly MethodSymbol BuildingViewCostCheckCandidate = new(
			"law.construction.buildingView.costCheckCandidate",
			"tsi",
			"Method_Private_Boolean_Il2CppReferenceArray_1_ResNameAndCost_PDM_0");
	}

	internal static partial class SpellbookLaws
	{
		internal const string HeroMagicsTypeId = "law.spellbook.heroMagics";
		internal static readonly string[] HeroMagicsTypeHints =
			{ "Hex.Session.Data.HeroMagics", "HeroMagics" };

		internal static readonly MethodSymbol HeroMagicLookup = new(
			"law.spellbook.heroMagic.lookup",
			// June 18 refreshed law-surface dossier maps HeroMagics.bfxw to
			// this generated method with type-callable ordinal + signature
			// shape. Registration only; spellbook gameplay remains packet-gated.
			"Method_Public_MagicData_String_0",
			"bfxw");

		internal static readonly MethodSymbol HeroMagicCopy = new(
			"law.spellbook.heroMagic.copy",
			// June 18 refreshed law-surface dossier maps HeroMagics.bfxx to
			// this generated method with type-callable ordinal + signature
			// shape. Registration only; spellbook gameplay remains packet-gated.
			"Method_Public_Void_HeroMagics_0",
			"bfxx");

		internal static readonly MethodSymbol HeroMagicCount = new(
			"law.spellbook.heroMagic.count",
			// June 18 refreshed law-surface dossier maps HeroMagics.bfxy to
			// this generated method with type-callable ordinal + signature
			// shape. Registration only; spellbook gameplay remains packet-gated.
			"Method_Public_Int32_0",
			"bfxy");

		internal const string DataMagicsTypeId = "law.spellbook.dataMagics";
		internal static readonly string[] DataMagicsTypeHints =
			{ "Hex.Session.Data.DataMagics", "DataMagics" };

		internal static readonly MethodSymbol DataMagicLookup = new(
			"law.spellbook.dataMagic.lookup",
			// June 18 refreshed law-surface dossier maps DataMagics.bftu to
			// this generated method with type-callable ordinal + signature
			// shape. Registration only; spellbook gameplay remains packet-gated.
			"Method_Public_MagicData_String_PDM_0",
			"bftu");

		internal static readonly MethodSymbol DataMagicIndex = new(
			"law.spellbook.dataMagic.index",
			// June 18 refreshed law-surface dossier maps DataMagics.bftw to
			// this generated method with type-callable ordinal + signature
			// shape. Registration only; spellbook gameplay remains packet-gated.
			"Method_Public_Int32_String_PDM_0",
			"bftw");

		internal const string MagicDataTypeId = "law.spellbook.magicData";
		internal static readonly string[] MagicDataTypeHints =
			{ "Hex.Session.Data.MagicData", "MagicData" };

		internal static readonly string[] MagicDataSidConfigMembers =
			{ "sidConfig" };

		internal static readonly string[] MagicDataLevelMembers =
			{ "level" };

		internal static readonly string[] MagicDataIsLearnedMembers =
			{ "isLearned" };
		internal const string MagicRuntimeDataTypeId = "law.spellbook.magicRuntimeData";
		internal static readonly string[] MagicRuntimeDataTypeHints =
			{ "dro", "ObjectPublicMaHeccObInccStMacnBoUnique" };

		internal static readonly MethodSymbol MagicRuntimeDataInit = new(
			"law.spellbook.magicRuntimeData.init",
			"Init",
			"Method_Public_Void_MagicData_Hero_PDM_0",
			"Method_Public_Void_MagicData_Hero_PDM_1",
			"Method_Public_Void_MagicData_Hero_PDM_2");

		internal const string CastedMagicTypeId = "law.spellbook.castedMagic";
		internal static readonly string[] CastedMagicTypeHints =
			{ "eew", "ObjectPublicObcfInStcfInObcnMacfUnique" };
		internal const string MagicBookViewTypeId = "law.spellbook.magicBookView";
		internal static readonly string[] MagicBookViewTypeHints =
			{ "Hex.Session.UI.BhMagicBookView", "BhMagicBookView" };

		internal static readonly MethodSymbol MagicBookInit = new(
			"law.spellbook.magicBook.init",
			"Init");

		internal static readonly MethodSymbol MagicBookShow = new(
			"law.spellbook.magicBook.show",
			"Show");

		internal static readonly MethodSymbol MagicBookUpdateView = new(
			"law.spellbook.magicBook.updateView",
			"UpdateView");

		internal static readonly MethodSymbol MagicBookTypeFilter = new(
			"law.spellbook.magicBook.typeFilter",
			// June 18 refreshed law-surface dossier maps BhMagicBookView.zhq
			// to this generated method with type-callable ordinal + signature
			// shape. Registration only; UI/cast gating remains unproven.
			"Method_Public_Void_EMagicType_0",
			"zhq");

		internal static readonly MethodSymbol MagicBookSchoolFilters = new(
			"law.spellbook.magicBook.schoolFilters",
			// June 18 refreshed law-surface dossier maps BhMagicBookView.zhs
			// to this generated method with type-callable ordinal + signature
			// shape. Registration only; UI/cast gating remains unproven.
			"Method_Public_Void_ESchool_0",
			"zhs",
			"zht",
			"zhu");

		internal static readonly MethodSymbol MagicBookSelection = new(
			"law.spellbook.magicBook.selection",
			"zhy");

		internal const string CastMagicEventArgsTypeId = "law.spellbook.castMagicEventArgs";
		internal static readonly string[] CastMagicEventArgsTypeHints =
			{ "Hex.Session.Battle.CastMagicEventArgs", "CastMagicEventArgs" };

		internal static readonly MethodSymbol CastMagicFromArrayFactory = new(
			"law.spellbook.castMagic.arrayFactory",
			"bctq");

		internal static readonly MethodSymbol CastMagicFromListsFactory = new(
			"law.spellbook.castMagic.listsFactory",
			"Method_Public_Static_CastMagicEventArgs_ObjectPublicPrcgObPrcgInTrPrcgInUnique_ObjectPublicObcfInStcfInObcnMacfUnique_List_1_Hex_List_1_Hex_0");
	}

	internal static partial class AdventureVisionLaws
	{
		internal const string DataFogOfWarTypeId = "law.vision.dataFogOfWar";
		internal static readonly string[] DataFogOfWarTypeHints =
			{ "Hex.Session.Data.DataFogOfWar", "DataFogOfWar" };

		internal static readonly MethodSymbol FogInitialize = new(
			"law.vision.fog.initialize",
			"bfri",
			"Method_Public_Void_Int32_Int32_0");

		internal static readonly MethodSymbol FogVisibilityRead = new(
			"law.vision.fog.visibilityRead",
			"bfrj",
			"Method_Public_Boolean_Int32_0");

		internal static readonly MethodSymbol FogCountCandidate = new(
			"law.vision.fog.countCandidate",
			"bfrl",
			"Method_Public_Int32_PDM_0");

		// Side.fogData (dump). Live DataSides current side is Method_Public_get_Side_0 (not lookFor).
		internal static readonly string[] SideFogDataMembers =
			{ "fogData", "get_fogData", "field_Public_DataFogOfWar_0", "get_field_Public_DataFogOfWar_0", "<fogData>k__BackingField" };

		internal static readonly string[] DataFogVisibilityMapMembers =
			{ "visibilityMap", "get_visibilityMap", "field_Public_ArrayOf_Boolean_0", "field_Public_Il2CppStructArray_1_Boolean_0" };

		internal static readonly MethodSymbol DataSidesCurrentSide = new(
			"law.vision.dataSides.currentSide",
			"Method_Public_get_Side_0",
			"get_Side",
			"bezu",
			"get_cmyp",
			"cmyp",
			"lookFor",
			"get_lookFor",
			"field_Public_Side_0",
			"get_field_Public_Side_0");

		internal static readonly string[] DataSidesArrayMembers =
			{ "array", "get_array", "field_Public_ArrayOf_Side_0", "get_field_Public_ArrayOf_Side_0" };

		internal static readonly string[] DataSidesMyIndexMembers =
			{ "myIndex", "get_myIndex", "field_Public_Int32_0", "get_field_Public_Int32_0" };

		internal static readonly string[] SessionWorldMembers =
			{ "world", "get_world", "<world>k__BackingField", "field_Public_World_0", "get_field_Public_World_0" };

		internal static readonly string[] WorldSidesMembers =
			{ "sides", "get_sides", "<sides>k__BackingField", "Method_Public_get_DataSides_0", "get_field_Public_DataSides_0", "field_Public_DataSides_0" };

		internal static readonly string[] LookForDataMembers =
			{ "data", "get_data", "<data>k__BackingField", "field_Public_Data_0", "get_field_Public_Data_0" };

		// Esquire fog sync / SessionProbe: world is on static holders, not MonoBehaviours under WORLD.
		// Live Golden Era interop: ObjectPublicAbstractSealedSecaMaDacaStObHaca1Unique exposes
		// get_field_Private_Static_Data_0 (Hex.Session.Data.Data) and get_field_Private_Static_Map_0.
		internal static readonly string[] SessionHolderTypeHints =
		{
			"ObjectPublicAbstractSealedSecaMaDacaStObHaca1Unique",
			"Hex.Session.BhSession",
			"Hex.Session.Loader",
			"Hex.Session.Hud.BhHUDSession",
			"Hex.UI.City.BhCityUISession",
			"cta",
			"hl",
			"czr",
			"czk"
		};

		internal static readonly string[] SessionHolderStaticNames =
		{
			"me",
			"instance",
			"current",
			"field_Public_Static_BhHUDSession_0",
			"field_Public_Static_BhSession_0",
			"field_Public_Static_BhCityUISession_0",
			"field_Private_Static_Data_0",
			"get_field_Private_Static_Data_0",
			"field_Private_Static_Map_0",
			"get_field_Private_Static_Map_0"
		};

		internal static readonly string[] SessionDataMembers =
		{
			"field_Private_Static_Data_0",
			"get_field_Private_Static_Data_0",
			"data",
			"get_data",
			"field_Public_Data_0",
			"get_field_Public_Data_0"
		};

		internal const string MapMagicsTypeId = "law.vision.mapMagics";
		internal static readonly string[] MapMagicsTypeHints =
			{ "Hex.Session.Data.MapMagics", "MapMagics" };

		internal static readonly MethodSymbol MapMagicAdd = new(
			"law.vision.mapMagic.add",
			"bgca",
			"Method_Public_Void_String_0");

		internal static readonly MethodSymbol MapMagicLookup = new(
			"law.vision.mapMagic.lookup",
			"bgcb",
			"Method_Public_MapMagic_String_0");

		internal const string MapVisionObjectDescTypeId = "law.vision.mapVisionObjectDesc";
		internal static readonly string[] MapVisionObjectDescTypeHints =
			{ "Hex.Map.MapVisionObjectDesc", "MapVisionObjectDesc" };

		internal static readonly MethodSymbol MapVisionCity = new(
			"law.vision.mapVision.city",
			"City");

		internal static readonly MethodSymbol MapVisionHero = new(
			"law.vision.mapVision.hero",
			"Hero");

		internal static readonly MethodSymbol MapVisionItem = new(
			"law.vision.mapVision.item",
			"Item");

		internal static readonly MethodSymbol MapVisionSquadCandidate = new(
			"law.vision.mapVision.squadCandidate",
			"okz",
			"Method_Public_Static_MapVisionObjectDesc_Int32_PDM_0");

		internal static readonly MethodSymbol MapVisionBySid = new(
			"law.vision.mapVision.bySid",
			"ola",
			"Method_Public_Static_MapVisionObjectDesc_String_PDM_0");
	}

	internal static partial class BattleEventLaws
	{
		internal const string BattleEventDispatcherTypeId = "law.battleEvents.dispatcher";
		internal static readonly string[] BattleEventDispatcherTypeHints =
			{ "edb", "eda" };

		internal static readonly MethodSymbol BattleEventDispatch = new(
			"law.battleEvents.dispatch",
			// June 18 refreshed law-surface dossier maps edb.bcso to this
			// generated method with type-callable ordinal + signature shape.
			// Registration only; broad event dispatch patching remains unsafe
			// unless a narrow exact consumer proves runtime ordering first.
			"Method_Public_Void_Object_BattleEventArgs_PDM_128",
			"bcso",
			"bcjc");

		internal const string UnitPosChangedEventArgsTypeId = "law.battleEvents.unitPosChanged";
		internal static readonly string[] UnitPosChangedEventArgsTypeHints =
			{ "Hex.Session.Battle.UnitPosChangedEventArgs", "UnitPosChangedEventArgs" };

		internal const string UnitStartedMovementEventArgsTypeId = "law.battleEvents.unitStartedMovement";
		internal static readonly string[] UnitStartedMovementEventArgsTypeHints =
			{ "Hex.Session.Battle.UnitStartedMovementEventArgs", "UnitStartedMovementEventArgs" };

		internal const string ObjectTookDamageEventArgsTypeId = "law.battleEvents.objectTookDamage";
		internal static readonly string[] ObjectTookDamageEventArgsTypeHints =
			{ "Hex.Session.Battle.ObjectTookDamageEventArgs", "ObjectTookDamageEventArgs" };

		internal const string ObjectDestroyedEventArgsTypeId = "law.battleEvents.objectDestroyed";
		internal static readonly string[] ObjectDestroyedEventArgsTypeHints =
			{ "Hex.Session.Battle.ObjectDestroyedEventArgs", "ObjectDestroyedEventArgs" };

		internal const string ObjectSpawnedEventArgsTypeId = "law.battleEvents.objectSpawned";
		internal static readonly string[] ObjectSpawnedEventArgsTypeHints =
			{ "Hex.Session.Battle.ObjectSpawnedEventArgs", "ObjectSpawnedEventArgs" };

		// Round / action start-end have no typed BattleEventArgs subclass in the live interop.
		// 2026-09-26 Golden Era BepInEx/interop/Hex.dll: the 38 BattleEventArgs subclasses include no
		// Start/EndRound, RoundStarted/Ended, Start/EndUnitTurn or ActionStarted/Ended type (the only
		// "StartRound" name is a nested delegate OnStartRound). The retired hint sets missed every
		// session and each miss cost a full AccessTools.TypeByName scan during session load.
		// Round/action context comes from the *Dispatcher method symbols below instead.
		internal const string RoundActionEventArgsTypesAbsentLive =
			"no typed round/action BattleEventArgs subclass in live interop (2026-09-26); use dispatcher symbols";

		// Logic hub runtime type. Specialized event payloads (e.g.
		// ObjectTookDamageEventArgs) ride the shared BattleEventArgs parameter
		// slot; resolve dispatchers by producer RVA/token → interop Method_N,
		// never by mono ordinal Method_N guesses.
		internal static readonly string[] BattleLogicEventsTypeHints =
			{ "eda", "ObjectPublicEv1BacfEv1BacfBoEvUnique" };

		// eep action-start publishes eda.bciu (RVA 0x1EE4580, token 0x6009C42)
		// paired with edb.bcse (OnStartAction). Method_4/kwl is a different thin
		// raiser; Method_5/bcig is Crit — not ActionEnd.
		internal static readonly MethodSymbol ActionStartedDispatcher = new(
			"directState.battleEvents.actionStarted",
			"Method_Public_Void_Object_BattleEventArgs_45");

		// ekk action-end publishes eda.bciv (RVA 0x1EE4750, token 0x6009C3F)
		// paired with edb.bcsf (OnEndAction).
		internal static readonly MethodSymbol ActionEndedDispatcher = new(
			"directState.battleEvents.actionEnded",
			"Method_Public_Void_Object_BattleEventArgs_42");

		internal static readonly MethodSymbol RoundStartedDispatcher = new(
			"directState.battleEvents.roundStarted",
			"bcht",
			"Method_Public_Void_Object_BattleEventArgs_7");

		internal static readonly MethodSymbol RoundEndedDispatcher = new(
			"directState.battleEvents.roundEnded",
			"bchu",
			"Method_Public_Void_Object_BattleEventArgs_PDM_1");

		// dya.bmj constructs ObjectTookDamageEventArgs then calls eda.bcix
		// (RVA 0x1EE4A10, token 0x6009C41) → Method_44. Ordinal Method_9 was
		// bcjf/cfjd — wrong surface (ObjectTookDamage miss logs).
		internal static readonly MethodSymbol ObjectTookDamageDispatcher = new(
			"directState.battleEvents.objectTookDamage",
			"Method_Public_Void_Object_BattleEventArgs_44");

		internal static readonly MethodSymbol DamageFailedDispatcher = new(
			"directState.battleEvents.damageFailed",
			"Method_Public_Void_Object_BattleEventArgs_10");

		// LIVE-POSITIVE 2026-07-26 (player Wait vs Defend/Skip): Method_15 is Wait
		// (was wrongly awarded +3 when labeled Skip). Method_47 is Defend/Skip
		// (was wrongly a no-op when labeled Wait). Wait may raise Method_15 alone
		// or Method_15 then Method_47; arm Wait on Method_15 and award +3 only on
		// Method_47 when that arm is clear. Static eep.bdhp/bdho Method_N comments
		// that swapped these are contradicted.
		internal static readonly MethodSymbol SkipDispatcher = new(
			"directState.battleEvents.skip",
			"Method_Public_Void_Object_BattleEventArgs_47");

		internal static readonly MethodSymbol WaitDispatcher = new(
			"directState.battleEvents.wait",
			"Method_Public_Void_Object_BattleEventArgs_15");

		// LIVE-NEGATIVE 2026-07-26: Harmony postfix on Method_34
		// (CastAbility Method_N→field_(N+1) candidate) re-enters itself through
		// il2cpp_runtime_invoke during map/BattleLogic.Init and stack-overflows.
		// Do not Harmony-patch these Method_N rows for Runes until a volatile
		// probe proves a non-reentrant raiser. Short DiffableCs names retained
		// for static xref only.
		internal static readonly MethodSymbol ChangeAbilityDispatcher = new(
			"directState.battleEvents.changeAbility",
			"Method_Public_Void_Object_BattleEventArgs_23");

		internal static readonly MethodSymbol CastAbilityDispatcher = new(
			"directState.battleEvents.castAbility",
			"Method_Public_Void_Object_BattleEventArgs_34");

		internal const string EnergyUpdateEventArgsTypeId = "law.battleEvents.energyUpdate";
		internal static readonly string[] EnergyUpdateEventArgsTypeHints =
			{ "Hex.Session.Battle.EnergyUpdateEventArgs", "EnergyUpdateEventArgs" };

		internal const string EnergyUpdatedByMechEventArgsTypeId = "law.battleEvents.energyUpdatedByMech";
		internal static readonly string[] EnergyUpdatedByMechEventArgsTypeHints =
			{ "Hex.Session.Battle.EnergyUpdatedByMechEventArgs", "EnergyUpdatedByMechEventArgs" };

		internal const string SideUsedEnergyEventArgsTypeId = "law.battleEvents.sideUsedEnergy";
		internal static readonly string[] SideUsedEnergyEventArgsTypeHints =
			{ "Hex.Session.Battle.SideUsedEnergyEventArgs", "SideUsedEnergyEventArgs" };

		internal const string CastAbilityEventArgsTypeId = "law.battleEvents.castAbility";
		internal static readonly string[] CastAbilityEventArgsTypeHints =
			{ "Hex.Session.Battle.CastAbilityEventArgs", "CastAbilityEventArgs" };

		internal const string BattleUnitTypeId = "law.battleEvents.unit";
		internal static readonly string[] BattleUnitTypeHints =
			{ "Hex.Session.Battle.Unit", "Unit" };

		internal static readonly MethodSymbol BattleUnitApplyDamage = new(
			"law.battleEvents.unitApplyDamage",
			// June 19 live metadata on Hex.Session.Battle.Unit proved this exact
			// EMechType-shaped direct damage method at runtime callable ordinal 1.
			// Do not add stale bbgw as a fallback: current runtime does not expose
			// it, and failing closed is safer than silently binding an older alias.
			// Committed-damage ordering and safe mutation semantics remain unproven.
			"Method_Public_Virtual_Void_InterfacePublicAbstractbaObbbUnInbbUnObbbObUnique_InterfacePublicAbstractbaBoaObVobabaObInUnique_ObjectPublicCacodaCaObceObceUnique_Int32_EMechType_Boolean_Single_Boolean_0");

		internal static readonly string[] BattleEventTargetMembers =
			{ "target" };

		internal static readonly string[] BattleEventRoundMembers =
			{ "roundNumber" };

		internal static readonly string[] UnitPosChangedTargetHexMembers =
			{ "targetHex" };

		internal static readonly string[] UnitStartedMovementPathMembers =
			{ "path" };

		internal static readonly string[] ObjectTookDamageCasterMembers =
			{ "caster" };

		internal static readonly string[] ObjectTookDamageCastSourceMembers =
			{ "castSource" };

		internal static readonly string[] ObjectTookDamageReceiverMembers =
			{ "damageReceiver" };

		internal static readonly string[] ObjectTookDamageDealerMembers =
			{ "dealer" };

		internal static readonly string[] ObjectSpawnedObjectMembers =
			{ "spawnedObject", "target" };

		internal static readonly string[] ObjectSpawnedCasterMembers =
			{ "caster" };

		internal static readonly string[] ObjectSpawnedCastSourceMembers =
			{ "castSource" };

		internal static readonly string[] ObjectTookDamageValueMembers =
			{ "damage", "stacksDestroyed", "immuneToDamage", "cumulative", "fromMech" };

		internal static readonly string[] ObjectDestroyedMembers =
			{ "destroyedObject", "isTimeout", "caster", "castSource" };

		internal static readonly string[] CastAbilityAttackedObjectsMembers =
			{ "attackedObjects" };

		internal static readonly string[] CastAbilityAttackedHexesMembers =
			{ "attackedHexes" };

		internal static readonly string[] CastAbilityIdMembers =
			{
				// Live Golden Era interop AbilityLogicConfig surface (preferred).
				"prop_AbilityID_0",
				"_bxmh_k__BackingField",
				"Method_Public_get_AbilityID_0",
				// DiffableCs / DummyDll short names retained as secondary.
				"abilityID",
				"<bxmh>k__BackingField",
				"bxmh",
				"rnw",
			};

		internal static readonly string[] CastAbilityNameMembers =
			{ "abilityName" };

		internal static readonly string[] CastAbilityCasterMembers =
			{ "caster" };

		internal static readonly string[] CastAbilityImmuneObjectsMembers =
			{ "immuneObjectsOut" };

		internal static readonly string[] AbilityIdTypeMembers =
			{ "abilityType" };

		internal static readonly string[] AbilityIdIndexMembers =
			{ "indexInArray" };

		// Source-prepared from dxy/ekx ISIL plus generated interop metadata:
		// ChangeAbilityEventArgs ctor is (whoChangedAbility, abilityType, indexInArray),
		// ekx reads [event+0x28] as abilityType and [event+0x2C] as indexInArray.
		// Names are exact reflection reads only; if generated names drift or are absent
		// this must fail closed.
		internal static readonly string[] ChangeAbilityTargetMembers =
			{ "whoChangedAbility", "get_whoChangedAbility" };

		internal static readonly string[] ChangeAbilityTypeMembers =
			{ "abilityType", "get_abilityType" };

		internal static readonly string[] ChangeAbilityIndexMembers =
			{ "indexInArray", "get_indexInArray" };

		internal static readonly string[] AbilityLogicClassificationMembers =
			{ "rank", "cd", "charges", "energyLevel", "dontUseEnergy", "attackType_", "castType_", "moveType", "actionCost", "cndd", "rod" };

		internal static readonly string[] AbilityLogicDealerMembers =
			{ "damageDealer", "selfDealer", "allyDealer" };

		internal static readonly string[] CastDealerClassificationMembers =
			{ "attackPatternSid", "triggerCounter", "sideCastType", "minBaseDmg", "maxBaseDmg", "minStackDmg", "maxStackDmg", "shootRange", "shootThreshold", "shootDmgBuff", "runDmgBuff", "damageType_", "castTarget_", "damageTarget_", "targetCondition_", "selection", "buffTarget_", "multitargetType", "cndh", "cndi", "cndk", "cndl", "cndg" };

		internal static readonly string[] UnitLogicConfigMembers =
			{
				"Method_Public_get_UnitLogicConfig_0",
				"chgu", "bewi", "<chgu>k__BackingField", "_chgu_k__BackingField",
				"chfz", "bevj", "<chfz>k__BackingField", "_chfz_k__BackingField",
				"chjp", "<chjp>k__BackingField", "_chjp_k__BackingField",
				"chez", "chbv", "cgha", "beye"
			};

		internal static readonly string[] UnitViewConfigMembers =
			{
				"Method_Public_get_UnitViewConfig_0",
				"chgv", "bewk", "<chgv>k__BackingField", "_chgv_k__BackingField",
				"chga", "bevl", "<chga>k__BackingField", "_chga_k__BackingField",
				"chjq", "<chjq>k__BackingField", "_chjq_k__BackingField",
				"chfa", "chbw", "beyg"
			};

		internal static readonly string[] UnitDataMembers =
			{ "Method_Public_get_UnitData_0", "get__chjr_k__BackingField", "_chjr_k__BackingField", "<chjr>k__BackingField", "chjr", "beyi" };

		// Do not probe managed get_baseSid/get_upgradeSid here: those getters call
		// Il2CppStringToManaged and can AccessViolation on uninitialized UnitLogicConfig.
		// Prefer configSid / native field aliases; baseSid is read only via DeobfInteropCompat.
		internal static readonly string[] UnitConfigSidMembers =
			{ "configSid", "sid", "unitSid", "cngz", "scs", "cnhd", "sef" };

		internal static readonly string[] UnitConfigFactionMembers =
			{ "fraction" };

		internal static readonly string[] UnitConfigTierMembers =
			{ "tier" };

		/// <summary>
		/// Core unit-logic <c>stats.moveType</c> is the exact flyer surface
		/// (<c>"fly"</c>). Do not probe readable battle-Unit bool names.
		/// </summary>
		internal static readonly string[] UnitConfigStatsMembers =
			{ "stats", "get_stats", "field_Public_UnitStats_0", "get_field_Public_UnitStats_0" };

		internal static readonly string[] UnitConfigStatsMoveTypeMembers =
			{ "moveType", "get_moveType" };

		internal const string UnitConfigFlyMoveTypeValue = "fly";

		internal static readonly string[] BattleObjectSideMembers =
			{ "get_field_Public_TransferSide_0", "field_Public_TransferSide_0" };

		// Source-prepared 2026-06-20 from chained xrefs:
		// dxy.bast() populates ChangeAbilityEventArgs.whoChangedAbility from
		// dxy.ceis (ede). FieldObject/ede exposes the battle context eir via
		// basa()/bcuk()/cfnp, and eir owns the exact TransferSide at cgle.
		// Runtime proof is still pending for counterattack event timing.
		internal static readonly string[] BattleObjectBattleContextMembers =
			{ "Method_Public_get_ObjectPublicPrcgObPrcgInTrPrcgInUnique_0", "Method_Public_Virtual_Final_New_ObjectPublicPrcgObPrcgInTrPrcgInUnique_0", "get__cfnp_k__BackingField" };

		internal static readonly string[] BattleContextTransferSideMembers =
			{ "get_field_Public_TransferSide_0", "field_Public_TransferSide_0" };

		// June 20 staged battle-law owner proof: DiffableCs/ISIL show
		// Hex.Session.Battle.TransferSide.sideIdInWorld at field offset 0x20.
		// This is the battle-side-to-Data.Side bridge; keep semantic names first
		// and legacy generated aliases last so stale aliases cannot mask drift.
		internal static readonly string[] TransferSideSideIdMembers =
			{ "sideIdInWorld", "get_sideIdInWorld", "field_Public_Int32_1", "get_field_Public_Int32_1", "field_Public_Int32_0", "get_field_Public_Int32_0", "cglb" };

		// Runtime-proofed 2026-06-20: ObjectPublicPrcgObPrcgInTrPrcgInUnique battle-side wrappers expose
		// field_Public_Int32_0/get_field_Public_Int32_0 as the battle-local side index matching
		// Homm3BattleUnitLawOwnerRegistry SideIndexToDataSide keys. Do not apply this group to
		// native Hex.Session.Battle.TransferSide; garrison battles proved native sideIdInWorld can be 0 for both sides.
		internal static readonly string[] BattleSideWrapperLocalSideIndexMembers =
			{ "field_Public_Int32_0", "get_field_Public_Int32_0" };

		internal static readonly string[] BattleObjectBattleLogicMembers =
			{ "Method_Public_Virtual_Final_New_get_ObjectPublicPrcfInPrcfSiBoPrcfInUnique_0", "get__cfni_k__BackingField", "cfni", "bbdr" };

		internal static readonly string[] BattleObjectHexMembers =
			// Source-prepared 2026-06-20 from current readable decomp:
			// ede.bcuh/cnyr expose the owning Hex through FieldObject.cfnp.
			// Runtime proof is still pending for counterattack event timing.
			{ "Method_Public_Virtual_Final_New_get_Hex_0" };

		internal static readonly string[] BattleLogicTransferBattleMembers =
			{ "Method_Public_get_TransferBattle_0", "Method_Public_get_TransferBattle_1", "get__cfvh_k__BackingField", "get__cfvi_k__BackingField" };

		internal static readonly string[] TransferBattleSidesMembers =
			{ "get_sides", "sides" };

		internal static readonly string[] UnitTransferUnitMembers =
			{ "Method_Public_get_TransferUnit_0", "get__chjo_k__BackingField" };


		internal static readonly string[] CasterBattleSideMembers =
			{ "Method_Public_Abstract_Virtual_New_ObjectPublicPrcgObPrcgInTrPrcgInUnique_0" };

		internal static readonly string[] TransferUnitConfigSidMembers =
			{ "get_configSid", "configSid" };

		internal static readonly string[] TransferUnitSlotPosMembers =
			{ "get_slotPos", "slotPos" };

		internal static readonly string[] TransferSideUnitsMembers =
			{ "get_units", "units" };

		internal static readonly string[] HexIndexMembers =
			{ "index" };

		internal static readonly string[] HexXMembers =
			{ "x" };

		internal static readonly string[] HexZMembers =
			{ "z" };

		internal static readonly string[] HexOccupantMembers =
			// Source-prepared 2026-06-20; Direct State M1 erratum 2026-07-20:
			// Hex.cfqf/bcxn is mono lastCorpse (Unit-typed), NOT movement occupancy.
			// Push occupancy is Hex.fieldObjects via bcyl/bcyn. Do not use for ownership.
			{ "Method_Public_get_Unit_0", "get__cfqf_k__BackingField" };
	}

	internal static partial class DirectStateLaws
	{
		internal static readonly string[] BattleHexTypeHints =
			{ "Hex.Session.Battle.Hex", "Hex" };

		// ISIL-proven eew storage slot used by bdmg/bdmh/bdmi. The generated
		// backing-field names are retained as exact compatibility identifiers.
		internal static readonly string[] SpellStoredCooldownMembers =
			{ "cfxk", "_cfxk_k__BackingField", "field_Public_Int32_0", "field_Private_Int32_0" };

		internal const string UnitAbilityTypeId = "directState.unitAbility";
		internal static readonly string[] UnitAbilityTypeHints =
			{ "dxy", "ObjectPublicObceInBoInceAbObELInUnique" };

		internal static readonly string[] AbilityCooldownMembers =
			{ "ceit", "barp", "_ceit_k__BackingField", "cd", "get_cd", "_cd_k__BackingField", "armedCd" };

		internal static readonly string[] AbilityChargesMembers =
			{ "charges", "get_charges", "_charges_k__BackingField", "castsPerBattleLeft" };

		internal static readonly string[] AbilityCastCounterMembers =
			{ "castCounter", "castsUsed", "get_castCounter", "_castCounter_k__BackingField" };

		internal static readonly string[] UnitStackCountMembers =
			{ "stacks", "get_stacks", "_stacks_k__BackingField", "count", "get_count", "bbaz", "bbcg", "bajq", "bayd", "ish", "crf", "bbak" };

		internal static readonly string[] UnitAbilityManagerMembers =
			{ "cfng", "get__cfng_k__BackingField", "Method_Public_get_ObjectPublicObceDiObce2EAInBoInUnique_0" };

		internal static readonly MethodSymbol AbilityManagerResolve = new(
			"directState.unitAbilityManager.resolve",
			"Method_Public_Boolean_EAbilityType_Int32_byref_ObjectPublicObceInBoInceAbObELInUnique_0",
			"Method_Public_Boolean_EAbilityType_Int32_byref_ObjectPublicObceInBoInceAbObELInUnique_PDM_0",
			"barb",
			"bgl");

		internal static readonly string[] FocusValueMembers =
			{ "energy", "get_energy", "_energy_k__BackingField", "currentEnergy", "field_Private_Int32_0" };

		// Direct State M1: cfqf/bcxo is mono lastCorpse (Hex+0x30) — NOT movement occupancy.
		// Real push occupancy is Hex.fieldObjects (+0x28) via bcyn/bcyl inside edf.bcuo,
		// owned by journaled UnitData.bfdi. Do not teach HexOccupantWriteMembers as the
		// MovementPush commit store. movement.commit.bfdi_v1 is equivalence-proven
		// (2026-07-20; 5 bar-C proven + 4 blocked-with-reason). Helper+_cfqf dual-write
		// remains diagnostic-only. MovementPush ungated after M3 focused live-positive
		// (ds_m3_movement_push_live_positive). MovementTeleport / non-push relocate reuses
		// this same bfdi commit triad via movement.relocate.bfdi_v1 (M6); ungates only after
		// focused live-positive dual-readback on journaled TryCommitUnitHexMove.
		internal static readonly string[] HexOccupantWriteMembers =
			{ "_cfqf_k__BackingField", "cfqf", "Unit" };

		// Live Hex.dll: Unit/FieldObject hex lives on position helper
		// field_Public_ObjectPublicHecfFiVecfBocnBoHecfUnique_0.field_Private_Hex_0
		// (not a direct FieldObject._hex_ member; BattleLogic Method_Public_Void_Unit_Hex_0
		// does not publish get_Hex — proven live 2026-07-19).
		internal static readonly string[] FieldObjectPositionHelperMembers =
			{ "field_Public_ObjectPublicHecfFiVecfBocnBoHecfUnique_0" };

		internal static readonly string[] FieldObjectHexWriteMembers =
			{ "field_Private_Hex_0" };

		// movement.commit.bfdi_v1 proven surfaces only (bar-C field-delta). Obfuscated
		// live GE names — do not scatter; resolve through these registries.
		// Dump/DummyDll name is bfdi; Golden Era BepInEx interop renames the same Hex
		// setter to Method_Public_set_Void_Hex_0 (callable ordinal 11). Prefer both.
		// Blocked (not exported): UnitData.bfdh readback; eep.bdhv/bdhw empty-listener /
		// plant-incomplete notify; eda.bcim null-cfia publish plant.
		internal static readonly string[] MovementCommitOwnerMembers =
			{ "bfdi", "Method_Public_set_Void_Hex_0" };

		internal static readonly string[] FieldObjectDataHexMembers =
			{ "bcuo", "bcun", "Method_Public_set_Void_Hex_0", "Method_Public_get_Hex_0" };

		internal static readonly string[] HexFieldObjectsMutatorMembers =
			{ "bcyl", "bcyn", "Method_Public_Void_FieldObject_0", "Method_Public_Void_FieldObject_1" };

		internal const string MovementCommitCardId = "movement.commit.bfdi_v1";

		// M6 relocate/teleport binding — reuses MovementCommitCardId triad; no new write symbols.
		internal const string MovementRelocateCardId = "movement.relocate.bfdi_v1";

		// movement.dest.ehh_bdpe_v1 proven dest-recipe surfaces only (bar-C call-trace).
		// Role=dest_recipe INPUT — never commit ownership. Blocked (not exported):
		// ehh.bdpe ApplyForReceiver (plant-incomplete); een.bdep/bdeo neighbour helpers.
		// Production Shoulder Check interim policy: axial away via Hex neighbour fields +
		// Hex.bcyf / fieldObjects (interim_axial_away_bcyf_fieldobjects_v1).
		internal static readonly string[] MechPushUnitInitMembers =
			{ "Init", "Init_Private_Void_Il2CppStringArray_0", "izh" };

		internal static readonly string[] HexIsLockedForSideMembers =
			{ "bcyf", "IsLockedForSide", "Method_Public_Boolean_Int32_Boolean_ETargetAllegiance_0" };

		internal static readonly string[] HexDistanceMembers =
			{ "bdke", "gme", "HexDistance", "Method_Public_Static_Int32_Hex_Hex_0" };

		internal const string MovementDestRecipeCardId = "movement.dest.ehh_bdpe_v1";

		// damage.side_effect.bfde_v1 proven surfaces only (bar-C field-delta, 2026-07-20).
		// bfdd shares bfde VA — not exported as distinct. Hex.bcxo/bcxn are lastCorpse
		// corpse_store only — NEVER occupancy (M1 banned). DamageScalar remains gateway
		// TryCommitPreparedDamage (pre-commit ref-int); full ApplyDamage not recovered here.
		internal static readonly string[] UnitDataSumHpWriteMembers =
			{ "bfde", "Method_Public_Void_Int32_0" };

		internal static readonly string[] UnitDataAllStacksReadMembers =
			{ "bfda", "Method_Public_get_Int32_0", "Method_Public_Int32_0" };

		internal static readonly string[] UnitDataAliveReadMembers =
			{ "bfdf", "Method_Public_Boolean_0", "Method_Public_get_Boolean_0" };

		internal static readonly string[] HexLastCorpseWriteMembers =
			{ "bcxo", "Method_Private_set_Void_Unit_0", "Method_Public_set_Void_Unit_0" };

		internal static readonly string[] HexLastCorpseReadMembers =
			{ "bcxn", "Method_Public_get_Unit_0", "Method_Private_get_Unit_0" };

		internal const string DamageSideEffectCardId = "damage.side_effect.bfde_v1";

		internal static readonly string[] HexBlockedMembers =
			{ "blockedByMap", "get_blockedByMap", "blockedFromAll", "get_blockedFromAll", "tempBlocked", "get_tempBlocked" };

		// Do-not-invoke metadata only. Live Method.Invoke on these AccessViolation'd
		// through Harmony / Il2CppObjectPool. Movement adapters must never call them.
		internal static readonly string[] HexNeighbourMembers =
		{
			"Method_Public_get_Hex_0",
			"Method_Public_get_Hex_1",
			"Method_Public_get_Hex_2",
			"Method_Public_get_Hex_3",
			"Method_Public_get_Hex_4",
			"Method_Public_get_Hex_5",
		};

		// Live Golden Era Hex.dll (Cecil): Hex.Session.Battle.Hex neighbour slots in ring
		// order. Read via NativeFieldInfoPtr__cfqh…__cfqm + IL2CPP field offset only.
		internal static readonly string[] HexNeighbourFieldMembers =
		{
			"_cfqh_k__BackingField",
			"_cfqi_k__BackingField",
			"_cfqj_k__BackingField",
			"_cfqk_k__BackingField",
			"_cfql_k__BackingField",
			"_cfqm_k__BackingField",
		};

		internal static readonly string[] HexFieldObjectsMembers =
			{ "fieldObjects", "get_fieldObjects", "_fieldObjects_k__BackingField" };

		// Retired: Method_Public_Void_Unit_Hex_0 does not publish get_Hex (live Golden Era proof).
		// Movement writes go through Homm3DirectStateUnitHexNative / FieldObjectHexWriteMembers.

		// Live Golden Era (audit A3, 2026-09-27): native eix.bdwx is interop
		// ObjectPublicIncgInObcgObIncgIncgUnique.Method_Public_Void_Int32_1 (metadata token match).
		// GameAssembly disasm: it calls Method_Public_Void_Int32_0(delta) (energy += delta, clamped)
		// and raises SideUsedEnergyEventArgs(side, delta). Native callers pass -cost (neg before the
		// call), so a spend of N is invoked with -N. Exact names only; missing = fail closed.
		internal static readonly MethodSymbol FocusSpend = new(
			"directState.focus.spend",
			"bdwx",
			"Method_Public_Void_Int32_1");

		// STALE / CONTRADICTED for MovementPush commit publish (Direct State M1):
		// Live push/walk commit publish is eep.bdhw → eda.bcim → eda.cfia (+0xC0)
		// (Logic OnUnitEndedMovement, ordinal-inferred). Do not treat edb / Method_N
		// dump-era ChangedHex mappings as the commit publish hub (W11; pin table 5a′/5d).
		// These MethodSymbol rows remain registration-only metadata until a promoted
		// symbol card rewrites them; adapters must not invoke them as bfdi publish.
		// ISIL short names are absent from Golden Era interop hubs. Proven ActionStart
		// mapping is Method_Public_Void_Object_BattleEventArgs_4 → event field_5
		// (OnStartAction). Same Method_N → field_(N+1) correlation pins:
		// OnUnitChangedHex field_21 → Method_20; OnUnitEndTacticsMovement field_46
		// (ISIL bcqv / UnitPosChangedEventArgs) → Method_45.
		internal static readonly MethodSymbol MovementPositionChangedDispatch = new(
			"directState.movement.positionChanged",
			"Method_Public_Void_Object_BattleEventArgs_45",
			"bcqv");

		internal static readonly MethodSymbol MovementStartedDispatch = new(
			"directState.movement.started",
			"bcsh");

		internal static readonly MethodSymbol MovementChangedHexDispatch = new(
			"directState.movement.changedHex",
			"Method_Public_Void_Object_BattleEventArgs_20",
			"bcqt");

		internal static readonly MethodSymbol MovementEndedDispatch = new(
			"directState.movement.ended",
			"bcst");

		// Mono/demo ordinal table: OnUnitChangedHex = 21. Prefer this over
		// dispatcher short names when invoking subscribers directly.
		internal static readonly string[] MovementChangedHexEventHandlerMembers =
			{ "field_Private_EventHandler_1_BattleEventArgs_21", "get_field_Private_EventHandler_1_BattleEventArgs_21" };
		internal static readonly string[] ActionQueueEntryTypeHints =
			{ "elz", "elq", "ObjectPublicUnchInBhchTuTuchchUnique" };

		internal static readonly string[] ActionQueueEntryUnitMembers =
			{ "unit", "cgyk", "cgzy" };

		internal static readonly string[] ActionQueueEntryTurnStateMembers =
			{ "turnState", "cgyh", "cgzw" };

		internal static readonly string[] BattleLogicActionQueueMembers =
			{ "turnQueue", "actionQueue", "field_Private_List_1_ObjectPublicUnchInBhchTuTuchchUnique_0" };
	}

	internal static partial class MoraleTriggerLaws
	{
		internal const string BattleLogicTypeId = "law.morale.battleLogic";
		internal static readonly string[] BattleLogicTypeHints =
			{ "ObjectPublicPrcfInPrcfSiBoPrcfInUnique", "eep" };

		internal static readonly MethodSymbol PositiveMoraleRoll = new(
			"law.morale.positiveRoll",
			// June 18 refreshed law-surface dossier maps eep.bdhu to this
			// generated method with type-callable ordinal + signature shape.
			// Registration only; morale gameplay remains packet-gated.
			"Method_Public_Boolean_Unit_Random_0",
			"bdhu");

		internal static readonly MethodSymbol NegativeMoraleRoll = new(
			"law.morale.negativeRoll",
			// June 18 refreshed law-surface dossier maps eep.grw to this
			// generated method with type-callable ordinal + signature shape.
			// Registration only; morale gameplay remains packet-gated.
			"Method_Public_Boolean_Unit_Random_Boolean_PDM_0",
			"grw");

		internal static readonly string[] MoraleRollCandidateNames =
			{
				"bdht", "bdhu", "bxb", "bxf", "cam", "grw", "jmj",
				"Method_Public_Boolean_Unit_Random_PDM_1",
				"Method_Public_Boolean_Unit_Random_Boolean_PDM_1",
				"Method_Public_Boolean_Unit_Random_PDM_2",
				"Method_Public_Boolean_Unit_Random_PDM_0",
				"Method_Public_Boolean_Unit_Random_Boolean_PDM_0",
				"Method_Public_Boolean_Unit_Random_Boolean_0",
				"Method_Public_Boolean_Unit_Random_0"
			};

		internal static readonly string[] UnitStatMembers =
			{ "<stats>k__BackingField", "stats", "get_stats", "bbcl", "bbcm", "bcuj", "<chju>k__BackingField", "chju", "<chjv>k__BackingField", "chjv" };

		internal static readonly string[] UnitMoraleGateMembers =
			{ "chkd", "chke", "chop", "chka", "chkb", "chkc" };

		internal static readonly string[] UnitStatSnapshotMembers =
			{ "moral", "moralMin", "moralMax", "moralPerc", "luck", "luckMin", "luckMax", "luckPerc" };

		internal static readonly string[] UnitCurrentMoraleValueMembers =
			{ "moral" };
	}

	/// <summary>
	/// Marshal Suppressing Fire trap. Live Golden Era type is
	/// FieldObjectPublicObBoTrAcTrcg1AcHeUnUnique; keep ekh only as a legacy alias.
	/// Init allocates empty UnitStat at cgtp; Magog statDmgMult therefore cannot scale
	/// from the placer. Wall-of-Flame CastDealerConfig on the instance TrapConfig clone
	/// (_cgtl / cgtl) is the stamped-damage owner.
	/// </summary>
	internal static partial class MarshalSuppressingFireTrap
	{
		internal const string TrapSid = "homm3_factory_suppressing_fire_trap";

		internal static readonly string[] TrapRuntimeTypeHints =
			{ "FieldObjectPublicObBoTrAcTrcg1AcHeUnUnique", "ekh" };

		internal static readonly string[] TrapInitMembers =
			{ "Init", "Method_Public_Boolean_String_Int32_eep_eir_Hex_eac_0" };

		internal static readonly string[] InstanceTrapConfigMembers =
			{ "_cgtl_k__BackingField", "<cgtl>k__BackingField", "cgtl", "becz" };
	}

	internal static partial class FocusLaws
	{
		internal const string EnergyUpdateEventArgsTypeId = "law.focus.energyUpdate";
		internal static readonly string[] EnergyUpdateEventArgsTypeHints =
			{ "Hex.Session.Battle.EnergyUpdateEventArgs", "EnergyUpdateEventArgs" };

		internal const string EnergyUpdatedByMechEventArgsTypeId = "law.focus.energyUpdatedByMech";
		internal static readonly string[] EnergyUpdatedByMechEventArgsTypeHints =
			{ "Hex.Session.Battle.EnergyUpdatedByMechEventArgs", "EnergyUpdatedByMechEventArgs" };

		internal const string SideUsedEnergyEventArgsTypeId = "law.focus.sideUsedEnergy";
		internal static readonly string[] SideUsedEnergyEventArgsTypeHints =
			{ "Hex.Session.Battle.SideUsedEnergyEventArgs", "SideUsedEnergyEventArgs" };

		internal const string HeroAbilityButtonViewTypeId = "law.focus.heroAbility.buttonView";
		internal static readonly string[] HeroAbilityButtonViewTypeHints =
			{ "Hex.UI.BhHeroAbilitiyView", "BhHeroAbilitiyView" };

		internal const string HeroAbilityContainerViewTypeId = "law.focus.heroAbility.containerView";
		internal static readonly string[] HeroAbilityContainerViewTypeHints =
			{ "Hex.UI.BhHeroAbilitiesView", "BhHeroAbilitiesView" };

		internal static readonly string[] EnergyUpdateSideMembers =
			{ "side" };

		internal static readonly string[] EnergyUpdateDeltaMembers =
			{ "energyDelta" };

		internal static readonly string[] EnergyUpdateEnergyMembers =
			{ "energy" };

		internal static readonly string[] EnergyUpdateDistributionMembers =
			{ "energyDistribution" };

		internal static readonly string[] EnergyUpdatedByMechSideMembers =
			{ "side" };

		internal static readonly string[] EnergyUpdatedByMechTypeMembers =
			{ "type" };

		internal static readonly string[] EnergyUpdatedByMechDeltaMembers =
			{ "delta" };

		internal static readonly string[] SideUsedEnergyDeltaMembers =
			{ "delta" };

		internal static readonly string[] SideUsedEnergySideMembers =
			{ "whoChangedEnergy" };

		internal static readonly string[] AbilityEnergyMembers =
			{ "configEnergyLevel", "energyLevel", "cd", "castsPerBattleLeft", "charges", "sid", "id", "level" };

		internal static readonly string[] AbilityConfigMembers =
			{ "config", "logic", "viewConfig" };

		internal static readonly string[] AbilityConfigEnergyMembers =
			{ "energyLevel", "dontUseEnergy", "cd", "sid", "id" };

		internal const string EnergyManagerTypeId = "law.focus.energyManager";
		internal static readonly string[] EnergyManagerTypeHints =
			{ "eix", "ObjectPublicIncgInObcgObIncgIncgUnique" };

		// Live Golden Era (audit A3): side eir.cglw is interop
		// ObjectPublicPrcgObPrcgInTrPrcgInUnique.field_Public_ObjectPublicIncgInObcgObIncgIncgUnique_0.
		internal static readonly string[] SideEnergyManagerMembers =
			{ "cglw", "field_Public_ObjectPublicIncgInObcgObIncgIncgUnique_0" };

		// Live Golden Era (audit A3): native eix.bdwy is interop Method_Public_Void_Int32_0
		// (metadata token match). GameAssembly disasm: energy += delta, clamped to [0, max level],
		// then raises EnergyUpdateEventArgs(side, delta). Exact names only; missing = fail closed.
		internal static readonly MethodSymbol GrantEnergy = new(
			"law.focus.energyManager.grantEnergy",
			"bdwy",
			"Method_Public_Void_Int32_0");
	}

	internal static partial class SpellCooldownLaws
	{
		internal const string BattleSpellLogicTypeId = "law.spellCooldown.battleSpellLogic";
		internal static readonly string[] BattleSpellLogicTypeHints =
			{ "eew", "ObjectPublicObcfInStcfInObcnMacfUnique" };

		internal static readonly MethodSymbol EffectiveCooldown = new(
			"law.spellCooldown.effectiveCooldown",
			"bdmd",
			"Method_Public_get_Int32_0");

		internal static readonly MethodSymbol DecrementCooldown = new(
			"law.spellCooldown.decrementCooldown",
			"bdmg",
			"Method_Public_Void_PDM_1");

		internal static readonly MethodSymbol SetCooldown = new(
			"law.spellCooldown.setCooldown",
			// June 20 static ISIL proof identifies eew.bdmh(Int32) as the single-spell
			// absolute cooldown setter: it writes max(0, value) to eew.cfxk/[this+0x18].
			// June 18 live bridge resolve_decomp_method still rejected shape-only generated
			// Void(Int32) candidates because generated ordinals drifted, so keep only the
			// decomp name here and fail closed if runtime exact-name resolution ever breaks.
			"bdmh");

		internal static readonly MethodSymbol AddCooldownIfReady = new(
			"law.spellCooldown.addCooldownIfReady",
			"bdmi",
			"Method_Public_Void_Int32_PDM_1");

		internal const string BattleSpellPoolTypeId = "law.spellCooldown.battleSpellPool";
		internal static readonly string[] BattleSpellPoolTypeHints =
			{ "eex" };

		internal static readonly MethodSymbol SpellPoolInit = new(
			"law.spellCooldown.poolInit",
			"Init");

		internal static readonly MethodSymbol SpellPoolCooldownShift = new(
			"law.spellCooldown.poolCooldownShift",
			"bdnj",
			"Method_Public_Void_Int32_Boolean_0");

		internal static readonly string[] BattleSpellPoolSpellArrayMembers =
			{ "cfxr", "<cfxr>k__BackingField" };

		internal static readonly string[] BattleSpellPoolSpellArrayAccessorMethods =
			{ "bdmq" };

		internal static readonly string[] BattleSpellPoolCurrentSpellMembers =
			{ "cfxv" };

		internal static readonly string[] BattleSpellPoolCasterMembers =
			{ "cfyd" };

		// DiffableCs: eir.cglf is the side-owned BattleMagicSet (eex) spell pool.
		internal static readonly string[] BattleSideSpellPoolMembers =
			{ "cglf" };

		// June 18 source-prepared/static-only owner chain:
		// eex.cfyd -> eir.cgle -> TransferSide.logicHero. Homm3CustomFactionLawRuntime
		// resolves that logic hero to Data.Side through exact logic/data members before
		// any future spell-cooldown handler may enter gameplay.
		internal static readonly string[] BattleSpellCasterTransferSideMembers =
			{ "cgle" };

		internal static readonly string[] BattleSpellTransferSideLogicHeroMembers =
			{ "logicHero" };

		internal static readonly string[] BattleSpellSidMembers =
			{ "cnyy", "bdma" };

		internal static readonly string[] BattleSpellMagicConfigMembers =
			{ "cnyz", "bdmb" };

		internal static readonly string[] MagicConfigSchoolMembers =
			{ "bxti", "get_bxti", "<bxti>k__BackingField", "school_" };

		internal static readonly string[] MagicConfigSidMembers =
			{ "normalMagicSid" };

		internal static readonly string[] MagicConfigRankMembers =
			{ "rank" };
	}

	internal static partial class SpellCastGateLaws
	{
		internal const string BattleSpellLogicTypeId = "law.spellCastGate.battleSpellLogic";
		internal static readonly string[] BattleSpellLogicTypeHints =
			{ "eew" };

		internal static readonly MethodSymbol CooldownReadinessGate = new(
			"law.spellCastGate.cooldownReadiness",
			"Method_Public_Virtual_Final_New_Boolean_0",
			"basy");

		internal static readonly MethodSymbol FullCastGate = new(
			"law.spellCastGate.fullCastGate",
			"Method_Public_Virtual_Final_New_Boolean_ObjectPublicPrcgObPrcgInTrPrcgInUnique_0",
			"base");

		internal const string BattleSpellPoolTypeId = "law.spellCastGate.battleSpellPool";
		internal static readonly string[] BattleSpellPoolTypeHints =
			{ "eex" };

		internal static readonly MethodSymbol SpellCounterGate = new(
			"law.spellCastGate.spellCounterGate",
			"Method_Public_Boolean_String_ESchool_0",
			"bdnm");

		internal static readonly MethodSymbol SpellIndexSelectionGate = new(
			"law.spellCastGate.indexSelectionGate",
			"Method_Public_Boolean_Int32_0",
			"bdnn");
	}

	internal static partial class TowerArcaneBattery
	{
		internal const string AbilitySid = "skill_faction_homm3_tower_ability_arcane_battery";
		internal const string ManaWellAegisSubSkillSid = "sub_skill_faction_homm3_tower_arcane_battery_mana_well_aegis";
	}

	internal static partial class TowerBottomlessKnowledge
	{
		internal const string RewardApplierTypeId = "homm3.tower.bottomlessKnowledge.rewardApplier";
		internal static readonly string RewardApplierTypeHint = "czy";

		internal static readonly MethodSymbol ManaRewardSetAppliers = new(
			"homm3.tower.bottomlessKnowledge.manaRewardSetAppliers",
			"Method_Public_Void_Hero_DataRewardSet_PDM_0");

		internal static readonly string[] LogicHeroDataHeroMembers =
			{ "get__cbfh_k__BackingField", "get_cbfh", "xal", "cbfh", "_cbfh_k__BackingField", "ccez", "_ccez_k__BackingField" };

		internal static readonly string[] DataHeroSkillsMembers =
			{ "get_skills", "skills" };

		internal static readonly string[] HeroSkillsListMembers =
			{ "get_list", "list" };

		internal static readonly string[] HeroSkillSubSkillsMembers =
			{ "get_subSkills", "subSkills" };

		internal static readonly string[] HeroSubSkillSidMembers =
			{ "get_sid", "sid" };
	}

	/// <summary>
	/// Cove Treasure Hunting Plunder. Chests pay out from the current-build chest map-object logic (fmo) open
	/// virtual; mines from the mine map-object logic (fno) visit virtuals and its owner-change override.
	/// <see cref="TowerBottomlessKnowledge.ManaRewardSetAppliers"/> is bound only as a diagnostic (it is a UI
	/// event subscriber, not the reward applier). Current build 25672315 only; static evidence in
	/// tools/port_current/remap/current_scope_overrides_25672315.json. Runtime unproven.
	/// </summary>
	internal static partial class CovePlunder
	{
		/// <summary>Chest map-object logic (native fmo): ctor(Hex.Session.Data.ObjChest), base fnt.</summary>
		internal const string ChestLogicTypeId = "homm3.cove.plunder.chestLogic";
		internal static readonly string ChestLogicTypeHint = "Object1PublicStcoObcucoObcoObcoObUnique";

		internal static readonly string[] ChestLogicChestMembers =
			{ "field_Private_ObjChest_0" };

		/// <summary>Chest open virtual taking the world hero (native fmo.bmbi): clones the chest reward set and starts the reward choice.</summary>
		internal static readonly MethodSymbol ChestHeroOpen = new(
			"homm3.cove.plunder.chestOpen",
			"Method_Protected_Virtual_Void_ObjectPublicHeObInObcnSiObVeBoObUnique_0");

		internal const string MineLogicTypeId = "homm3.cove.plunder.mineLogic";
		internal static readonly string MineLogicTypeHint = "Object1PublicObcoInObcocoUnique";

		/// <summary>Core resource sid of ore (a data id, not a build symbol); the ResHeap member is generated on current.</summary>
		internal const string OreResourceName = "ore";

		internal static readonly string[] MineLogicResMineMembers =
			{ "field_Private_ObjResMine_0" };

		internal static readonly string[] MineLogicConfigMembers =
			{ "field_Private_ObjResMineConfig_0" };

		/// <summary>Mine logic virtuals taking the visiting world hero (fdq); prefixes only record the visitor.</summary>
		internal static readonly MethodSymbol MineHeroVisitMethods = new(
			"homm3.cove.plunder.mineHeroVisit",
			"Method_Public_Virtual_Void_ObjectPublicHeObInObcnSiObVeBoObUnique_0",
			"Method_Protected_Virtual_Void_ObjectPublicHeObInObcnSiObVeBoObUnique_0",
			"Method_Protected_Virtual_Void_ObjectPublicHeObInObcnSiObVeBoObUnique_1");

		/// <summary>Mine override of the map-object owner-change virtual (old side logic, new side logic).</summary>
		internal static readonly MethodSymbol MineOwnerChanged = new(
			"homm3.cove.plunder.mineOwnerChanged",
			"Method_Protected_Virtual_Void_ObjectPublicObBhcpObIncpSiObIncuUnique_ObjectPublicObBhcpObIncpSiObIncuUnique_0");
	}
	/// <summary>
	/// Fortress Hunting Grounds (skill_faction_homm3_fortress). Current build 25672315 only; static evidence in
	/// tools/port_current/remap/current_scope_overrides_25672315.json. Runtime unproven.
	/// </summary>
	internal static partial class FortressHuntingGrounds
	{
		/// <summary>Event-bank map-object logic (native fmt): ctor(Hex.Session.Data.ObjEventBank), base fnt.</summary>
		internal const string EventBankLogicTypeId = "homm3.fortress.huntingGrounds.eventBankLogic";
		internal static readonly string EventBankLogicTypeHint = "Object1PublicObco52Obco35cu35VocoUnique";

		internal static readonly string[] EventBankLogicBankMembers =
			{ "field_Private_ObjEventBank_0" };

		internal static readonly string[] EventBankLogicConfigMembers =
			{ "field_Private_ObjEventBankConfig_0" };

		/// <summary>Event-bank interact virtual taking the world hero (native bmbi: can-visit check, then visit or the before-interact window).</summary>
		internal static readonly MethodSymbol EventBankHeroInteract = new(
			"homm3.fortress.huntingGrounds.eventBankInteract",
			"Method_Protected_Virtual_Void_ObjectPublicHeObInObcnSiObVeBoObUnique_0");

		/// <summary>Event-bank week turn (real name): rerolls variants / clears visitors per the bank config, fires one change event.</summary>
		internal static readonly MethodSymbol EventBankOnStartWeek = new(
			"homm3.fortress.huntingGrounds.eventBankOnStartWeek",
			"OnStartWeek");

		/// <summary>Hex.Session.Logic.Hero → hero map-buff manager (same member as the Captives lane; kept here so this slice owns its pins).</summary>
		internal static readonly string[] LogicHeroBuffManagerMembers =
			{ "prop_Object1PublicHechInVo_hbaHeBuaLoUnique_0", "_chno_k__BackingField" };

		/// <summary>Buff manager Add(string sid, BuffDuration[] durations).</summary>
		internal static readonly MethodSymbol BuffManagerAdd = new(
			"homm3.fortress.huntingGrounds.buffManager.add",
			"Method_Public_Void_String_Il2CppReferenceArray_1_BuffDuration_0");

		/// <summary>Buff manager Remove(string sid); only removes isDispellable configs.</summary>
		internal static readonly MethodSymbol BuffManagerRemove = new(
			"homm3.fortress.huntingGrounds.buffManager.remove",
			"Method_Public_Void_String_0");

		/// <summary>Buff manager Get(string sid) → Hex.Session.Logic.Buff or null.</summary>
		internal static readonly MethodSymbol BuffManagerGet = new(
			"homm3.fortress.huntingGrounds.buffManager.get",
			"Method_Public_Buff_String_0");
	}

	internal static partial class CastleEliteStrategem
	{
		internal static readonly string[] NecromancyWorldMagicHandlerTypeHints =
			{ "Object1PublicbhBoECbhVoaVoMabbhUnique", "eug" };
		internal const string LogicHeroTypeName = "Hex.Session.Logic.Hero";

		internal static readonly MethodSymbol NecromancyWorldMagicCast = new(
			"homm3.castle.eliteStrategem.necromancyWorldMagic.cast",
			"Method_Public_Virtual_Boolean_0",
			"bhkt");

		internal static readonly MethodSymbol LogicHeroDataHeroGetter = new(
			"homm3.castle.eliteStrategem.logicHero.dataHeroGetter",
			"Method_Public_get_Hero_0",
			"xpv",
			"get__ccez_k__BackingField");

		internal static readonly string[] NecromancyWorldMagicSettingMembers =
			{ "get_field_Protected_MagicSetting_0", "field_Protected_MagicSetting_0", "ciim" };

		/// <summary>
		/// World-magic handler base (live <c>eue</c>, native field <c>ciio</c>) → casting WorldHero
		/// (live <c>etc</c> = <see cref="HomecomingBoatTravel.WorldHeroTypeHints"/>). Pinned against live
		/// Golden Era interop 2026-09-27; resolved once at registration with an exact property-type
		/// check. The previous hint named a non-existent type and every cast failed closed with
		/// "world-magic WorldHero member missing".
		/// </summary>
		internal static readonly string NecromancyWorldMagicWorldHeroProperty =
			"field_Protected_ObjectPublicHeObInObciSiObVeSeObUnique_0";

		/// <summary>WorldHero (live <c>etc</c>) → Hex.Session.Logic.Hero auto-property backing field <c>&lt;ciez&gt;k__BackingField</c>.</summary>
		internal static readonly string WorldHeroLogicHeroProperty = "_ciez_k__BackingField";

		/// <summary>DataHero numeric id members for elite-strategem identity.</summary>
		internal static readonly string[] DataHeroIdMembers =
			{ "id", "get_id", "Id", "field_Public_Int32_0" };
	}
	internal static partial class DraconicDominion
	{
		internal const string DiplomacyHelperTypeId = "homm3.dungeon.draconicDominion.diplomacyHelper";
		internal static readonly string DiplomacyHelperTypeHint = "ObjectPublicAbstractSealedHa1StciUnique";
		internal const string SquadEscapeUiTypeId = "homm3.dungeon.draconicDominion.squadEscapeUi";
		internal const string SquadEscapeUiTypeName = "Hex.Session.UI.BhSquadEscapeUISession";
		internal const string NativeNavigatorTypeId = "homm3.dungeon.draconicDominion.nativeNavigator";
		internal static readonly string NativeNavigatorTypeHint = "ObjectPublicAbstractObcccnObcccnObObUnique";
		internal const string BattleLogicTypeId = "homm3.dungeon.draconicDominion.battleLogic";
		internal static readonly string BattleLogicTypeHint = "eep";
		internal const string TransferBattleTypeId = "homm3.dungeon.draconicDominion.transferBattle";
		internal const string TransferBattleTypeName = "Hex.Session.Battle.TransferBattle";
		internal static readonly string[] NativeNavigatorTypeHints =
			{ "ObjectPublicAbstractObcccnObcccnObObUnique", "dum" };
		internal static readonly string[] BattleLogicTypeHints =
			{ "ObjectPublicPrcfInPrcfSiBoPrcfInUnique", "eep" };

		internal static readonly MethodSymbol CanDiplomacy = new(
			"homm3.dungeon.draconicDominion.canDiplomacy",
			"bgvq",
			"Method_Public_Static_Boolean_ObjectPublicHeObInObciSiObVeSeObUnique_ObjectPublicDaInVeInBoObcjObBocoUnique_0");

		internal static readonly MethodSymbol OfferPercent = new(
			"homm3.dungeon.draconicDominion.offerPercent",
			"bgvr",
			"Method_Public_Static_Single_ObjectPublicDaInVeInBoObcjObBocoUnique_ObjectPublicHeObInObciSiObVeSeObUnique_0");

		internal static readonly MethodSymbol ValidateTransfer = new(
			"homm3.dungeon.draconicDominion.validateTransfer",
			"bgvt",
			"Method_Public_Static_Boolean_ObjectPublicDaInVeInBoObcjObBocoUnique_DataParty_ObjectPublicHeObInObciSiObVeSeObUnique_0");

		internal static readonly MethodSymbol UnitCost = new(
			"homm3.dungeon.draconicDominion.unitCost",
			"bgvs",
			"Method_Public_Static_UnitCost_Boolean_ObjectPublicHeObInObciSiObVeSeObUnique_String_0");

		internal static readonly MethodSymbol DiplomacyUnitsPanelCommandCallback = new(
			"homm3.dungeon.draconicDominion.unitsPanel.commandCallback",
			"yuo",
			"Method_Public_Void_ObjectPublicAbstractByInbsInbsByInbsbsUnique_PDM_0");

		internal static readonly MethodSymbol DiplomacyUnitsPanelHide = new(
			"homm3.dungeon.draconicDominion.unitsPanel.hide",
			"OnHide");

		internal static readonly MethodSymbol SquadEscapeOnEscapeClick = new(
			"homm3.dungeon.draconicDominion.squadEscape.onEscapeClick",
			"OnEscapeClick");

		internal static readonly MethodSymbol SquadEscapeHide = new(
			"homm3.dungeon.draconicDominion.squadEscape.hide",
			"OnHide");

		internal static readonly MethodSymbol NativeNavigatorGetter = new(
			"homm3.dungeon.draconicDominion.nativeNavigator.getter",
			"yva",
			"Method_Public_Static_get_ObjectPublicAbstractObcccnObcccnObObUnique_0");

		internal static readonly MethodSymbol NativeOpenDiplomacy = new(
			"homm3.dungeon.draconicDominion.nativeNavigator.openDiplomacy",
			"yws",
			"Method_Public_Void_ObjectPublicDaInVeInBoObcjObBocoUnique_ObjectPublicHeObInObciSiObVeSeObUnique_PDM_0");

		internal static readonly MethodSymbol BattleLogicInit = new(
			"homm3.dungeon.draconicDominion.battleLogic.init",
			"Init");

		internal static readonly MethodSymbol TransferHeroFromDataHero = new(
			"homm3.dungeon.draconicDominion.transferHero.fromDataHero",
			"becc",
			"becd",
			"Method_Public_Static_TransferHero_Hero_0");

		internal static readonly string[] SquadEscapeSquadMembers =
			{ "field_Private_ObjectPublicDaInVeInBoObcjObBocoUnique_0", "get_field_Private_ObjectPublicDaInVeInBoObcjObBocoUnique_0", "ccvc" };

		internal static readonly string[] SquadEscapeLogicHeroMembers =
			{ "field_Private_ObjectPublicHeObInObciSiObVeSeObUnique_0", "get_field_Private_ObjectPublicHeObInObciSiObVeSeObUnique_0", "ccvb" };

		internal static readonly string[] SquadWrapperDataSquadMembers =
			{ "Method_Public_get_DataSquad_0", "get__cjoa_k__BackingField", "get_cjoa", "cjoa", "<cjoa>k__BackingField", "_cjoa_k__BackingField" };

		internal static readonly MethodSymbol LogicHeroDataHeroGetter = new(
			"homm3.dungeon.draconicDominion.logicHero.dataHeroGetter",
			"bgzx",
			"Method_Public_get_Hero_0");

		internal static readonly string[] DataHeroSkillsMembers =
			{ "get_skills", "skills" };

		internal static readonly string[] DataHeroSidMembers =
			{ "get_configSid", "configSid", "get_sid", "sid" };

		internal static readonly string[] HeroSkillsListMembers =
			{ "get_list", "list" };

		internal static readonly string[] HeroSkillSidMembers =
			{ "get_field_Public_String_0", "field_Public_String_0", "get_sid", "sid" };

		internal static readonly string[] HeroSkillLevelMembers =
			{ "get_level", "level" };

		internal static readonly string[] DataSquadUnitSidMembers =
			{ "get_field_Public_String_0", "field_Public_String_0", "get_sid", "sid" };

		internal static readonly string[] DataPartyUnitSidMembers =
			{ "get_field_Public_String_0", "field_Public_String_0", "get_sid", "sid" };

		internal static readonly string[] ResNameAndCostNameMembers =
			{ "field_Public_String_0", "name", "get_name" };

		internal static readonly string[] ResNameAndCostCostMembers =
			{ "field_Public_Int32_0", "cost", "get_cost" };

		internal static readonly string[] HeroSkillSubSkillsMembers =
			{ "get_subSkills", "subSkills" };

		internal static readonly string[] HeroSubSkillSidMembers =
			{ "get_field_Public_String_0", "field_Public_String_0", "get_sid", "sid" };

		internal static readonly string[] DiplomacyInfoSquadMembers =
			{ "squad", "field_Public_ObjectPublicDaInVeInBoObcjObBocoUnique_0" };

		internal static readonly string[] DiplomacyInfoHeroMembers =
			{ "hero", "field_Public_ObjectPublicHeObInObciSiObVeSeObUnique_0" };

		internal static readonly string[] DiplomacyInfoPartyMembers =
			{ "party", "field_Public_DataParty_0" };

		internal static readonly string[] TransferBattleSidesMembers =
			{ "sides" };

		internal static readonly string[] TransferSideTransferHeroMembers =
			{ "get_hero", "hero" };

		internal static readonly string[] TransferSideUnitsMembers =
			{ "get_units", "units" };

		internal static readonly string[] TransferHeroHeroStatMembers =
			{ "get_heroStat", "heroStat" };

		internal static readonly string[] TransferHeroHeroStatUnclampedMembers =
			{ "get_heroStatUnclamped", "heroStatUnclamped" };

		internal static readonly string[] BattleLogicHeroDataHeroMembers =
			{ "get__cbfh_k__BackingField", "get_cbfh", "xal", "cbfh", "_cbfh_k__BackingField", "ccez", "_ccez_k__BackingField" };

		internal static readonly string[] TransferUnitLogicConfigMembers =
			{ "get_cnzz", "cnzz", "becr", "cgtg", "field_Private_UnitLogicConfig_0" };

		internal static readonly string[] UnitConfigFactionMembers =
			{ "fraction" };

	}

	/// <summary>
	/// HoMM3 Dungeon Captives (replaces Draconic Dominion). Current-only 25672315 surfaces pinned by
	/// static native disassembly (GameAssembly D9972B0E); runtime unproven. Escape-UI, world-magic
	/// handler and hero-identity surfaces are shared with <see cref="DraconicDominion"/> and
	/// <see cref="CastleEliteStrategem"/>.
	/// </summary>
	internal static partial class DungeonCaptives
	{
		/// <summary>Hex.Session.Logic.Hero → hero experience component (native AddExp owner).</summary>
		internal static readonly string[] LogicHeroExpComponentMembers =
			{ "prop_Object1PublicHechInVo_hbaHeBoancUnique_0", "_chnq_k__BackingField" };

		/// <summary>Native AddExp(int exp, bool applyExpBonus = true): clamps, sets exp, runs the native level-up loop.</summary>
		internal static readonly MethodSymbol ExpComponentAddExp = new(
			"homm3.dungeon.captives.expComponent.addExp",
			"Method_Public_Void_Int32_Boolean_0");

		/// <summary>Hex.Session.Logic.Hero → hero map-buff manager.</summary>
		internal static readonly string[] LogicHeroBuffManagerMembers =
			{ "prop_Object1PublicHechInVo_hbaHeBuaLoUnique_0", "_chno_k__BackingField" };

		/// <summary>Buff manager Add(string sid, BuffDuration[] durations); dispatches on the config additionType.</summary>
		internal static readonly MethodSymbol BuffManagerAdd = new(
			"homm3.dungeon.captives.buffManager.add",
			"Method_Public_Void_String_Il2CppReferenceArray_1_BuffDuration_0");

		/// <summary>Buff manager Remove(string sid); removes only when the buff config isDispellable.</summary>
		internal static readonly MethodSymbol BuffManagerRemove = new(
			"homm3.dungeon.captives.buffManager.remove",
			"Method_Public_Void_String_0");

		/// <summary>Buff manager Get(string sid) → Hex.Session.Logic.Buff or null (dictionary TryGetValue).</summary>
		internal static readonly MethodSymbol BuffManagerGet = new(
			"homm3.dungeon.captives.buffManager.get",
			"Method_Public_Buff_String_0");

		/// <summary>Hero-profile buff slot view; OnHover shows BhTooltips(name, description, durationText).</summary>
		internal const string HeroBuffViewTypeName = "Hex.Session.UI.HeroProfile.BhHeroBuffView";

		/// <summary>Hero-profile data view; Init(Logic.Hero, bool isArena, bool isFight) binds the shown hero.</summary>
		internal const string HeroDataViewTypeName = "Hex.Session.UI.HeroProfile.BhHeroDataView";

		/// <summary>BhHeroDataView.Init(Logic.Hero _hero, bool _isArena, bool _isFight).</summary>
		internal static readonly MethodSymbol HeroDataViewInit = new(
			"homm3.dungeon.captives.heroDataView.init",
			"Init");

		/// <summary>BhHeroBuffView private string builder whose only caller is OnHover: the tooltip's third (duration) text.</summary>
		internal static readonly MethodSymbol HeroBuffViewDurationText = new(
			"homm3.dungeon.captives.heroBuffView.durationText",
			"Method_Private_String_0");

		/// <summary>BhHeroBuffView → the bound Hex.Session.Logic.Buff.</summary>
		internal static readonly string[] HeroBuffViewBuffMembers =
			{ "field_Private_Buff_0" };

		/// <summary>Hex.Session.Logic.Buff → its Hex.Session.Data.Buff (auto-property).</summary>
		internal static readonly string[] LogicBuffDataMembers =
			{ "prop_Buff_0", "_chkp_k__BackingField" };

		/// <summary>Hex.Session.Data.Buff native field "sid".</summary>
		internal static readonly string[] DataBuffSidMembers =
			{ "field_Public_String_0" };
	}

	/// <summary>
	/// Shared hero-skill meter (Homm3HeroSkillMeterHud): a gauge beside the adventure hero-bar portrait in the
	/// style of the vanilla necromancy meter (BhFrameEnergyHero "ContainerEnergy"), hover text through the native
	/// BhTooltips single-text Show that BhFrameEnergyHero.Show uses (snap Left), closed with BhTooltips.Hide.
	/// </summary>
	internal static partial class HeroSkillMeter
	{
		internal const string TooltipsTypeName = "Hex.UI.Tooltips.BhTooltips";
		internal const string SnapDirectionName = "Left";

		/// <summary>Static BhTooltips singleton field (read at statics+0 by BhFrameEnergyHero.Show).</summary>
		internal static readonly string[] TooltipsInstanceMembers =
			{ "field_Private_Static_BhTooltips_0" };

		/// <summary>BhTooltips.Show(string text, RectTransform target, ESnapDirection snap, bool); BhFrameEnergyHero.Show calls it with snap Left, false.</summary>
		internal static readonly MethodSymbol TooltipsShowText = new(
			"homm3.heroSkillMeter.tooltips.showText",
			"Method_Public_Void_String_RectTransform_ESnapDirection_Boolean_1");

		internal static readonly MethodSymbol TooltipsHide = new(
			"homm3.heroSkillMeter.tooltips.hide",
			"Hide");
	}

	internal static partial class CoveAfterShot
	{
		internal const string BuffManagerTypeId = "homm3.cove.afterShot.buffManager";
		internal static readonly string BuffManagerTypeHint = "dzv";

		internal static readonly MethodSymbol[] BuffAddMethods =
		{
			new("homm3.cove.afterShot.buffAdd.bbgf", "bbgf"),
			new("homm3.cove.afterShot.buffAdd.okg", "okg"),
			new("homm3.cove.afterShot.buffAdd.nyc", "nyc"),
			new("homm3.cove.afterShot.buffAdd.bber", "bber"),
			new("homm3.cove.afterShot.buffAdd.nyl", "nyl"),
			new("homm3.cove.afterShot.buffAdd.bvq", "bvq"),
			new("homm3.cove.afterShot.buffAdd.bbcv", "bbcv"),
			new("homm3.cove.afterShot.buffAdd.jeg", "jeg"),
			new("homm3.cove.afterShot.buffAdd.dgc", "dgc"),
			new("homm3.cove.afterShot.buffAdd.bbbv", "bbbv"),
			new("homm3.cove.afterShot.buffAdd.hrc", "hrc"),
			new("homm3.cove.afterShot.buffAdd.fhp", "fhp"),
			new("homm3.cove.afterShot.buffAdd.jlv", "jlv"),
			new("homm3.cove.afterShot.buffAdd.jon", "jon"),
		};

		internal static readonly MethodSymbol[] BuffListMethods =
		{
			new("homm3.cove.afterShot.buffList.bbfn", "bbfn"),
			new("homm3.cove.afterShot.buffList.bbfl", "bbfl"),
			new("homm3.cove.afterShot.buffList.bbdx", "bbdx"),
			new("homm3.cove.afterShot.buffList.kv", "kv"),
			new("homm3.cove.afterShot.buffList.kab", "kab"),
			new("homm3.cove.afterShot.buffList.bbcb", "bbcb"),
			new("homm3.cove.afterShot.buffList.dyw", "dyw"),
			new("homm3.cove.afterShot.buffList.bbbb", "bbbb"),
			new("homm3.cove.afterShot.buffList.cpi", "cpi"),
			new("homm3.cove.afterShot.buffList.mks", "mks"),
			new("homm3.cove.afterShot.buffList.deobfHasBool", "Method_Public_Boolean_String_0"),
			new("homm3.cove.afterShot.buffList.deobfGetList", "Method_Public_List_1_Object1PublicBoInchStBucodaBuObtaUnique_String_PDM_0"),
		};

		internal static readonly MethodSymbol BuffListHasBool = new(
			"homm3.cove.afterShot.buffList.hasBool",
			"bbfn", "bbdx", "kv", "kab", "Method_Public_Boolean_String_0");

		internal static readonly MethodSymbol BuffListBySid = new(
			"homm3.cove.afterShot.buffList.bySid",
			"bbfl", "bbcb", "bbbb", "Method_Public_List_1_Object1PublicBoInchStBucodaBuObtaUnique_String_PDM_0");

		internal static readonly MethodSymbol BuffAddShape = new(
			"homm3.cove.afterShot.buffAdd.shape",
			"bbgf", "bber", "bbcv", "Method_Public_Object1PublicBoInchStBucodaBuObtaUnique_String_Int32_Int32_InterfacePublicAbstractbaObbbUnInbbUnObbbObUnique_Int32_Boolean_0");

		internal static readonly MethodSymbol CasterBattleObject = new("homm3.cove.afterShot.caster.battleObject", "bbcb", "bbbb", "bano");

		internal static readonly MethodSymbol CasterRoot = new("homm3.cove.afterShot.caster.root", "bbaq", "baxu");
	}

	internal static partial class BuffDebuffLaws
	{
		internal const string BuffManagerTypeId = "law.buffDebuff.buffManager";
		internal static readonly string BuffManagerTypeHint = "dzv";

		internal static readonly MethodSymbol BuffAdd = new(
			"law.buffDebuff.buffAdd",
			"bbgf",
			"Method_Public_Object1PublicBoInchStBucodaBuObtaUnique_String_Int32_Int32_InterfacePublicAbstractbaObbbUnInbbUnObbbObUnique_Int32_Boolean_0");
		// Live Golden Era exposes three Boolean_String methods (bbfn / dud / ink). Do not
		// treat any single Boolean_String_* hint as presence authority — Homm3BuffDebuffNativeAdapter
		// proves presence via BuffListBySid Count (bbfl). Boolean hints remain diagnostic only.
		internal static readonly MethodSymbol BuffHasBySid = new(
			"law.buffDebuff.buffHasBySid",
			"bbfn",
			"Method_Public_Boolean_String_PDM_0",
			"Method_Public_Boolean_String_0");

		// DiffableCs bbfl is the dict-keyed list lookup (TryGetValue on ceqq). Live pin is the
		// List_*_String_PDM_0 neighbor of the full-shape buff-add method.
		internal static readonly MethodSymbol BuffListBySid = new(
			"law.buffDebuff.buffListBySid",
			"bbfl",
			"Method_Public_List_1_Object1PublicBoInchStBucodaBuObtaUnique_String_PDM_0");

		internal static readonly string[] BuffPayloadMembers =
			{ "sid", "id", "level", "duration", "turns", "rounds", "caster", "target", "source", "amount", "value", "stat" };

		internal static readonly string[] BuffManagerReceiverMembers =
			{ "ceqy", "get_field_Private_InterfacePublicAbstractObcnbbObcnFiBobbVoaUnique_0" };

		internal static readonly string[] BuffReceiverManagerMembers =
			{ "cnyb", "bbds", "get__cfnh_k__BackingField", "Method_Public_Virtual_Final_New_get_ObjectPublicDi2StLi1ObceInLi1Unique_0" };

		internal static readonly string[] BuffReceiverSideMembers =
			{ "basa", "get_field_Public_TransferSide_0", "field_Public_TransferSide_0" };

		internal static readonly string[] BuffReceiverObjectMembers =
			{ "bbdp", "Method_Public_Abstract_Virtual_New_FieldObject_0" };

		internal static readonly string[] BuffReceiverHexMembers =
			{ "cnyr", "bcuh" };

		internal static readonly string[] BuffReceiverIdMembers =
			{ "bbdu", "cnyc" };

		// June 19 source-normalization route: DiffableCs shows eab.bbce() returns eab,
		// and Unit inherits ede -> eab. Use this exact native self/source getter before
		// invoking dzv.bbgf; do not broaden to arbitrary assignable getter scans.
		internal static readonly string[] BuffSourceSelfMembers =
			{ "bbce", "Method_Public_Abstract_Virtual_New_InterfacePublicAbstractbaObbbUnInbbUnObbbObUnique_0", "Method_Public_Virtual_Final_New_InterfacePublicAbstractbaObbbUnInbbUnObbbObUnique_0" };

		// June 19 exact status-source route: decomp/live metadata show battle field objects expose
		// cfng/dxx ability manager, and dxx stores the initialized caster/source as its private
		// FieldObject/eab owner. This is diagnostic source normalization only, not a broad fallback.
		internal static readonly string[] BuffSourceAbilityManagerMembers =
			{ "cfng", "get__cfng_k__BackingField", "Method_Public_get_ObjectPublicObceDiObce2EAInBoInUnique_0" };

		internal static readonly string[] BuffAbilityManagerSourceMembers =
			{ "ceig", "get_field_Private_FieldObjectPublicAbstractObUnObcfcnObstcnUnHeUnique_0" };

		// dxx.ceih -> ecz, and ecz.cfhc -> eda event hub. This is the native event
		// dispatch owner used by dxx.baqj; do not dispatch BuffEventArgs on ceig/bbdt.
		internal static readonly string[] BuffAbilityManagerEventContextMembers =
			{ "ceih", "get_field_Private_ObjectPublic82cf49Vocfa22Unique_0" };

		internal static readonly string[] BuffEventContextEventHubMembers =
			{ "cfhc", "get_field_Public_ObjectPublicEv1BacfEv1BacfBoEvUnique_0" };

		internal const string BuffEventArgsTypeId = "law.buffDebuff.buffEventArgs";
		internal const string BuffEventArgsTypeHint = "Hex.Session.Battle.BuffEventArgs";

		// Live-negative 2026-07-26: Method_39 raises field_39/cfir and listeners cast to
		// ChangeAbilityEventArgs (InvalidCastException on BuffEventArgs). DiffableCs method
		// index 39 coincidentally equals Method_39 but is the wrong numbering scheme.
		// ISIL eda.bcja loads EventHandler at +0x128 = cfin; interop
		// GetIl2CppField(..., "cfin") is field_Private_EventHandler_1_BattleEventArgs_35,
		// so the matching raise is Method_Public_Void_Object_BattleEventArgs_35.
		// Invoke as hub.bcja(nativeSourceObject, args) — Object sender is baqj's `a`, never
		// the hub. Hub resolution stays cfng.ceih.cfhc.
		internal static readonly MethodSymbol BuffEventDispatch = new(
			"law.buffDebuff.buffEventDispatch.bcja",
			"bcja",
			"Method_Public_Void_Object_BattleEventArgs_35");
	}

	internal static partial class RampartAvengerLaws
	{
		internal const string AbilitySid = "skill_faction_homm3_rampart_ability_avenger";

		internal const string Rank1BuffSid = "skill_faction_homm3_rampart_ability_avenger_rank_1_effect";
		internal const string Rank2BuffSid = "skill_faction_homm3_rampart_ability_avenger_rank_2_effect";
		internal const string Rank3BuffSid = "skill_faction_homm3_rampart_ability_avenger_rank_3_effect";
		internal const string Rank2DecayBuffSid = "skill_faction_homm3_rampart_ability_avenger_rank_2_decay_effect";
		internal const string CustomMarkerBuffSid = "homm3_law_marker_avenger_intensity";

		internal static readonly string[] MarkBuffSids =
		{
			Rank1BuffSid,
			Rank2BuffSid,
			Rank3BuffSid,
			Rank2DecayBuffSid,
		};

		internal static readonly string[] CustomMarkerBuffSids =
		{
			CustomMarkerBuffSid,
		};

		internal static bool TryDescribeMarkBuffSid(string sid, out string description)
		{
			description = null;
			if (string.IsNullOrWhiteSpace(sid))
				return false;
			if (string.Equals(sid, Rank1BuffSid, StringComparison.Ordinal))
			{
				description = "rampart-avenger-mark:rank1";
				return true;
			}
			if (string.Equals(sid, Rank2BuffSid, StringComparison.Ordinal))
			{
				description = "rampart-avenger-mark:rank2";
				return true;
			}
			if (string.Equals(sid, Rank3BuffSid, StringComparison.Ordinal))
			{
				description = "rampart-avenger-mark:rank3";
				return true;
			}
			if (string.Equals(sid, Rank2DecayBuffSid, StringComparison.Ordinal))
			{
				description = "rampart-avenger-mark:rank2-decay";
				return true;
			}
			return false;
		}
	}

	internal static partial class UnitViewConfig
	{
		internal static readonly MethodSymbol MapMeshLoader = new(
			"unitViewConfig.mapMesh.loader",
			"Method_Public_GameObject_0");

		// Current 25672315 F interop: ConfigElementBase<string>.id is generated as IDType_0.
		// The native reader verifies the declaring generic owner and native String type.
		// Static pin only; a live UnitViewConfig read has not yet been validated.
		internal const string ConfigElementBaseGenericTypeFullName = "Hex.Configs.ConfigElementBase`1";
		internal static readonly string[] ConfigElementBaseStringIdNativeFieldAliases =
			{ "id", "field_Public_IDType_0" };
	}

	internal static partial class MapSquadVisual
	{
		// Golden Era May 2026 map squad visual controller (Il2CppDumper on Golden Era install).
		// Do not use ezg here; that name is reused for ambient sound (fwo) in the same build.
		internal static readonly string[] ControllerTypeHints =
			{ "ObjectPublicGaObcjObUncjAnBhObStUnique", "ezp", "ezn" };

		internal static readonly string[] WorldSquadTypeHints =
			{ "ObjectPublicDaInVeInBoObcjObBocoUnique", "fdh", "fdf" };

		internal static readonly string[] InitContextTypeHints =
			{ "MonoBehaviour1PublicObmeLa1caObMeDaNoBoUnique", "ctr", "ctq" };

		internal static readonly MethodSymbol InitBind = new(
			"mapSquadVisual.init",
			"Init", "kih", "hwp");

		internal static readonly MethodSymbol VisibilityBind = new(
			"mapSquadVisual.visibility",
			"bieq", "jxp",
			"Method_Public_Void_Boolean_PDM_2");

		internal static readonly string[] RootFields =
		{
			"ciyg", "<ciyg>k__BackingField", "_ciyg_k__BackingField",
			"_cjbb_k__BackingField", "<cjbb>k__BackingField", "cjbb"
		};

		internal static readonly MethodSymbol RootGetter = new(
			"mapSquadVisual.root.getter",
			"bigc", "Method_Public_get_GameObject_0", "biee");

		internal static readonly string[] ViewConfigFields =
			{ "ciyk", "field_Private_UnitViewConfig_0", "cjbf" };
	}

	internal static partial class UnitPreview
	{
		internal const string PartySelectorSlotType = "Hex.Session.City.BhUpgradeUnitSlot";

		internal static readonly MethodSymbol PartySelectorSlotUnitBind = new(
			"unitPreview.partySelectorSlot.unitBind",
			"Init");

		internal static readonly MethodSymbol PartySelectorSlotSidBind = new(
			"unitPreview.partySelectorSlot.sidBind",
			"baon", "Method_Public_Void_String_Int32_Action_1_BhUpgradeUnitSlot_Int32_Boolean_0", "bamz", "bald", "baji");

		internal static readonly string[] PartySelectorSlotIconFields =
			{ "icon" };

		internal static readonly string[] PartySelectorSlotUnitFields =
			{ "cegy", "cnxt", "baok", "field_Private_Unit_0", "Method_Public_get_Unit_0", "ceen", "unit", "cnut" };

		internal static readonly string[] PartySelectorSlotSidFields =
			{ "cehc", "cnxv", "baom", "field_Private_String_0", "Method_Public_get_String_0", "ceer", "sid", "configSid", "cnuv" };

		internal static readonly FieldSymbol WindowPreviewWrapperField = new(
			"unitPreview.window.wrapper",
			"NativeFieldInfoPtr_field_Private_MonoBehaviourPublicSealedGaRoMoGaMeBaStSiUnique_0",
			"field_Private_MonoBehaviourPublicSealedGaRoMoGaMeBaStSiUnique_0");

		internal static readonly string[] PreviewWrapperTypeNames =
			{ "MonoBehaviourPublicSealedGaRoMoGaMeBaStSiUnique", "clt" };

		internal static readonly MethodSymbol WindowFactory = new(
			"unitPreview.window.factory",
			"Method_Public_MonoBehaviourPublicSealedGaRoMoGaMeBaStSiUnique_String_Transform_0", "bewc", "beth", "betg", "beri", "bebc");

		internal static readonly MethodSymbol SharedPreviewFactory = new(
			"unitPreview.shared.factory",
			"Method_Public_Boolean_String_Single_byref_MonoBehaviourPublicSealedGaRoMoGaMeBaStSiUnique_0", "htv", "htf", "hqr");

		// Current-build pool pins; Golden aliases identify the exact old methods only and assert no Golden behavior.
		internal static readonly MethodSymbol SharedPreviewWarmup = new(
			"unitPreview.shared.warmup",
			"Method_Private_Void_0", "htu");

		internal static readonly MethodSymbol SharedPreviewCreate = new(
			"unitPreview.shared.create",
			"Method_Private_MonoBehaviourPublicSealedGaRoMoGaMeBaStSiUnique_UnitViewConfig_0", "htz");

		/// <summary>
		/// Town hire screen (large 3D recruit panel): <c>BhHireUnitItemView.tvn(IReadOnlyList&lt;string&gt;)</c> returns the
		/// previous wrappers to the <c>BhUnitPreviews</c> per-sid pool, then fills its own wrapper list from <c>htv(sid)</c>
		/// for every sid in the upgrade chain. Its per-item <c>tvp</c> is inlined natively and never runs.
		/// </summary>
		internal static readonly MethodSymbol HireItemModelList = new(
			"unitPreview.hireItem.modelList",
			"Method_Public_Void_IReadOnlyList_1_String_0", "tvn");

		/// <summary><c>BhHireUnitItemView.bzii</c> (List&lt;clt&gt;, 0x130): the wrappers <c>tvn</c> just built.</summary>
		internal static readonly string[] HireItemModelListFields =
			{ "field_Private_List_1_MonoBehaviourPublicSealedGaRoMoGaMeBaStSiUnique_0", "bzii" };

		/// <summary>
		/// <c>BhUnitPreviews.me</c> static singleton. Live Golden Era interop names it
		/// <c>field_Public_Static_BhUnitPreviews_0</c>; the deobf <c>me</c> accessor does not exist live
		/// (a direct <c>BhUnitPreviews.me</c> reference threw MissingMethodException on 2026-09-26).
		/// </summary>
		internal static readonly string[] SharedPreviewsInstanceMembers =
			{ "field_Public_Static_BhUnitPreviews_0", "me" };

		/// <summary><c>BhUnitPreviews.prefab</c>: the shared template wrapper that must never be mutated.</summary>
		internal static readonly string[] SharedPreviewPrefabFields =
			{ "prefab", "field_Private_MonoBehaviourPublicSealedGaRoMoGaMeBaStSiUnique_0" };
	}

	internal static partial class TooltipPortrait
	{
		internal static readonly string[] TooltipUnitTypeHints =
			{ "Hex.UI.BhTooltipUnit" };

		internal static readonly string[] SidSurfaceMethodNames =
			{ "tcy", "Show", "tda", "tcr", "tcp", "Method_Public_Void_String_0", "Method_Public_Void_String_1" };

		internal const int ExpectedSidSurfaceCount = 4;

		internal static readonly string[] PortraitImageFields =
			{ "portrait" };

		internal static readonly string[] DiagnosticOwnedObjectFields =
			{ "white", "armyCountBack", "armyCountFrame", "skullLoss" };
	}

	internal static partial class Projectile
	{
		internal static readonly MethodSymbol AbilityViewProjectileGetter = new(
			"battle.projectile.abilityView.getProjectile",
			"rog", "Method_Public_ProjectileConfig_0",
			"rnu", "rnh", "rne", "rmp", "rcs");

		internal static readonly MethodSymbol HeroAbilityLevelProjectileGetter = new(
			"battle.projectile.heroAbilityLevel.getProjectile",
			"rwf", "Method_Public_ProjectileConfig_0",
			"rvt", "rvg");

		internal static readonly MethodSymbol ControllerInit = new(
			"battle.projectile.controller.init",
			"Init");

		internal static readonly MethodSymbol ControllerSetPositions = new(
			"battle.projectile.controller.setPositions",
			"bbst", "Method_Public_Void_Vector3_Vector3_Vector3_0",
			"bbrd", "bbqc", "bbqd", "q");

		internal static readonly MethodSymbol ControllerUpdate = new(
			"battle.projectile.controller.update",
			"bbsv", "Method_Public_Virtual_Void_Single_0",
			"bbrf", "bbqe", "bbqf", "ldk");
	}

	/// <summary>
	/// Native unit/spell VFX helper. Mono <c>BhEffectHelper.Init(Transform, bool isRight)</c>
	/// survived as <c>Init</c> on Golden Era interop; play/hide names drifted.
	/// </summary>
	internal static partial class BattleEffect
	{
		internal static readonly string[] HelperTypeNames =
		{
			"BhEffectHelper",
			"Hex.Session.Battle.BhEffectHelper"
		};

		internal static readonly string[] SpawnAsChildFields = { "spawnAsChild" };

		internal static readonly MethodSymbol Init = new(
			"battle.effect.helper.init",
			"Init",
			"Method_Public_Virtual_New_Void_Transform_Boolean_0");

		internal static readonly MethodSymbol StartPlaying = new(
			"battle.effect.helper.startPlaying",
			"StartPlaying",
			"baiv");
	}

	internal static partial class BattleCommand
	{
		internal static readonly string CounterEventRuntimeType = "eiw";
		internal static readonly string BattleExecutorRuntimeType = "ems";

		internal static readonly string[] AbilityManagerTypeNames =
			{ "dxr" };

		internal static readonly string[] RuntimeUnitTypeNames =
			{ "ecx" };

		internal static readonly MethodSymbol AttackCommandExecute = new(
			"battle.attackCommand.execute",
			"hrq");

		internal static readonly MethodSymbol AbilityLookup = new(
			"battle.abilityManager.lookup",
			"baop", "baoq");

		internal static readonly MethodSymbol AbilityBucket = new(
			"battle.abilityManager.bucket",
			"bana", "bama", "baoa", "banz", "klu", "ihh", "fnd", "fsk", "bar", "drf");

		internal static readonly MethodSymbol AbilityManagerInit = new(
			"battle.abilityManager.initAliases",
			"Init");

		internal static readonly string[] AbilityLogicConfigFields =
			{ "cejb", "cedw", "cdgt" };

		internal static readonly string[] AbilityViewConfigFields =
			{ "cejc", "cedx", "cdgu" };

		internal static readonly string[] RuntimeTagListFields =
			{ "cfjh" };

		internal static readonly string[] AttackTypeMembers =
			{ "cmyi" };

		internal static readonly string[] UnitSidFields =
			{ "cfla", "cfhr", "cfjg", "configId", "configSid", "sid", "id", "unitSid" };

		internal static readonly string[] UnitNestedConfigFields =
			{ "chey", "chbu", "cggz", "cfjc", "<cfjc>k__BackingField", "_cfjc_k__BackingField" };

		internal static readonly string[] UnitConfigSidMembers =
			{ "configSid", "sid", "id", "unitSid" };

		internal static readonly MethodSymbol UnitConfigSidGetter = new(
			"battle.unit.configSid.getter",
			"bcqo", "bcqp", "GetConfigId", "get_configId");

		internal static readonly MethodSymbol CounterGate = new(
			"battle.counter.gate",
			"dtr");

		internal static readonly MethodSymbol CounterHelper = new(
			"battle.counter.preCounterHelper",
			"jqy");

		internal static readonly MethodSymbol AttackResolver = new(
			"battle.counter.attackResolver",
			"bdht",
			"bdib",
			"ux",
			"hqg");

		internal static readonly MethodSymbol CounterEligibility = new(
			"battle.counter.eligibility",
			"bdiq",
			"gko",
			"cza",
			"bdhz",
			"cgj");

		internal static readonly MethodSymbol CounterSchedule = new(
			"battle.counter.schedule",
			"eqk",
			"bdij",
			"bdjh",
			"byx");

		internal static readonly MethodSymbol CounterEventBuilder = new(
			"battle.counter.eventBuilder",
			"bdht",
			"bdib",
			"bdic",
			"eql",
			"jxi",
			"bdhu",
			"fej");

		internal static readonly MethodSymbol MoveClassifier = new(
			"battle.counter.moveClassifier",
			"buw");

		internal static readonly MethodSymbol TargetShape = new(
			"battle.counter.targetShape",
			"bdil");

		internal static readonly MethodSymbol UnitPair = new(
			"battle.counter.unitPair",
			"nbq");

		internal static readonly MethodSymbol CounterEventExecute = new(
			"battle.counter.eventExecute",
			"bdvn", "bdvo");

		internal static readonly MethodSymbol EventQueue = new(
			"battle.counter.eventQueue",
			"bdvw", "bdvx");

		internal static readonly MethodSymbol BattleExecutorAttack = new(
			"battle.executor.attack",
			"lee",
			"bezr",
			"zg",
			"daj");

		internal static readonly MethodSymbol BattleExecutorMove = new(
			"battle.executor.move",
			"bezv", "bezu");
	}

	// Native sprite resolver (Golden Era cko): singleton sfk, sprite-by-key sfo, sprite catalog dictionary 0.
	// A June 24 runtime probe proved sfo resolves keys from dictionary 0 before returning WIP.
	internal static partial class NativeSpriteCatalog
	{
		internal static readonly string[] ResolverTypeHints = { "ObjectPublicObbxDi2StSpbxDi2StUnique" };

		internal static readonly MethodSymbol ResolverSingleton = new(
			"nativeSpriteCatalog.resolver.singleton",
			"Method_Public_Static_ObjectPublicObbxDi2StSpbxDi2StUnique_0");

		internal static readonly MethodSymbol SpriteCatalogGetter = new(
			"nativeSpriteCatalog.resolver.catalogGetter",
			"get_field_Public_Dictionary_2_String_Sprite_0");

		internal static readonly MethodSymbol ResolveSprite = new(
			"nativeSpriteCatalog.resolver.resolveSprite",
			"Method_Public_Sprite_String_0");
	}

	internal static partial class ReleaseTownUi
	{
		internal static readonly string[] CityWrapperTypeHints =
			{ "ezx", "ObjectPublicObcjHeObcjcjObcjUnique", "Object1PublicObInObcjcoObcjInObcjUnique" };

		internal static readonly string[] FbiCityWrapperTypeHints =
			{ "fbi", "ObjectPrivateObcjHeObcjcjObcjUnique" };

		// ScUpgradeUnits close surfaces. Golden Era exposes the real names; on 25509697 both are obfuscated
		// (OnEscapeClick -> Method_Private_Void_1 bdrw, ICF-folded with OnExitButtonClick, body 0.993;
		// OnHide override -> Method_Public_Virtual_Void_0 igf, body 0.895). They postdate the 25509697 remap,
		// so that build scopes them through reviewed overrides (current_scope_overrides_25509697.json).
		internal static readonly MethodSymbol UpgradeUnitsEscapeClick = new(
			"release.town.upgradeUnits.escapeClick",
			"OnEscapeClick");

		internal static readonly MethodSymbol UpgradeUnitsHide = new(
			"release.town.upgradeUnits.hide",
			"OnHide");

		// The UI-window OnHide override is renamed on 25509697 (Golden Era: 144 types declare a method named
		// OnHide; 25509697: one). Each owner's override gets its own interop name there, so every OnHide
		// surface is a per-owner symbol rather than a hard-coded string.
		internal static readonly MethodSymbol HeroStatRewardHide = new(
			"release.town.heroStatReward.hide",
			"OnHide");

		internal static readonly MethodSymbol CitySessionHide = new(
			"release.town.citySession.hide",
			"OnHide");

		internal static readonly MethodSymbol BuildingViewHide = new(
			"release.town.buildingView.hide",
			"OnHide");

		// BhMagicItemView.Show(arg0, _, arg2, _, bool): parameter types 0 and 2 (Golden Era dtl / dtm).
		internal static readonly string[] MagicItemShowArg0TypeHints = { "dtl" };

		internal static readonly string[] MagicItemShowArg2TypeHints = { "dtm" };

		internal static readonly MethodSymbol CitySessionRefresh = new(
			"release.town.citySession.refresh",
			"Method_Public_Void_0", "Method_Private_Void_0", "Method_Public_Void_1", "Method_Private_Void_1",
			"giw", "gix", "hrz", "tza", "tzb", "tzc", "tzd", "tze", "tzf", "tzg", "tzh", "tzi", "tzj",
			"tzk", "tzl", "tzm", "tzn", "tzo", "tzp", "tzq", "tzr", "tzs", "tzt", "tzu", "tzv",
			"tzx", "tzy", "tzz", "uaa", "uab",
			"gip", "giq", "hrs", "tyh", "tyi", "tyj", "tyk", "tyl", "tym", "tyn",
			"tyo", "typ", "tyq", "tyr", "tys", "tyt", "tyu", "tyv", "tyw",
			"tye", "tyf", "tyg");

		internal static readonly MethodSymbol BuildingsManagerRefresh0 = new(
			"release.town.buildingsManager.refresh0",
			"OnEnable", "baih");

		internal static readonly MethodSymbol BuildingsManagerRefresh1 = new(
			"release.town.buildingsManager.refresh1",
			"baid", "baie", "baif", "baig", "baih");

		internal static readonly MethodSymbol BuildingsManagerRefresh2 = new(
			"release.town.buildingsManager.refresh2",
			"baif");

		internal static readonly MethodSymbol BuildingSessionRefresh = new(
			"release.town.buildingSession.refresh",
			"giw", "tso", "tsp", "tsq", "tss", "trv", "trw", "trx", "trz", "trr", "trs", "trt", "trb", "trc", "trd", "trf");

		internal static readonly MethodSymbol BuildingUiShown = new(
			"release.town.buildingUi.shown",
			"giw", "tso", "tsp");

		internal static readonly string[] BuildingDataListMembers =
			{
				"field_Private_List_1_BuildingData_0",
				"cnzd", "bgbh", "cnye", "bgae", "cnyb", "bgad", "chsd", "cnxb", "chrg", "bfzh", "cnvj", "chpr", "cnvk", "chps", "cgtl", "cmzg", "fkz"
			};

		internal static readonly string[] BuildingDataListMethods =
			{ "Method_Public_get_List_1_BuildingData_0" };

		internal static readonly MethodSymbol CityUiElementRefreshIndexed = new(
			"release.town.cityUiElement.refreshIndexed",
			"wbr");

		internal static readonly MethodSymbol CityUiElementRefresh = new(
			"release.town.cityUiElement.refresh",
			"wbs");

		internal static readonly MethodSymbol BuildingViewBind = new(
			"release.town.buildingView.bind",
			"Method_Public_Void_Object1PublicObInObcjcoObcjInObcjUnique_ObjectPublicBuObcdStObcdcnInBocnUnique_Int32_0",
			"tot", "tqf");

		internal static readonly MethodSymbol BuildingViewSecondaryBind = new(
			"release.town.buildingView.secondaryBind",
			"tou", "tqg");

		internal static readonly MethodSymbol BuildingViewHoverRefresh = new(
			"release.town.buildingView.hoverRefresh",
			"tqh", "tqi", "tqj", "tqk", "tql", "tqm", "tqn", "tqo", "tqp", "tqq");

		internal static readonly MethodSymbol BuildingTooltipBind = new(
			"release.town.buildingTooltip.bind",
			"tam", "tan");

		internal static readonly string[] BuildingTooltipViewFields =
			{ "field_Private_BhBuildingView_0", "byps" };

		internal static readonly string[] CityHudCityFields =
			{ "cbcr", "cbba", "cazz", "cawv", "cafp" };

		internal static readonly string[] SessionCityDataFields =
			{
				"field_Public_ObjCity_0",
				"cjgv", "_cjgv_k__BackingField", "<cjgv>k__BackingField",
				"cjea", "_cjea_k__BackingField", "<cjea>k__BackingField",
				"cidl", "_cidl_k__BackingField", "<cidl>k__BackingField",
				"cjdc", "_cjdc_k__BackingField", "<cjdc>k__BackingField",
				"cjcx", "cjbz", "_cjan_k__BackingField", "cjao", "_cjao_k__BackingField", "<cjao>k__BackingField",
				"cjce", "ciyz"
			};

		internal static readonly string[] SessionCityDataMethods =
			{ "Method_Public_get_ObjCity_0" };

		internal static readonly string[] SessionCityConfigFields =
			{
				"field_Public_ObjCityConfig_0",
				"cjgu", "_cjgu_k__BackingField", "<cjgu>k__BackingField",
				"cjdz", "_cjdz_k__BackingField", "<cjdz>k__BackingField",
				"cidk", "_cidk_k__BackingField", "<cidk>k__BackingField",
				"cjdb", "_cjdb_k__BackingField", "<cjdb>k__BackingField",
				"cjcw", "cjby", "_cjam_k__BackingField", "cjbz", "_cjan_k__BackingField",
				"cjcd", "ciyy"
			};

		internal static readonly string[] SessionCityConfigMethods =
			{ "Method_Public_get_ObjCityConfig_0" };

		internal static readonly string[] DataObjectConfigFields =
			{
				"field_Private_BuildingConfigBase_0",
				"cnzc", "bgaj", "cnyd", "bfzg", "cnxc", "cntu", "chrh", "choe"
			};

		internal static readonly string[] DataObjectConfigMethods =
			{ "Method_Public_get_BuildingConfigBase_0" };

		internal static readonly string[] BuildingDataSidMembers =
			{ "field_Public_String_0", "cnrm", "cnou", "cnqm", "babw", "baay" };

		internal static readonly string[] BuildingDataSidAccessorMethods =
			{ "get_field_Public_String_0" };

		internal static readonly string[] BuildingDataLevelMembers =
			{ "level", "cnrn", "cnov", "cnqn", "babx", "baaz" };

		internal static readonly string[] BuildingDataLevelAccessorMethods =
			{ "get_level" };

		internal static readonly string[] BuildingDataConstructedMembers =
			{ "isConstructed" };

		internal static readonly string[] BuildingDataConstructedAccessorMethods =
			{ "get_isConstructed" };

		internal static readonly string[] BuildingModelTypeNames =
			{ "dwc", "dvw", "ObjectPublicBuObcdStObcdcnInBocnUnique" };

		internal static readonly string[] BuildingModelDataMembers =
			{
				"field_Private_BuildingData_0",
				"cdzv", "<cdzv>k__BackingField", "_cdzv_k__BackingField",
				"cdxk", "<cdxk>k__BackingField", "_cdxk_k__BackingField", "babz",
				"cdvr", "<cdvr>k__BackingField", "_cdvr_k__BackingField", "babb"
			};

		internal static readonly string[] BuildingModelDataMethods =
			{ "Method_Public_get_BuildingData_0" };

		internal static readonly string[] BuildingModelSidMembers =
			{
				"field_Public_String_0",
				"babw", "baay", "cnrm", "cnou", "cnqm", "cmsy"
			};

		internal static readonly string[] BuildingModelSidMethods =
			{ "Method_Public_get_String_0" };

		internal static readonly string[] BuildingConfigSidMembers =
			{ "field_Public_String_0" };

		internal static readonly string[] BuildingModelLevelMembers =
			{ "babx", "baaz", "cnrn", "cnov", "cnqn", "level" };

		internal static readonly string[] BuildingModelLevelMethods =
			{ "Method_Public_get_Int32_0" };

		internal static readonly MethodSymbol NavigationBack = new(
			"release.town.navigation.back",
			"sms", "smg", "sme", "slp");

		internal static readonly MethodSymbol NavigationSelect = new(
			"release.town.navigation.select",
			"Method_Public_Void_ECityNavigation_0",
			"tvp", "tuc", "tte");

		internal static readonly MethodSymbol NavigationTabSelect = new(
			"release.town.navigation.tabSelect",
			"Method_Public_Void_BhNavigationTabView_PDM_0");

		internal static readonly MethodSymbol NavigationTabClick = new(
			"release.town.navigationTab.click",
			"OnClick");

		internal static readonly MethodSymbol NavigationTabVisualSelect = new(
			"release.town.navigationTab.visualSelect",
			"Select");

		internal static readonly string[] NavigationStateFields =
			{ "field_Private_ECityNavigation_0", "bzji", "bzgw", "bzfe", "bzeg", "bzcr" };

		internal static readonly string[] NavigationTabStateFields =
			{ "eNavigation" };

		internal static readonly FieldSymbol CitySessionNavigation = new(
			"release.town.citySession.navigation",
			"NativeFieldInfoPtr_navigation",
			"navigation");

		internal static readonly MethodSymbol DayPanelBack = new(
			"release.town.dayPanel.back",
			"hly", "hlr", "hlm");

		internal static readonly MethodSymbol BuildingScreenBack = new(
			"release.town.buildingScreen.back",
			"hly", "hlr");

		internal static readonly MethodSymbol HireScreenBack = new(
			"release.town.hireScreen.back",
			"hly", "hlr");

		internal static readonly MethodSymbol GenericButtonBack = new(
			"release.town.genericButton.back",
			"hly", "hlr", "hlm");

		internal static readonly MethodSymbol ExitHudShowState = new(
			"release.town.exitHud.showState",
			"vxn", "vxi");

		internal static readonly MethodSymbol UpgradeUiShown = new(
			"release.town.upgradeUi.shown",
			"giw", "bano", "banu", "gip", "vsj", "bamv", "vsf", "bamw");

		internal static readonly MethodSymbol HireUiShown = new(
			"release.town.hireUi.shown",
			"Method_Public_Virtual_Void_0",
			"giw", "ttd", "tte", "ttf", "tti", "gip");

		// Native UI screen object names from CityUI / sessionUI scene assets
		// (CityHire/Market/ItemsMarket/ArtifactChanger/Tavern-HeroBuy).
		internal const string BuildingViewPanelCanvasName = "BUILDING VIEW PANEL";
		internal const string HireViewPanelCanvasName = "HIRE VIEW PANEL";
		internal const string UpgradeUnitPanelCanvasName = "UPGRADE UNIT PANEL";
		internal const string MarketViewPanelCanvasName = "MARKET VIEW";
		internal const string ItemMarketPanelCanvasName = "CanvasItemMarket";
		internal const string ArtifactChangerPanelCanvasName = "ArtifactChanger";
		// Tavern nav tab opens Hex.Session.UI.BhHeroBuySession; canvas lives in sessionUI as CanvasHeroBuying.
		internal const string HeroBuyPanelCanvasName = "CanvasHeroBuying";

		internal static readonly MethodSymbol MarketUiShown = new(
			"release.town.marketUi.shown",
			"Method_Public_Virtual_Void_0",
			"giw", "gip");

		internal static readonly MethodSymbol ItemMarketUiShown = new(
			"release.town.itemMarketUi.shown",
			"Method_Public_Virtual_Void_0",
			"giw", "gip");

		internal static readonly MethodSymbol ArtifactChangerUiShown = new(
			"release.town.artifactChangerUi.shown",
			"Method_Public_Virtual_Void_0",
			"giw", "gip");

		internal static readonly MethodSymbol TavernUiShown = new(
			"release.town.tavernUi.shown",
			"Method_Public_Virtual_Void_0",
			"giw", "gip", "giz", "hmh");

		internal static readonly MethodSymbol TooltipUnitsViewBind = new(
			"release.town.tooltipUnits.bind",
			"tnh", "tlu");

		internal static readonly MethodSymbol HireUnitItemRefresh = new(
			"release.town.hireUnitItem.refresh",
			"ttx", "tty", "ttz");

		internal static readonly MethodSymbol HireUnitItemModelList = new(
			"release.town.hireUnitItem.modelList",
			"tuc");

		internal static readonly MethodSymbol HireUnitItemModelOut = new(
			"release.town.hireUnitItem.modelOut",
			"tue");

		internal static readonly MethodSymbol CitySpecialRefresh = new(
			"release.town.citySpecial.refresh",
			"ube");

		internal static readonly string[] CitySpecialRecruitmentItemLists =
			{ "items", "itemsLow4", "itemsLow3", "bzkd" };

		internal static bool IsCitySpecialTopRecruitmentItemList(string fieldName)
		{
			return string.Equals(fieldName, "items", StringComparison.Ordinal)
			       || string.Equals(fieldName, "bzkd", StringComparison.Ordinal);
		}

		internal static bool IsCitySpecialLowRecruitmentItemList(string fieldName)
		{
			return IsCitySpecialLow3RecruitmentItemList(fieldName)
			       || IsCitySpecialLow4RecruitmentItemList(fieldName);
		}

		internal static bool IsCitySpecialLow3RecruitmentItemList(string fieldName)
		{
			return string.Equals(fieldName, "itemsLow3", StringComparison.Ordinal);
		}

		internal static bool IsCitySpecialLow4RecruitmentItemList(string fieldName)
		{
			return string.Equals(fieldName, "itemsLow4", StringComparison.Ordinal);
		}

		internal static readonly MethodSymbol HireIncrementItemBind = new(
			"release.town.hireIncrementItem.bind",
			"uau");

		internal static readonly MethodSymbol HireIncrementItemSprite = new(
			"release.town.hireIncrementItem.sprite",
			"uav");

		internal static readonly MethodSymbol HeroStatRewardShow = new(
			"release.town.heroStatReward.show",
			"giw");

		internal static readonly MethodSymbol HeroStatRewardHideOrApply = new(
			"release.town.heroStatReward.hideOrApply",
			"hly");

		internal static readonly MethodSymbol SimulatedBattleResultRefresh = new(
			"release.town.simulatedBattle.resultRefresh",
			"Update", "OnHide", "Hide", "OnApplyBtn", "OnFakeWin",
			"vqj", "vqk", "vql", "vqm", "vqn", "vqo", "vqp", "vqq", "vqr", "vqs",
			"vqt", "vqu", "vqv", "vqw", "vqx", "vqy", "vqz", "vra", "vrb", "vrc",
			"vrd", "vre", "vrf", "vrg", "vrh");

		internal static readonly string[] SimulatedBattleArmyListFields =
			{ "armyLeft", "armyRight" };

		internal static readonly string[] TransferSideUnitsFields =
			{ "units" };

		internal static readonly string[] TransferUnitConfigSidFields =
			{ "configSid", "sid" };

		internal static readonly FieldSymbol BuildingViewModel = new(
			"release.town.buildingView.model",
			"NativeFieldInfoPtr_bzdg",
			"bzdg");

		internal static readonly string[] BuildingViewModelFields =
			{ "field_Private_ObjectPublicBuObcdStObcdcnInBocnUnique_0", "bzfs", "bzdg" };

		internal static readonly FieldSymbol[] BuildingViewLevelIntFields =
		{
			new("release.town.buildingView.level.bzdd", "NativeFieldInfoPtr_bzdd", "bzdd"),
			new("release.town.buildingView.level.bzde", "NativeFieldInfoPtr_bzde", "bzde"),
			new("release.town.buildingView.level.bzdi", "NativeFieldInfoPtr_bzdi", "bzdi"),
			new("release.town.buildingView.level.bzdo", "NativeFieldInfoPtr_bzdo", "bzdo"),
			new("release.town.buildingView.level.bzdp", "NativeFieldInfoPtr_bzdp", "bzdp"),
			new("release.town.buildingView.level.bzds", "NativeFieldInfoPtr_bzds", "bzds"),
			new("release.town.buildingView.level.bzan", "NativeFieldInfoPtr_bzan", "bzan"),
			new("release.town.buildingView.level.bzao", "NativeFieldInfoPtr_bzao", "bzao"),
			new("release.town.buildingView.level.bzas", "NativeFieldInfoPtr_bzas", "bzas"),
			new("release.town.buildingView.level.cnej", "NativeFieldInfoPtr_cnej", "cnej"),
			new("release.town.buildingView.level.cnek", "NativeFieldInfoPtr_cnek", "cnek"),
			new("release.town.buildingView.level.cnel", "NativeFieldInfoPtr_cnel", "cnel")
		};

		internal static readonly string[] BuildingViewFieldOnlyMembers =
		{
			"bzfs", "bzft", "bzfu",
			"bzdg", "bzdh", "bzar", "bzdd", "bzde", "bzdi", "bzdo", "bzdp", "bzds",
			"byzd", "bzbm", "bzbl", "bzbq",
			"bzan", "bzao", "bzas",
			"cnej", "cnek", "cnel", "cnga"
		};

		internal static readonly string[] BuildingViewSidFields =
			{ "field_Private_String_0", "bzft", "bzar" };

		internal static bool IsBuildingViewFieldOnlyMember(string name)
		{
			if (string.IsNullOrEmpty(name))
				return false;
			if (string.Equals(name, BuildingViewModel.FieldName, StringComparison.Ordinal))
				return true;
			for (var i = 0; i < BuildingViewFieldOnlyMembers.Length; i++)
			{
				if (string.Equals(name, BuildingViewFieldOnlyMembers[i], StringComparison.Ordinal))
					return true;
			}
			return false;
		}

		internal static readonly FieldSymbol BuildingSessionRoot = new(
			"release.town.buildingSession.root",
			"NativeFieldInfoPtr_root",
			"root");

		internal static readonly FieldSymbol BuildingSessionNavigation = new(
			"release.town.buildingSession.navigation",
			"NativeFieldInfoPtr_navigation",
			"navigation");

		internal static readonly FieldSymbol BuildingSessionExitButton = new(
			"release.town.buildingSession.exitButton",
			"NativeFieldInfoPtr_exitButton",
			"exitButton");

		internal static readonly FieldSymbol BuildingSessionArrowsCg = new(
			"release.town.buildingSession.arrowsCg",
			"NativeFieldInfoPtr_arrowsCg",
			"arrowsCg");

		internal static readonly FieldSymbol BuildingSessionAllViews = new(
			"release.town.buildingSession.allViews",
			"NativeFieldInfoPtr_buildingsUIs",
			"buildingsUIs");

		internal static readonly FieldSymbol BuildingSessionCurrentViews = new(
			"release.town.buildingSession.currentViews",
			"NativeFieldInfoPtr_field_Private_List_1_BhBuildingView_0",
			"field_Private_List_1_BhBuildingView_0");

		internal static readonly FieldSymbol BuildingSessionCurrentViewsOld = new(
			"release.town.buildingSession.currentViews.old",
			"NativeFieldInfoPtr_bzcp",
			"bzcp");

		internal static readonly FieldSymbol BuildingSessionViewLookup = new(
			"release.town.buildingSession.viewLookup",
			"NativeFieldInfoPtr_field_Private_Dictionary_2_String_BhBuildingView_0",
			"field_Private_Dictionary_2_String_BhBuildingView_0");

		internal static readonly FieldSymbol BuildingSessionViewLookupOld = new(
			"release.town.buildingSession.viewLookup.old",
			"NativeFieldInfoPtr_bzcq",
			"bzcq");

		internal static readonly FieldSymbol CitySessionBuildingSession = new(
			"release.town.citySession.buildingSession",
			"NativeFieldInfoPtr_buildingSession",
			"buildingSession");

		internal static readonly FieldSymbol CitySessionStaticCurrent = new(
			"release.town.citySession.current",
			"NativeFieldInfoPtr_field_Public_Static_BhCityUISession_0",
			"field_Public_Static_BhCityUISession_0");

		internal static readonly FieldSymbol CitySessionCityWrapper = new(
			"release.town.citySession.cityWrapper",
			"NativeFieldInfoPtr_field_Private_Object1PublicObInObcjcoObcjInObcjUnique_0",
			"field_Private_Object1PublicObInObcjcoObcjInObcjUnique_0");

		internal static readonly string[] CitySessionCityWrapperFields =
			{ "cityWrapper", "field_Private_Object1PublicObInObcjcoObcjInObcjUnique_0", "bzlr", "field_Public_Object_0", "field_Private_Object_0", "bzjf", "bynh", "bzdm" };

		internal static readonly FieldSymbol BuildingSessionCityWrapper = new(
			"release.town.buildingSession.cityWrapper",
			"NativeFieldInfoPtr_field_Private_Object1PublicObInObcjcoObcjInObcjUnique_0",
			"field_Private_Object1PublicObInObcjcoObcjInObcjUnique_0");

		internal static readonly FieldSymbol BuildingViewCityWrapper = new(
			"release.town.buildingView.cityWrapper",
			"NativeFieldInfoPtr_field_Private_Object1PublicObInObcjcoObcjInObcjUnique_0",
			"field_Private_Object1PublicObInObcjcoObcjInObcjUnique_0");

		internal static readonly string[] BuildingViewCityWrapperFields =
			{ "field_Private_Object1PublicObInObcjcoObcjInObcjUnique_0", "bzfr" };

		internal static readonly FieldSymbol HireViewNavigation = new(
			"release.town.hireView.navigation",
			"NativeFieldInfoPtr_navigation",
			"navigation");

		internal static readonly string[] UpgradeViewBodyComponentFields =
			{ "cross", "updateOrConvertButton" };

		internal static readonly string[] RecruitmentSelectionSidListFields =
			{ "cmea" };

		internal static readonly string[] RecruitmentSelectionSidListMethods =
			{ "htw" };

		internal static readonly FieldSymbol HireViewDayPanel = new(
			"release.town.hireView.dayPanel",
			"NativeFieldInfoPtr_dayPanel",
			"dayPanel");

		internal static readonly FieldSymbol CityWrapperConfig = new(
			"release.town.cityWrapper.config",
			"NativeFieldInfoPtr__cjgu_k__BackingField",
			"_cjgu_k__BackingField");

		internal static readonly FieldSymbol CityWrapperCity = new(
			"release.town.cityWrapper.city",
			"NativeFieldInfoPtr__cjgv_k__BackingField",
			"_cjgv_k__BackingField");

		internal static readonly FieldSymbol ObjCityConfigFraction = new(
			"release.town.objCityConfig.fraction",
			"NativeFieldInfoPtr_fraction",
			"fraction");

		internal static readonly FieldSymbol FbiConfig = new(
			"release.town.fbi.config",
			"NativeFieldInfoPtr__cjdz_k__BackingField",
			"<cjdz>k__BackingField");

		internal static readonly FieldSymbol FbiCity = new(
			"release.town.fbi.city",
			"NativeFieldInfoPtr__cjea_k__BackingField",
			"<cjea>k__BackingField");
	}

	internal static partial class LawIcon
	{
		internal static readonly MethodSymbol FractionLawViewBind = new(
			"release.lawIcon.fractionLawView.bind",
			"zgh", "Method_Public_Void_Object1PublicSiObFrObccSiLiObcc1Unique_ObjectPublicDaccObLicc1QuObSt1Unique_0");

		internal static readonly MethodSymbol FractionLawViewRefresh = new(
			"release.lawIcon.fractionLawView.refresh",
			"zgj", "Method_Public_Void_0");

		internal static readonly string[] LawConfigFields =
			{
				"ccep", "chvf", "cnpl", "cobp",
				"field_Private_DataFractionLaw_0",
				"field_Private_FractionLawConfig_0",
				"cccd", "chsk", "ccak", "chrp", "ccah", "cnlk", "cnxn", "chrm", "cnkk", "cbzj", "cnwn", "chqp", "cnis", "cnuv", "cbxu", "chpa", "cgsu", "config", "lawConfig", "data", "ccbx", "cmrv"
			};

		internal static readonly string[] LawConfigGetters =
			{
				"xow", "bfwo", "get_cnpl", "get_cobp", "Method_Public_get_FractionLawConfig_0",
				"xno", "bfuq", "get_cnmm", "get_cnyp", "xmr", "bftn", "xmo", "get_cnlk", "bftm", "get_cnxn", "xlu", "bfsq", "get_cnkk", "get_cnwn", "xku", "bfrn", "get_cnis", "get_cnuv", "bfbj", "get_cmys", "get_cmrv", "yog"
			};

		internal static readonly string[] LawIconDiagnosticGetters =
			{ "xow", "bfwo", "Method_Public_get_FractionLawConfig_0", "xno", "bfuq", "xmr", "bftn", "xmo", "bftm", "xku", "bfrn", "bfbj", "yog" };
	}

	internal static partial class SmoothOpening
	{
		internal static readonly string[] OpenTimeTrackerTypeHints =
			{
				// June 24 runtime map: ddd resolves to this generated runtime type.
				// ModActions.GetHexType performs exact assembly lookup, so alias-only
				// hints do not register this hook in the live game.
				"ObjectPublicSicbInStcbOpSiETStBoUnique",
				"ddd",
				"ddb"
			};

		internal static readonly string[] OpeningFacadeTypeHints =
			{
				// June 24 runtime map: ddh resolves to this generated runtime type.
				"ObjectPublicAbstractSealedIncbUnique",
				"ddh"
			};

		internal static readonly MethodSymbol CityFrameCount = new(
			"smoothOpening.city.frameCount",
			// June 24 runtime map: current Golden Era ddd exposes generated
			// EType/string int open-time readers; keep older decomp names as drift
			// tolerance, but generated names are the validated active route.
			"Method_Public_Int32_EType_String_0",
			"Method_Public_Int32_EType_String_PDM_0",
			"Method_Public_Int32_EType_String_PDM_1",
			"Method_Public_Int32_EType_String_PDM_2",
			"car", "edj", "ekm", "wnr",
			"hg", "esd", "oam", "wmj",
			"beh", "wkq", "ioq", "jhi", "fmy");

		internal static readonly MethodSymbol OpeningFrameCount = new(
			"smoothOpening.facade.frameCount",
			// June 24 runtime map: current Golden Era ddh exposes generated
			// static EType/string int facade wrappers; keep older decomp names as
			// drift tolerance, but generated names are the validated active route.
			"Method_Private_Static_Int32_EType_String_0",
			"Method_Private_Static_Int32_EType_String_PDM_0",
			"Method_Private_Static_Int32_EType_String_PDM_1",
			"Method_Private_Static_Int32_EType_String_PDM_2",
			"Method_Private_Static_Int32_EType_String_PDM_3",
			"bra", "gwx", "kjz", "oqv", "wog",
			"emz", "wmy", "jof", "hkb");
	}

	internal static partial class ImportVisuals
	{
		internal static readonly MethodSymbol ResManagerObjectLoader = new(
			"importVisuals.resManager.objectLoader",
			"bmts", "bmsl", "bmsi", "bmfq", "Get",
			"Method_Private_Object_String_0");

		/// <summary>
		/// Il2CppInterop nested store for the inflated public static <c>ResManager.Get&lt;GameObject&gt;(string)</c>
		/// (deobf <c>bmvo</c>, Mono <c>Get&lt;T&gt;</c>): bundle dictionary first, then <c>Resources.Load</c>.
		/// Live Hex.ResManager.dll name. Do not Invoke the Harmony DMD; read Pointer and
		/// <c>il2cpp_runtime_invoke</c> from LateUpdate only.
		/// Never load through <c>MethodInfoStoreGeneric_Method_Private_Object_String_0`1</c> (<c>bmvq</c>, Mono
		/// <c>GetAssetFromBundle&lt;T&gt;</c>): it only searches loaded AssetBundles, and Golden Era ships every
		/// vanilla prefab in resources.assets, so it returns null for all of them (2026-09-26 mesh-FX miss).
		/// </summary>
		internal const string ResManagerStaticGetGenericStore =
			"MethodInfoStoreGeneric_Method_Public_Static_a_String_0`1";

		internal static readonly string[] BattlePoolTypeHints =
			{ "eam", "eai", "dzk" };

		/// <summary>
		/// Third out-param of the 3-arg battle-pool loader (live <c>eat.bbmh(string, out GameObject, out bep)</c>).
		/// Live Golden Era <c>bep</c> = <c>ObjectPublicGabsLi1ReMabsLi1InUnique</c>, the drawer's renderer/material
		/// set with <c>ctor(GameObject, bool, string)</c>; vanilla builds it as <c>new bep(go, false, null)</c>
		/// (<c>eat+ear.bbmc</c>) and <c>eck.Init</c> stores it in <c>eck.cfdq</c>, which <c>eck.bcah</c> dereferences
		/// without a null check. Never hint <c>bei</c>: on live that is an unrelated MonoBehaviour
		/// (<c>MonoBehaviourPublicStbsCaRebsLi1RabsNuUnique</c>), which made the 3-arg loader look 2-arg,
		/// left <c>eck.cfdq</c> null for every synthetic unit, and softlocked the battle-result step (2026-09-27).
		/// Registration verifies this type against the loader signature and fails closed on mismatch.
		/// </summary>
		internal static readonly string[] BattlePoolMetadataTypeHints =
			{ "ObjectPublicGabsLi1ReMabsLi1InUnique", "bep" };

		internal static readonly MethodSymbol BattlePoolLoader = new(
			"importVisuals.battlePool.loader",
			"uu", "dvu", "jyt", "bbgy", "dia", "bbjs", "cry", "bath");

		internal static readonly MethodSymbol HeroHudPanelRefresh = new(
			"importVisuals.armyStrip.heroHud.refresh",
			"gix", "vsl", "vsh", "Method_Public_Void_0");

		// Audit A7 (2026-09-27): "vso" is stale on Golden Era. By name it bound
		// Method_Public_Void_ObjectPublicVo2_PDM_0, whose parameter is obfuscator junk type ye
		// (ObjectPublicVo2), so every refresh logged "Data.Hero unresolved from session hero type
		// ObjectPublicVo2". The only BhHeroHUDPanel void method taking the session hero type
		// (HeroMap.SessionHeroTypeHints) is native vty = the interop name below. The caller also
		// requires that parameter type, and skips with a log otherwise.
		internal static readonly MethodSymbol HeroHudPanelHeroArgRefresh = new(
			"importVisuals.armyStrip.heroHud.heroArgRefresh",
			"Method_Private_Void_ObjectPublicHeObInObciSiObVeSeObUnique_0",
			"vty");

		internal static readonly MethodSymbol CityHeroWithPartyRefresh = new(
			"importVisuals.armyStrip.cityHeroWithParty.refresh",
			"Method_Public_Void_ObjectPublicInDaObETccLiIncc1cnUnique_PDM_0",
			"uag", "uah", "uai", "uaj", "uak");

		internal static readonly MethodSymbol CityHeroesGroupRefresh = new(
			"importVisuals.armyStrip.cityHeroesGroup.refresh",
			"txq", "txr", "txs", "txv", "txw", "txy", "txz", "tya", "tyb", "tyd", "tye", "tyj", "tyl", "tym");

		internal static readonly string[] CityHeroesGroupViewFields =
			{ "heroesWithParty" };

		internal static readonly string[] CityHeroWithPartyTooltipFields =
			{ "heroView", "cnhf" };

		internal static readonly string[] HeroHudPanelHeroViewFields =
			{ "heroView", "cnhf" };

		internal static readonly string[] CityHeroWithPartySessionHeroFields =
			{ "field_Private_ObjectPublicHeObInObciSiObVeSeObUnique_0", "bzlt", "bzjh", "bzhs", "bzgr", "bzdo" };

		internal static readonly string[] CityHeroWithPartyCanvasGroupFields =
			{ "cg" };

		internal static readonly string[] TooltipHeroItemPortraitFields =
			{ "heroFace" };

		internal static readonly string[] TooltipHeroItemSessionHeroFields =
			{ "field_Private_ObjectPublicHeObInObciSiObVeSeObUnique_0", "byop", "bynf", "bymf", "byjc" };

		internal static readonly string[] SessionHeroWrapperHeroFields =
			{ "<cice>k__BackingField", "_cice_k__BackingField", "cice", "coaa", "<cibj>k__BackingField", "_cibj_k__BackingField", "cibj", "<ciaj>k__BackingField", "_ciaj_k__BackingField", "<chxe>k__BackingField", "_chxe_k__BackingField", "ciaj", "chxe",
			  "_ciez_k__BackingField", "<ciez>k__BackingField", "ciez" };

		internal static readonly string[] SessionLogicHeroDataFields =
			{ "_ccez_k__BackingField", "<ccez>k__BackingField", "ccez" };

		internal static readonly string[] SessionHeroConfigFields =
			{ "configSid", "chsm", "bfuz", "chqr", "chno", "<bqep>k__BackingField", "_bqep_k__BackingField", "bqep",
			  "field_Public_String_0", "field_Public_String_1", "field_Private_String_0", "field_Public_HeroConfig_0", "field_Private_HeroConfig_0" };

		internal static readonly MethodSymbol SummaryCardHeroBind = new(
			"importVisuals.armyStrip.summaryCard.heroBind",
			"lwy", "lxc", "lwk", "lwo", "lwh", "lwi", "Method_Public_Void_HeroConfig_String_0");

		internal static readonly string[] HeroPortraitImageFields =
			{ "heroFace", "heroIcon", "pic", "icon", "portrait" };

		internal static readonly string[] SummaryCardRandomPortraitFields =
			{ "randomPortrait" };

		internal static readonly string[] UnitUiDataUnitMembers =
			{ "cazx", "cnkf", "vxu", "cnie", "vvf", "cavr", "cnev", "vuk", "cmmf" };

		internal static readonly string[] HeroHudPanelUnitSlotsMembers =
			{ "slots", "vse", "cnkc", "vrk", "cmkl" };

		internal static readonly string[] UnitSlotsListMembers =
			{ "slots", "cbew", "cnks", "cngz", "wcq", "cbap", "cnfi", "wbv", "cmlb" };
	}

	internal static partial class CustomGame
	{
		internal static readonly string[] UnitSlotTypeHints =
			{ "Hex.Pick.BhUnitSlot", "BhUnitSlot" };

		internal static readonly MethodSymbol UnitSlotBind = new(
			"customGame.unitSlot.bind",
			"lxd", "Method_Public_Void_Mode_String_Int32_Int32_0");

		internal static readonly MethodSymbol FactionDetailsBind = new(
			"customGame.factionDetails.bind",
			"hpj", "hpc", "hov", "Method_Public_Void_FractionConfig_0");

		internal static readonly MethodSymbol FactionDetailsRefresh = new(
			"customGame.factionDetails.refresh",
			"Init", "hpk", "hpd", "Method_Public_Void_Boolean_Single_Single_0");

		internal static readonly string[] FactionDetailsConfigFields =
			{ "bpkw" };

		internal static readonly MethodSymbol FactionSelectButtonBind = new(
			"customGame.factionSelectButton.bind",
			"hpm", "hpf", "hoy", "Method_Public_Void_FractionConfig_Action_Action_0");

		internal static readonly MethodSymbol FactionSelectButtonRefresh = new(
			"customGame.factionSelectButton.refresh",
			"hpn", "hoz", "Method_Public_Void_FractionConfig_Action_Action_0");

		internal static readonly (string Name, int ParameterCount)[] QuickStartRectLayoutMethods =
		{
			("ldm", 1),
			("ldl", 2),
			("ldk", 2),
			("lcl", 1),
			("lck", 2),
			("lcj", 2),
			("Method_Private_Void_Boolean_RectTransform_0", 2),
			("Method_Private_Void_Boolean_RectTransform_1", 2),
			("Method_Private_Void_RectTransform_0", 1),
		};

		internal static readonly MethodSymbol HeroSelectButtonBind = new(
			"customGame.heroSelectButton.bind",
			"hpt", "hpm", "hpf", "Method_Public_Void_HeroConfig_Action_Action_0");

		internal static readonly MethodSymbol HeroDetailsBind = new(
			"customGame.heroDetails.bind",
			"ltp", "lug", "ltf", "Method_Public_Void_HeroConfig_0");

		internal static readonly string[] SkillViewTypeHints =
			{ "Hex.Pick.BhSkillView" };

		internal static readonly MethodSymbol SkillViewSkillBind = new(
			"customGame.skillView.bindSkill",
			"lww", "Method_Public_Void_SkillParameter_ObjectPublicAbbwObBubwObItUnbwObUnique_0");

		internal static readonly MethodSymbol BhIconSetSprite = new(
			"customGame.bhIcon.setSprite",
			"suj", "Method_Public_Void_Sprite_0");

		internal static readonly string[] SkillParameterIconFields =
			{ "icon" };

		internal static readonly string[] SkillViewSkillIconFields =
			{ "skillIcon" };

		internal static readonly string[] HeroSpecializationObjectFields =
			{ "specialization", "specializationSid", "specializationId" };

		internal static readonly string[] HeroSpecializationIconFields =
			{ "icon", "cmyj" };

		internal static readonly string[] HeroSpecializationSidFields =
			{ "id", "sid", "name", "title" };

		internal static readonly string[] HeroSpecializationConfigSidFields =
			{ "specializationSid", "specializationId" };

		internal static readonly string[] HeroDetailsSpecializationIconFields =
			{ "specializationIcon" };

		internal static readonly string[] SummaryCardSpecializationIconFields =
			{ "specializationIcon" };
	}

	/// <summary>
	/// Native early-access bug report (docs/mod_bug_reporting.md). Every native report, the form's Submit and the
	/// multiplayer-desync auto report alike, leaves through <c>HexAnalytics.SendReport</c> (Hex.Shared), which hands
	/// the payload to the MagicOnion <c>IAnalyticsService</c> client. The form itself is
	/// <c>Hex.UI.Reports.BhBugReportScreen</c>; <c>Show(bool exitToMainMenu)</c> is its public opener (called by
	/// <c>BhSessionBugButton.OnClicked</c> and <c>BhNetBrokenSync.OnBtnInfo</c>). Readable names in the live interop,
	/// statically pinned against GameAssembly.dll 2026-06-04 / interop assembly-hash 9be885c8051fab859372900caf63217c.
	/// </summary>
	internal static partial class ModBugReporting
	{
		internal static readonly string[] SendReportOwnerTypeHints = { "Hex.SharedLibrary.HexAnalytics" };
		internal const string SendReportMethodName = "SendReport";
		// title, description, contact, category, tag, logs, additionalLogs, screenshot, gameId
		internal const int SendReportParameterCount = 9;

		internal static readonly string[] ScreenTypeHints = { "Hex.UI.Reports.BhBugReportScreen" };
		internal const string ScreenShowMethodName = "Show";
		internal const int ScreenShowParameterCount = 1;
		internal const string ScreenCloseMethodName = "Close";

		// Current-only UI route, pinned to build 25672315's native vbc -> cul state machine.
		internal const string CurrentSubmitHandlerNativeName = "vbc";
		internal const string CurrentSubmitHandlerMethodInfoFieldName = "NativeMethodInfoPtr_Method_Private_Void_PDM_0";
		internal static readonly MethodSymbol CurrentSubmitHandler = new(
			"bugReport.submit.handler", "Method_Private_Void_PDM_0");
		internal const string CurrentSubmitIteratorObfuscatedName = "Hex.UI.Reports.BhBugReportScreen+cul";
		internal const string CurrentSubmitIteratorManagedTypeFullName =
			"Hex.UI.Reports.BhBugReportScreen+ObjectNPrivateSealedIEnumerator1ObjectIEnumeratorIDisposableIncdObBhcdStByStDicdUnique";
		internal static readonly MethodSymbol CurrentSubmitIteratorMoveNext = new(
			"bugReport.submit.iterator.moveNext", "MoveNext");
		internal static readonly MethodSymbol CurrentScreenClose = new(
			"bugReport.screen.close", "Close");
		internal static readonly FieldSymbol CurrentSubmitIteratorState = new(
			"bugReport.submit.iterator.state", "NativeFieldInfoPtr_field_Private_Int32_0", "field_Private_Int32_0");
		internal static readonly FieldSymbol CurrentSubmitIteratorOwner = new(
			"bugReport.submit.iterator.owner", "NativeFieldInfoPtr_field_Public_BhBugReportScreen_0", "field_Public_BhBugReportScreen_0");
		internal static readonly FieldSymbol[] CurrentSubmitIteratorStrings =
		{
			new("bugReport.submit.iterator.string0", "NativeFieldInfoPtr_field_Private_String_0", "field_Private_String_0"),
			new("bugReport.submit.iterator.string1", "NativeFieldInfoPtr_field_Private_String_1", "field_Private_String_1"),
			new("bugReport.submit.iterator.string2", "NativeFieldInfoPtr_field_Private_String_2", "field_Private_String_2"),
			new("bugReport.submit.iterator.string3", "NativeFieldInfoPtr_field_Private_String_3", "field_Private_String_3"),
			new("bugReport.submit.iterator.string4", "NativeFieldInfoPtr_field_Private_String_4", "field_Private_String_4"),
		};
		internal static readonly FieldSymbol CurrentSubmitIteratorNativeLog = new(
			"bugReport.submit.iterator.nativeLog",
			"NativeFieldInfoPtr_field_Private_Il2CppStructArray_1_Byte_0",
			"field_Private_Il2CppStructArray_1_Byte_0");
		internal static readonly FieldSymbol CurrentSubmitIteratorAttachments = new(
			"bugReport.submit.iterator.attachments",
			"NativeFieldInfoPtr_field_Private_Dictionary_2_String_Il2CppStructArray_1_Byte_0",
			"field_Private_Dictionary_2_String_Il2CppStructArray_1_Byte_0");

		// Desync auto-report launcher (starts the static capture+send coroutine; no form is shown).
		internal static readonly MethodSymbol ScreenStaticAutoSend = new(
			"bugReport.screen.staticAutoSend",
			"Method_Public_Static_Void_Boolean_0");

		// Gameplay telemetry on the same HexAnalytics owner (NativeTelemetryBlock).
		// void SendGameMetrics(IEnumerable<GameMetric>), from Code.Network.MetricsCollector.
		internal const string SendGameMetricsMethodName = "SendGameMetrics";
		internal const int SendGameMetricsParameterCount = 1;
		// Task<bool> SendTable(List<ITable>), from Code.Network.AnalyticsCollector's row sender. The caller re-queues
		// the rows when the task result is false and drops them when it is true.
		internal const string SendTableMethodName = "SendTable";
		internal const int SendTableParameterCount = 1;
	}

	internal static partial class MainMenu
	{
		internal static readonly string NativeQuickStartOpenNativeName = "pdj";
		internal static readonly string NativeQuickStartOpenHandler = "Method_Private_Void_Boolean_0";
		internal const bool NativeQuickStartOpenHandlerArgument = true;
		internal static readonly string[] CampaignButtonFields = { "campaignButton" };
		internal static readonly string[] QuickStartButtonFields = { "quickStartButton" };
		internal static readonly string[] SkirmishButtonFields = { "skirmishButton" };
		internal static readonly string[] StartNewSkirmishButtonFields = { "startNewSkirmishButton" };
		internal static readonly string[] LoadSkirmishButtonFields = { "loadSkirmishButton" };
		internal static readonly string[] HotseatButtonFields = { "hotseatButton" };
	}

	internal static partial class SessionLoader
	{
		internal static readonly MethodSymbol StartWithStartInfo = new(
			"session.loader.start.startInfo",
			"Method_Public_Void_StartInfo_0",
			"Method_Public_Void_StartInfo_1");
	}

	internal static partial class HeroProfile
	{
		internal static readonly string[] ProfileWindowTypeHints =
			{ "Hex.Session.HeroProfile.BhHeroProfileWindow", "Hex.Session.UI.BhHeroProfileWindow" };

		internal static readonly MethodSymbol DataViewInit = new(
			"heroProfile.dataView.init",
			"Init");

		internal static readonly MethodSymbol DataViewRefresh = new(
			"heroProfile.dataView.refresh",
			"zfi", "zfj", "zfm", "zfn", "zfo", "hjd",
			"zwe", "zwf", "zwi", "zwj", "zwk", "hly",
			"zuj", "zuk", "zun", "zvf", "zvg", "zvh", "zvi", "zvj", "zvk", "zvl", "zvm", "ztj", "ztk", "ztn", "zto", "ztp");

		internal static readonly MethodSymbol PortraitViewBind = new(
			"heroProfile.portraitView.bind",
			"zxx", "zya", "zwm", "zwp", "zvo", "zvr", "ztr", "ztu");

		internal static readonly MethodSymbol ProfileWindowShown = new(
			"heroProfile.window.shown",
			"giw", "gip");

		internal static readonly MethodSymbol SpecializationViewBind = new(
			"heroProfile.specializationView.bind",
			"zvr", "zvs", "zxm", "zxn", "zur", "zus", "zwo", "zwp");

		internal static readonly MethodSymbol SkillViewBind = new(
			"heroProfile.skillView.bind",
			"zwv", "zua", "zvx");

		internal static readonly MethodSymbol SubSkillViewBind = new(
			"heroProfile.subSkillView.bind",
			"zxt", "zuy", "zwv");

		internal static readonly string[] SpecializationConfigFields =
			{ "cduv", "cdqm", "cdtc", "cdsb", "bwck", "cmtl", "config", "specializationConfig" };

		internal static readonly string[] SpecializationPayloadFields =
			{ "cdsc", "cduw", "cdqn", "cdtd", "payload", "heroProfilePayload", "bwdy", "bwdz", "cmvc", "cmvd" };

		internal static readonly string[] SkillRuntimeFields =
			{ "field_Public_ObjectPublicHeccDiHecc2InLi1ObUnique_0", "cdum", "bwfs", "cdqd", "cdst", "cdrs", "bwbu", "skill", "heroSkill" };

		internal static readonly string[] SkillPayloadFields =
			{ "field_Private_ObjectPublicAbbwObBubwObItUnbwObUnique_0", "cdun", "cdqe", "cdsu", "cdrt", "payload", "heroProfilePayload" };

		internal static readonly string[] SkillConfigFields =
			{ "cnnz", "chso", "cnyx", "cnkf", "ccdd", "cnna", "cnxy", "config", "skillConfig", "chrt" };

		internal static readonly string[] SkillConfigGetters =
			{ "Method_Public_get_SkillConfig_0", "xya", "bfwc", "get_cnnz", "get_cnyx", "xvg", "xxg", "bfuz", "rzs", "get_cnkf", "get_cnna", "get_cnxy" };

		internal static readonly string[] SkillDataFields =
			{ "ccgx", "data", "heroSkillData" };

		internal static readonly string[] SkillLevelFields =
			{ "Method_Public_get_Int32_0", "cnoa", "level" };

		internal static readonly string[] SubSkillRuntimeFields =
			{ "cdvf", "bwft", "cdqw", "cdtm", "cdsl", "bwbv", "subSkill", "heroSubSkill" };

		internal static readonly string[] SubSkillPayloadFields =
			{ "cdvg", "cdqx", "cdtn", "cdsm", "payload", "heroProfilePayload" };

		internal static readonly string[] SubSkillConfigFields =
			{ "cnok", "chsr", "cnyz", "cnkq", "cnnl", "config", "subSkillConfig", "ccfp" };

		internal static readonly string[] SubSkillConfigGetters =
			{ "xzh", "bfxp", "get_cnok", "get_cnyz", "xwm", "xyo", "get_cnkq", "get_cnnl" };

		internal static readonly MethodSymbol HeroSelectButtonBind = new(
			"heroPortrait.heroSelectButton.bind",
			"hpt", "hpm");

		internal static readonly MethodSymbol TooltipHeroItemBind = new(
			"heroPortrait.tooltipHeroItem.bind",
			"tcj", "tck", "tcl", "tco", "tcb", "tcc", "tcd", "tcg",
			"Method_Public_Void_Hero_Boolean_Boolean_0",
			"Method_Public_Void_Hero_Boolean_0");

		internal static readonly MethodSymbol TooltipHeroItemWrapperBind = new(
			"heroPortrait.tooltipHeroItem.wrapperBind",
			"Method_Public_Void_ObjectPublicHeObInObciSiObVeSeObUnique_Boolean_0",
			"Method_Public_Void_ObjectPublicHeObInObciSiObVeSeObUnique_Boolean_1");

		internal static readonly MethodSymbol TooltipHeroItemRefresh = new(
			"heroPortrait.tooltipHeroItem.refresh",
			"LateUpdate");

		internal static readonly MethodSymbol TavernHeroBind = new(
			"heroPortrait.tavernHero.bind",
			"zer");

		internal static readonly MethodSymbol SideHeroInit = new(
			"heroPortrait.sideHero.init",
			"Init");

		// Live Golden Era pin: Method_Private_Void_0 (GameMember shape pick; legacy wcb-wce / May-decomp waj-wak drift).
		internal static readonly MethodSymbol SideHeroRefresh = new(
			"heroPortrait.sideHero.refresh",
			"Method_Private_Void_0", "waj", "wak", "wcb", "wcc", "wcd", "wce");

		internal static readonly string[] SideHeroFields =
			{ "field_Private_ObjectPublicHeObInObciSiObVeSeObUnique_0", "cbda", "cbai", "cbbj", "cayu", "cayt" };

		internal static readonly FieldSymbol SideHeroIcon = new(
			"heroPortrait.sideHero.icon",
			"NativeFieldInfoPtr_heroIcon",
			"heroIcon");

		internal static readonly string[] SideHeroIconFields =
			{ "heroIcon", "field_Private_Image_0", "field_Public_Image_0", "NativeFieldInfoPtr_heroIcon" };

		internal static readonly string[] HeroStateFields =
			{ "ckif", "<ckif>k__BackingField", "_ckif_k__BackingField", "byop", "bzjh", "caww", "cbda", "cdap", "cdpz", "cdrl", "cdro", "ckgi", "<ckgi>k__BackingField", "_ckgi_k__BackingField", "cdsj", "cdsm", "cdsp", "ckhg", "<ckhg>k__BackingField", "_ckhg_k__BackingField", "ckhj", "<ckhj>k__BackingField", "_ckhj_k__BackingField", "bkkj", "bkki", "ccuj", "ccum", "cduf", "cdui", "cdpw" };

		internal static readonly string[] DataViewHeroPortraitFields =
			{ "heroView", "portraitView", "heroPortraitView" };

		internal static readonly string[] ProfileWindowPortraitViewFields =
			{ "portraitView", "heroPortraitView" };

		internal static readonly string[] ProfileWindowDataViewFields =
			{ "heroDataView", "dataView" };

		internal static readonly string[] HeroConfigFields =
			{ "configSid", "sid", "id", "heroSid", "icon", "cnbz", "cnca", "cncb", "cncc", "cncd", "cnce", "cncf", "cmyj", "cnxr" };

		internal static readonly string[] HeroConfigNestedFields =
			{ "ckif", "<ckif>k__BackingField", "_ckif_k__BackingField", "byop", "bzjh", "caww", "cbda", "cdap", "cdpz", "cdrl", "cdro", "bwcl", "cmtm", "ckgi", "<ckgi>k__BackingField", "_ckgi_k__BackingField", "bkkj", "bkki", "ccuj", "ccum", "cduf", "cdui", "cnyt", "<cnyt>k__BackingField", "_cnyt_k__BackingField", "bqdp", "<bqdp>k__BackingField", "_bqdp_k__BackingField", "bqep", "<bqep>k__BackingField", "_bqep_k__BackingField", "bqhv", "chqr", "chsm", "bfuz", "cbzu", "<cbzu>k__BackingField", "_cbyf_k__BackingField", "chpd", "cnva", "chrr", "cbfh", "<cbfh>k__BackingField", "_cbfh_k__BackingField", "cccn", "<cccn>k__BackingField", "_cccn_k__BackingField", "ccau", "<ccau>k__BackingField", "_ccau_k__BackingField", "cice", "<cice>k__BackingField", "_cice_k__BackingField", "coaa", "<coaa>k__BackingField", "_coaa_k__BackingField", "cibj", "<cibj>k__BackingField", "_cibj_k__BackingField", "_ciez_k__BackingField", "<ciez>k__BackingField", "ciez", "_ccez_k__BackingField", "<ccez>k__BackingField", "ccez", "cmyw", "cgsw", "cmgf", "bqax", "cnxr", "cmhu", "cnwr", "chys", "<chys>k__BackingField", "chyt", "<chyt>k__BackingField", "ciaj", "<ciaj>k__BackingField", "_ciaj_k__BackingField", "cnxy", "heroConfig", "config", "hero", "heroView", "cnhf", "bzhs", "bynf", "bzgr", "bymf", "byjc", "cbai", "cbbj", "cavf", "cayv", "cayw", "casp", "caue", "casu", "casv", "cast", "cayt", "cayu", "cayx" };

		internal static readonly string[] HeroConfigGetters =
			{ "rwi", "rwj", "rwk", "rwl", "rwm", "rwn", "rwo", "bfuz", "get_cnyt", "get_cnbz", "get_cnca", "get_cncb", "get_cncc", "get_cncd", "get_cnce", "get_cncf", "bkls", "get_ckif", "ipu", "ivn", "bfsz", "bkjl", "get_bqdp", "get_bqep", "ipx", "get_cmhu", "get_cnwr", "get_ckgi", "bftv", "bftw", "xnq", "xal", "get_cnxr", "bgwj", "emx", "get_chys", "eif", "get_chyt", "xlt", "get_cbyf", "get_cibj", "get_ciaj", "get_cnxy", "get_chpd", "get_cnva", "get_cmyj", "ivd", "ipk", "get_cbfh", "get_cmyw", "get_cgsw", "get_cmeo", "get_bqax", "get_heroConfig", "tyr", "get_cnfd" };
	}

	internal static partial class HeroMap
	{
		internal const string DrawerTypeId = "heroMap.drawer";
		// Keep legacy drawer/visual hints as compatibility hints only; prefer live shape proof before
		// treating any current short name as a concrete hero-map visual.
		internal static readonly string[] DrawerTypeHints = { "esd", "esf", "erw", "erv", "err" };

		internal const string SessionHeroTypeId = "heroMap.sessionHero";
		internal static readonly string[] SessionHeroTypeHints =
			{ "ObjectPublicHeObInObciSiObVeSeObUnique", "etc", "eta" };

		internal static readonly string[] SessionHeroVisualTypeHints =
			{ "ObjectPublicbgVoabgVoVeSibgVoaUnique", "esg", "ese" };

		internal static readonly MethodSymbol RootGameObjectGetter = new(
			"heroMap.drawer.rootGameObject",
			"get__cibn_k__BackingField",
			"Method_Public_get_GameObject_0",
			"bgus", "bgun", "eiq", "bguu", "fsl", "fnd", "cfl",
			"bgwl", "bgws", "gtn", "lah", "ndc", "oee",
			"bgtp", "bgtk", "bgto", "bgtj", "gzd", "bgtq", "hbj", "ein", "bgsn", "bgss", "hug", "bgrd", "bgrk");

		internal static readonly string[] RootGameObjectProperties =
			{ "cibn", "<cibn>k__BackingField", "_cibn_k__BackingField", "chys", "<chys>k__BackingField", "_chys_k__BackingField", "chxu", "<chxu>k__BackingField", "_chxu_k__BackingField", "chts", "<chts>k__BackingField", "_chts_k__BackingField", "chwx", "<chwx>k__BackingField", "_chwx_k__BackingField" };

		internal static readonly string[] HeroConfigFields =
			{ "chzc", "cibx", "field_Private_HeroConfig_0", "chsm", "chye", "chvq", "chuc", "chxh", "heroConfig", "config", "bqax", "cmgf" };

		internal static readonly string[] HeroSidFields =
			{ "configSid" };

		internal static readonly string[] DrawerHeroIdFields =
			{ "chzo", "field_Public_Int32_0", "heroId", "id" };

		internal static readonly string[] DrawerHeroFields =
			{ "chzp", "cick", "field_Private_Hero_0" };

		internal static readonly string[] DrawerSessionHeroFields =
			{ "chzq", "cicl", "field_Private_ObjectPublicHeObInObciSiObVeSeObUnique_0" };

		internal static readonly MethodSymbol HeroConfigGetter = new(
			"heroMap.drawer.heroConfig",
			"bftv", "njr", "ipk", "ivd", "rtn");

		internal static readonly MethodSymbol DrawerRefresh = new(
			"heroMap.drawer.refresh",
			"Method_Public_Virtual_Void_EHeroDrawerRefresh_0",
			"Method_Public_Virtual_Void_EHeroDrawerRefresh_1",
			"bgux", "bguy", "bgwv", "bgww");

		internal static readonly MethodSymbol SessionHeroInit = new(
			"heroMap.sessionHero.init",
			"Init", "fih", "cjd");

		internal static readonly MethodSymbol SessionHeroVisualSetter = new(
			"heroMap.sessionHero.visualSetter",
			"bgzd", "bhbb", "set__cifk_k__BackingField", "Method_Private_set_Void_ObjectPublicbgVoabgVoVeSibgVoaUnique_0");

		internal static readonly MethodSymbol SessionHeroVisualGetter = new(
			"heroMap.sessionHero.visualGetter",
			"Method_Public_get_ObjectPublicbgVoabgVoVeSibgVoaUnique_0", "get__cifk_k__BackingField", "bgzc", "bhba");

		internal static readonly string[] SessionHeroVisualFields =
			{ "<cifk>k__BackingField", "_cifk_k__BackingField", "cifk", "prop_ObjectPublicbgVoabgVoVeSibgVoaUnique_0", "<cifu>k__BackingField", "_cifu_k__BackingField", "cifu", "<cicp>k__BackingField", "_cicp_k__BackingField", "cicp" };

		internal static readonly string[] SessionHeroLogicFields =
			{ "<ciez>k__BackingField", "_ciez_k__BackingField", "ciez", "prop_Hero_0", "<cifh>k__BackingField", "_cifh_k__BackingField", "cifh", "<cice>k__BackingField", "_cice_k__BackingField", "cice" };
	}

	/// <summary>
	/// Framebuffer alpha class for the ReShade HoMM2 shade. Values match VCMI RestyleObjectClass.
	/// Landscape vs visitable comes from ObjectConfig.isInteractable, the same bit
	/// Settings "always highlight interactibles" uses. Not pixel heuristics.
	/// </summary>
	internal static partial class Homm2ShadeObjectClass
	{
		internal const byte LandscapeAlpha = 90;
		internal const byte VisitableAlpha = 180;

		internal const string ObjectConfigIsInteractableId = "homm2.shade.objectConfig.isInteractable";

		internal static readonly string[] ObjectConfigIsInteractableFields =
			{ "isInteractable" };

		internal static readonly MethodSymbol ObjConfigObjectType = new(
			"homm2.shade.objConfig.objectType",
			"rxb",
			"Method_Public_Virtual_New_EObjectType_0",
			"Method_Public_Virtual_EObjectType_0");

		internal static readonly MethodSymbol WorldCameraCamera = new(
			"homm2.shade.worldCamera.camera",
			"hib",
			"Method_Public_get_Camera_0");
	}

	internal static partial class CustomFactionLawRuntime
	{
		internal static readonly MethodSymbol FractionLawViewBind = new(
			"customFactionLaw.fractionLawView.bind",
			"Method_Public_Void_Object1PublicSiObFrObccSiLiObcc1Unique_ObjectPublicDaccObLicc1QuObSt1Unique_0",
			"zgh");

		internal static readonly MethodSymbol FractionLawViewRefresh = new(
			"customFactionLaw.fractionLawView.refresh",
			"Method_Public_Void_0",
			"zgj");

		// Source-prepared 2026-06-19: DiffableCs identifies Hex.Session.Data.DataSides
		// as the native owner of Side[] array. These lifecycle methods populate/load
		// that exact array; combat law owner resolution may preseed from them, but
		// gameplay mutation remains disabled until runtime proof confirms side-index
		// correlation in battle.
		internal static readonly MethodSymbol DataSidesNewGamePopulate = new(
			"customFactionLaw.dataSides.populate.newGame",
			"bfuz");

		internal static readonly MethodSymbol DataSidesLoadPopulate = new(
			"customFactionLaw.dataSides.populate.load",
			"bfva");

		internal static readonly MethodSymbol DataSidesMetaPopulate = new(
			"customFactionLaw.dataSides.populate.meta",
			"bfve");

		internal static readonly MethodSymbol DataRootConstructFromSession = new(
			"customFactionLaw.dataRoot.constructFromSession",
			"bfqy");

		internal static readonly MethodSymbol DataRootNewGamePopulate = new(
			"customFactionLaw.dataRoot.populate.newGame",
			"bfrc");

		internal static readonly MethodSymbol DataRootMetaPopulate = new(
			"customFactionLaw.dataRoot.populate.meta",
			"bfrd");

		internal static readonly MethodSymbol DataRootRestartPopulate = new(
			"customFactionLaw.dataRoot.populate.restart",
			"bfre");

		internal static readonly string[] SideFactionFields =
			{ "fraction", "<fraction>k__BackingField", "_fraction", "chqo", "<chqo>k__BackingField", "_chqo" };

		internal static readonly string[] SideFractionConfigFields =
			{ "cnzk", "chty", "cnvq", "fractionConfig", "<fractionConfig>k__BackingField", "_fractionConfig" };

		internal static readonly string[] SideRootGetters =
			{ "get__ccng_k__BackingField", "Method_Public_get_Side_0" };

		internal static readonly string[] SideFractionLawsGetters =
			{ "get__ccnl_k__BackingField", "Method_Public_get_FractionLaws_0" };

		internal static readonly string[] FractionConfigIdFields =
			{ "id", "<id>k__BackingField", "_id", "sid", "<sid>k__BackingField", "_sid" };

		internal static readonly string[] LawRuntimeFields =
			{ "ccep", "field_Private_DataFractionLaw_0", "cnpl", "field_Private_FractionLawConfig_0", "config", "lawConfig", "data", "law", "cccd", "chsk", "ccak", "chrp", "ccah", "cnlk", "cnxn" };

		internal static readonly string[] LawDataFields =
			{ "sid", "<sid>k__BackingField", "_sid", "id", "<id>k__BackingField", "_id", "icon", "rank", "level", "currentLevel", "activeRank", "line", "group", "wasApplied" };

		internal static readonly string[] LawConfigGetters =
			{ "Method_Public_get_FractionLawConfig_0", "get_cnpl", "cnpl", "xow", "bfwo", "get_cobp", "cobp" };

		internal static readonly string[] LawDataGetters =
			{ "get_field_Private_DataFractionLaw_0" };

		internal static readonly string[] LawLevelGetters =
			{ "xot", "get_cnpi", "cnpi", "bfwp", "get_cobq", "cobq" };

		internal static readonly string[] LogicSideDataSideMembers =
			{ "ymo", "get_ccng", "get__ccng_k__BackingField", "<ccng>k__BackingField", "field_Private_Side_0" };

		// Source-prepared 2026-06-19: dtj/Object1PublicSiObFrObccSiLiObcc1Unique constructor creates
		// and initializes Hex.Session.Logic.FractionLaws, then stores it in <ccnl>k__BackingField.
		// The constructor postfix only registers that exact wrapper for diagnostics.
		internal static readonly string[] LogicSideRuntimeTypeNames =
			{ "Object1PublicSiObFrObccSiLiObcc1Unique" };

		internal static readonly string[] LogicSideConstructorParameterTypes =
			{ "Side", "ObjectPublicObDaObSeEvccObccDaSeUnique" };

		internal static readonly string[] LogicSideFractionLawsMembers =
			{ "ymw", "get_ccnl", "get__ccnl_k__BackingField", "<ccnl>k__BackingField", "field_Private_FractionLaws_0" };

		internal static readonly string[] LogicFractionLawsDataMembers =
			{ "ccew", "get_field_Private_DataFractionLaws_0", "field_Private_DataFractionLaws_0" };

		// Source-prepared 2026-06-19: FractionLaws.xpk/xpl ISIL reads/writes through ccev (dtj).
		// This is diagnostic/test-only; use it to invoke native law LevelUp/spend gates, never raw law row writes.
		internal static readonly string[] LogicFractionLawsLogicSideMembers =
			{ "get_field_Private_Object1PublicSiObFrObccSiLiObcc1Unique_0", "ccev", "field_Private_Object1PublicSiObFrObccSiLiObcc1Unique_0" };

		// Source-prepared 2026-06-19: generated interop identifies Hex.Session.Logic.FractionLaws
		// callable ordinal 3 as ObjectPublicDaccObLicc1QuObSt1Unique Method_Public_ObjectPublicDaccObLicc1QuObSt1Unique_String_0(string).
		// Runtime proof is still pending; this is used only as an exact diagnostic/read path until proven.
		internal static readonly string[] LogicFractionLawBySidMethods =
			{ "Method_Public_ObjectPublicDaccObLicc1QuObSt1Unique_String_0" };

		internal static readonly string[] LogicFractionLawsTypeHints =
			{ "Hex.Session.Logic.FractionLaws", "FractionLaws" };

		// Source-prepared 2026-06-19: cvj/fir ISIL call Hex.Session.Logic.FractionLaws.xpk(sid, level)
		// before Hex.Session.Logic.FractionLaws.xpl(sid, level), and generated interop maps those to
		// callable ordinals 6/7. Runtime proof is pending; use only for the explicit law seed diagnostic.
		internal static readonly string[] LogicFractionLawCanApplyMethods =
			{ "Method_Public_Boolean_String_Int32_0" };

		internal static readonly string[] LogicFractionLawApplyMethods =
			{ "Method_Public_Void_String_Int32_0" };

		// Source-prepared + live-metadata-proven 2026-06-19: live bridge method_signatures
		// maps FractionLaws.xpm/xpn/xpp/xpq/xpr/xps to callable ordinals 8/9/11/12/13/14.
		// These are exposed only through explicit native_law_state diagnostics/apply-if-xpk.
		internal static readonly string[] LogicFractionLawCostMethods =
			{ "Method_Public_Int32_ObjectPublicDaccObLicc1QuObSt1Unique_Int32_0", "xpm" };

		internal static readonly string[] LogicFractionLawRankEligibleMethods =
			{ "Method_Public_Boolean_ObjectPublicDaccObLicc1QuObSt1Unique_Int32_0", "xpn" };

		internal static readonly string[] LogicFractionLawLineVisibleMethods =
			{ "Method_Public_Boolean_ObjectPublicDaccObLicc1QuObSt1Unique_0", "xpp" };

		internal static readonly string[] LogicFractionLawsUnlockedLineMethods =
			{ "Method_Public_Int32_0", "xpq" };

		internal static readonly string[] LogicFractionLawsSpentPointsMethods =
			{ "Method_Public_Int32_1", "xpr" };

		internal static readonly string[] LogicFractionLawsLineRequirementMethods =
			{ "Method_Public_Int32_Int32_0", "xps" };

		// Source-prepared 2026-06-19: dtj.LevelUp increments Side.currentLevel and Side.currentLawsPoints;
		// dtj.ynu checks Side.currentLawsPoints >= amount. Exposed only through explicit bridge proof commands.
		internal static readonly string[] LogicSideLevelUpMethods =
			{ "LevelUp" };

		internal static readonly string[] LogicSideCanSpendLawPointsMethods =
			{ "Method_Public_Boolean_Int32_0", "ynu", "dgz" };

		internal static readonly string[] LogicHeroDataHeroMembers =
			{ "<ccez>k__BackingField", "ccez", "xpv", "get_ccez" };

		internal static readonly string[] LogicHeroLogicRootMembers =
			{ "ccfu" };

		internal static readonly string[] GlobalLogicRootTypeHints =
			{ "dsu", "ObjectPublicObDaObSeEvccObccDaSeUnique" };

		internal static readonly string[] GlobalLogicRootInstanceMembers =
			{ "yfn", "cckz", "get_cckz", "get__cckz_k__BackingField", "<cckz>k__BackingField", "Method_Public_Static_get_ObjectPublicObDaObSeEvccObccDaSeUnique_PDM_0" };
		internal static readonly string[] LogicRootDataMembers =
			{ "<cclb>k__BackingField", "cclb", "yfr", "get_cclb", "get__cclb_k__BackingField" };

		// Source-prepared 2026-06-19: dsu/ObjectPublicObDaObSeEvccObccDaSeUnique initializes
		// dto/ObjectPublicObDaccObDaccUnique in its void(Data, SerializableRandom) methods. dto owns
		// the dtj logic-side array and exact side-by-index accessors. Runtime proof is pending; this
		// route is diagnostic-only and exists to bind Data.Side index -> Logic.FractionLaws without
		// raw DataFractionLaw writes.
		internal static readonly string[] LogicRootInitParameterTypes =
			{ "Data", "SerializableRandom" };

		internal static readonly string[] LogicRootSideCollectionMembers =
			{ "yfz", "get_cclf", "get__cclf_k__BackingField", "<cclf>k__BackingField", "Method_Public_get_ObjectPublicObDaccObDaccUnique_0" };

		internal static readonly string[] LogicSideCollectionByIndexMethods =
			{
				"Method_Public_Object1PublicSiObFrObccSiLiObcc1Unique_Int32_0",
				"Method_Public_Object1PublicSiObFrObccSiLiObcc1Unique_Int32_1",
				"Method_Public_Object1PublicSiObFrObccSiLiObcc1Unique_Int32_2"
			};

		internal static readonly string[] BattleSideTransferSideMembers =
			{ "cgle", "get_field_Public_TransferSide_0", "field_Public_TransferSide_0" };

		internal static readonly string[] TransferSideLogicHeroMembers =
			{ "get_logicHero", "logicHero" };

		internal static readonly string[] DataHeroSideIdMembers =
			{ "sideId" };

		internal static readonly string[] DataRootSidesMembers =
			{ "sides", "get_sides" };

		internal static readonly string[] DataSidesArrayMembers =
			{ "array", "get_array" };

		internal static readonly MethodSymbol DataSideInit = new(
			"customFactionLaw.dataSide.init",
			"bghv");
		internal static readonly string[] DataSideIndexMembers =
			{ "index", "get_index" };

		internal static readonly string[] DataSideFractionLawMembers =
			{ "fractionLaws", "get_fractionLaws" };

		internal static readonly string[] DataSideFactionMembers =
			{ "fraction", "get_fraction" };

		internal static readonly string[] DataSideCurrentLevelMembers =
			{ "currentLevel", "get_currentLevel" };

		internal static readonly string[] DataSideCurrentLawsPointsMembers =
			{ "currentLawsPoints", "get_currentLawsPoints" };

		internal static readonly string[] DataFractionLawsFactionMembers =
			{ "fraction", "get_fraction" };

		internal static readonly string[] DataFractionLawsListMembers =
			{ "list", "get_list" };

		// Runtime-observed 2026-06-19: DataFractionLaws.list is Il2CppSystem.Collections.Generic.List<DataFractionLaw>,
		// not a CLR enumerable. Access it through exact generated List Count/get_Item members only.
		internal static readonly string[] DataFractionLawsListCountMembers =
			{ "Count", "get_Count" };

		internal static readonly string[] DataFractionLawsListItemMethods =
			{ "get_Item", "Item" };

		internal static readonly string[] DataFractionLawSidMembers =
			{ "sid", "get_field_Public_String_0", "field_Public_String_0" };

		internal static readonly string[] DataFractionLawLevelMembers =
			{ "level", "get_level" };

		internal static readonly string[] DataFractionLawLineMembers =
			{ "line", "get_line" };

		internal static readonly string[] DataFractionLawGroupMembers =
			{ "group", "get_group" };

		// Source-prepared + live-metadata-proven 2026-06-19:
		// Hex.Session.Data.DataFractionLaw has a real wasApplied field, but the
		// current IL2CPP generated runtime exposes it through get_wasApplied().
		// Keep both exact names; do not treat level > 0 alone as an active law.
		internal static readonly string[] DataFractionLawWasAppliedMembers =
			{ "wasApplied", "get_wasApplied" };
	}

	internal static partial class CustomTownMapBillboard
	{
		internal const string PlacedObjectTypeId = "map.customTownBillboard.placedObject";
		internal static readonly string[] PlacedObjectTypeHints = { "ObjectPublicObInbvByInSiLi1MaLiUnique", "bvb", "bvc" };

		internal const string ObjectMetaTypeId = "map.customTownBillboard.objectMeta";
		internal static readonly string[] ObjectMetaTypeHints = { "bvd", "ObjectPublicObbvGaSpObBoLi1ReMeUnique", "ObjectPublicObbvLiObbv1InLi1InUnique" };

		internal static readonly MethodSymbol PlacedObjectInit = new(
			"map.customTownBillboard.placedObject.init",
			"cjd", "fw", "Init",
			"Method_Public_Void_Map_ObjectPublicObbvGaSpObBoLi1ReMeUnique_Int32_Byte_Single_0");

		internal static readonly MethodSymbol PlacedObjectSetSid = new(
			"map.customTownBillboard.placedObject.setSid",
			"ooc", "Method_Public_Void_String_0");

		internal static readonly string[] MetaFields =
			{ "bvob", "<bvob>k__BackingField", "_bvob_k__BackingField", "bvmr", "<bvmr>k__BackingField", "_bvmr_k__BackingField", "meta", "bvmo", "<bvmo>k__BackingField", "_bvmo_k__BackingField", "bvkd", "bvlr", "<bvkd>k__BackingField", "_bvkd_k__BackingField", "<bvlr>k__BackingField", "_bvlr_k__BackingField" };

		internal static readonly string[] MetaConfigFields =
			{ "bvpj", "bvnz", "config", "buwy", "bvnw", "bvll", "bvmz", "bvlm",
			  "field_Public_ObjectConfig_0", "field_Private_ObjectConfig_0",
			  "<bvnz>k__BackingField", "_bvnz_k__BackingField" };

		// Golden Era 2026-06-09 live probe: ObjectPublicObbvGaSpObBoLi1ReMeUnique
		// exposes map-object prefab resources as bvrm / Il2CppReferenceArray<GameObject>.
		internal static readonly string[] MetaPrefabGameObjectArrayFields =
			{ "_bvrm_k__BackingField", "<bvrm>k__BackingField", "bvrm" };

		internal static readonly string[] MetaPrefabGameObjectArrayGetters =
			{ "get__bvrm_k__BackingField", "Method_Public_get_Il2CppReferenceArray_1_GameObject_0" };

		internal static readonly string[] MetaCombinedGeometryOkFields =
			{ "_bvrp_k__BackingField", "<bvrp>k__BackingField", "bvrp", "IsCombinedGeometryOk", "<IsCombinedGeometryOk>k__BackingField" };

		internal static readonly string[] PlacedObjectSidFields =
			{ "bvoy", "bvno", "sid", "objectSid", "id",
			  "field_Private_String_0", "field_Public_String_0",
			  "<bvno>k__BackingField", "_bvno_k__BackingField" };

		// Prefer logical "id"/sid names. Do NOT lead with field_Public_String_0: on ObjectConfig
		// that generated slot is often `tag` (category token e.g. "Artifact"), not ConfigElementBase.id.
		// Callers that need Golden Era id reads should use DeobfInteropCompat.GetConfigElementId.
		internal static readonly string[] ConfigIdFields =
			{ "id", "sid", "cluu", "cmql", "cmsc", "field_Private_String_0", "field_Public_String_0" };

		internal static readonly string[] ConfigSizeXFields =
			{ "sizeX", "field_Public_Int32_0" };

		internal static readonly string[] ConfigSizeZFields =
			{ "sizeZ", "field_Public_Int32_1" };

		internal static readonly string[] ConfigPivotXFields =
			{ "pivotX", "field_Public_Int32_2" };

		internal static readonly string[] ConfigPivotZFields =
			{ "pivotZ", "field_Public_Int32_3" };

		internal static readonly string[] ConfigNodesFields =
			{ "nodes", "field_Public_Byte_Array_0", "field_Public_Il2CppStructArray_1_Byte_0" };

		internal static readonly string[] RootGameObjectFields =
			{ "bvon", "<bvon>k__BackingField", "_bvon_k__BackingField", "bvnd", "<bvnd>k__BackingField", "_bvnd_k__BackingField", "gameObject", "buwc", "bvna", "<bvna>k__BackingField", "_bvna_k__BackingField", "bvng", "_bvkp_k__BackingField", "<bvkp>k__BackingField", "_bvmd_k__BackingField", "<bvmd>k__BackingField", "bvks", "bvmg",
			  "bvqp", "<bvqp>k__BackingField", "_bvqp_k__BackingField", "field_Private_GameObject_0" };

		internal static readonly string[] RootTransformFields =
			{ "bvoo", "<bvoo>k__BackingField", "_bvoo_k__BackingField", "bvne", "<bvne>k__BackingField", "_bvne_k__BackingField", "bvnh", "bvnb", "<bvnb>k__BackingField", "_bvnb_k__BackingField", "bvkq", "<bvkq>k__BackingField", "_bvkq_k__BackingField", "<bvme>k__BackingField", "_bvme_k__BackingField", "bvkt", "bvmh",
			  "bvqq", "<bvqq>k__BackingField", "_bvqq_k__BackingField", "field_Private_Transform_0" };

		internal static readonly MethodSymbol RootGameObjectGetter = new(
			"map.customTownBillboard.rootGameObject",
			"Method_Public_get_GameObject_0", "get__bvqp_k__BackingField", "get_field_Private_GameObject_0",
			"omx", "omk");

		internal static readonly MethodSymbol RootTransformGetter = new(
			"map.customTownBillboard.rootTransform",
			"Method_Public_get_Transform_0", "get__bvqq_k__BackingField", "get_field_Private_Transform_0",
			"omz", "omm");

		// Resolver path for cities that share the generic "city-spawner" / "random-city" sid:
		// placed object -> Map.ogc/cmwh -> ObjectsProperties.ovi/ovj(ObjectProp.EType.MapObject, field_Public_Int32_0/current id)
		// -> PropCity.factionSid. Legacy bvms/bvoc and the bvb.Init node arg can be stale placement data, not the property id.
		internal static readonly string[] PlacedObjectMapFields =
			{ "<bvoi>k__BackingField", "_bvoi_k__BackingField", "bvoi", "<bvmy>k__BackingField", "_bvmy_k__BackingField", "bvmy",
			  "_bvqk_k__BackingField", "<bvqk>k__BackingField", "bvqk", "prop_Map_0", "map", "<map>k__BackingField" };

		internal static readonly string[] PlacedObjectNodeFields =
			{ "<bvod>k__BackingField", "_bvod_k__BackingField", "bvod", "<bvmt>k__BackingField", "_bvmt_k__BackingField", "bvmt",
			  "_bvqf_k__BackingField", "<bvqf>k__BackingField", "bvqf", "node", "<node>k__BackingField" };

		internal static readonly string[] PlacedObjectRotationFields =
			{ "<bvmu>k__BackingField", "_bvmu_k__BackingField", "bvmu",
			  "field_Private_Byte_0" };

		internal static readonly string[] PlacedObjectIdFields =
			{ "field_Public_Int32_0", "id", "<id>k__BackingField", "_id",
			  "bvoc", "<bvoc>k__BackingField", "_bvoc_k__BackingField", "bvms", "<bvms>k__BackingField", "_bvms_k__BackingField" };

		internal static readonly string[] MapObjectsPropertiesFields =
			{ "<cmtm>k__BackingField", "_cmtm_k__BackingField", "cmtm", "<cmsp>k__BackingField", "_cmsp_k__BackingField",
			  "objectsProperties", "<objectsProperties>k__BackingField" };

		internal static readonly string[] MapObjectsPropertiesGetters =
			{ "ogc", "get_cmwh", "cmwh", "oel", "cmpx", "get_cmpx", "ofq", "cmtm", "get_cmtm", "ofc", "cmsp", "get_cmsp", "get_objectsProperties",
			  "Method_Public_get_ObjectsProperties_0" };

		// Golden Era 2026-06-08: bvb._bvkc / ObjectPublicMabvBoLibv1ObDi2InUnique is map-squad storage,
		// not Hex.Map.ObjectsProperties. Accepting it masks the real ObjectsProperties getter and prevents PropCity lookup.
		internal static readonly string[] RejectedMapObjectsPropertiesTypeNames =
			{ "ObjectPublicMabvBoLibv1ObDi2InUnique" };

		internal static readonly string[] MapObjectPropertiesGetters =
			{ "ovi", "ovj", "oux", "ouw", "ouk", "ouj", "ots", "ott",
			  "Method_Public_List_1_ObjectProp_EType_Int32_0",
			  "Method_Public_List_1_ObjectProp_EType_Int32_1" };

		internal static readonly string[] PropCitiesFields =
			{ "propCities", "<propCities>k__BackingField", "_propCities" };

		internal static readonly string[] PropCitiesGetters =
			{ "oum", "get_cmxl", "cmxl", "otz", "osv", "get_cmup", "cmup", "otm", "get_propCities", "Method_Public_get_List_1_PropCity_0", "cmts", "get_cmts" };

		internal static readonly string[] PropCityFactionFields =
			{ "factionSid", "<factionSid>k__BackingField", "_factionSid", "FactionSid" };

		internal static readonly string[] PropCityFactionGetters =
			{ "get_factionSid" };

		internal static readonly string[] PropCityIdFields =
			{ "field_Public_Int32_0", "id", "<id>k__BackingField", "_id", "Id" };

		internal static readonly string[] PropCityIdGetters =
			{ "get_field_Public_Int32_0" };

		internal static readonly string[] MapObjectPropValueFields =
			{ "field_Public_Int32_0", "id", "<id>k__BackingField", "_id" };

		internal static readonly string[] MapObjectPropValueGetters =
			{ "get_field_Public_Int32_0" };
	}

	internal static partial class CustomDwellingRandomHire
	{
		internal const string RandomHireWorldObjectTypeId = "map.customDwelling.randomHireWorldObject";
		internal static readonly string[] RandomHireWorldObjectTypeHints = { "fcj" };

		internal const string RandomHireResolverTypeId = "map.customDwelling.randomHireResolver";
		internal static readonly string RandomHireResolverTypeHint = "czr";

		// Golden Era shape-locked generated names; short vfm/hgh/… are legacy aliases only.
		internal static readonly MethodSymbol RandomHireFactionTierResolvers = new(
			"map.customDwelling.randomHireResolver.factionTierMethods",
			"Method_Private_Static_Void_FractionConfig_String_Int32_Side_PDM_0",
			"Method_Private_Static_Void_FractionConfig_String_Int32_Side_PDM_1",
			"Method_Private_Static_Void_FractionConfig_String_Int32_Side_PDM_2",
			"Method_Private_Static_Void_FractionConfig_String_Int32_Side_PDM_3",
			"Method_Private_Static_Void_FractionConfig_String_Int32_Side_PDM_4",
			"vfm");

		internal static readonly MethodSymbol HireMapObjectSpawners = new(
			"map.customDwelling.randomHireResolver.hireMapObjectSpawners",
			"Method_Private_Static_Void_Side_MapObjectInfo_PDM_0",
			"Method_Private_Static_Void_Side_MapObjectInfo_PDM_1",
			"Method_Private_Static_Void_Side_MapObjectInfo_PDM_2",
			"Method_Private_Static_Void_Side_MapObjectInfo_PDM_3",
			"Method_Private_Static_Void_Side_MapObjectInfo_PDM_4",
			"hgh", "kiu", "vfj", "hkd");

		internal static readonly string[] FractionConfigIdFields =
			{ "id", "<id>k__BackingField", "_id" };

		internal static readonly string[] SideFactionFields =
			{ "fraction", "<fraction>k__BackingField", "_fraction", "chqo", "<chqo>k__BackingField", "_chqo" };

		internal static readonly string[] SideFractionConfigFields =
			{ "cnzk", "chty", "cnvq", "fractionConfig", "<fractionConfig>k__BackingField", "_fractionConfig" };

		internal const string RandomHireSessionDataTypeId = "map.customDwelling.randomHireSessionData";
		internal static readonly string[] RandomHireSessionDataTypeHints = { "Hex.Session.Data.ObjRandomHire" };

		internal static readonly string[] WorldObjectDataFields =
			{ "cjhx", "<cjhx>k__BackingField", "_cjhx_k__BackingField", "cjek", "<cjek>k__BackingField", "_cjek_k__BackingField", "dataObject", "data" };

		internal static readonly string[] WorldObjectRandomHireDataFields =
			{ "cjha", "<cjha>k__BackingField", "_cjha_k__BackingField", "cjgf", "<cjgf>k__BackingField", "_cjgf_k__BackingField", "cjdn", "<cjdn>k__BackingField", "_cjdn_k__BackingField", "randomHire", "objRandomHire" };

		internal static readonly string[] WorldObjectRandomHireConfigFields =
			{ "cjgz", "<cjgz>k__BackingField", "_cjgz_k__BackingField", "cjge", "<cjge>k__BackingField", "_cjge_k__BackingField", "cjdm", "<cjdm>k__BackingField", "_cjdm_k__BackingField", "config", "randomHireConfig" };

		internal static readonly string[] DataObjectIdFields =
			{ "idMapObject", "<idMapObject>k__BackingField", "_idMapObject", "id", "<id>k__BackingField", "_id" };

		internal static readonly string[] DataObjectConfigSidFields =
			{ "sidConfig", "<sidConfig>k__BackingField", "_sidConfig" };

		internal static readonly string[] DataObjectOwnerSideFields =
			{ "ownerSide", "<ownerSide>k__BackingField", "_ownerSide" };

		internal static readonly string[] AssortmentFields =
			{ "assortmentData", "<assortmentData>k__BackingField", "_assortmentData" };

		internal static readonly string[] UnitSetsFields =
			{ "unitSets", "<unitSets>k__BackingField", "_unitSets" };

		internal static readonly string[] RandomHireUnitsFields =
			{ "units", "<units>k__BackingField", "_units" };

		internal static readonly string[] UnitSidListFields =
			{ "sids", "<sids>k__BackingField", "_sids" };

		internal static readonly string[] PropRandomHireGetters =
			{ "Method_Public_get_List_1_PropRandomHire_0", "get_propRandomHires" };

		internal static readonly string[] PropRandomHireFields =
			{ "propRandomHires", "<propRandomHires>k__BackingField", "_propRandomHires" };

		internal static readonly string[] PropRandomHireIdFields =
			{ "field_Public_Int32_0", "id", "<id>k__BackingField", "_id", "Id" };

		internal static readonly string[] PropRandomHireTierGetters =
			{ "get_tier" };

		internal static readonly string[] PropRandomHireTierFields =
			{ "tier", "<tier>k__BackingField", "_tier" };

		internal static readonly string[] PropRandomHireFractionGetters =
			{ "get_fraction" };

		internal static readonly string[] PropRandomHireFractionFields =
			{ "fraction", "<fraction>k__BackingField", "_fraction" };

		internal static readonly string[] PropFractionResolverTypeNames =
			{ "ObjectPublicAbstractSealedbwStaEPbMacInbgBoUnique" };

		internal static readonly string[] PropFractionMapResolverMethods =
		{
			"Method_Public_Static_String_EPropFraction_Map_Int32_PDM_0",
			"Method_Public_Static_String_EPropFraction_Map_Int32_PDM_1",
			"Method_Public_Static_String_EPropFraction_Map_Int32_PDM_2",
			"Method_Public_Static_String_EPropFraction_Map_Int32_PDM_3"
		};

		internal static readonly string[] MapDataGetters =
			{ "Method_Public_get_MapData_0", "get__bvjr_k__BackingField", "get_mapData" };

		internal static readonly string[] MapDataFields =
			{ "_bvjr_k__BackingField", "<bvjr>k__BackingField", "mapData" };

		internal static readonly string[] MapDataAreasGetters =
			{ "get_areas" };

		internal static readonly string[] MapDataAreasFields =
			{ "areas", "<areas>k__BackingField", "_areas" };

		internal static readonly string[] MapDataAreaNodesGetters =
			{ "get_nodes" };

		internal static readonly string[] MapDataAreaRootNodeGetters =
			{ "get_rootNode" };

		internal static readonly string[] MapDataAreaKeyObjectIdGetters =
			{ "get_keyObjectId" };

		internal static readonly string[] MapDataAreaIdGetters =
			{ "get_field_Public_Int32_0" };

		internal static readonly string[] MapDataAreaBiomeGetters =
			{ "get_biome" };
	}

	internal static partial class CustomDwellingHire
	{
		internal const string HireWorldObjectTypeId = "map.customDwelling.hireWorldObject";
		// No verified ObjHire world-object type on Golden Era; dwelling billboards use
		// map-object / random-hire / city hooks. Do not re-add fbx /
		// Object1PublicObcjIncjUnique without an ObjHire shape (they are hero wrappers).
		internal static readonly string[] HireWorldObjectTypeHints = Array.Empty<string>();
		// Build 25672315 only, consumed through TypeGroups.CustomDwellingHireWorldObject (shape-pinned): the
		// ObjHire world object is native fmz (its only ctor takes Hex.Session.Data.ObjHire).
		internal static readonly string[] HireWorldObjectCurrentTypeHints = { "Object1PublicObcoLiObco1IncuObcoUnique" };

		internal static readonly MethodSymbol HireWorldObjectInit = new(
			"map.customDwelling.hireWorldObject.init",
			"Init");

		internal const string HireSessionDataTypeId = "map.customDwelling.hireSessionData";
		internal static readonly string[] HireSessionDataTypeHints = { "Hex.Session.Data.ObjHire" };

		internal static readonly string[] WorldObjectHireDataFields =
			{ "cjfb", "<cjfb>k__BackingField", "_cjfb_k__BackingField", "cjeg", "<cjeg>k__BackingField", "_cjeg_k__BackingField", "hire", "objHire" };

		internal static readonly string[] WorldObjectHireConfigFields =
			{ "cjfd", "<cjfd>k__BackingField", "_cjfd_k__BackingField", "cjei", "<cjei>k__BackingField", "_cjei_k__BackingField", "config", "hireConfig" };

		internal static readonly string[] HireDataConfigSidFields =
			{ "sidConfig", "<sidConfig>k__BackingField", "_sidConfig" };

		internal static readonly string[] HireConfigFactionFields =
			{ "fraction", "<fraction>k__BackingField", "_fraction" };

		internal static readonly string[] HireConfigUnitsDataFields =
			{ "unitsData", "<unitsData>k__BackingField", "_unitsData" };

		internal static readonly string[] HireConfigUnitsFields =
			{ "units", "<units>k__BackingField", "_units" };

		internal static readonly string[] HireDataGuardUnitsFields =
			{ "initGuardUnits", "<initGuardUnits>k__BackingField", "_initGuardUnits" };

		internal static readonly string[] UnitSidFields =
			{ "sid", "<sid>k__BackingField", "_sid" };
	}

	internal static partial class CustomDwellingCity
	{
		internal const string CityWorldObjectTypeId = "map.customDwelling.cityWorldObject";
		internal static readonly string[] CityWorldObjectTypeHints =
			{ "fbj", "fbq", "ObjectPublicAbstractObcjESObcjcoEScocjObUnique" };

		internal static readonly MethodSymbol CityWorldObjectInit = new(
			"map.customDwelling.cityWorldObject.init",
			"Init",
			"Method_Public_Void_0",
			"Method_Public_Void_1",
			"Method_Public_Void_2",
			"Method_Public_Void_3");

		internal const string CitySessionDataTypeId = "map.customDwelling.citySessionData";
		internal static readonly string[] CitySessionDataTypeHints = { "Hex.Session.Data.ObjCity" };

		internal static readonly string[] WorldObjectCityDataFields =
			{ "cjea", "<cjea>k__BackingField", "_cjea_k__BackingField", "cjdf", "<cjdf>k__BackingField", "_cjdf_k__BackingField", "city", "objCity" };

		internal static readonly string[] WorldObjectCityConfigFields =
			{ "cjdz", "<cjdz>k__BackingField", "_cjdz_k__BackingField", "cjde", "<cjde>k__BackingField", "_cjde_k__BackingField", "config", "cityConfig" };
	}

	internal static partial class MapBillboardDeathFade
	{
		internal const string IdRemovalTypeId = "map.billboardDeathFade.idRemovalType";
		internal static readonly string[] IdRemovalTypeHints = { "fce" };

		internal const string ObjectRemovalTypeId = "map.billboardDeathFade.objectRemovalType";
		internal static readonly string[] ObjectRemovalTypeHints = { "fcd" };

		internal static readonly MethodSymbol IdRemovalMethods = new(
			"map.billboardDeathFade.idRemovalMethods",
			"mut", "kum", "bpb", "oou", "ixc", "jb", "kmz");

		internal static readonly MethodSymbol ObjectNoArgRemovalMethods = new(
			"map.billboardDeathFade.objectNoArgRemovalMethods",
			"bbw", "nle");

		internal static readonly MethodSymbol ObjectIntRemovalMethods = new(
			"map.billboardDeathFade.objectIntRemovalMethods",
			"cwi", "nbh", "bixw", "eri", "mdi", "hja");

		internal static readonly string[] ObjectDataFields =
			{ "cjcw" };

		internal static readonly MethodSymbol ObjectDataGetter = new(
			"map.billboardDeathFade.objectDataGetter",
			"bfb");

		internal static readonly string[] ObjectIdFields =
			{ "idMapObject", "mapObjectId", "id", "objectId", "buwr", "bvib" };
	}

	internal static partial class WarcryHeroAbility
	{
		// Hero ability container view. Golden Era: Hex.UI.BhHeroAbilitiesView. Live build 25061458 moved it
		// to Hex.UI.Battle.BhHeroAbilitiesView (docs/port_to_current_game_version.md section 2); resolve it
		// only through TypeGroups.WarcryHeroAbilityHeroAbilitiesView, never by a compile-time reference.
		internal const string HeroAbilitiesViewTypeId = "warcry.heroAbilitiesView";
		internal static readonly string[] HeroAbilitiesViewTypeHints = { "Hex.UI.BhHeroAbilitiesView" };
		internal static readonly string[] HeroAbilitiesViewCurrentTypeHints = { "Hex.UI.Battle.BhHeroAbilitiesView" };

		internal const string LegacyControllerTypeId = "warcry.legacy.controllerType";
		internal static readonly string[] LegacyControllerTypeHints = { "crg" };

		internal static readonly MethodSymbol LegacyAvailability = new(
			"warcry.legacy.heroAbility.availability",
			"lis");

		internal static readonly MethodSymbol LegacyEnergyGetter = new(
			"warcry.legacy.heroAbility.energyGetter",
			"god", "mgn");

		internal static readonly MethodSymbol LegacyContainerBuild = new(
			"warcry.legacy.heroAbilitiesView.listBuild",
			"ryt", "ryu");

		internal static readonly MethodSymbol LegacyHeroButtonBind = new(
			"warcry.legacy.heroAbilityView.buttonBind",
			"rzt");

		internal static readonly MethodSymbol LegacyHeroViewRefreshDiagnostic = new(
			"warcry.legacy.heroAbilitiesView.refreshDiagnostic",
			"rzi", "ryy", "ryw", "ryz", "rza", "rzb", "rzc", "rzd", "rze");

		internal static readonly MethodSymbol LegacyControllerDiagnostic = new(
			"warcry.legacy.controller.diagnostic",
			"tuq", "tun", "tur", "tuz", "tva", "tvb", "tvc", "tux");

		internal static readonly MethodSymbol LegacyHeroViewAbilityGetter = new(
			"warcry.legacy.heroAbilityView.abilityGetter",
			"rzq");

		internal static readonly string[] LegacyHeroViewAbilityProperties =
			{ "cmfk", "bxfy" };

		// Per-ability button bind: current BhHeroAbilitiyView.sli(bzd, emb). Older builds used bzc/bzd + elz/els wrappers. /2.
		internal static readonly MethodSymbol PerAbilityBind = new(
			"warcry.heroAbilityView.perAbilityBind",
			"sli", "skw", "skk",
			"Method_Public_Void_ObjectPublicAbbwObBubwObItUnbwObUnique_ObjectPublicObBochBoObchBochBoUnique_0");

		// Container bind: current BhHeroAbilitiesView.ski/skj(bzd, List<edn>). Older builds used sjw/sjx/sjk/sjl. /2.
		internal static readonly MethodSymbol ContainerBind = new(
			"warcry.heroAbilitiesView.containerBind",
			"ski", "skj", "sjw", "sjx", "sjk", "sjl",
			"Method_Public_Void_ObjectPublicAbbwObBubwObItUnbwObUnique_List_1_ObjectPublicStInHeInObHecfObchcfUnique_0",
			"Method_Public_Void_ObjectPublicAbbwObBubwObItUnbwObUnique_List_1_ObjectPublicStInHeInObHecfObchcfUnique_1");

		// Container arena bind: current BhHeroAbilitiesView.skk(bzd, ead, List<edn>). /3.
		internal static readonly MethodSymbol ContainerBindWithArena = new(
			"warcry.heroAbilitiesView.containerBindWithArena",
			"skk");

		// Container context-set / refresh: current BhHeroAbilitiesView.skp(edn). Older builds used skd/sjr. /1.
		internal static readonly MethodSymbol ContainerContextSet = new(
			"warcry.heroAbilitiesView.containerContextSet",
			"skp", "skd", "sjr",
			"Method_Public_Void_ObjectPublicStInHeInObHecfObchcfUnique_PDM_0");

		internal static readonly string[] HeroAbilityTypeNames =
			{ "edn", "edg", "ObjectPublicStInHeInObHecfObchcfUnique" };

		internal static readonly string[] HeroAbilityWrapperTypeNames =
			{ "emb", "bzd", "elz", "els", "ObjectPublicInchObUnchFu1BhchDiUnique", "ObjectPublicUnchInBhchTuTuchchUnique", "ObjectPublicObBochBoObchBochBoUnique" };

		internal static readonly string[] WrapperProbeLegacyInitializerTypeNames =
			{ "ekj" };

		internal static readonly string[] HeroAbilityFields =
			{
				"bydd", "bwhs", "chev", "<chev>k__BackingField", "bybb", "bxzr",
				"field_Private_edn_0", "field_Public_edn_0",
				"field_Private_ObjectPublicStInHeInObHecfObchcfUnique_0",
				"prop_ObjectPublicStInHeInObHecfObchcfUnique_0",
			};

		internal static readonly string[] HeroAbilityWrapperFields =
			{
				"bydf", "byde", "bybd", "bxzt",
				"field_Private_ObjectPublicObBochBoObchBochBoUnique_0",
			};

		internal static readonly string[] HeroAbilityGetters =
			{ "slf", "get_cnhp", "skt", "skh", "get_cneu", "get_cndx" };

		internal static readonly string[] HeroAbilityOutGetters =
			{
				"beuf", "cwk", "dmw", "dlx", "csf", "beqn", "fby", "mgo", "besj", "mzn", "berk", "hhg",
				"Method_Public_Boolean_ObjectPublicUnchInBhchTuTuchchUnique_PDM_0",
				"Method_Public_Boolean_ObjectPublicUnchInBhchTuTuchchUnique_PDM_1",
			};

		internal static readonly string[] HeroAbilityViewListFields =
			{ "heroAbilities", "separateHeroAbilities" };
	}

	internal static partial class CounterattackCorrelationLaws
	{
		internal const string BattleAttackCommandTypeId = "law.counterattackCorrelation.battleAttackCommand";
		internal static readonly string[] BattleAttackCommandTypeHints = { "cty" };

		// Source-prepared/runtime-unproven June 19: DiffableCs/ISIL identify cty.hsg() as the
		// battle attack command body, and runtime_interop_map maps cty callable ordinal 1 to
		// Method_Public_Virtual_Boolean_0. Keep this exact and fail closed; do not widen to ECmd
		// dispatchers or broad battle event buses.
		internal static readonly MethodSymbol BattleAttackExecute = new(
			"law.counterattackCorrelation.battleAttack.execute",
			"hsg",
			"Method_Public_Virtual_Boolean_0");

		internal static readonly string[] CommandAttackerIdFields = { "caby", "get_field_Public_Int32_0" };
		internal static readonly string[] CommandTargetIdFields = { "cabz", "get_field_Public_Int32_1" };
		internal static readonly string[] CommandAbilityTypeFields = { "bzxg" };
		internal static readonly string[] CommandAbilityIndexFields = { "bzxh" };

		internal const string AbilityManagerTypeId = "law.counterattackCorrelation.abilityManager";
		internal static readonly string[] AbilityManagerTypeHints = { "dxx" };

		internal static readonly MethodSymbol AbilityManagerResolve = new(
			"law.counterattackCorrelation.abilityManager.resolve",
			// dxx.barb/bgl resolver set. DiffableCs exposes exactly two
			// bool(EAbilityType,int,out dxy) methods, and the live bridge
			// exposed exactly these two generated names with that shape on
			// 2026-06-18. Runtime counterattack packet correlation is still
			// unproven; this only authorizes exact diagnostic registration.
			"Method_Public_Boolean_EAbilityType_Int32_byref_ObjectPublicObceInBoInceAbObELInUnique_0",
			"Method_Public_Boolean_EAbilityType_Int32_byref_ObjectPublicObceInBoInceAbObELInUnique_PDM_0",
			"barb",
			"bgl");

		internal const string BattleLogicTypeId = "law.counterattackCorrelation.battleLogic";
		internal static readonly string[] BattleLogicTypeHints = { "een" };

		internal static readonly MethodSymbol AttackResolver = new(
			"law.counterattackCorrelation.attackResolver");

		internal const string AbilityListenerTypeId = "law.counterattackCorrelation.abilityListener";
		internal static readonly string[] AbilityListenerTypeHints = { "ebv" };

		internal static readonly MethodSymbol AbilityListenerChanged = new(
			"law.counterattackCorrelation.abilityListener.changed",
			// ebv.bbwi/jsd/nhw listener set. DiffableCs exposes exactly
			// three void(Unit,EAbilityType,int) methods, and live bridge
			// metadata exposed exactly these three generated methods with
			// that shape on 2026-06-18. Individual ordinal mapping is not
			// proven for all three, so treat this as an exact set for
			// diagnostics only, not gameplay authorization.
			"Method_Public_Void_Unit_EAbilityType_Int32_PDM_0",
			"Method_Public_Void_Unit_EAbilityType_Int32_PDM_1",
			"Method_Public_Void_Unit_EAbilityType_Int32_PDM_2",
			"bbwi",
			"jsd",
			"nhw");

		internal const string AbilityRuntimeTypeId = "law.counterattackCorrelation.abilityRuntime";
		internal static readonly string[] AbilityRuntimeTypeHints = { "dxy" };

		// Static evidence only, generated by experiments/cpp2il_readable_csharp/samples/latest_refresh/symbol_map.json
		// on 2026-06-18. Runtime proof is pending; these identify dxy.bast/kda/dwf/mgi
		// ChangeAbilityEventArgs factories for diagnostics, not gameplay authorization.
		internal static readonly MethodSymbol AbilityRuntimeChangeEvent = new(
			"law.counterattackCorrelation.abilityRuntime.changeEvent",
			"Method_Private_ChangeAbilityEventArgs_0",
			"Method_Private_ChangeAbilityEventArgs_PDM_0",
			"Method_Private_ChangeAbilityEventArgs_PDM_1",
			"Method_Private_ChangeAbilityEventArgs_PDM_2",
			"bast",
			"kda",
			"dwf",
			"mgi");
	}

	internal static partial class ConstructionCommitLaws
	{
		internal const string BuildingDataTypeId = "law.constructionCommit.buildingData";
		internal static readonly string[] BuildingDataTypeHints = { "Hex.Session.Data.BuildingData", "BuildingData" };

		internal static readonly MethodSymbol BuildingConstructStateMutation = new(
			"law.constructionCommit.buildingData.constructStateMutation",
			"bgck",
			"Method_Public_Void_Int32_Boolean_0");

		internal const string BuildingsDataTypeId = "law.constructionCommit.buildingsData";
		internal static readonly string[] BuildingsDataTypeHints = { "Hex.Session.Data.BuildingsData", "BuildingsData" };

		internal const string ObjCityTypeId = "law.constructionCommit.objCity";
		internal static readonly string[] ObjCityTypeHints = { "Hex.Session.Data.ObjCity", "ObjCity" };

		internal const string CityLogicTypeId = "law.constructionCommit.cityLogic";
		internal static readonly string[] CityLogicTypeHints = { "fbs" };

		internal static readonly string[] ObjCityBuildingsMembers =
			{ "buildings" };

		internal static readonly string[] CityLogicObjCityMembers =
			{ "cjgv", "<cjgv>k__BackingField" };

		internal static readonly string[] CityLogicObjCityAccessorMethods =
			{ "biso" };

		internal static readonly string[] ObjCityOwnerSideMembers =
			{ "ownerSide" };

		internal static readonly string[] CityLogicSessionMembers =
			{ "cjhd" };

		internal static readonly string[] SessionDataMembers =
			{ "caan", "<caan>k__BackingField", "uzb" };

		internal static readonly string[] TodaysConstructionsCountFields =
			{ "todaysConstructionsCount" };
	}

	internal static partial class AdventureObjectScoutingLaws
	{
		internal const string DataObjectTypeId = "law.vision.dataObject";
		internal static readonly string[] DataObjectTypeHints = { "Hex.Session.Data.DataObject", "DataObject" };

		internal static readonly string[] DataObjectIdMembers = CustomDwellingRandomHire.DataObjectIdFields;
		internal static readonly string[] DataObjectConfigSidMembers = CustomDwellingRandomHire.DataObjectConfigSidFields;
		internal static readonly string[] DataObjectOwnerSideMembers = CustomDwellingRandomHire.DataObjectOwnerSideFields;

		internal static readonly MethodSymbol ObjectScoutedBySide = new(
			"law.vision.dataObject.scoutedBySide",
			"bgdo",
			"Method_Public_Void_Int32_PDM_0");
	}

	internal static partial class BattleVisual
	{
		internal static readonly string[] BattleControllerTypeNames =
			{ "eaq", "eax" };

		internal static readonly string[] BattleControllerSingletonMembers =
			{ "ceso", "<ceso>k__BackingField" };

		internal static readonly string[] BattleLogicOnControllerMembers =
			{ "cesq", "<cesq>k__BackingField" };

		internal static readonly string[] BattleLogicTransferBattleMembers =
			{ "cfqx", "cfqy", "<cfqx>k__BackingField", "<cfqy>k__BackingField" };

		internal static readonly string[] BattleDrawerTypeNames =
			{ "Object1PublicIncfUnIncfObBhIncfAnUnique", "eck", "ecd" };

		// elw is legacy-only on Golden Era; keep last so multi-hint resolve stays quiet.
		internal static readonly string[] SpawnHelperTypeNames =
			{ "enk", "eni", "enp", "elw" };

		internal static readonly string[] SummonMechanicBaseTypeNames =
			{ "efw" };

		internal static readonly string[] SpawnFactoryTypeNames =
			{ "ObjectPublicObLi1FicfHeLi1IncfUnique", "ebz", "edh", "eda" };

		internal static readonly string[] RawFieldObjectSpawnMethodNames =
			{
				"Method_Public_FieldObject_EFieldObjectType_String_Int32_ObjectPublicPrcgObPrcgInTrPrcgInUnique_Hex_Int32_Boolean_Boolean_Boolean_InterfacePublicAbstractbaBoaObVobabaObInUnique_InterfacePublicAbstractbaObbbUnInbbUnObbbObUnique_0",
				"Method_Public_FieldObject_EFieldObjectType_String_Int32_ObjectPublicPrcgObPrcgInTrPrcgInUnique_Hex_Int32_Boolean_Boolean_Boolean_InterfacePublicAbstractbaBoaObVobabaObInUnique_InterfacePublicAbstractbaObbbUnInbbUnObbbObUnique_PDM_0",
				"bcvc",
				"leh",
			};

		internal static readonly MethodSymbol SpawnObject = new(
			"battle.visual.spawnObject",
			"Method_Public_Static_FieldObject_ObjectPublicObLi1FicfHeLi1IncfUnique_Unit_ObjectPublicPrcgObPrcgInTrPrcgInUnique_Int32_String_Boolean_Boolean_Boolean_0",
			"Method_Public_Static_FieldObject_ObjectPublicObLi1FicfHeLi1IncfUnique_Unit_ObjectPublicPrcgObPrcgInTrPrcgInUnique_Int32_String_Boolean_Boolean_Boolean_1",
			"bffg",
			"fua",
			"ndy",
			"beki",
			"bfdk",
			"bfcl",
			"bpk");

		internal static readonly MethodSymbol TimelineAttackBind = new(
			"battle.visual.timeline.attackBind",
			"bbvf", "bbrl", "bbtf", "bbue", "bbuf", "bbtg");

		internal static readonly string[] BattleUnitTransferFields =
			{ "chgt", "bewg", "<chgt>k__BackingField", "_chgt_k__BackingField", "chfy", "bevh", "<chfy>k__BackingField", "_chfy_k__BackingField", "chey", "chbu", "cggz" };

		internal static readonly string[] BattleUnitConfigSidMembers =
			{ "configSid" };

		internal static readonly string[] BattleUnitLogicConfigFields =
			{ "chgu", "bewi", "<chgu>k__BackingField", "_chgu_k__BackingField", "chfz", "bevj", "<chfz>k__BackingField", "_chfz_k__BackingField", "chjp", "<chjp>k__BackingField", "_chjp_k__BackingField", "chez", "chbv", "cgha" };

		internal static readonly string[] BattleUnitViewConfigFields =
			{ "chgv", "bewk", "<chgv>k__BackingField", "_chgv_k__BackingField", "chga", "bevl", "<chga>k__BackingField", "_chga_k__BackingField", "chjq", "<chjq>k__BackingField", "_chjq_k__BackingField", "chfa", "chbw" };

		internal static readonly string[] BattleControllerInstanceMembers =
			{ "ceuj", "<ceuj>k__BackingField", "ceso", "<ceso>k__BackingField", "bblx", "bbkw", "bbok" };

		internal static readonly string[] BattleControllerSideMembers =
			{ "cevo", "cett", "cnvl", "cntj", "cfmz", "cflf", "bbnn", "bbnw", "bbml", "bbmv" };

		internal static readonly string[] BattleControllerDrawerManagerMembers =
			{ "ceur", "<ceur>k__BackingField", "_ceur_k__BackingField", "bbmm", "cetx", "<cetx>k__BackingField", "_cetx_k__BackingField", "bbll" };

		internal static readonly MethodSymbol DrawerManagerDrawerForUnit = new(
			"battle.visual.drawerManager.drawerForUnit",
			"bbzn", "bbym");

		internal static readonly string[] DrawerSupplementalBaseTypeNames =
			{ "ObjectPublicGacfTrInGaTrcfBoBocfUnique", "edg", "ObjectPublic82cf49Vocfa22Unique", "ecz" };

		internal static readonly string[] DrawerInitGeneratedNamePrefixes =
			{ "Method_Public_Boolean_UnitViewConfig_TransferUnit_Random_Vector3_Single_Boolean_Int32" };

		internal static readonly string[] EcdVisualGameObjectFields =
			{ "field_Private_GameObject_0", "cfbg", "cfam", "cfaj", "cexw", "cexx" };

		internal static readonly string[] CurrentEcdVisualGameObjectFields =
			{ "field_Private_GameObject_0", "cfam", "cfbg" };

		internal static readonly string[] EcdAnimatorFields =
			{ "field_Private_Animator_0", "cfbc", "cfai", "cfaf", "cexs", "cext" };

		internal static readonly string[] CurrentEcdAnimatorFields =
			{ "field_Private_Animator_0", "cfai", "cfbc" };

		internal static readonly string[] EcdSpriteRendererFields =
			{ "field_Private_SpriteRenderer_0", "cfbl", "cfar", "cfao", "ceyb", "ceyc" };

		internal static readonly string[] CurrentEcdSpriteRendererFields =
			{ "field_Private_SpriteRenderer_0", "cfar", "cfbl" };

		internal static readonly string[] EczRootGameObjectFields =
			{ "cflk", "cflm", "cfkq", "cfks", "cfkn", "cfkp", "cfjs", "cezl", "cexw", "cfid", "cfib" };

		internal static readonly string[] CurrentEczMovementGameObjectFields =
			{ "field_Public_GameObject_0", "field_Private_GameObject_2", "field_Public_GameObject_2", "cflk", "cfkq" };

		internal static readonly string[] CurrentEczOrientationGameObjectFields =
			{ "_cfnx_k__BackingField", "<cfnx>k__BackingField", "cfnx", "field_Private_GameObject_1", "field_Public_GameObject_1", "cflm", "cfks" };

		internal static readonly string[] EczRootTransformFields =
			{ "cfll", "cfln", "cfkr", "cfkt", "cfko", "cfkq", "cfjt", "cfic", "cfie" };

		internal static readonly string[] CurrentEczMovementTransformFields =
			{ "_cfnw_k__BackingField", "<cfnw>k__BackingField", "cfnw", "field_Private_Transform_1", "cfll", "cfkr" };

		internal static readonly string[] CurrentEczOrientationTransformFields =
			{ "field_Protected_Transform_0", "field_Private_Transform_0", "cfln", "cfkt" };

		internal static readonly string[] AttackFacingViewUnitMembers =
			{ "cfax", "_cfax_k__BackingField", "<cfax>k__BackingField", "bbvz", "cezc", "_cezc_k__BackingField", "<cezc>k__BackingField", "bbta", "cexn", "hiq", "unit", "_cexn_k__BackingField", "<cexn>k__BackingField" };

		internal static readonly string[] AttackFacingTimelineHelperMembers =
			{ "cfaz", "_cfaz_k__BackingField", "<cfaz>k__BackingField", "bbwd", "ceze", "_ceze_k__BackingField", "<ceze>k__BackingField", "bbue", "cexp", "mlu", "_cexp_k__BackingField", "<cexp>k__BackingField" };

		internal static readonly string[] AttackFacingViewRootGameObjectMembers =
			{ "cezl", "bbuz", "cfjs", "bcrc", "cexw", "cfid", "bvn", "cfib" };

		internal static readonly string[] AttackFacingViewTransformMembers =
			{ "cfic", "lti" };

		/// <summary>
		/// Native unit view helper (mono <c>BhUnitViewHelper</c>: projectileSpawnPoint, projectileEndPoint,
		/// shieldPoint, shieldScale, meshRenderer, idleVFX). Live Golden Era interop
		/// <c>MonoBehaviourPublicTrprshTrprVeSkTrshmeUnique</c> (obfuscated <c>ebe</c>): live ISIL
		/// <c>eaj.bbiz(ESpawnPoint, ebe, ref Vector3, Hex)</c> reads its shieldPoint/projectileEndPoint, and
		/// <c>eck.Init</c> stores <c>meshHolder.GetComponent&lt;ebe&gt;()</c> in <c>eck.&lt;cfdj&gt;k__BackingField</c>.
		/// </summary>
		internal static readonly string[] UnitViewHelperTypeNames =
			{ "MonoBehaviourPublicTrprshTrprVeSkTrshmeUnique", "Hex.Session.Battle.BhUnitViewHelper", "ebe" };

		/// <summary>Unit drawer's view-helper slot (mono <c>UnitDrawer.viewHelper</c>; live <c>eck.&lt;cfdj&gt;k__BackingField</c>).</summary>
		internal static readonly string[] DrawerViewHelperMembers =
			{ "_cfdj_k__BackingField", "<cfdj>k__BackingField", "cfdj", "viewHelper", "_viewHelper_k__BackingField" };

	}

	internal static partial class DialogAvatar
	{
		// Current Golden Era generated names. ISIL proves SlideAvatarBind is the
		// DialogSlideConfig body that calls Resources.Load then BhAvatar.rfu.
		internal const string SlideAvatarBindMethod =
			"Method_Private_Void_DialogSlideConfig_PDM_3";
		internal const string AvatarImageBindMethod =
			"Method_Public_Void_Sprite_Vector2_HashSet_1_EAvatarAnimation_PDM_0";
	}

	/// <summary>
	/// Factory-owned city world scene registrar (Castle-parity LoadScene/Move path).
	/// Pins from live Golden Era Hex.dll reflection — see docs/factory_city_scene_load_pins.md.
	/// Do not port failed playtest city_hive helpers; do not alias onto vanilla Hive cityDemon.
	/// </summary>
	internal static partial class FactoryCityScene
	{
		internal const string FactoryFractionSid = "homm3_factory";
		internal const string FactoryUnitySceneName = "cityFactory";
		internal const string DonorUnitySceneName = "cityHuman2";
		/// <summary>
		/// Frozen-install pin: former unused EScene.cityGnome ordinal, renamed to cityFactory
		/// in global-metadata.dat (see tools/pin_escene_city_factory.py). Interop Hex.dll may
		/// still expose the managed name cityGnome; always use this ordinal for session binds.
		/// All release custom factions share this single spare owned city world.
		/// </summary>
		internal const ushort SessionESceneOrdinal = 26;
		internal const string SessionESceneTokenName = "cityFactory";

		/// <summary>
		/// Custom factions that abandon donor city scenes and present HotA art on cityFactory.
		/// Keep in sync with custom_factions citySceneName=cityFactory and town_scene_refs.
		/// </summary>
		internal static readonly string[] OwnedCityWorldFactionSids =
		{
			"homm3_bulwark",
			"homm3_castle",
			"homm3_conflux",
			"homm3_cove",
			"homm3_dungeon",
			"homm3_factory",
			"homm3_fortress",
			"homm3_inferno",
			"homm3_necropolis",
			"homm3_rampart",
			"homm3_stronghold",
			"homm3_tower"
		};

		internal static bool IsOwnedCityWorldFaction(string fraction)
		{
			if (string.IsNullOrEmpty(fraction))
				return false;
			for (var i = 0; i < OwnedCityWorldFactionSids.Length; i++)
			{
				if (string.Equals(OwnedCityWorldFactionSids[i], fraction, StringComparison.Ordinal))
					return true;
			}
			return false;
		}

		/// <summary>Castle cityHuman2 BhBuilding variant floor from vanilla ledger.</summary>
		internal const int ExpectedBhBuildingCount = 34;
		internal const string BuildingsManagerTypeName = "Hex.Session.City.BhBuildingsManager";
		internal const string BuildingTypeName = "Hex.Session.City.BhBuilding";
		/// <summary>
		/// Town camera driver on the CityCamera pivot and its serialized settings members (plain Unity field names
		/// on the live Golden Era interop, Hex.dll). Framing (Homm3TownScene3d) swaps <c>settings</c> for a scaled clone.
		/// </summary>
		internal const string CityCameraControllerTypeName = "Hex.Session.City.BhCityCameraController";
		internal const string CityCameraSettingsMember = "settings";
		internal const string CityCameraPositionNodesMember = "positionNodes";
		internal const string CityCameraDeltaHorizontalAngleMember = "deltaHorizontalAngle";
		internal const string CityCameraDeltaVerticalAngleMember = "deltaVerticalAngle";

		/// <summary>
		/// Current Golden Era generated interop property for BhBuilding.ceco (dwc), the
		/// native Building logic object used by OnPointerClick. Keep this patch-sensitive
		/// name centralized and fail closed when it drifts.
		/// </summary>
		internal static readonly string BuildingBoundLogicPropertyName =
			"field_Private_ObjectPublicBuObcdStObcdcnInBocnUnique_0";

		/// <summary>
		/// Exact Golden Era BhBuildingsManager.bajs(dwc, bool) body. It returns only after
		/// native dxg.bajn has reconciled a scene slot, making its postfix the presentation
		/// refresh boundary for construction and upgrade changes.
		/// </summary>
		internal static readonly string BuildingMutationMethodName =
			"Method_Private_Void_ObjectPublicBuObcdStObcdcnInBocnUnique_Boolean_PDM_0";

		/// <summary>
		/// Live-positive (cityFactory black screen): after LoadScene(cityHuman2)+Move into a
		/// synthetic cityFactory container, native Void(EScene) leaves these roots inactive.
		/// Activating them restored Castle 3D visibility. Fail closed if either is missing.
		/// </summary>
		internal static readonly string[] RequiredPresentationRootNames =
		{
			"CityCamera",
			"Lights"
		};

		internal const string SceneNameParseTypeId = "factory.cityScene.esceneFromString";
		internal static readonly string[] SceneNameParseTypeHints =
		{
			"ObjectPublicAbstractSealedihESaStjlhxESaStBoUnique"
		};

		internal static readonly MethodSymbol SceneNameParse = new(
			"factory.cityScene.esceneFromString.parse",
			"Method_Public_Static_EScene_String_0",
			"Method_Public_Static_EScene_String_PDM_0",
			"Method_Public_Static_EScene_String_PDM_1",
			"Method_Public_Static_EScene_String_PDM_2");

		internal const string SessionSceneEntryTypeId = "factory.cityScene.sessionSceneEntry";
		internal static readonly string[] SessionSceneEntryTypeHints =
		{
			"ObjectPublicESScbwBoLibw1GacnESUnique"
		};

		/// <summary>
		/// Hex helper that loads/registers scenes by EScene (not SceneManager.LoadScene(string)).
		/// Live-negative: string LoadScene intercept alone never saw cityFactory/cityGnome.
		/// </summary>
		internal const string EsceneSceneLoadTypeId = "factory.cityScene.esceneSceneLoad";
		internal static readonly string[] EsceneSceneLoadTypeHints =
		{
			"ObjectPublicDi2ESObbwUnique"
		};

		internal static readonly MethodSymbol EsceneSceneLoad = new(
			"factory.cityScene.esceneSceneLoad.load",
			"Method_Public_Void_EScene_0",
			"Method_Public_Void_EScene_PDM_0",
			"Method_Public_Void_EScene_PDM_1",
			"Method_Public_Void_EScene_PDM_2",
			"Method_Public_Void_EScene_Boolean_0",
			"Method_Public_Void_EScene_Boolean_PDM_0",
			"Method_Public_Void_EScene_Boolean_PDM_1",
			"Method_Public_Void_EScene_Boolean_PDM_2",
			"Method_Public_Void_EScene_Boolean_PDM_3");

		internal static readonly MethodSymbol EsceneSceneIsLoaded = new(
			"factory.cityScene.esceneSceneLoad.isLoaded",
			"Method_Public_Boolean_EScene_0");

		/// <summary>
		/// Di2 instance dictionary of EScene → session scene entry. Native Void(EScene)
		/// activates through this map (dump name cee.bwjz / ced). Do not skip Void without
		/// a valid entry pointing at a loaded Scene.
		/// </summary>
		internal static readonly string[] EsceneSceneLoadDictionaryMembers =
		{
			"get_field_Private_Dictionary_2_EScene_ObjectPublicESScbwBoLibw1GacnESUnique_0",
			"field_Private_Dictionary_2_EScene_ObjectPublicESScbwBoLibw1GacnESUnique_0"
		};

		internal const string SessionLoaderTypeId = "factory.cityScene.sessionLoader";
		internal static readonly string[] SessionLoaderTypeHints =
		{
			"Hex.Session.Loader"
		};

		internal static readonly MethodSymbol SessionLoaderAllScenesLoaded = new(
			"factory.cityScene.sessionLoader.allScenesLoaded",
			"Method_Protected_Virtual_Void_Il2CppReferenceArray_1_ObjectPublicESScbwBoLibw1GacnESUnique_0");

		/// <summary>Live Golden Era session entry EScene readers (pins doc).</summary>
		internal static readonly string[] SessionEntryEsceneGetterNames =
		{
			"Method_Public_get_EScene_0",
			"prop_EScene_0",
			"_bwnh_k__BackingField"
		};

		/// <summary>Live Golden Era session entry Scene writers (pins doc).</summary>
		internal static readonly string[] SessionEntrySceneSetterNames =
		{
			"field_Private_Scene_0",
			"set_field_Private_Scene_0"
		};

		internal static readonly string[] ExpectedSceneSlotNames =
		{
			"Main",
			"Tier_1",
			"Tier_2",
			"Tier_3",
			"Tier_4",
			"Tier_5",
			"Tier_6",
			"Tier_7",
			"Artifact_Market",
			"Intelligence_Academy",
			"Golden_Calf",
			"Tavern",
			"Magic_Guild",
			"Training_Range",
			"Treasury",
			"Bank",
			"Market",
			"Walls",
			"Resource_Depot",
			"Resource_Depot_2"
		};
	}

	/// <summary>
	/// HoMM3 Tower Artificing on-hit grafts (Homm3TowerArtificingRuntime). Source-prepared 2026-10-25 from the
	/// Golden Era interop (ilspycmd of BepInEx/interop/Hex.dll) and the readable decomp; runtime proof pending.
	/// </summary>
	internal static partial class TowerArtificing
	{
		/// <summary>Hex.Session.Battle.UnitHealer (static).</summary>
		internal static readonly string[] UnitHealerTypeHints =
			{ "ObjectPublicAbstractSealedruVoaUnbIncdInBoUnique", "Hex.Session.Battle.UnitHealer" };

		/// <summary>UnitHealer.Heal(this Unit, int amount, EHealType, bool revive). Not the private (Unit, int, bool, EHealType) copies.</summary>
		internal static readonly MethodSymbol UnitHealerHeal = new(
			"homm3.tower.artificing.unitHealer.heal",
			"Method_Public_Static_Void_Unit_Int32_EHealType_Boolean_0",
			"Heal");

		/// <summary>Hex.Session.Battle.MechBerserk.</summary>
		internal static readonly string[] MechBerserkTypeHints =
			{ "Object1PublicStclLi1HeObclLi1HeUnique", "Hex.Session.Battle.MechBerserk" };

		/// <summary>MechBerserk.ApplyBerserk(Logic, List&lt;Hex&gt;, List&lt;Hex&gt;, FieldObject target, int numActions, HashSet&lt;Unit&gt; killed):
		/// the static MechRevengeBerserk calls from its event handler. Not the _PDM_0 copy.</summary>
		internal static readonly MethodSymbol MechBerserkApply = new(
			"homm3.tower.artificing.mechBerserk.applyBerserk",
			"Method_Public_Static_Void_ObjectPublicPrclInPrclSiBoPrclInUnique_List_1_Hex_List_1_Hex_FieldObject_Int32_HashSet_1_Unit_0",
			"ApplyBerserk");

		/// <summary>CastDealer (ObjectPublicCacodaCaObckObckUnique) → CastDealerConfig; data first (the instance clone), then config.</summary>
		internal static readonly string[] CastDealerConfigMembers =
			{ "data", "config" };

		/// <summary>CastDealerConfig.tags (basic_attack, melee_attack / shoot_attack / range_attack, counter_attack).</summary>
		internal static readonly string[] CastDealerConfigTagsMembers =
			{ "tags" };

		/// <summary>Logic.Hero.RecalculateStats(): rebuilds hero stats from bonuses; native UnitSets calls it on every army change.</summary>
		internal static readonly MethodSymbol LogicHeroRecalculateStats = new(
			"homm3.tower.artificing.logicHero.recalculateStats",
			"Method_Public_Void_1",
			"RecalculateStats");

		/// <summary>Battle Ability.Init(AbilityLogicConfig, AbilityViewConfig, AbilityID) (AbilitiesSet.InitAbilityArray's call). Not the _PDM_0 twin.</summary>
		internal static readonly MethodSymbol AbilityInit = new(
			"homm3.tower.artificing.ability.init",
			"Init");

		/// <summary>Native passive action runner (ejh): one per UnitPassiveConfig action; casts its own effects with itself as castSource.</summary>
		internal static readonly string[] PassiveActionRunnerTypeHints =
			{ "ObjectPublicObckBuObckInObckObckUnique" };

		/// <summary>ejh.befp(object, BattleEventArgs): the trigger handler befm subscribes per trigger; checks conditions,
		/// gathers targets and casts. Not the _PDM_1..3 handlers (nmv, fig, lxi).</summary>
		internal static readonly MethodSymbol PassiveActionRunnerTrigger = new(
			"homm3.tower.artificing.passiveAction.trigger",
			"Method_Private_Void_Object_BattleEventArgs_PDM_0",
			"befp");

		/// <summary>ejh.ckap: the BuffActionConfig the runner executes (config identity vs UnitLogicConfig.passives[i].actions[j]).</summary>
		internal static readonly string[] PassiveActionRunnerConfigMembers =
			{ "field_Private_BuffActionConfig_0", "ckap" };

		/// <summary>ejh.ckak: the owner (caster) the runner acts for; a battle Unit for unit passives.</summary>
		internal static readonly string[] PassiveActionRunnerOwnerMembers =
			{ "field_Private_InterfacePublicAbstractbdObbeUnHebeUnInbeObUnique_0", "ckak" };
	}

	/// <summary>
	/// Build-scoped type hint groups consumed through GameMember.ResolveTypeGroup (the one central type
	/// resolver; the per-file ResolveFirstType copies are gone). Golden scopes reuse the existing hint
	/// arrays and pin the shape of the type the pre-migration first-hint resolver bound on Golden Era;
	/// tools/validate_game_symbols_hint_contract.py proves both, and that each scope reaches exactly one
	/// type of that shape. Current scopes are TypeHintScope.Generated: GameSymbolsCurrent.g.cs fills them
	/// from the P1 remap (tools/port_current/generate_current_symbol_scopes.py) when the group's golden
	/// hints are scoped for that build, and they stay empty (refused) otherwise.
	/// </summary>
	internal static partial class TypeGroups
	{
		// Real-name type that moved namespace; both scopes pinned from their own interop (current: 25509697 base MonoBehaviourPublicBoceBoceUnique).
		internal static readonly TypeHintGroup WarcryHeroAbilityHeroAbilitiesView = new(
			WarcryHeroAbility.HeroAbilitiesViewTypeId,
			golden: new(WarcryHeroAbility.HeroAbilitiesViewTypeHints, new TypeShape("UnityEngine.MonoBehaviour", 42, 53)),
			current: new(WarcryHeroAbility.HeroAbilitiesViewCurrentTypeHints, new TypeShape("MonoBehaviourPublicBoceBoceUnique", 21, 25)));

		// Golden Era: Hex.Session.Data.DataObject (full hint).
		internal static readonly TypeHintGroup AdventureObjectScoutingLawsDataObject = new(
			AdventureObjectScoutingLaws.DataObjectTypeId,
			golden: new(AdventureObjectScoutingLaws.DataObjectTypeHints, new TypeShape("Il2CppSystem.Object", 33, 45)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Data.DataFogOfWar (full hint).
		internal static readonly TypeHintGroup AdventureVisionLawsDataFogOfWar = new(
			AdventureVisionLaws.DataFogOfWarTypeId,
			golden: new(AdventureVisionLaws.DataFogOfWarTypeHints, new TypeShape("Il2CppSystem.Object", 8, 10)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Data.MapMagics (full hint).
		internal static readonly TypeHintGroup AdventureVisionLawsMapMagics = new(
			AdventureVisionLaws.MapMagicsTypeId,
			golden: new(AdventureVisionLaws.MapMagicsTypeHints, new TypeShape("Il2CppSystem.Object", 6, 6)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Map.MapVisionObjectDesc (full hint).
		internal static readonly TypeHintGroup AdventureVisionLawsMapVisionObjectDesc = new(
			AdventureVisionLaws.MapVisionObjectDescTypeId,
			golden: new(AdventureVisionLaws.MapVisionObjectDescTypeHints, new TypeShape("Il2CppSystem.ValueType", 9, 13)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Battle.Unit (full hint).
		internal static readonly TypeHintGroup BattleEventLawsBattleUnit = new(
			BattleEventLaws.BattleUnitTypeId,
			golden: new(BattleEventLaws.BattleUnitTypeHints, new TypeShape("FieldObjectPublicAbstractObUnObcfcnObstcnUnHeUnique", 114, 136)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Battle.CastAbilityEventArgs (full hint).
		internal static readonly TypeHintGroup BattleEventLawsCastAbilityEventArgs = new(
			BattleEventLaws.CastAbilityEventArgsTypeId,
			golden: new(BattleEventLaws.CastAbilityEventArgsTypeHints, new TypeShape("Hex.Session.Battle.BattleEventArgs", 7, 12)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Battle.EnergyUpdateEventArgs (full hint).
		internal static readonly TypeHintGroup BattleEventLawsEnergyUpdateEventArgs = new(
			BattleEventLaws.EnergyUpdateEventArgsTypeId,
			golden: new(BattleEventLaws.EnergyUpdateEventArgsTypeHints, new TypeShape("Hex.Session.Battle.BattleEventArgs", 6, 8)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Battle.EnergyUpdatedByMechEventArgs (full hint).
		internal static readonly TypeHintGroup BattleEventLawsEnergyUpdatedByMechEventArgs = new(
			BattleEventLaws.EnergyUpdatedByMechEventArgsTypeId,
			golden: new(BattleEventLaws.EnergyUpdatedByMechEventArgsTypeHints, new TypeShape("Hex.Session.Battle.BattleEventArgs", 4, 6)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Battle.ObjectDestroyedEventArgs (full hint).
		internal static readonly TypeHintGroup BattleEventLawsObjectDestroyedEventArgs = new(
			BattleEventLaws.ObjectDestroyedEventArgsTypeId,
			golden: new(BattleEventLaws.ObjectDestroyedEventArgsTypeHints, new TypeShape("Hex.Session.Battle.BattleEventArgs", 5, 8)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Battle.ObjectSpawnedEventArgs (full hint).
		internal static readonly TypeHintGroup BattleEventLawsObjectSpawnedEventArgs = new(
			BattleEventLaws.ObjectSpawnedEventArgsTypeId,
			golden: new(BattleEventLaws.ObjectSpawnedEventArgsTypeHints, new TypeShape("Hex.Session.Battle.BattleEventArgs", 3, 4)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Battle.ObjectTookDamageEventArgs (full hint).
		internal static readonly TypeHintGroup BattleEventLawsObjectTookDamageEventArgs = new(
			BattleEventLaws.ObjectTookDamageEventArgsTypeId,
			golden: new(BattleEventLaws.ObjectTookDamageEventArgsTypeHints, new TypeShape("Hex.Session.Battle.BattleEventArgs", 11, 20)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Battle.SideUsedEnergyEventArgs (full hint).
		internal static readonly TypeHintGroup BattleEventLawsSideUsedEnergyEventArgs = new(
			BattleEventLaws.SideUsedEnergyEventArgsTypeId,
			golden: new(BattleEventLaws.SideUsedEnergyEventArgsTypeHints, new TypeShape("Hex.Session.Battle.BattleEventArgs", 3, 4)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Battle.UnitPosChangedEventArgs (full hint).
		internal static readonly TypeHintGroup BattleEventLawsUnitPosChangedEventArgs = new(
			BattleEventLaws.UnitPosChangedEventArgsTypeId,
			golden: new(BattleEventLaws.UnitPosChangedEventArgsTypeHints, new TypeShape("Hex.Session.Battle.BattleEventArgs", 2, 2)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Battle.UnitStartedMovementEventArgs (full hint).
		internal static readonly TypeHintGroup BattleEventLawsUnitStartedMovementEventArgs = new(
			BattleEventLaws.UnitStartedMovementEventArgsTypeId,
			golden: new(BattleEventLaws.UnitStartedMovementEventArgsTypeHints, new TypeShape("Hex.Session.Battle.BattleEventArgs", 8, 14)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Data.BuildingData (full hint).
		internal static readonly TypeHintGroup ConstructionCommitLawsBuildingData = new(
			ConstructionCommitLaws.BuildingDataTypeId,
			golden: new(ConstructionCommitLaws.BuildingDataTypeHints, new TypeShape("Il2CppSystem.Object", 21, 29)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Data.BuildingsData (full hint).
		internal static readonly TypeHintGroup ConstructionCommitLawsBuildingsData = new(
			ConstructionCommitLaws.BuildingsDataTypeId,
			golden: new(ConstructionCommitLaws.BuildingsDataTypeHints, new TypeShape("Il2CppSystem.Object", 26, 46)),
			current: TypeHintScope.Generated);

		// Golden Era: Object1PublicObInObcjcoObcjInObcjUnique (obf hint).
		internal static readonly TypeHintGroup ConstructionCommitLawsCityLogic = new(
			ConstructionCommitLaws.CityLogicTypeId,
			golden: new(ConstructionCommitLaws.CityLogicTypeHints, new TypeShape("ObjectPublicObcjDaBoObcoDacjBoObUnique", 99, 111)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Data.ObjCity (full hint).
		internal static readonly TypeHintGroup ConstructionCommitLawsObjCity = new(
			ConstructionCommitLaws.ObjCityTypeId,
			golden: new(ConstructionCommitLaws.ObjCityTypeHints, new TypeShape("Hex.Session.Data.DataObject", 23, 33)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.UI.City.BhUIBuildingSession (full hint).
		internal static readonly TypeHintGroup ConstructionLawsBuildingSession = new(
			ConstructionLaws.BuildingSessionTypeId,
			golden: new(ConstructionLaws.BuildingSessionTypeHints, new TypeShape("Hex.UI.BhScreen", 30, 45)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.UI.City.BhBuildingView (full hint).
		internal static readonly TypeHintGroup ConstructionLawsBuildingView = new(
			ConstructionLaws.BuildingViewTypeId,
			golden: new(ConstructionLaws.BuildingViewTypeHints, new TypeShape("UnityEngine.MonoBehaviour", 97, 143)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.City.BhBuildingsManager (full hint).
		internal static readonly TypeHintGroup ConstructionLawsBuildingsManager = new(
			ConstructionLaws.BuildingsManagerTypeId,
			golden: new(ConstructionLaws.BuildingsManagerTypeHints, new TypeShape("UnityEngine.MonoBehaviour", 14, 18)),
			current: TypeHintScope.Generated);

		// Golden Era: ObjectPublicObcfBocfBocfBocfBocfUnique (obf hint).
		internal static readonly TypeHintGroup CounterattackCorrelationLawsAbilityListener = new(
			CounterattackCorrelationLaws.AbilityListenerTypeId,
			golden: new(CounterattackCorrelationLaws.AbilityListenerTypeHints, new TypeShape("Il2CppSystem.Object", 89, 118)),
			current: TypeHintScope.Generated);

		// Golden Era: ObjectPublicObceDiObce2EAInBoInUnique (obf hint).
		internal static readonly TypeHintGroup CounterattackCorrelationLawsAbilityManager = new(
			CounterattackCorrelationLaws.AbilityManagerTypeId,
			golden: new(CounterattackCorrelationLaws.AbilityManagerTypeHints, new TypeShape("Il2CppSystem.Object", 124, 135)),
			current: TypeHintScope.Generated);

		// Golden Era: ObjectPublicObceInBoInceAbObELInUnique (obf hint).
		internal static readonly TypeHintGroup CounterattackCorrelationLawsAbilityRuntime = new(
			CounterattackCorrelationLaws.AbilityRuntimeTypeId,
			golden: new(CounterattackCorrelationLaws.AbilityRuntimeTypeHints, new TypeShape("Il2CppSystem.Object", 101, 116)),
			current: TypeHintScope.Generated);

		// Golden Era: Object1PublicIncaBoIncaVoaVobcaUnique (obf hint).
		internal static readonly TypeHintGroup CounterattackCorrelationLawsBattleAttackCommand = new(
			CounterattackCorrelationLaws.BattleAttackCommandTypeId,
			golden: new(CounterattackCorrelationLaws.BattleAttackCommandTypeHints, new TypeShape("ObjectPublicAbstractByInbsInbsByInbsbsUnique", 7, 8)),
			current: TypeHintScope.Generated);

		// Golden Era: ObjectPublicSicfInSicfHeInBySicfUnique (obf hint).
		internal static readonly TypeHintGroup CounterattackCorrelationLawsBattleLogic = new(
			CounterattackCorrelationLaws.BattleLogicTypeId,
			golden: new(CounterattackCorrelationLaws.BattleLogicTypeHints, new TypeShape("Il2CppSystem.Object", 38, 47)),
			current: TypeHintScope.Generated);

		// Golden Era: ObjectPublicObceInBoInceAbObELInUnique (obf hint).
		internal static readonly TypeHintGroup CounterstrokeDoctrineAbilityExecution = new(
			CounterstrokeDoctrine.AbilityExecutionTypeId,
			golden: new(CounterstrokeDoctrine.AbilityExecutionTypeHints, new TypeShape("Il2CppSystem.Object", 101, 116)),
			current: TypeHintScope.Generated);

		// Golden Era: ObjectPublicAbstractSealedddBoaDabeVo95abhmUnique (obf hint).
		internal static readonly TypeHintGroup CounterstrokeDoctrineDamageCalculator = new(
			CounterstrokeDoctrine.DamageCalculatorTypeId,
			golden: new(CounterstrokeDoctrine.DamageCalculatorTypeHints, new TypeShape("Il2CppSystem.Object", 20, 20)),
			current: TypeHintScope.Generated);

		// Golden Era: ObjectPublicPrcfEvPrcf1BaPrcfEvUnique (obf hint).
		internal static readonly TypeHintGroup CounterstrokeDoctrineEventDispatcher = new(
			CounterstrokeDoctrine.EventDispatcherTypeId,
			golden: new(CounterstrokeDoctrine.EventDispatcherTypeHints, new TypeShape("Il2CppSystem.Object", 557, 649)),
			current: TypeHintScope.Generated);

		// Golden Era: ObjectPublicObceInBoInceAbObELInUnique (obf hint).
		internal static readonly TypeHintGroup DirectStateLawsUnitAbility = new(
			DirectStateLaws.UnitAbilityTypeId,
			golden: new(DirectStateLaws.UnitAbilityTypeHints, new TypeShape("Il2CppSystem.Object", 101, 116)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Data.ResHeap (full hint).
		internal static readonly TypeHintGroup EconomyLawsResHeapData = new(
			EconomyLaws.ResHeapDataTypeId,
			golden: new(EconomyLaws.ResHeapDataTypeHints, new TypeShape("Il2CppSystem.Object", 13, 21)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Data.Resource (full hint).
		internal static readonly TypeHintGroup EconomyLawsResourceData = new(
			EconomyLaws.ResourceDataTypeId,
			golden: new(EconomyLaws.ResourceDataTypeHints, new TypeShape("Il2CppSystem.Object", 8, 9)),
			current: TypeHintScope.Generated);

		// Golden Era: ObjectPublicIncgInObcgObIncgIncgUnique (obf hint).
		internal static readonly TypeHintGroup FocusLawsEnergyManager = new(
			FocusLaws.EnergyManagerTypeId,
			golden: new(FocusLaws.EnergyManagerTypeHints, new TypeShape("Il2CppSystem.Object", 54, 63)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Battle.EnergyUpdateEventArgs (full hint).
		internal static readonly TypeHintGroup FocusLawsEnergyUpdateEventArgs = new(
			FocusLaws.EnergyUpdateEventArgsTypeId,
			golden: new(FocusLaws.EnergyUpdateEventArgsTypeHints, new TypeShape("Hex.Session.Battle.BattleEventArgs", 6, 8)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Battle.EnergyUpdatedByMechEventArgs (full hint).
		internal static readonly TypeHintGroup FocusLawsEnergyUpdatedByMechEventArgs = new(
			FocusLaws.EnergyUpdatedByMechEventArgsTypeId,
			golden: new(FocusLaws.EnergyUpdatedByMechEventArgsTypeHints, new TypeShape("Hex.Session.Battle.BattleEventArgs", 4, 6)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.UI.BhHeroAbilitiyView (full hint).
		internal static readonly TypeHintGroup FocusLawsHeroAbilityButtonView = new(
			FocusLaws.HeroAbilityButtonViewTypeId,
			golden: new(FocusLaws.HeroAbilityButtonViewTypeHints, new TypeShape("UnityEngine.MonoBehaviour", 28, 37)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.UI.BhHeroAbilitiesView (full hint).
		internal static readonly TypeHintGroup FocusLawsHeroAbilityContainerView = new(
			FocusLaws.HeroAbilityContainerViewTypeId,
			golden: new(FocusLaws.HeroAbilityContainerViewTypeHints, new TypeShape("UnityEngine.MonoBehaviour", 42, 53)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Battle.SideUsedEnergyEventArgs (full hint).
		internal static readonly TypeHintGroup FocusLawsSideUsedEnergyEventArgs = new(
			FocusLaws.SideUsedEnergyEventArgsTypeId,
			golden: new(FocusLaws.SideUsedEnergyEventArgsTypeHints, new TypeShape("Hex.Session.Battle.BattleEventArgs", 3, 4)),
			current: TypeHintScope.Generated);

		// Golden Era: ObjectPublicHeObInObciSiObVeSeObUnique (obf hint).
		internal static readonly TypeHintGroup HomecomingBoatTravelWorldHero = new(
			HomecomingBoatTravel.WorldHeroTypeId,
			golden: new(HomecomingBoatTravel.WorldHeroTypeHints, new TypeShape("Il2CppSystem.Object", 219, 238)),
			current: TypeHintScope.Generated);

		// Golden Era: MonoBehaviourPublicObmeGarenoGareObarchUnique (full hint).
		internal static readonly TypeHintGroup HomecomingBoatTravelWorldOwner = new(
			HomecomingBoatTravel.WorldOwnerTypeId,
			golden: new(HomecomingBoatTravel.WorldOwnerTypeHints, new TypeShape("UnityEngine.MonoBehaviour", 228, 280)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.BhWorldCamera (full hint).
		internal static readonly TypeHintGroup HomecomingLayerViewToggleWorldCamera = new(
			HomecomingLayerViewToggle.WorldCameraTypeId,
			golden: new(HomecomingLayerViewToggle.WorldCameraTypeHints, new TypeShape("UnityEngine.MonoBehaviour", 67, 81)),
			current: TypeHintScope.Generated);

		// Golden Era: ObjectPublicPrcfInPrcfSiBoPrcfInUnique (full hint).
		internal static readonly TypeHintGroup MoraleTriggerLawsBattleLogic = new(
			MoraleTriggerLaws.BattleLogicTypeId,
			golden: new(MoraleTriggerLaws.BattleLogicTypeHints, new TypeShape("Il2CppSystem.Object", 210, 257)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Data.DataRewardSets (full hint).
		internal static readonly TypeHintGroup RewardCommitLawsDataRewardSets = new(
			RewardCommitLaws.DataRewardSetsTypeId,
			golden: new(RewardCommitLaws.DataRewardSetsTypeHints, new TypeShape("Il2CppSystem.Object", 6, 7)),
			current: TypeHintScope.Generated);

		// Golden Era: ObjectPrivateviVoaAc172b8058viUnique (obf hint).
		internal static readonly TypeHintGroup RewardCommitLawsRewardApplier = new(
			RewardCommitLaws.RewardApplierTypeId,
			golden: new(RewardCommitLaws.RewardApplierTypeHints, new TypeShape("Il2CppSystem.Object", 71, 70)),
			current: TypeHintScope.Generated);

		// Golden Era: ObjectPublicObbqMaSebqMaDaNobqQuUnique (obf hint).
		internal static readonly TypeHintGroup RmgMapCaptureMapContainer = new(
			RmgMapCapture.MapContainerTypeId,
			golden: new(RmgMapCapture.MapContainerTypeHints, new TypeShape("Il2CppSystem.Object", 33, 43)),
			current: TypeHintScope.Generated);

		// Golden Era: ObjectPublicObcfInStcfInObcnMacfUnique (obf hint).
		internal static readonly TypeHintGroup SpellCastGateLawsBattleSpellLogic = new(
			SpellCastGateLaws.BattleSpellLogicTypeId,
			golden: new(SpellCastGateLaws.BattleSpellLogicTypeHints, new TypeShape("Il2CppSystem.Object", 61, 68)),
			current: TypeHintScope.Generated);

		// Golden Era: ObjectPublicObDi2StIncfESDi2LiUnique (obf hint).
		internal static readonly TypeHintGroup SpellCastGateLawsBattleSpellPool = new(
			SpellCastGateLaws.BattleSpellPoolTypeId,
			golden: new(SpellCastGateLaws.BattleSpellPoolTypeHints, new TypeShape("Il2CppSystem.Object", 77, 89)),
			current: TypeHintScope.Generated);

		// Golden Era: ObjectPublicObcfInStcfInObcnMacfUnique (obf hint).
		internal static readonly TypeHintGroup SpellCooldownLawsBattleSpellLogic = new(
			SpellCooldownLaws.BattleSpellLogicTypeId,
			golden: new(SpellCooldownLaws.BattleSpellLogicTypeHints, new TypeShape("Il2CppSystem.Object", 61, 68)),
			current: TypeHintScope.Generated);

		// Golden Era: ObjectPublicObDi2StIncfESDi2LiUnique (obf hint).
		internal static readonly TypeHintGroup SpellCooldownLawsBattleSpellPool = new(
			SpellCooldownLaws.BattleSpellPoolTypeId,
			golden: new(SpellCooldownLaws.BattleSpellPoolTypeHints, new TypeShape("Il2CppSystem.Object", 77, 89)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Battle.CastMagicEventArgs (full hint).
		internal static readonly TypeHintGroup SpellbookLawsCastMagicEventArgs = new(
			SpellbookLaws.CastMagicEventArgsTypeId,
			golden: new(SpellbookLaws.CastMagicEventArgsTypeHints, new TypeShape("Hex.Session.Battle.BattleEventArgs", 11, 17)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Data.DataMagics (full hint).
		internal static readonly TypeHintGroup SpellbookLawsDataMagics = new(
			SpellbookLaws.DataMagicsTypeId,
			golden: new(SpellbookLaws.DataMagicsTypeHints, new TypeShape("Il2CppSystem.Object", 8, 8)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.Data.HeroMagics (full hint).
		internal static readonly TypeHintGroup SpellbookLawsHeroMagics = new(
			SpellbookLaws.HeroMagicsTypeId,
			golden: new(SpellbookLaws.HeroMagicsTypeHints, new TypeShape("Il2CppSystem.Object", 6, 6)),
			current: TypeHintScope.Generated);

		// Golden Era: Hex.Session.UI.BhMagicBookView (full hint).
		internal static readonly TypeHintGroup SpellbookLawsMagicBookView = new(
			SpellbookLaws.MagicBookViewTypeId,
			golden: new(SpellbookLaws.MagicBookViewTypeHints, new TypeShape("UnityEngine.MonoBehaviour", 34, 51)),
			current: TypeHintScope.Generated);

		// Current-only: no verified ObjHire world object on Golden Era (CustomDwellingHire.HireWorldObjectTypeHints
		// stays empty there). Build 25672315: native fmz, ctor(ObjHire), fields cowo ObjHire / cowp ObjHireConfig;
		// shape from the 25672315 interop shape index. Keep this group last (no golden shape to parse).
		internal static readonly TypeHintGroup CustomDwellingHireWorldObject = new(
			CustomDwellingHire.HireWorldObjectTypeId,
			golden: TypeHintScope.None,
			current: new(CustomDwellingHire.HireWorldObjectCurrentTypeHints, new TypeShape("ObjectPublicObcoDaBoObLi1ObcucoUnique", 33, 37)));
	}
}
