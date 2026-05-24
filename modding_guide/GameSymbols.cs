using System;

namespace OfflineUnlockMod;

// Semantic registry for hotfix-sensitive obfuscated game symbols. If a Steam
// hotfix only renames obfuscated members, update this file first instead of
// scattering find/replace edits across hook implementations.
internal static class GameSymbols
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

	internal static class BattleForecast
	{
		internal const string CalculatorTypeId = "battle.forecast.calculator";
		internal static readonly string[] CalculatorTypeHints = { "elj", "eky", "elc" };
	}

	internal static class TerrainMaterial
	{
		internal static readonly MethodSymbol InstanceGetter = new(
			"terrain.material.instance.getter",
			"kwa", "kvm", "kuz");

		internal static readonly MethodSymbol MaterialGetter = new(
			"terrain.material.material.getter",
			"kwb", "kvn", "kva");

		internal const string RendererTypeId = "terrain.material.renderer";
		internal const string RendererTypeHint = "beg";

		internal static readonly MethodSymbol RendererBuildMap = new(
			"terrain.material.renderer.buildMap",
			"kwg", "kvs");

		internal static readonly MethodSymbol RendererPrepareMap = new(
			"terrain.material.renderer.prepareMap",
			"kwc", "jmr", "kvo");

		internal static readonly MethodSymbol RendererRebuildMaterialArrays = new(
			"terrain.material.renderer.rebuildMaterialArrays",
			"nac", "ivz", "kwe", "bbd");

		internal static readonly MethodSymbol RendererPackMaterialTextures = new(
			"terrain.material.renderer.packMaterialTextures",
			"hd", "kvq");

		internal static readonly MethodSymbol RendererApplyMaterialGlobals = new(
			"terrain.material.renderer.applyMaterialGlobals",
			"lqt", "kvr");

		internal static readonly FieldSymbol[] RendererMaterialLookups =
		{
			new("terrain.material.renderer.materialLookup.may21", "NativeFieldInfoPtr_bsge", "bsge"),
			new("terrain.material.renderer.roadLookup.may21", "NativeFieldInfoPtr_bsgi", "bsgi"),
			new("terrain.material.renderer.materialLookup", "NativeFieldInfoPtr_bseu", "bseu"),
			new("terrain.material.renderer.roadLookup", "NativeFieldInfoPtr_bsey", "bsey"),
			new("terrain.material.renderer.materialLookup.oldMay", "NativeFieldInfoPtr_bsdu", "bsdu"),
			new("terrain.material.renderer.roadLookup.oldMay", "NativeFieldInfoPtr_bsdy", "bsdy"),
			new("terrain.material.renderer.materialLookup.old", "NativeFieldInfoPtr_bscg", "bscg"),
			new("terrain.material.renderer.roadLookup.old", "NativeFieldInfoPtr_bsck", "bsck")
		};

	}

	internal static class TerrainSound
	{
		internal const string HeroBiomeSoundTypeId = "terrain.sound.heroBiome";
		internal const string HeroBiomeSoundTypeHint = "eza";

		internal static readonly MethodSymbol HeroBiomeBuildMap = new(
			"terrain.sound.heroBiome.buildMap",
			"bias", "bhzp");

		internal static readonly MethodSymbol HeroBiomeLookupByTileCode = new(
			"terrain.sound.heroBiome.lookupByTileCode",
			"biat", "bhzq", "get_Item", "fvl", "mij");

		internal static readonly FieldSymbol HeroBiomeSoundByTileCode = new(
			"terrain.sound.heroBiome.soundByTileCode",
			"NativeFieldInfoPtr_ciwe",
			"ciwe");

		internal static readonly FieldSymbol[] HeroBiomeStaticArrays =
		{
			new("terrain.sound.heroBiome.soundByTileCode", "NativeFieldInfoPtr_ciwe", "ciwe"),
			new("terrain.sound.heroBiome.selector.soundByTileCode", "NativeFieldInfoPtr_civj", "civj")
		};

		internal static readonly FieldSymbol[] HeroBiomeInstanceArrays =
		{
			new("terrain.sound.heroBiome.instanceByTileCode", "NativeFieldInfoPtr_ciwc", "ciwc"),
			new("terrain.sound.heroBiome.instanceByTileCode.oldMay", "NativeFieldInfoPtr_civh", "civh")
		};

		internal static readonly FieldSymbol[] HeroBiomeSelectorFields =
		{
			new("terrain.sound.heroBiome.selector", "NativeFieldInfoPtr_ciws", "ciws")
		};

		internal const string HeroBiomeControllerTypeId = "terrain.sound.heroBiome.controller";
		internal const string HeroBiomeControllerTypeHint = "ezh";

		internal static readonly MethodSymbol HeroBiomeControllerLifecycle = new(
			"terrain.sound.heroBiome.controller.lifecycle",
			"Init", "hva", "huz");

		internal static readonly FieldSymbol[] HeroBiomeControllerSelectorFields =
		{
			new("terrain.sound.heroBiome.controller.selector", "NativeFieldInfoPtr_cixn", "cixn")
		};

		internal const string AmbientBiomeSoundTypeId = "terrain.sound.ambientBiome";
		internal const string AmbientBiomeSoundTypeHint = "ezb";

		internal static readonly MethodSymbol AmbientBiomeBuild = new(
			"terrain.sound.ambientBiome.build",
			"biav", "bhzs");

		internal static readonly MethodSymbol AmbientBiomeGetVolumes = new(
			"terrain.sound.ambientBiome.getVolumes",
			"GetSoundsVolume", "iwv", "ch", "fiw");

		internal static readonly FieldSymbol AmbientSoundByTileCode = new(
			"terrain.sound.ambientBiome.soundByTileCode",
			"NativeFieldInfoPtr_ciwk",
			"ciwk");

		internal static readonly FieldSymbol[] AmbientInstanceArrays =
		{
			new("terrain.sound.ambientBiome.counts", "NativeFieldInfoPtr_ciwg", "ciwg"),
			new("terrain.sound.ambientBiome.volumes", "NativeFieldInfoPtr_ciwh", "ciwh"),
			new("terrain.sound.ambientBiome.activeTypes", "NativeFieldInfoPtr_ciwi", "ciwi")
		};

		internal const string AmbientFogControllerTypeId = "terrain.sound.ambientFogController";
		internal const string AmbientFogControllerTypeHint = "ezg";

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

	internal static class DamageKill
	{
		internal static readonly string[] UnitDataFields =
			{ "chgw", "<chgw>k__BackingField", "cghc", "chgb" };

		internal static readonly MethodSymbol UnitStatsGetter = new(
			"battle.damageKill.unitStats.getter",
			"bewo", "bewq", "bcbb");

		internal static readonly MethodSymbol UnitDataGetter = new(
			"battle.damageKill.unitData.getter",
			"bewm");

		internal static readonly MethodSymbol StackCountGetter = new(
			"battle.damageKill.stackCount.getter",
			"bbaz", "bbcg", "bajq", "bayd", "ish", "crf", "bbak");

		internal static readonly string[] HpLastUnitFields =
			{ "chmb", "cgmp" };

		internal static readonly string[] AllStacksFields =
			{ "fullStacks", "cmxs" };

		internal static readonly string[] HpPerFallbackFields =
			{ "chmb", "cgmk" };
	}

	internal static class DamageForecast
	{
		internal static readonly string[][] FieldGroups =
		{
			new[] { "chan", "chao", "chai", "chaj" },
			new[] { "chai", "chaj", "chan", "chao" },
			new[] { "cgau", "cgav", "cgaz", "cgba" },
			new[] { "cgwy", "cgwz", "cgxd", "cgxe" }
		};
	}

	internal static class DamageRetaliation
	{
		internal static readonly MethodSymbol CasterSourceGetter = new(
			"battle.damageRetaliation.casterSource.getter",
			"bbbb", "bajs");
	}

	internal static class SelectedUnitHud
	{
		internal static readonly MethodSymbol HudEventBind = new(
			"battle.selectedUnit.hud.eventBind",
			"behr", "begs", "befw", "beeu", "begr", "befv", "beet");

		internal static readonly MethodSymbol HudDirectBind = new(
			"battle.selectedUnit.hud.directBind",
			"behs", "begt", "begs", "befw", "beia");

		internal static readonly MethodSymbol ControlsClick = new(
			"battle.selectedUnit.controls.click",
			"bejs", "beit", "beis", "behw");

		internal static readonly MethodSymbol ControlsHotkey = new(
			"battle.selectedUnit.controls.hotkey",
			"beki", "bejj", "beji", "beim");

		internal static readonly MethodSymbol AbilityViewBind = new(
			"battle.selectedUnit.abilityView.bind",
			"bejc");

		internal static readonly MethodSymbol AbilityViewBaseFocusMarkers = new(
			"battle.selectedUnit.abilityViewBase.focusMarkers",
			"uga", "ucx", "ufi");

		internal static readonly string[] AbilityViewWrapperTypeNames =
			{ "elz", "els" };

		internal static readonly MethodSymbol AbilityWrapperTryGetAbility = new(
			"battle.selectedUnit.abilityWrapper.tryGetAbility",
			"besi", "beri", "flz", "eca", "berj", "lqt", "hgc", "jdi", "kvk", "mll", "fd", "mzp", "beqo", "gfs", "zp");

		internal static readonly MethodSymbol ControlsBind = new(
			"battle.selectedUnit.controls.bindAbilities",
			"bejr", "beis", "beir", "behv");

		internal static readonly MethodSymbol ControlsClickEnabled = new(
			"battle.selectedUnit.controls.setClickEnabled",
			"bekd", "beje", "beii", "bejd", "beih");

		internal static readonly MethodSymbol ControlsSelect = new(
			"battle.selectedUnit.controls.selectAbility",
			"bejx", "beiy", "beic", "beix", "beib");

		internal static readonly MethodSymbol AbilityBucket = new(
			"battle.selectedUnit.abilityManager.bucket",
			"baox", "jus", "itp", "mpy", "bana", "bama", "baoa", "banz", "klu", "ihh", "fnd", "fsk", "bar", "drf");

		internal static readonly string[] AbilityManagerFields =
			{ "cfkv", "<cfkv>k__BackingField", "_cfkv_k__BackingField", "cfkb", "<cfkb>k__BackingField", "_cfkb_k__BackingField" };

		internal static readonly MethodSymbol AbilityManagerGetter = new(
			"battle.selectedUnit.abilityManager.getter",
			"bcsn", "bcrm");

		internal static readonly string[] AbilityLogicFields =
			{ "cegq", "ceex", "<ceex>k__BackingField", "ceeu", "<ceeu>k__BackingField", "cech", "cedw", "cdgt" };

		internal static readonly string[] AbilityViewFields =
			{ "cegr", "ceey", "<ceey>k__BackingField", "ceev", "<ceev>k__BackingField", "ceci", "cedx", "cdgu" };

		internal static readonly string[] AbilityViewAbilityFields =
			{ "cgxk", "cgwp", "cgwm", "cgvp", "cnvi", "cgua" };

		internal static readonly string[] AbilityViewWrapperFields =
			{ "cgxj", "cgwo", "cgvr", "cgwl", "cgvo", "cgtz" };

		internal static readonly string[] ControlsSelectedViewFields =
			{ "cgxt", "cgwy", "cgwv", "cgvy", "cguj" };

		internal static readonly string[] ControlsCurrentAbilityArrayFields =
			{ "cgxu", "cgwz", "cgvz", "cguk" };
	}

	internal static class UnitPreviewAbilityIcons
	{
		internal static readonly MethodSymbol AbilityItemPrimaryBind = new(
			"unit.preview.abilityItem.primaryBind",
			"baly");

		internal static readonly MethodSymbol AbilityItemSecondaryBind = new(
			"unit.preview.abilityItem.secondaryBind",
			"balz");

		internal static readonly MethodSymbol AbilityViewPrimaryBind = new(
			"unit.preview.abilityView.primaryBind",
			"bama");

		internal static readonly MethodSymbol AbilityViewSecondaryBind = new(
			"unit.preview.abilityView.secondaryBind",
			"bamb");

		internal static readonly MethodSymbol HireUnitAbilitiesBind = new(
			"unit.preview.hireUnitAbilities.bind",
			"hue");

		internal static readonly string[] ConfigRootMembers =
			{ "cnbn", "bxmi", "cnaq" };

		internal static readonly string[] UnitLogicConfigTables =
			{ "bxnu", "bxmk" };

		internal static readonly string[] UnitViewConfigTables =
			{ "bxnv", "bxml" };

		internal static readonly MethodSymbol ConfigTableTryGet = new(
			"unit.preview.configTable.tryGet",
			"rub", "rto");

		internal static readonly string[] UnitLogicConfigFields =
			{ "chgu", "<chgu>k__BackingField", "_chgu_k__BackingField", "bewi", "chfz", "<chfz>k__BackingField", "_chfz_k__BackingField", "bevj", "chez", "chbv", "cgha" };

		internal static readonly string[] UnitViewConfigFields =
			{ "chgv", "<chgv>k__BackingField", "_chgv_k__BackingField", "bewk", "chga", "<chga>k__BackingField", "_chga_k__BackingField", "bevl", "chfa", "chbw" };

	}

	internal static class UnitAbilityNative
	{
		internal static readonly MethodSymbol UnitAbilityAvailability = new(
			"unitAbility.native.unitAbility.availability",
			"lis");

		internal static readonly MethodSymbol ControlsNativeUnitBind = new(
			"unitAbility.native.controls.unitBind",
			"dng");
	}

	internal static class BattleUi
	{
		internal static readonly MethodSymbol SelectedHudEventBind = new(
			"battle.ui.selectedHud.eventBind",
			"behr", "begs", "beic", "begr", "beib");

		internal static readonly MethodSymbol SelectedHudDirectBind = new(
			"battle.ui.selectedHud.directBind",
			"behs", "begt", "beib", "begs", "beia");

		internal static readonly MethodSymbol SelectedUnitViewBind = new(
			"battle.ui.selectedUnitView.bind",
			"behx", "begy", "begc", "befa", "beig", "begx", "begb", "beez", "beif");

		internal static readonly MethodSymbol QueueLayout = new(
			"battle.ui.queue.layout",
			"beef", "bede", "becg", "bedf", "bech", "jnk", "bebg");

		internal static readonly string[] TurnItemTypeNames =
			{ "elx", "elq", "elm" };

		internal static readonly string[] TurnItemUnitFields =
			{ "chbr", "chaw", "chat", "cgzw", "cgyh", "cgwt", "cgxm", "unit", "_unit" };

		internal static readonly string[] TurnItemViewFields =
			{ "chbt", "chay", "chav", "cgzy", "cgyj", "cgwv", "view", "turnView" };

		internal static readonly string[] TurnItemKnownUnitFields =
			{ "chbr", "chaw", "chat", "cgzw", "cgyh" };

		internal static readonly string[] TurnItemKnownViewFields =
			{ "chbt", "chay", "chav", "cgzy", "cgyj" };

		internal static readonly string[] TurnViewUnitFields =
			{ "cgva", "cgvu", "_cgvu_k__BackingField", "<cgvu>k__BackingField", "cgux", "cgti", "cgru", "unit", "_unit", "cgyh" };

		internal static readonly string[] UnitTransferFields =
			{ "chgt", "bewg", "<chgt>k__BackingField", "chfy", "bevh", "<chfy>k__BackingField", "chfv", "<chfv>k__BackingField", "chcp", "<chcp>k__BackingField", "chbu", "<chbu>k__BackingField", "cggz" };

		internal static readonly string[] UnitConfigIdFields =
			{ "chgu", "bewi", "<chgu>k__BackingField", "chgv", "bewk", "<chgv>k__BackingField", "chgw", "bewm", "<chgw>k__BackingField", "chgt", "bewg", "<chgt>k__BackingField", "chfz", "bevj", "<chfz>k__BackingField", "chga", "bevl", "<chga>k__BackingField", "chgb", "bevn", "<chgb>k__BackingField", "chfw", "<chfw>k__BackingField", "chfx", "<chfx>k__BackingField", "chfy", "bevh", "<chfy>k__BackingField", "chbv", "<chbv>k__BackingField", "chbw", "<chbw>k__BackingField", "cgha" };

		internal static readonly string[] UnitShapeNestedFields =
			{ "chgt", "chgu", "chgv", "chgw", "<chgt>k__BackingField", "<chgu>k__BackingField", "<chgv>k__BackingField", "<chgw>k__BackingField", "chfy", "chfz", "chga", "chgb", "<chfy>k__BackingField", "<chfz>k__BackingField", "<chga>k__BackingField", "<chgb>k__BackingField", "chfv", "chfw", "chfx", "chfy", "<chfv>k__BackingField", "<chfw>k__BackingField", "<chfx>k__BackingField", "<chfy>k__BackingField", "chcp", "chcq", "chcr", "_chcp_k__BackingField", "_chcq_k__BackingField", "_chcr_k__BackingField", "<chcp>k__BackingField", "<chcq>k__BackingField", "<chcr>k__BackingField", "chbu", "chbv", "chbw", "_chbu_k__BackingField", "_chbv_k__BackingField", "_chbw_k__BackingField", "<chbu>k__BackingField", "<chbv>k__BackingField", "<chbw>k__BackingField", "chey", "chez", "chfa", "chfb", "_chdi_k__BackingField", "_chdj_k__BackingField", "_chdk_k__BackingField", "_chdl_k__BackingField", "<chey>k__BackingField", "<chez>k__BackingField", "<chfa>k__BackingField", "<chfb>k__BackingField", "cggz", "cgha" };

		internal static readonly string[] HeroNestedFields =
			{ "cguy", "cgsm", "cgfa", "hero", "logicHero", "cbye", "<cbye>k__BackingField", "_cbye_k__BackingField", "cbzt", "<cbzt>k__BackingField", "chyt", "_chyt_k__BackingField", "<chyt>k__BackingField", "chys", "_chys_k__BackingField", "<chys>k__BackingField", "cbzu", "_cbyf_k__BackingField", "<cbzu>k__BackingField", "chpd", "cnva", "cmgf", "bqax", "ciaj", "<ciaj>k__BackingField", "cnxy", "heroConfig", "config" };

		internal static readonly MethodSymbol ResultHeroPortraitRefresh = new(
			"battle.ui.resultHeroPortrait.refresh",
			"vpm", "vnu", "von", "vom");
	}

	internal static class BattleUnitInit
	{
		internal const string UnitTypeId = "Hex.Session.Battle.Unit";
		internal const string HexTypeId = "Hex.Session.Battle.Hex";

		internal static readonly string[] BattleLogicTypeHints =
			{ "eeo", "eeh" };

		internal static readonly string[] SideTypeHints =
			{ "eip", "eii" };

		internal static readonly MethodSymbol Init = new(
			"battle.unit.init",
			"Init");
	}

	internal static class SkeletalNecromancy
	{
		internal static readonly MethodSymbol SubstituteByHpCast = new(
			"battle.skeletalNecromancy.substituteByHp.cast",
			"bdml");

		internal static readonly string[] TransferSideStatisticsFields =
			{ "sideStatistics", "<sideStatistics>k__BackingField" };

		internal static readonly string[] BattleUnitTransferFields =
			{ "chgt", "bewg", "<chgt>k__BackingField", "_chgt_k__BackingField", "chfy", "bevh", "<chfy>k__BackingField", "_chfy_k__BackingField", "chey", "chcp", "chbu", "cggz" };

		internal static readonly string[] BattleUnitLogicConfigFields =
			{ "chgu", "bewi", "<chgu>k__BackingField", "_chgu_k__BackingField", "chfz", "bevj", "<chfz>k__BackingField", "_chfz_k__BackingField", "chez", "chbv", "cgha" };

		internal static readonly string[] BattleUnitViewConfigFields =
			{ "chgv", "bewk", "<chgv>k__BackingField", "_chgv_k__BackingField", "chga", "bevl", "<chga>k__BackingField", "_chga_k__BackingField", "chfa", "chbw" };

		internal static readonly string[] BattleUnitDataFields =
			{ "chgw", "bewm", "<chgw>k__BackingField", "_chgw_k__BackingField", "chgb", "bevn", "<chgb>k__BackingField", "_chgb_k__BackingField", "chfb", "chdl" };

		internal static readonly string[] BattleUnitBattleLogicFields =
			{ "eeo", "cnub", "bbbf", "cfkd", "<cfkd>k__BackingField", "_cfkd_k__BackingField", "cnsy", "cfjd" };

		internal static readonly string[] BattleLogicFieldFactoryFields =
			{ "cfrz", "<cfrz>k__BackingField", "_cfrz_k__BackingField", "cfqz" };

		internal static readonly string[] BattleControllerInstanceMembers =
			{ "cetp", "<cetp>k__BackingField", "bbok" };

		internal static readonly string[] BattleControllerDrawerManagerMembers =
			{ "cetx", "<cetx>k__BackingField", "_cetx_k__BackingField", "bbll" };

		internal static readonly MethodSymbol DrawerManagerDrawerForUnit = new(
			"battle.skeletalNecromancy.drawerManager.drawerForUnit",
			"bbym");

		internal static readonly string[] UnitDataFullStackMembers =
			{ "fullStacks", "startBattleFullStacks", "chlh", "chlb", "chkh", "cnvq" };

		internal static readonly string[] HeroAbilityLevelConfigMembers =
			{ "config", "get_config", "<config>k__BackingField", "_config_k__BackingField" };

		internal static readonly string[] HeroAbilityCasterSideMembers =
			{ "cfmf", "<cfmf>k__BackingField", "_cfmf_k__BackingField" };

		internal static readonly MethodSymbol TransferUnitLogicConfigGetter = new(
			"battle.skeletalNecromancy.transferUnit.logicConfig.getter",
			"bdzu");

		internal static readonly MethodSymbol SideStatisticsDictionaryGetter = new(
			"battle.skeletalNecromancy.sideStatistics.dictionary.getter",
			"bdue");
	}

	internal static class UnitViewConfig
	{
		internal static readonly MethodSymbol MapMeshLoader = new(
			"unitViewConfig.mapMesh.loader",
			"sec");
	}

	internal static class MapSquadVisual
	{
		internal static readonly string[] ControllerTypeHints =
			{ "ezg", "ezf", "eya" };

		internal static readonly string[] WorldSquadTypeHints =
			{ "fcx", "fcy", "fbl" };

		internal static readonly string[] SessionTypeHints =
			{ "ctp", "cta" };

		internal static readonly string[] RootFields =
			{ "cixl", "<cixl>k__BackingField", "_cixl_k__BackingField", "ciut", "<ciut>k__BackingField", "ciwk", "<ciwk>k__BackingField", "chym", "<chym>k__BackingField" };

		internal static readonly MethodSymbol RootGetter = new(
			"mapSquadVisual.root.getter",
			"bidb", "biau", "bice");

		internal static readonly string[] ViewConfigFields =
			{ "cixp", "ciux", "ciwo", "chyq" };
	}

	internal static class UnitPreview
	{
		internal static readonly string[] WindowWrapperFields =
			{ "cheb", "chdg", "chdd", "cgzd", "char", "cgei" };

		internal static readonly MethodSymbol WindowFactory = new(
			"unitPreview.window.factory",
			"beth", "betg", "beri", "bebc");

		internal static readonly MethodSymbol SharedPreviewFactory = new(
			"unitPreview.shared.factory",
			"htf", "hqr");
	}

	internal static class TooltipPortrait
	{
		internal static readonly string[] TooltipUnitTypeHints =
			{ "Hex.UI.BhTooltipUnit" };

		internal static readonly string[] SidSurfaceMethodNames =
			{ "tcy", "Show", "tda" };

		internal const int ExpectedSidSurfaceCount = 4;

		internal static readonly string[] PortraitImageFields =
			{ "portrait" };

		internal static readonly string[] DiagnosticOwnedObjectFields =
			{ "white", "armyCountBack", "armyCountFrame", "skullLoss" };
	}

	internal static class Projectile
	{
		internal static readonly MethodSymbol AbilityViewProjectileGetter = new(
			"battle.projectile.abilityView.getProjectile",
			"rnu", "rnh", "rne", "rmp", "rcs");

		internal static readonly MethodSymbol HeroAbilityLevelProjectileGetter = new(
			"battle.projectile.heroAbilityLevel.getProjectile",
			"rvt", "rvg");

		internal static readonly MethodSymbol ControllerInit = new(
			"battle.projectile.controller.init",
			"Init");

		internal static readonly MethodSymbol ControllerSetPositions = new(
			"battle.projectile.controller.setPositions",
			"bbrd", "bbqc", "bbqd", "q");

		internal static readonly MethodSymbol ControllerUpdate = new(
			"battle.projectile.controller.update",
			"bbrf", "bbqe", "bbqf", "ldk");
	}

	internal static class BattleCommand
	{
		internal const string CounterEventRuntimeType = "eiw";
		internal const string BattleExecutorRuntimeType = "ems";

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
			{ "cedw", "cdgt" };

		internal static readonly string[] AbilityViewConfigFields =
			{ "cedx", "cdgu" };

		internal static readonly string[] RuntimeTagListFields =
			{ "cfjh" };

		internal static readonly string[] AttackTypeMembers =
			{ "cmyi" };

		internal static readonly string[] UnitSidFields =
			{ "cfjg", "configId", "sid", "cfhm", "<cfhm>k__BackingField" };

		internal static readonly string[] UnitNestedConfigFields =
			{ "chey", "cfjc", "<cfjc>k__BackingField", "_cfjc_k__BackingField" };

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

	internal static class ReleaseTownUi
	{
		internal static readonly MethodSymbol CitySessionRefresh = new(
			"release.town.citySession.refresh",
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
			{ "cnzd", "bgbh", "cnye", "bgae", "cnyb", "bgad", "chsd", "cnxb", "chrg", "bfzh", "cnvj", "chpr", "cnvk", "chps", "cgtl", "cmzg", "fkz" };

		internal static readonly MethodSymbol CityUiElementRefreshIndexed = new(
			"release.town.cityUiElement.refreshIndexed",
			"wbr");

		internal static readonly MethodSymbol CityUiElementRefresh = new(
			"release.town.cityUiElement.refresh",
			"wbs");

		internal static readonly MethodSymbol BuildingViewBind = new(
			"release.town.buildingView.bind",
			"tqf");

		internal static readonly MethodSymbol BuildingViewSecondaryBind = new(
			"release.town.buildingView.secondaryBind",
			"tqg");

		internal static readonly MethodSymbol BuildingViewHoverRefresh = new(
			"release.town.buildingView.hoverRefresh",
			"tqh", "tqi", "tqj", "tqk", "tql", "tqm", "tqn", "tqo", "tqp", "tqq");

		internal static readonly MethodSymbol BuildingTooltipBind = new(
			"release.town.buildingTooltip.bind",
			"tam", "tan");

		internal static readonly string[] CityHudCityFields =
			{ "cbcr", "cbba", "cazz", "cawv", "cafp" };

		internal static readonly string[] SessionCityDataFields =
			{
				"cjea", "_cjea_k__BackingField", "<cjea>k__BackingField",
				"cidl", "_cidl_k__BackingField", "<cidl>k__BackingField",
				"cjdc", "_cjdc_k__BackingField", "<cjdc>k__BackingField",
				"cjcx", "cjbz", "_cjan_k__BackingField", "cjao", "_cjao_k__BackingField", "<cjao>k__BackingField",
				"cjce", "ciyz"
			};

		internal static readonly string[] SessionCityConfigFields =
			{
				"cjdz", "_cjdz_k__BackingField", "<cjdz>k__BackingField",
				"cidk", "_cidk_k__BackingField", "<cidk>k__BackingField",
				"cjdb", "_cjdb_k__BackingField", "<cjdb>k__BackingField",
				"cjcw", "cjby", "_cjam_k__BackingField", "cjbz", "_cjan_k__BackingField",
				"cjcd", "ciyy"
			};

		internal static readonly string[] DataObjectConfigFields =
			{ "cnzc", "bgaj", "cnyd", "bfzg", "cnxc", "cntu", "chrh", "choe" };

		internal static readonly string[] BuildingModelTypeNames =
			{ "dwc", "dvw" };

		internal static readonly string[] BuildingModelDataMembers =
			{ "cdxk", "<cdxk>k__BackingField", "_cdxk_k__BackingField", "babz", "cdvr", "<cdvr>k__BackingField", "_cdvr_k__BackingField", "babb" };

		internal static readonly string[] BuildingModelSidMembers =
			{ "babw", "baay", "cnrm", "cnou", "cnqm", "sid" };

		internal static readonly string[] BuildingModelLevelMembers =
			{ "babx", "baaz", "cnrn", "cnov", "cnqn", "level" };

		internal static readonly MethodSymbol NavigationBack = new(
			"release.town.navigation.back",
			"sms", "smg", "sme", "slp");

		internal static readonly MethodSymbol NavigationSelect = new(
			"release.town.navigation.select",
			"tvp", "tuc", "tte");

		internal static readonly string[] NavigationStateFields =
			{ "bzgw", "bzfe", "bzeg", "bzcr" };

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
			"giw", "ttd", "tte", "ttf", "tti", "gip");

		internal static readonly MethodSymbol TooltipUnitsViewBind = new(
			"release.town.tooltipUnits.bind",
			"tnh");

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
			"bzdg", "bzdh", "bzdd", "bzde", "bzdi", "bzdo", "bzdp", "bzds",
			"byzd", "bzbm", "bzbl", "bzbq",
			"bzan", "bzao", "bzas",
			"cnej", "cnek", "cnel", "cnga"
		};

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
			"NativeFieldInfoPtr_bzeh",
			"bzeh");

		internal static readonly FieldSymbol BuildingSessionCurrentViewsOld = new(
			"release.town.buildingSession.currentViews.old",
			"NativeFieldInfoPtr_bzcp",
			"bzcp");

		internal static readonly FieldSymbol BuildingSessionViewLookup = new(
			"release.town.buildingSession.viewLookup",
			"NativeFieldInfoPtr_bzei",
			"bzei");

		internal static readonly FieldSymbol BuildingSessionViewLookupOld = new(
			"release.town.buildingSession.viewLookup.old",
			"NativeFieldInfoPtr_bzcq",
			"bzcq");

		internal static readonly FieldSymbol CitySessionBuildingSession = new(
			"release.town.citySession.buildingSession",
			"NativeFieldInfoPtr_buildingSession",
			"buildingSession");

		internal static readonly FieldSymbol CitySessionCityWrapper = new(
			"release.town.citySession.cityWrapper",
			"NativeFieldInfoPtr_bzjf",
			"bzjf");

		internal static readonly string[] CitySessionCityWrapperFields =
			{ "bzjf", "bynh", "bzdm" };

		internal static readonly FieldSymbol BuildingSessionCityWrapper = new(
			"release.town.buildingSession.cityWrapper",
			"NativeFieldInfoPtr_bzeg",
			"bzeg");

		internal static readonly FieldSymbol HireViewNavigation = new(
			"release.town.hireView.navigation",
			"NativeFieldInfoPtr_navigation",
			"navigation");

		internal static readonly FieldSymbol HireViewDayPanel = new(
			"release.town.hireView.dayPanel",
			"NativeFieldInfoPtr_dayPanel",
			"dayPanel");

		internal static readonly FieldSymbol CityWrapperConfig = new(
			"release.town.cityWrapper.config",
			"NativeFieldInfoPtr__cjdz_k__BackingField",
			"<cjdz>k__BackingField");

		internal static readonly FieldSymbol CityWrapperCity = new(
			"release.town.cityWrapper.city",
			"NativeFieldInfoPtr__cjea_k__BackingField",
			"<cjea>k__BackingField");

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

	internal static class LawIcon
	{
		internal static readonly MethodSymbol FractionLawViewBind = new(
			"release.lawIcon.fractionLawView.bind",
			"zez");

		internal static readonly MethodSymbol FractionLawViewRefresh = new(
			"release.lawIcon.fractionLawView.refresh",
			"zfb");

		internal static readonly string[] LawConfigFields =
			{ "cccd", "chsk", "ccak", "chrp", "ccah", "cnlk", "cnxn", "chrm", "cnkk", "cbzj", "cnwn", "chqp", "cnis", "cnuv", "cbxu", "chpa", "cgsu", "config", "lawConfig", "data", "ccbx", "cmrv" };

		internal static readonly string[] LawConfigGetters =
			{ "xno", "bfuq", "get_cnmm", "get_cnyp", "xmr", "bftn", "xmo", "get_cnlk", "bftm", "get_cnxn", "xlu", "bfsq", "get_cnkk", "get_cnwn", "xku", "bfrn", "get_cnis", "get_cnuv", "bfbj", "get_cmys", "get_cmrv", "yog" };

		internal static readonly string[] LawIconDiagnosticGetters =
			{ "xno", "bfuq", "xmr", "bftn", "xmo", "bftm", "xku", "bfrn", "bfbj", "yog" };
	}

	internal static class SmoothOpening
	{
		internal static readonly string[] OpenTimeTrackerTypeHints =
			{ "ddd", "ddb" };

		internal static readonly string[] OpeningFacadeTypeHints =
			{ "ddh" };

		internal static readonly MethodSymbol CityFrameCount = new(
			"smoothOpening.city.frameCount",
			"hg", "esd", "oam", "wmj",
			"beh", "wkq", "ioq", "jhi", "fmy");

		internal static readonly MethodSymbol OpeningFrameCount = new(
			"smoothOpening.facade.frameCount",
			"emz", "wmy", "jof", "hkb");
	}

	internal static class ImportVisuals
	{
		internal static readonly MethodSymbol ResManagerObjectLoader = new(
			"importVisuals.resManager.objectLoader",
			"bmts", "bmsl", "bmsi", "bmfq", "Get");

		internal static readonly string[] BattlePoolTypeHints =
			{ "eam", "eai", "dzk" };

		internal static readonly MethodSymbol BattlePoolLoader = new(
			"importVisuals.battlePool.loader",
			"uu", "dvu", "jyt", "bbgy", "dia", "bbjs", "cry", "bath");

		internal static readonly MethodSymbol HeroHudPanelRefresh = new(
			"importVisuals.armyStrip.heroHud.refresh",
			"gix", "vsl", "vsh");

		internal static readonly MethodSymbol HeroHudPanelHeroArgRefresh = new(
			"importVisuals.armyStrip.heroHud.heroArgRefresh",
			"vso");

		internal static readonly MethodSymbol CityHeroWithPartyRefresh = new(
			"importVisuals.armyStrip.cityHeroWithParty.refresh",
			"uag", "uah", "uai", "uaj", "uak");

		internal static readonly MethodSymbol CityHeroesGroupRefresh = new(
			"importVisuals.armyStrip.cityHeroesGroup.refresh",
			"txq", "txr", "txs", "txv", "txw", "txy", "txz", "tya", "tyb", "tyd", "tye", "tyj", "tyl", "tym");

		internal static readonly string[] CityHeroesGroupViewFields =
			{ "heroesWithParty" };

		internal static readonly string[] CityHeroWithPartyTooltipFields =
			{ "heroView", "cnhf" };

		internal static readonly string[] CityHeroWithPartySessionHeroFields =
			{ "bzjh", "bzhs", "bzgr", "bzdo" };

		internal static readonly string[] CityHeroWithPartyCanvasGroupFields =
			{ "cg" };

		internal static readonly string[] TooltipHeroItemPortraitFields =
			{ "heroFace" };

		internal static readonly string[] TooltipHeroItemSessionHeroFields =
			{ "byop", "bynf", "bymf", "byjc" };

		internal static readonly string[] SessionHeroWrapperHeroFields =
			{ "<cice>k__BackingField", "_cice_k__BackingField", "cice", "coaa", "<cibj>k__BackingField", "_cibj_k__BackingField", "cibj", "<ciaj>k__BackingField", "_ciaj_k__BackingField", "<chxe>k__BackingField", "_chxe_k__BackingField", "ciaj", "chxe" };

		internal static readonly string[] SessionHeroConfigFields =
			{ "configSid", "chsm", "bfuz", "chqr", "chno", "<bqep>k__BackingField", "_bqep_k__BackingField", "bqep" };

		internal static readonly MethodSymbol SummaryCardHeroBind = new(
			"importVisuals.armyStrip.summaryCard.heroBind",
			"lwy", "lxc", "lwk", "lwo");

		internal static readonly string[] UnitUiDataUnitMembers =
			{ "cazx", "cnkf", "vxu", "cnie", "vvf", "cavr", "cnev", "vuk", "cmmf" };

		internal static readonly string[] HeroHudPanelUnitSlotsMembers =
			{ "slots", "vse", "cnkc", "vrk", "cmkl" };

		internal static readonly string[] UnitSlotsListMembers =
			{ "slots", "cbew", "cnks", "cngz", "wcq", "cbap", "cnfi", "wbv", "cmlb" };
	}

	internal static class CustomGame
	{
		internal static readonly string[] UnitSlotTypeHints =
			{ "Hex.Pick.BhUnitSlot", "BhUnitSlot" };

		internal static readonly MethodSymbol UnitSlotBind = new(
			"customGame.unitSlot.bind",
			"lxd");

		internal static readonly MethodSymbol FactionDetailsBind = new(
			"customGame.factionDetails.bind",
			"hpj", "hpc", "hov");

		internal static readonly MethodSymbol FactionDetailsRefresh = new(
			"customGame.factionDetails.refresh",
			"Init", "hpk", "hpd");

		internal static readonly string[] FactionDetailsConfigFields =
			{ "bpkw" };

		internal static readonly MethodSymbol FactionSelectButtonBind = new(
			"customGame.factionSelectButton.bind",
			"hpm", "hpf", "hoy");

		internal static readonly MethodSymbol HeroSelectButtonBind = new(
			"customGame.heroSelectButton.bind",
			"hpt", "hpm", "hpf");
	}

	internal static class HeroProfile
	{
		internal static readonly string[] ProfileWindowTypeHints =
			{ "Hex.Session.HeroProfile.BhHeroProfileWindow", "Hex.Session.UI.BhHeroProfileWindow" };

		internal static readonly MethodSymbol DataViewInit = new(
			"heroProfile.dataView.init",
			"Init");

		internal static readonly MethodSymbol DataViewRefresh = new(
			"heroProfile.dataView.refresh",
			"zuj", "zuk", "zun", "zvf", "zvg", "zvh", "zvi", "zvj", "zvk", "zvl", "zvm", "ztj", "ztk", "ztn", "zto", "ztp");

		internal static readonly MethodSymbol PortraitViewBind = new(
			"heroProfile.portraitView.bind",
			"zwm", "zwp", "zvo", "zvr", "ztr", "ztu");

		internal static readonly MethodSymbol ProfileWindowShown = new(
			"heroProfile.window.shown",
			"giw", "gip");

		internal static readonly MethodSymbol SpecializationViewBind = new(
			"heroProfile.specializationView.bind",
			"zxm", "zxn", "zur", "zus", "zwo", "zwp");

		internal static readonly MethodSymbol SkillViewBind = new(
			"heroProfile.skillView.bind",
			"zwv", "zua", "zvx");

		internal static readonly MethodSymbol SubSkillViewBind = new(
			"heroProfile.subSkillView.bind",
			"zxt", "zuy", "zwv");

		internal static readonly string[] SpecializationConfigFields =
			{ "cdqm", "cdtc", "cdsb", "bwck", "cmtl", "config", "specializationConfig" };

		internal static readonly string[] SpecializationPayloadFields =
			{ "cdqn", "cdtd", "cdsc", "payload", "heroProfilePayload" };

		internal static readonly string[] SkillRuntimeFields =
			{ "cdqd", "cdst", "cdrs", "bwbu", "skill", "heroSkill" };

		internal static readonly string[] SkillPayloadFields =
			{ "cdqe", "cdsu", "cdrt", "payload", "heroProfilePayload" };

		internal static readonly string[] SkillConfigFields =
			{ "cnkf", "ccdd", "cnna", "cnxy", "config", "skillConfig", "chrt" };

		internal static readonly string[] SkillConfigGetters =
			{ "xvg", "xxg", "bfuz", "rzs", "get_cnkf", "get_cnna", "get_cnxy" };

		internal static readonly string[] SubSkillRuntimeFields =
			{ "cdqw", "cdtm", "cdsl", "bwbv", "subSkill", "heroSubSkill" };

		internal static readonly string[] SubSkillPayloadFields =
			{ "cdqx", "cdtn", "cdsm", "payload", "heroProfilePayload" };

		internal static readonly string[] SubSkillConfigFields =
			{ "cnkq", "cnnl", "config", "subSkillConfig", "ccfp" };

		internal static readonly string[] SubSkillConfigGetters =
			{ "xwm", "xyo", "get_cnkq", "get_cnnl" };

		internal static readonly MethodSymbol HeroSelectButtonBind = new(
			"heroPortrait.heroSelectButton.bind",
			"hpt", "hpm");

		internal static readonly MethodSymbol TooltipHeroItemBind = new(
			"heroPortrait.tooltipHeroItem.bind",
			"tcj", "tck", "tcl", "tco", "tcb", "tcc", "tcd", "tcg");

		internal static readonly MethodSymbol TooltipHeroItemRefresh = new(
			"heroPortrait.tooltipHeroItem.refresh",
			"LateUpdate");

		internal static readonly MethodSymbol TavernHeroBind = new(
			"heroPortrait.tavernHero.bind",
			"zer");

		internal static readonly MethodSymbol SideHeroInit = new(
			"heroPortrait.sideHero.init",
			"Init");

		internal static readonly MethodSymbol SideHeroRefresh = new(
			"heroPortrait.sideHero.refresh",
			"wcb", "wcc", "wcd", "wce");

		internal static readonly string[] SideHeroFields =
			{ "cbda", "cbai", "cbbj", "cayu", "cayt" };

		internal static readonly FieldSymbol SideHeroIcon = new(
			"heroPortrait.sideHero.icon",
			"NativeFieldInfoPtr_heroIcon",
			"heroIcon");

		internal static readonly string[] SideHeroIconFields =
			{ "heroIcon" };

		internal static readonly string[] HeroStateFields =
			{ "ckif", "<ckif>k__BackingField", "_ckif_k__BackingField", "byop", "bzjh", "caww", "cbda", "cdap", "cdpz", "cdrl", "cdro", "ckgi", "<ckgi>k__BackingField", "_ckgi_k__BackingField", "cdsj", "cdsm", "cdsp", "ckhg", "<ckhg>k__BackingField", "_ckhg_k__BackingField", "ckhj", "<ckhj>k__BackingField", "_ckhj_k__BackingField", "bkkj", "bkki", "ccuj", "cdpw" };

		internal static readonly string[] HeroConfigFields =
			{ "configSid", "sid", "id", "heroSid", "icon", "cnbz", "cnca", "cncb", "cncc", "cncd", "cnce", "cncf", "cmyj", "cnxr" };

		internal static readonly string[] HeroConfigNestedFields =
			{ "ckif", "<ckif>k__BackingField", "_ckif_k__BackingField", "byop", "bzjh", "caww", "cbda", "cdap", "cdpz", "cdrl", "cdro", "bwcl", "cmtm", "ckgi", "<ckgi>k__BackingField", "_ckgi_k__BackingField", "bkkj", "bkki", "cnyt", "<cnyt>k__BackingField", "_cnyt_k__BackingField", "bqdp", "<bqdp>k__BackingField", "_bqdp_k__BackingField", "bqep", "<bqep>k__BackingField", "_bqep_k__BackingField", "bqhv", "chqr", "chsm", "bfuz", "cbzu", "<cbzu>k__BackingField", "_cbyf_k__BackingField", "chpd", "cnva", "chrr", "cbfh", "<cbfh>k__BackingField", "_cbfh_k__BackingField", "ccau", "<ccau>k__BackingField", "_ccau_k__BackingField", "cice", "<cice>k__BackingField", "_cice_k__BackingField", "coaa", "<coaa>k__BackingField", "_coaa_k__BackingField", "cibj", "<cibj>k__BackingField", "_cibj_k__BackingField", "cmyw", "cgsw", "cmgf", "bqax", "cnxr", "cmhu", "cnwr", "chys", "<chys>k__BackingField", "chyt", "<chyt>k__BackingField", "ciaj", "<ciaj>k__BackingField", "_ciaj_k__BackingField", "cnxy", "heroConfig", "config", "hero", "heroView", "cnhf", "bzhs", "bynf", "bzgr", "bymf", "byjc", "cbai", "cbbj", "cavf", "cayv", "cayw", "casp", "caue", "casu", "casv", "cast", "cayt", "cayu", "cayx" };

		internal static readonly string[] HeroConfigGetters =
			{ "rwi", "rwj", "rwk", "rwl", "rwm", "rwn", "rwo", "bfuz", "get_cnyt", "get_cnbz", "get_cnca", "get_cncb", "get_cncc", "get_cncd", "get_cnce", "get_cncf", "bkls", "get_ckif", "ipu", "ivn", "bfsz", "bkjl", "get_bqdp", "get_bqep", "ipx", "get_cmhu", "get_cnwr", "get_ckgi", "bftv", "bftw", "xnq", "xal", "get_cnxr", "bgwj", "emx", "get_chys", "eif", "get_chyt", "xlt", "get_cbyf", "get_cibj", "get_ciaj", "get_cnxy", "get_chpd", "get_cnva", "get_cmyj", "ivd", "ipk", "get_cbfh", "get_cmyw", "get_cgsw", "get_cmeo", "get_bqax", "get_heroConfig", "tyr", "get_cnfd" };
	}

	internal static class HeroMap
	{
		internal const string DrawerTypeId = "heroMap.drawer";
		internal static readonly string[] DrawerTypeHints = { "erw", "erv", "err" };

		internal static readonly MethodSymbol RootGameObjectGetter = new(
			"heroMap.drawer.rootGameObject",
			"bgtp", "bgtk", "bgto", "bgtj", "gzd", "bgtq", "hbj", "ein", "bgsn", "bgss", "hug", "bgrd", "bgrk");

		internal static readonly string[] RootGameObjectProperties =
			{ "chxu", "chts", "chwx" };

		internal static readonly string[] HeroConfigFields =
			{ "chye", "chvq", "chuc", "chxh", "heroConfig", "config", "bqax", "cmgf" };

		internal static readonly MethodSymbol HeroConfigGetter = new(
			"heroMap.drawer.heroConfig",
			"bftv", "njr", "ipk", "ivd", "rtn");
	}

	internal static class CustomTownMapBillboard
	{
		internal const string PlacedObjectTypeId = "map.customTownBillboard.placedObject";
		internal static readonly string[] PlacedObjectTypeHints = { "bvb" };

		internal const string ObjectMetaTypeId = "map.customTownBillboard.objectMeta";
		internal static readonly string[] ObjectMetaTypeHints = { "bvd" };

		internal static readonly MethodSymbol PlacedObjectInit = new(
			"map.customTownBillboard.placedObject.init",
			"cjd", "fw", "Init");

		internal static readonly MethodSymbol PlacedObjectSetSid = new(
			"map.customTownBillboard.placedObject.setSid",
			"ooc");

		internal static readonly string[] MetaFields =
			{ "bvob", "<bvob>k__BackingField", "_bvob_k__BackingField", "bvmr", "<bvmr>k__BackingField", "_bvmr_k__BackingField", "meta", "bvmo", "<bvmo>k__BackingField", "_bvmo_k__BackingField", "bvkd", "bvlr", "<bvkd>k__BackingField", "_bvkd_k__BackingField", "<bvlr>k__BackingField", "_bvlr_k__BackingField" };

		internal static readonly string[] MetaConfigFields =
			{ "bvpj", "bvnz", "config", "buwy", "bvnw", "bvll", "bvmz", "bvlm" };

		internal static readonly string[] PlacedObjectSidFields =
			{ "bvoy", "bvno", "sid", "objectSid", "id" };

		internal static readonly string[] ConfigIdFields =
			{ "id", "sid", "cluu", "cmql", "cmsc" };

		internal static readonly string[] RootGameObjectFields =
			{ "bvon", "<bvon>k__BackingField", "_bvon_k__BackingField", "bvnd", "<bvnd>k__BackingField", "_bvnd_k__BackingField", "gameObject", "buwc", "bvna", "<bvna>k__BackingField", "_bvna_k__BackingField", "bvng", "_bvkp_k__BackingField", "<bvkp>k__BackingField", "_bvmd_k__BackingField", "<bvmd>k__BackingField", "bvks", "bvmg" };

		internal static readonly string[] RootTransformFields =
			{ "bvoo", "<bvoo>k__BackingField", "_bvoo_k__BackingField", "bvne", "<bvne>k__BackingField", "_bvne_k__BackingField", "bvnh", "bvnb", "<bvnb>k__BackingField", "_bvnb_k__BackingField", "bvkq", "<bvkq>k__BackingField", "_bvkq_k__BackingField", "<bvme>k__BackingField", "_bvme_k__BackingField", "bvkt", "bvmh" };

		internal static readonly MethodSymbol RootGameObjectGetter = new(
			"map.customTownBillboard.rootGameObject",
			"omx", "omk");

		internal static readonly MethodSymbol RootTransformGetter = new(
			"map.customTownBillboard.rootTransform",
			"omz", "omm");

		// Resolver path for cities that share the generic "city-spawner" / "random-city" sid:
		// bvb -> Map -> ObjectsProperties.ouk/older oui(ObjectProp.EType.MapObject, bvb.bvms)
		// -> PropCity.factionSid. The bvb.Init node arg is placement data, not the property id.
		internal static readonly string[] PlacedObjectMapFields =
			{ "<bvoi>k__BackingField", "_bvoi_k__BackingField", "bvoi", "<bvmy>k__BackingField", "_bvmy_k__BackingField", "bvmy", "map", "<map>k__BackingField" };

		internal static readonly string[] PlacedObjectNodeFields =
			{ "<bvod>k__BackingField", "_bvod_k__BackingField", "bvod", "<bvmt>k__BackingField", "_bvmt_k__BackingField", "bvmt", "node", "<node>k__BackingField" };

		internal static readonly string[] PlacedObjectIdFields =
			{ "bvoc", "bvms", "id", "<id>k__BackingField", "_id" };

		internal static readonly string[] MapObjectsPropertiesFields =
			{ "<cmtm>k__BackingField", "_cmtm_k__BackingField", "cmtm", "<cmsp>k__BackingField", "_cmsp_k__BackingField", "objectsProperties", "<objectsProperties>k__BackingField" };

		internal static readonly string[] MapObjectsPropertiesGetters =
			{ "ofq", "cmtm", "get_cmtm", "ofc", "cmsp", "get_cmsp", "get_objectsProperties" };

		internal static readonly string[] MapObjectPropertiesGetters =
			{ "oux", "ouw", "ouk", "ouj" };

		internal static readonly string[] PropCitiesFields =
			{ "propCities", "<propCities>k__BackingField", "_propCities" };

		internal static readonly string[] PropCitiesGetters =
			{ "otz", "get_cmup", "cmup", "otm", "get_propCities", "cmts", "get_cmts" };

		internal static readonly string[] PropCityFactionFields =
			{ "factionSid", "<factionSid>k__BackingField", "_factionSid", "FactionSid" };

		internal static readonly string[] PropCityIdFields =
			{ "id", "<id>k__BackingField", "_id", "Id" };
	}

	internal static class CustomDwellingRandomHire
	{
		internal const string RandomHireWorldObjectTypeId = "map.customDwelling.randomHireWorldObject";
		internal static readonly string[] RandomHireWorldObjectTypeHints = { "fcj" };

		internal const string RandomHireResolverTypeId = "map.customDwelling.randomHireResolver";
		internal const string RandomHireResolverTypeHint = "czr";

		internal static readonly MethodSymbol RandomHireFactionTierResolvers = new(
			"map.customDwelling.randomHireResolver.factionTierMethods",
			"vfm");

		internal static readonly MethodSymbol HireMapObjectSpawners = new(
			"map.customDwelling.randomHireResolver.hireMapObjectSpawners",
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
	}

	internal static class CustomDwellingHire
	{
		internal const string HireWorldObjectTypeId = "map.customDwelling.hireWorldObject";
		internal static readonly string[] HireWorldObjectTypeHints = { "fbx" };

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

	internal static class CustomDwellingCity
	{
		internal const string CityWorldObjectTypeId = "map.customDwelling.cityWorldObject";
		internal static readonly string[] CityWorldObjectTypeHints = { "fbq" };

		internal const string CitySessionDataTypeId = "map.customDwelling.citySessionData";
		internal static readonly string[] CitySessionDataTypeHints = { "Hex.Session.Data.ObjCity" };

		internal static readonly string[] WorldObjectCityDataFields =
			{ "cjea", "<cjea>k__BackingField", "_cjea_k__BackingField", "cjdf", "<cjdf>k__BackingField", "_cjdf_k__BackingField", "city", "objCity" };

		internal static readonly string[] WorldObjectCityConfigFields =
			{ "cjdz", "<cjdz>k__BackingField", "_cjdz_k__BackingField", "cjde", "<cjde>k__BackingField", "_cjde_k__BackingField", "config", "cityConfig" };
	}

	internal static class MapBillboardDeathFade
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

	internal static class WarcryHeroAbility
	{
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

		// Per-ability button bind: BhHeroAbilitiyView.<method>(bzc, elz). /2.
		internal static readonly MethodSymbol PerAbilityBind = new(
			"warcry.heroAbilityView.perAbilityBind",
			"skw", "skk");

		// Container bind: BhHeroAbilitiesView.<method>(bzc, List<edn>). /2.
		internal static readonly MethodSymbol ContainerBind = new(
			"warcry.heroAbilitiesView.containerBind",
			"sjw", "sjx", "sjk", "sjl");

		// Container context-set / refresh: BhHeroAbilitiesView.<method>(edn). /1.
		internal static readonly MethodSymbol ContainerContextSet = new(
			"warcry.heroAbilitiesView.containerContextSet",
			"skd", "sjr");

		internal static readonly string[] HeroAbilityTypeNames =
			{ "edn", "edg" };

		internal static readonly string[] HeroAbilityWrapperTypeNames =
			{ "elz", "els" };

		internal static readonly string[] HeroAbilityFields =
			{ "bybb", "bxzr" };

		internal static readonly string[] HeroAbilityWrapperFields =
			{ "bybd", "bxzt" };

		internal static readonly string[] HeroAbilityGetters =
			{ "skt", "skh", "get_cneu", "get_cndx" };

		internal static readonly string[] HeroAbilityOutGetters =
			{ "dmw", "dlx", "csf", "beqn", "fby", "mgo", "besj", "mzn", "berk", "hhg" };

		internal static readonly string[] HeroAbilityViewListFields =
			{ "heroAbilities", "separateHeroAbilities" };
	}

	internal static class BattleVisual
	{
		internal static readonly string[] BattleControllerTypeNames =
			{ "eax", "eaq" };

		internal static readonly string[] BattleDrawerTypeNames =
			{ "eck", "ecd" };

		internal static readonly string[] SpawnHelperTypeNames =
			{ "eni", "ena" };

		internal static readonly string[] SpawnFactoryTypeNames =
			{ "edh", "eda" };

		internal static readonly MethodSymbol TimelineAttackBind = new(
			"battle.visual.timeline.attackBind",
			"bbvf", "bbrl", "bbtf", "bbue", "bbuf", "bbtg");

		internal static readonly string[] BattleUnitTransferFields =
			{ "chgt", "bewg", "<chgt>k__BackingField", "_chgt_k__BackingField", "chfy", "bevh", "<chfy>k__BackingField", "_chfy_k__BackingField", "chey", "chbu", "cggz" };

		internal static readonly string[] BattleUnitConfigSidMembers =
			{ "configSid" };

		internal static readonly string[] BattleControllerInstanceMembers =
			{ "ceuj", "<ceuj>k__BackingField", "bblx", "cetp", "<cetp>k__BackingField", "bbok" };

		internal static readonly string[] BattleControllerDrawerManagerMembers =
			{ "ceur", "<ceur>k__BackingField", "_ceur_k__BackingField", "bbmm", "cetx", "<cetx>k__BackingField", "_cetx_k__BackingField", "bbll" };

		internal static readonly MethodSymbol DrawerManagerDrawerForUnit = new(
			"battle.visual.drawerManager.drawerForUnit",
			"bbzn", "bbym");

		internal static readonly string[] EcdVisualGameObjectFields =
			{ "cfbg", "cfam", "cfaj", "cexw", "cexx" };

		internal static readonly string[] CurrentEcdVisualGameObjectFields =
			{ "cfbg" };

		internal static readonly string[] EcdAnimatorFields =
			{ "cfbc", "cfai", "cfaf", "cexs", "cext" };

		internal static readonly string[] CurrentEcdAnimatorFields =
			{ "cfbc" };

		internal static readonly string[] EcdSpriteRendererFields =
			{ "cfbl", "cfar", "cfao", "ceyb", "ceyc" };

		internal static readonly string[] CurrentEcdSpriteRendererFields =
			{ "cfbl" };

		internal static readonly string[] EczRootGameObjectFields =
			{ "cflk", "cflm", "cfkq", "cfks", "cfkn", "cfkp", "cfjs", "cezl", "cexw", "cfid", "cfib" };

		internal static readonly string[] CurrentEczMovementGameObjectFields =
			{ "cflk" };

		internal static readonly string[] CurrentEczOrientationGameObjectFields =
			{ "cflm" };

		internal static readonly string[] EczRootTransformFields =
			{ "cfll", "cfln", "cfkr", "cfkt", "cfko", "cfkq", "cfjt", "cfic", "cfie" };

		internal static readonly string[] CurrentEczMovementTransformFields =
			{ "cfll" };

		internal static readonly string[] CurrentEczOrientationTransformFields =
			{ "cfln" };

		internal static readonly string[] AttackFacingViewUnitMembers =
			{ "cfax", "_cfax_k__BackingField", "<cfax>k__BackingField", "bbvz", "cezc", "_cezc_k__BackingField", "<cezc>k__BackingField", "bbta", "cexn", "hiq", "unit", "_cexn_k__BackingField", "<cexn>k__BackingField" };

		internal static readonly string[] AttackFacingTimelineHelperMembers =
			{ "cfaz", "_cfaz_k__BackingField", "<cfaz>k__BackingField", "bbwd", "ceze", "_ceze_k__BackingField", "<ceze>k__BackingField", "bbue", "cexp", "mlu", "_cexp_k__BackingField", "<cexp>k__BackingField" };

		internal static readonly string[] AttackFacingUnitVisualViewMembers =
			{ "chhd", "beww", "_chhd_k__BackingField", "<chhd>k__BackingField", "chfi", "bexe", "_chfi_k__BackingField", "_chds_k__BackingField", "<chfi>k__BackingField", "<chds>k__BackingField" };

		internal static readonly string[] AttackFacingViewRootGameObjectMembers =
			{ "cezl", "bbuz", "cfjs", "bcrc", "cexw", "cfid", "bvn", "cfib" };

		internal static readonly string[] AttackFacingViewTransformMembers =
			{ "cfic", "lti" };

	}
}
