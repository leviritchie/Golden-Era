"""Guard the typed WORLD-root ownership path for adventure-map hover."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--repo-root", default=Path(__file__).resolve().parent.parent)
	args = parser.parse_args()
	root = Path(args.repo_root).resolve()
	mod = root / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod"
	hover_path = mod / "Homm3AiDriverBridge.Hover.cs"
	symbols_path = mod / "GameSymbols.cs"
	current_path = mod / "GameSymbolsCurrent.g.cs"

	errors: list[str] = []
	for path in (hover_path, symbols_path, current_path):
		if not path.is_file():
			errors.append(f"missing required file: {path.relative_to(root)}")
	if errors:
		for error in errors:
			print("ERROR " + error)
		return 1

	hover = hover_path.read_text(encoding="utf-8")
	symbols = symbols_path.read_text(encoding="utf-8")
	current = current_path.read_text(encoding="utf-8")
	node_reader = hover.split("private static bool TryReadNodeFromHoverContextObject", 1)[1].split("\n\t}", 1)[0]

	checks = (
		("hover monitor must accept its first stationary tick before frame-age arithmetic",
		 "if (!moved && _lastHoverTickFrame != int.MinValue" in hover
		 and "frame - _lastHoverTickFrame < HoverTickMinFrameGap" in hover),
		("hover event emission must allow its first event before debounce-age arithmetic",
		 "_lastHoverEmitFrame == int.MinValue" in hover
		 and "Time.frameCount - _lastHoverEmitFrame >= HoverDebounceFrames" in hover),
		("typed owner must resolve from the pinned WORLD MonoBehaviour group",
		 "GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.HomecomingBoatTravelWorldOwner)" in hover),
		("owner lookup must be rooted at the centralized WORLD scene root, not a Unity global scan",
		 "TryFindUniqueWorldRoot" in hover and "GameSymbols.HomecomingBoatTravel.WorldRootName" in hover
		 and "scene.GetRootGameObjects()" in hover and "worldRoot.GetComponent(Il2CppType.From(_cachedMapHoverOwnerType))" in hover
		 and "Activator.CreateInstance(_cachedMapHoverOwnerType, nativeOwner.Pointer) as Component" in hover
		 and "owner.GetType() == _cachedMapHoverOwnerType" in hover
		 and "Resources.FindObjectsOfTypeAll" not in hover),
		("root resolver must reject multiple WORLD roots instead of picking one",
		 "Multiple loaded scene roots named '" in hover),
		("cached owner must be invalidated when root instance or scene changes",
		 "_cachedMapHoverWorldRootInstanceId != worldRootInstanceId" in hover
		 and "_cachedMapHoverWorldSceneHandle != worldScene.handle" in hover
		 and "_cachedMapHoverOwner = null;" in hover),
		("WORLD root discovery must be amortized and invalidated on scene lifecycle changes",
		 "MapHoverWorldRootRefreshFrameInterval = 60" in hover
		 and "MapHoverWorldRootRetryFrameInterval = 10" in hover
		 and "scanAge < refreshInterval" in hover and "sceneCount == _cachedMapHoverWorldRootScanSceneCount" in hover
		 and "var loadedAction = new Action<Scene, LoadSceneMode>(OnMapHoverSceneLoaded);" in hover
		 and "var unloadedAction = new Action<Scene>(OnMapHoverSceneUnloaded);" in hover
		 and "SceneManager.sceneLoaded += (UnityEngine.Events.UnityAction<Scene, LoadSceneMode>)loadedAction;" in hover
		 and "SceneManager.sceneUnloaded += (UnityEngine.Events.UnityAction<Scene>)unloadedAction;" in hover
		 and "InvalidateMapHoverWorldRootScan();" in hover),
		("root-to-cursor members must be uniquely resolved as exact properties or fields and read failures retained",
		 "MapHoverOwnerStateContainerMembers" in hover and "MapHoverStateCursorOwnerMembers" in hover
		 and "TryReadUniqueInstanceMemberValue" in hover and "GetProperty(hint, flags)" in hover
		 and "property.GetValue(source, null)" in hover and "field.GetValue(source)" in hover
		 and "matches.Count != 1" in hover and 'semanticMember + " read failed:' in hover
		 and "TryReadUniqueInstanceField" not in hover),
		("cursor service must be validated against the centralized Golden/current type pin",
		 "GameMember.FindTypeFromHints(" in hover
		 and "GameSymbols.HomecomingWaterPresentation.EmptyTerrainCursorOwnerTypeHints" in hover
		 and "IsAssignableFrom(cursorOwnerType)" in hover),
		("Golden and current exact root-to-service fields must remain centralized",
		 all(name in symbols for name in (
			"_ciae_k__BackingField", "_cnnj_k__BackingField",
			"_cial_k__BackingField", "_cnnp_k__BackingField",
		))),
		("current generated owner/service/context/node pins must remain present",
		 all(name in current for name in (
			"MonoBehaviourPublicObmeGarenoGareObarcnUnique|UnityEngine.MonoBehaviour|260|316|fbu",
			"ObjectPrivateObcnBoObcnECcncnUnique|Il2CppSystem.Object|24|27|fcb",
			'"cnns"', '"Method_Public_get_Int32_0"',
		))
		 and 'MapHoverOwnerStateContainerMembers = GameSymbolScope.Members("HomecomingWaterPresentation.MapHoverOwnerStateContainerMembers", MapHoverOwnerStateContainerMembers, 0x97066C47u, new string[] { null, "_cnnj_k__BackingField" }, "MonoBehaviourPublicObmeGarenoGareObarcnUnique");' in current
		 and 'MapHoverStateCursorOwnerMembers = GameSymbolScope.Members("HomecomingWaterPresentation.MapHoverStateCursorOwnerMembers", MapHoverStateCursorOwnerMembers, 0xD3D6FEEEu, new string[] { null, "_cnnp_k__BackingField" }, "ObjectPrivateObcnObcnObcnObObObUnique");' in current),
		("interop property reads must use a readable instance getter without trying another accessor on failure",
		 "property.GetGetMethod(nonPublic: true)" in hover
		 and "getter == null || getter.IsStatic || property.GetIndexParameters().Length != 0" in hover
		 and "property.GetValue(source, null)" in hover
		 and "var cause = ex is TargetInvocationException && ex.InnerException != null ? ex.InnerException : ex;" in hover),
		("hover-node pins must resolve one exact Int32 method, field, or property and retain accessor errors",
		 "TryReadNodeFromHoverContextObject(hoverContext, out node, out gap)" in hover
		 and "GameSymbols.HomecomingWaterPresentation.HoverContextNodeMembers" in node_reader
		 and "methodInfo.IsStatic || methodInfo.ContainsGenericParameters" in node_reader
		 and "parameters.Length != 0 || methodInfo.ReturnType != typeof(int)" in node_reader
		 and "fieldInfo.IsStatic || fieldInfo.FieldType != typeof(int)" in node_reader
		 and "getter == null || getter.IsStatic || propertyInfo.GetIndexParameters().Length != 0" in node_reader
		 and "propertyInfo.PropertyType != typeof(int)" in node_reader
		 and "method.Invoke(hoverContext, null)" in node_reader
		 and "field.GetValue(hoverContext)" in node_reader
		 and "property.GetValue(hoverContext, null)" in node_reader
		 and "TargetInvocationException" in node_reader and "read failed:" in node_reader
		 and "while (cause is TargetInvocationException && cause.InnerException != null)" in node_reader
		 and "catch { }" not in node_reader and "Convert.ToInt32" not in node_reader
		 and "HoverContext did not yield a readable node." not in hover),
	)
	for message, passed in checks:
		if not passed:
			errors.append(message)

	for error in errors:
		print("ERROR " + error)
	print(f"homm3 ai hover owner contract: {'OK' if not errors else f'{len(errors)} errors'}")
	return 1 if errors else 0


if __name__ == "__main__":
	sys.exit(main())
