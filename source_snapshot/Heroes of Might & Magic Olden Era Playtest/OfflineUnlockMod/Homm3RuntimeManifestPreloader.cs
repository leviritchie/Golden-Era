using System;
using BepInEx.Logging;

namespace OfflineUnlockMod;

/// <summary>
/// Main-menu fail-closed payload gate for HoMM3 runtime manifests.
/// Intentionally does <b>not</b> decode hundreds of loose PNGs via ImageConversion.LoadImage —
/// that path dominated ScMainMenu.Start even at 58×64 and became catastrophic at painted 1254/1024.
/// Decode remains lazy on first UI/map need; missing files still fail closed here.
/// </summary>
internal static class Homm3RuntimeManifestPreloader
{
	private static bool _completed;

	internal static void PrewarmAtMainMenuOrFail(ManualLogSource log)
	{
		if (_completed)
			return;

		try
		{
			var validatedFiles = 0;
			var lightSprites = 0;

			// Small icon/card set — cheap enough to keep warm for custom-game UI.
			lightSprites += Homm3StrongholdFactionBannerSpriteCache.PrewarmManifestSprites();
			lightSprites += Homm3StrongholdCityIconSpriteCache.PrewarmManifestSprites();

			validatedFiles += Homm3ImportPortraitSpriteCache.ValidateRequiredStaticPortraitFilesOrFail();
			validatedFiles += Homm3DialogPortraitCatalog.ValidateRequiredDialogPortraitFilesOrFail(log);
			var cfg = LauncherConfigReader.TryLoad();
			if (cfg != null && cfg.Homm3UseUpscaledHeroPortraits)
				log?.LogInfo("HoMM3 runtime manifests: upscaled hero portraits enabled; full-res hero UI sprites load on demand from homm3_hero_portraits_upscaled/.");

			// Phase 2 pilot gates: when a bundle flag is on, the bundle file and its manifest.json must
			// exist and parse (manifest JSON only — no LoadAllAssets / texture decode at menu). PNG
			// payloads above remain fully validated; bundles and PNGs are dual-deployed during the pilot.
			if (cfg != null && cfg.Homm3UseUiPortraitBundles)
				Homm3UiPortraitBundle.ValidateBundlePayloadOrFail(log);
			if (cfg != null && cfg.Homm3UseBillboardBundles)
			{
				Homm3MapBillboardBundle.ValidateBundlePayloadOrFail(log);
				Homm3ArtifactMapBillboardBundle.ValidateBundlePayloadOrFail(log);
			}
			if (cfg != null && (cfg.Homm3MapBuildingMeshes || cfg.Homm3TowerCityMapMesh))
			{
				Homm3MapBuildingMeshBundle.ValidateBundlePayloadOrFail(log);
				Homm3MapBuildingAnim.ValidatePayloadOrFail(log);
			}
			if (cfg != null && cfg.Homm3ArtifactMeshes)
				Homm3ArtifactMeshBundle.ValidateBundlePayloadOrFail(log);
			if (cfg != null && cfg.Homm3TownSceneMeshes)
				Homm3TownSceneMeshBundle.ValidateBundlePayloadOrFail(log);
			if (cfg != null && cfg.Homm3TownScene3d)
				Homm3TownScene3d.ValidateCatalogPayloadsOrFail(log);

			validatedFiles += Homm3StrongholdDwellingMapBillboard.ValidateManifestTexturePathsOrFail(log);
			validatedFiles += Homm3CustomTownMapBillboard.ValidateManifestTexturePathsOrFail(log);
			var portraitIdleContractCount = Homm3ImportPortraitAnimationCache.ValidateRequiredIdleClipMetadata();

			_completed = true;
			log?.LogInfo(
				"HoMM3 runtime manifests: validated "
				+ validatedFiles
				+ " required portrait/billboard file(s) and "
				+ portraitIdleContractCount
				+ " recruitment idle clip contract(s) at main menu; prewarmed "
				+ lightSprites
				+ " light faction/city UI sprite(s). Unit portraits and map billboards decode lazily on first need.");
		}
		catch (Exception ex)
		{
			log?.LogFatal("HoMM3 runtime manifests: main-menu payload validation failed; terminating instead of deferring the fault to map/town callbacks: " + ex);
			Environment.FailFast("HoMM3 runtime manifest main-menu validation failed: " + ex);
			throw;
		}
	}
}
