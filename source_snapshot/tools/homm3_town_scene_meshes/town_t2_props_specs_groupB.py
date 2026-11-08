"""Group B towns' props-pass specs (2026-09-30) for town_t2_props_gen.py / town_t2_props.py / town_t2_anim_pass.py.

Loaded by town_t2_props_gen.py when TOWN_T2_PROPS_GROUP=B (budget: artifacts/meshy_town_scene_meshes/
_budget_props_20260930_groupB.json, cap 900). Towns: stronghold, fortress, cove, factory, bulwark. Conflux is on its
own full-3D lane (build_conflux_full3d_scene.py) and is not covered by these tools.

PROPS: town -> prop -> (crop of the HoMM3 town painting in frame px [x0, y0, x1, y1] (painted rect 1440x673 at x1.8),
painted height px, description). Each crop was chosen where the painting shows that object next to the surfaces
town_t2_streak_map.py flags at the sweep poses (candidate pb_v1 of each town, 2026-09-30).
RECIPES: town -> layer -> anim-pass recipe (none: every group B glow layer is left as staged).
"""

PROPS = {
    "stronghold": {
        # sweep streaks: the canyon ridge crests against the sky (left massif, the valley gap behind the castle, the
        # spiked right massif) -- badland spires and buttes of the painting's own banded red-brown rock
        "spire": ([1265, 10, 1375, 160], 150, "a tall pointed badlands rock spire of banded red-brown and tan "
                                               "sandstone, eroded vertical ridges, a sharp peak"),
        "butte": ([470, 130, 690, 290], 160, "a craggy eroded badlands ridge of layered red-brown and cream "
                                              "sandstone with deep vertical gullies"),
        "cones": ([1190, 380, 1300, 465], 80, "a cluster of pointed tan sandstone rock cones and hoodoos"),
    },
    "fortress": {
        # sweep streaks: the painted tree trunks and the misty background trees of the swamp forest
        "cypress": ([300, 0, 470, 540], 540, "a huge ancient swamp cypress tree with a thick mossy dark trunk, "
                                              "flared buttress roots and hanging green moss, a dark green crown, "
                                              "plain bark with no gem, sign or ornament on it"),
        "bgtree": ([790, 60, 890, 290], 230, "a tall slender misty swamp tree with a straight grey-brown trunk "
                                              "and a dark green leafy canopy"),
        "reeds": ([1080, 380, 1185, 465], 85, "a dense clump of tall green marsh reeds and cattails"),
        "fern": ([1165, 465, 1265, 555], 90, "a lush green tropical fern and broad-leaf swamp plant"),
    },
    "cove": {
        # sweep streaks: the mid-ground water edges, reeds and rocks and the cliff foot under the stilt houses
        "palm": ([418, 165, 515, 295], 130, "a tropical palm tree with a curved trunk and a crown of green fronds"),
        "reeds": ([985, 435, 1095, 510], 75, "a clump of tall green and brown marsh reeds and grass"),
        "agave": ([1225, 455, 1295, 530], 75, "a spiky green agave plant with long pointed leaves"),
        "crag": ([690, 325, 800, 430], 105, "a dark brown jagged coastal rock outcrop"),
    },
    "factory": {
        # sweep streaks: the canyon walls behind the elevator and the mesa edges of the mid ground
        "mesa": ([1150, 360, 1270, 450], 90, "a chunk of layered red-orange desert sandstone cliff with a flat top"),
        "joshua": ([228, 615, 300, 672], 57, "a small desert joshua tree with spiky green leaf clusters"),
        "scrub": ([945, 535, 1005, 595], 45, "a dry grey-green desert sagebrush shrub"),
    },
    "bulwark": {
        # sweep streaks: the snow slope by the rune stones / stair ruins and around the pyre and the market
        "boulder": ([400, 345, 500, 425], 75, "a mound of dark grey granite boulders capped with snow"),
        "ruin": ([805, 290, 905, 385], 90, "a short ruined grey stone wall and pillars dusted with snow"),
    },
}

RECIPES: dict = {}
