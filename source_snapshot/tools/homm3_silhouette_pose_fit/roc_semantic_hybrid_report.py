# Optional source-owned pairwise semantic report.

# LOCAL_GPU_SEMANTIC_EMBEDDING_STAGE
from roc_semantic_embedding_match import RocSemanticEmbedder
SEMANTIC_MODEL_ID = 'google/siglip2-base-patch16-512'
SEMANTIC_MESH_DIR = PILOT / 'roc_chroma_match_v1'
SEMANTIC_OUT = PILOT / 'roc_chroma_match_v1' / 'semantic_embedding_report.json'
SEMANTIC_OUT.parent.mkdir(parents=True, exist_ok=True)
semantic_pairs = []
for target in sorted(ANIMATION_TARGET_FRAMES.glob('*.png')):
    mesh = SEMANTIC_MESH_DIR / f'frame_{target.stem}.png'
    if mesh.exists():
        semantic_pairs.append((target, mesh))
semantic_encoder = RocSemanticEmbedder(model_id=SEMANTIC_MODEL_ID)  # asserts CUDA
semantic_rows = semantic_encoder.compare_pairs(semantic_pairs, batch_size=1)
dense_rows = []
dense_enabled = bool(globals().get('SEMANTIC_DENSE_ENABLED', False))
if dense_enabled:
    dense_encoder = globals().get('dense_semantic_encoder')
    if dense_encoder is None:
        raise RuntimeError(
            'SEMANTIC_DENSE_ENABLED is set, but initialize() did not expose '
            'dense_semantic_encoder; refusing to create a mismatched report-time model'
        )

    def _dense_input(path):
        # DenseFeatureScorer owns model-specific processor normalization and
        # patch layout; this only shares the neutral RGB/crop policy.
        image = semantic_encoder.load_image(Path(path))
        if globals().get('SEMANTIC_SUBJECT_CROP', False):
            image = semantic_encoder.load_subject_image_from_image(
                image,
                float(globals().get('SEMANTIC_SUBJECT_PADDING_FRAC', 0.18)),
            )
        return image

    for target, mesh in semantic_pairs:
        target_grids = dense_encoder.extract_layers([_dense_input(target)])
        mesh_grids = dense_encoder.extract_layers([_dense_input(mesh)])
        distance, layer_distances = dense_encoder.score_grid_layers_mean(
            target_grids,
            mesh_grids,
            window_radius=int(globals().get('SEMANTIC_DENSE_LOCAL_RADIUS', 1)),
            position_weight=float(globals().get('SEMANTIC_DENSE_POSITION_WEIGHT', 0.15)),
        )
        dense_rows.append({
            'frame': target.stem,
            'target': str(target),
            'mesh': str(mesh),
            'distance': float(distance),
            'layerDistances': {str(layer): float(value) for layer, value in layer_distances.items()},
        })
dense_report = {
    'enabled': dense_enabled,
    'model': str(globals().get('SEMANTIC_DENSE_MODEL_ID') or SEMANTIC_MODEL_ID),
    'layers': [str(layer) for layer in globals().get('SEMANTIC_DENSE_EMBEDDING_LAYERS', ())],
    'rows': dense_rows,
    'meanDistance': float(np.mean([row['distance'] for row in dense_rows])) if dense_rows else None,
}
semantic_report = {
    'model': SEMANTIC_MODEL_ID,
    'device': str(semantic_encoder.device),
    'pairs': semantic_rows,
    'meanCosine': float(np.mean([row['cosine'] for row in semantic_rows])) if semantic_rows else None,
    'dense': dense_report,
    'proof': 'local GPU global semantic and optional dense patch-feature comparison; original frames only',
}
SEMANTIC_OUT.write_text(json.dumps(semantic_report, indent=2) + '\n')
print('semantic mean cosine:', semantic_report['meanCosine'], 'pairs:', len(semantic_rows), 'device:', semantic_report['device'])
if dense_enabled:
    print('dense mean distance:', dense_report['meanDistance'], 'model:', dense_report['model'])
