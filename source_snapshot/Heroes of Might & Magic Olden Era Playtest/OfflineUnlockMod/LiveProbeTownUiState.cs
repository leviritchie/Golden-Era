namespace OfflineUnlockMod;

internal sealed class LiveProbeTownUiState
{
	internal string ActiveScene;
	internal string CachedFraction;
	internal string CurrentFraction;
	internal string CachedWrapperType;
	internal bool CachedWrapperPresent;
	internal bool CachedWrapperKnownType;
	internal bool CurrentCityDataNonNull;
	internal bool CurrentCityConfigNonNull;
	internal string CurrentCityDataType;
	internal string CurrentCityConfigType;
	internal LiveProbeTownLayerState Layers;
}

internal sealed class LiveProbeTownLayerState
{
	internal bool RootExists;
	internal bool RootActive;
	internal int RootObjectId;
	internal string RootPath;
	internal string RootScene;
	internal int ActiveLayerCount;
	internal int GraphicCount;
	internal int RawImageCount;
}

internal sealed class LiveProbeTownLayerRefreshResult
{
	internal bool Ok;
	internal string ErrorCode;
	internal string ErrorMessage;
	internal string OldFraction;
	internal bool OldCityDataNonNull;
	internal bool OldCityConfigNonNull;
	internal string WrapperType;
	internal string NewFraction;
	internal bool NewCityDataNonNull;
	internal bool NewCityConfigNonNull;
	internal LiveProbeTownLayerState LayersBefore;
	internal LiveProbeTownLayerState LayersAfter;
}
