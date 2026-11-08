import unittest

from tools.homm3_meshy_frame_pose.build_mesh_repair_fleet_queue import build_queue


class MeshRepairFleetQueueTests(unittest.TestCase):
    def test_source_defined_membership_is_not_fabricated(self):
        queue, ledger, neutral = build_queue()
        self.assertEqual(queue["membership"]["importManifestCount"], 262)
        self.assertEqual(queue["membership"]["statedUserRosterCount"], 261)
        self.assertEqual(queue["membership"]["candidateRosterCount"], 262)
        self.assertEqual(queue["membership"]["status"], "needs_user_confirmation")
        self.assertIsNone(queue["membership"]["ambiguousImportOnlyIds"])
        self.assertIn("no authoritative 261-ID membership list", queue["membership"]["ambiguousImportOnlyIdsEvidence"])
        self.assertEqual(ledger["counts"]["excludedPilots"], 3)
        self.assertEqual(len(neutral["rows"]), 17)

    def test_exclusions_are_read_only_rows(self):
        queue, _, _ = build_queue()
        rows = {row["unitSid"]: row for row in queue["animationRoster"]}
        for sid in ("h3_archer", "h3_crossbowman", "h3_wood_elf"):
            self.assertTrue(rows[sid]["repair"]["excluded"])
            self.assertEqual(rows[sid]["repair"]["processingState"], "excluded_prior_pilot")

    def test_neutral_identity_audit_keeps_catalog_only_entries_separate(self):
        queue, _, neutral = build_queue()
        catalog = {row["unitSid"] for row in queue["catalogOnlyNeutral"]}
        self.assertEqual(len(catalog), 13)
        self.assertEqual(len(neutral["rows"]), 17)
        self.assertIn("h3_neutral_halfling", catalog)
        self.assertNotIn("h3_neutral_halfling", {row["unitSid"] for row in queue["animationRoster"]})

    def test_fleet_manifests_and_reviews_are_reflected_per_unit(self):
        queue, ledger, _ = build_queue()
        rows = {row["unitSid"]: row for row in queue["animationRoster"]}
        dwarf = rows["h3_dwarf"]["repair"]
        crusader = rows["h3_crusader"]["repair"]
        self.assertEqual(dwarf["processingState"], "candidate_reviewed")
        self.assertEqual(dwarf["animationEvidence"]["repairCandidateStatus"], "experimental_candidate")
        self.assertTrue(dwarf["animationEvidence"]["repairAnimationReel"].endswith("animation_reel.gif"))
        guardsman = rows["h3_guardsman"]["repair"]["animationEvidence"]
        swordsman = rows["h3_swordsman"]["repair"]["animationEvidence"]
        self.assertIn("biped-fit-v2-sidechain-fix", guardsman["repairReview"])
        self.assertIn("biped-fit-v2-sidechain-fix", swordsman["repairReview"])
        self.assertTrue(swordsman["repairDetailReel"].endswith("detail_reel.gif"))
        self.assertTrue(swordsman["repairBilateralAudit"].endswith("bilateral_audit.json"))
        marksman = rows["h3_marksman"]["repair"]
        self.assertEqual(marksman["processingState"], "candidate_reviewed")
        self.assertTrue(marksman["animationEvidence"]["repairDetailReel"].endswith("detail_reel.gif"))
        battle_mage = rows["h3_battle_mage"]["repair"]
        gremlin = rows["h3_gremlin"]["repair"]
        mage = rows["h3_mage"]["repair"]
        self.assertIn("biped-fit-v2-sidechain-fix", battle_mage["animationEvidence"]["repairReview"])
        self.assertIn("biped-fit-v2-sidechain-fix", gremlin["animationEvidence"]["repairReview"])
        self.assertIn("biped-fit-v2-sidechain-fix", mage["animationEvidence"]["repairReview"])
        self.assertEqual(battle_mage["processingState"], "candidate_reviewed")
        self.assertEqual(gremlin["processingState"], "rejected_needs_shared_adapter")
        self.assertEqual(mage["processingState"], "candidate_reviewed")
        justiciar = rows["h3_justiciar"]["repair"]
        self.assertIn("mounted-adapter-v1", justiciar["animationEvidence"]["repairReview"])
        self.assertEqual(justiciar["processingState"], "candidate_reviewed")
        cavalier = rows["h3_cavalier"]["repair"]
        black_knight = rows["h3_black_knight"]["repair"]
        self.assertIn("z-mounted-adapter-v1", cavalier["animationEvidence"]["repairReview"])
        self.assertIn("z-mounted-adapter-v1", black_knight["animationEvidence"]["repairReview"])
        self.assertEqual(cavalier["processingState"], "candidate_reviewed")
        self.assertEqual(black_knight["processingState"], "candidate_reviewed")
        griffin = rows["h3_griffin"]["repair"]
        royal_griffin = rows["h3_royal_griffin"]["repair"]
        self.assertIn("z-eagle-flyer-v1", griffin["animationEvidence"]["repairReview"])
        self.assertIn("z-eagle-flyer-v1", royal_griffin["animationEvidence"]["repairReview"])
        self.assertEqual(griffin["processingState"], "needs_geometry_work")
        self.assertEqual(royal_griffin["processingState"], "needs_geometry_work")
        basilisk = rows["h3_basilisk"]["repair"]
        fire_hound = rows["h3_fire_hound"]["repair"]
        self.assertIn("z-zoo-quadruped-v1", basilisk["animationEvidence"]["repairReview"])
        self.assertIn("z-zoo-quadruped-v1", fire_hound["animationEvidence"]["repairReview"])
        self.assertEqual(basilisk["processingState"], "candidate_reviewed")
        self.assertEqual(fire_hound["processingState"], "candidate_reviewed")
        self.assertEqual(crusader["processingState"], "rejected_needs_shared_adapter")
        self.assertEqual(crusader["animationEvidence"]["repairCandidateStatus"], "experimental_candidate")
        self.assertEqual(rows["h3_marksman"]["repair"]["processingState"], "candidate_reviewed")
        steel_golem = rows["h3_steel_golem"]["repair"]
        self.assertEqual(steel_golem["processingState"], "candidate_reviewed")
        self.assertTrue(steel_golem["animationEvidence"]["repairDetailReel"].endswith("detail_reel.gif"))
        self.assertTrue(steel_golem["animationEvidence"]["repairBilateralAudit"].endswith("bilateral_audit.json"))
        rot_zombie = rows["h3_rot_zombie"]["repair"]
        self.assertEqual(rot_zombie["processingState"], "candidate_reviewed")
        self.assertTrue(rot_zombie["animationEvidence"]["repairDetailReel"].endswith("detail_reel.gif"))
        magnetic_golem = rows["h3_magnetic_golem"]["repair"]
        self.assertEqual(magnetic_golem["processingState"], "candidate_reviewed")
        self.assertTrue(magnetic_golem["animationEvidence"]["repairBilateralAudit"].endswith("bilateral_audit.json"))
        minotaur = rows["h3_minotaur_taskmaster"]["repair"]
        self.assertEqual(minotaur["processingState"], "candidate_reviewed")
        self.assertTrue(minotaur["animationEvidence"]["repairDetailReel"].endswith("detail_reel.gif"))
        self.assertIn("zz-smartrig-standard-legfix-v1", minotaur["animationEvidence"]["repairReview"])
        horned_demon = rows["h3_horned_demon"]["repair"]
        self.assertEqual(horned_demon["processingState"], "needs_shared_adapter")
        self.assertIn("Could not find a Left UniRig arm chain", horned_demon["animationEvidence"]["repairCandidateError"])
        hell_hound = rows["h3_hell_hound"]["repair"]
        self.assertEqual(hell_hound["processingState"], "candidate_reviewed")
        self.assertTrue(hell_hound["animationEvidence"]["repairDetailReel"].endswith("detail_reel.gif"))
        unicorn = rows["h3_unicorn"]["repair"]
        self.assertEqual(unicorn["processingState"], "candidate_reviewed")
        self.assertTrue(unicorn["animationEvidence"]["repairBilateralAudit"].endswith("bilateral_audit.json"))
        cerberus = rows["h3_cerberus"]["repair"]
        self.assertEqual(cerberus["processingState"], "candidate_reviewed")
        self.assertTrue(cerberus["animationEvidence"]["repairDetailReel"].endswith("detail_reel.gif"))
        ayssid = rows["hota_cove_ayssid"]["repair"]
        self.assertEqual(ayssid["processingState"], "candidate_reviewed")
        self.assertTrue(ayssid["animationEvidence"]["repairBilateralAudit"].endswith("bilateral_audit.json"))
        mammoth = rows["h3_mammoth_upg_alt"]["repair"]
        self.assertEqual(mammoth["processingState"], "candidate_reviewed")
        self.assertTrue(mammoth["animationEvidence"]["repairDetailReel"].endswith("detail_reel.gif"))
        mountain_ram = rows["h3_mountain_ram_upg_alt"]["repair"]
        self.assertEqual(mountain_ram["processingState"], "candidate_reviewed")
        self.assertTrue(mountain_ram["animationEvidence"]["repairBilateralAudit"].endswith("bilateral_audit.json"))
        sandworm = rows["h3_sandworm_upg_alt"]["repair"]
        self.assertEqual(sandworm["processingState"], "needs_geometry_work")
        self.assertTrue(sandworm["animationEvidence"]["repairDetailReel"].endswith("detail_reel.gif"))
        pristine_unicorn = rows["h3_pristine_unicorn"]["repair"]
        self.assertEqual(pristine_unicorn["processingState"], "candidate_reviewed")
        self.assertIn("zz-zoo-quadruped-horse-v1", pristine_unicorn["animationEvidence"]["repairReview"])
        war_unicorn = rows["h3_war_unicorn"]["repair"]
        self.assertEqual(war_unicorn["processingState"], "candidate_reviewed")
        hydra = rows["h3_ruinous_hydra"]["repair"]
        self.assertEqual(hydra["processingState"], "needs_geometry_work")
        self.assertIn("zz-zoo-quadruped-dragon-v1", hydra["animationEvidence"]["repairReview"])
        damsel_fly = rows["h3_damsel_fly"]["repair"]
        self.assertEqual(damsel_fly["processingState"], "candidate_reviewed")
        phoenix = rows["h3_phoenix"]["repair"]
        self.assertEqual(phoenix["processingState"], "candidate_reviewed")
        serpent_fly = rows["h3_serpent_fly"]["repair"]
        self.assertEqual(serpent_fly["processingState"], "candidate_reviewed")
        haspid = rows["hota_cove_haspid"]["repair"]
        self.assertEqual(haspid["processingState"], "needs_geometry_work")
        sea_serpent = rows["hota_cove_sea_serpent"]["repair"]
        self.assertEqual(sea_serpent["processingState"], "needs_geometry_work")
        olgoi = rows["hota_factory_olgoi_khorkhoi"]["repair"]
        self.assertEqual(olgoi["processingState"], "needs_geometry_work")
        argali = rows["hota_bulwark_argali"]["repair"]
        self.assertEqual(argali["processingState"], "candidate_reviewed")
        bulwark_mammoth = rows["hota_bulwark_mammoth"]["repair"]
        self.assertEqual(bulwark_mammoth["processingState"], "candidate_reviewed")
        ghost_behemoth = rows["toa_ghost_behemoth"]["repair"]
        self.assertEqual(ghost_behemoth["processingState"], "candidate_reviewed")
        red_dragon = rows["h3_red_dragon"]["repair"]
        self.assertEqual(red_dragon["processingState"], "candidate_reviewed")
        sacred_phoenix = rows["h3_sacred_phoenix"]["repair"]
        self.assertEqual(sacred_phoenix["processingState"], "candidate_reviewed")
        manticore = rows["h3_manticore"]["repair"]
        self.assertEqual(manticore["processingState"], "needs_geometry_work")
        dragon_fly = rows["h3_dragon_fly"]["repair"]
        self.assertEqual(dragon_fly["processingState"], "needs_geometry_work")
        self.assertIn("zzzzzzzz-dragon-fly-meshy-source-skin-fit-review-v1", dragon_fly["animationEvidence"]["repairReview"])
        scorpicore = rows["h3_scorpicore"]["repair"]
        self.assertEqual(scorpicore["processingState"], "needs_geometry_work")
        self.assertIn("zz-eagle-flyer-v1", scorpicore["animationEvidence"]["repairReview"])
        silver_pegasus = rows["h3_silver_pegasus"]["repair"]
        self.assertEqual(silver_pegasus["processingState"], "needs_geometry_work")
        self.assertIn("zz-eagle-flyer-v1", silver_pegasus["animationEvidence"]["repairReview"])
        halcyon = rows["hota_cove_halcyon"]["repair"]
        self.assertEqual(halcyon["processingState"], "candidate_reviewed")
        self.assertIn("zz-eagle-flyer-v1", halcyon["animationEvidence"]["repairReview"])
        stormbird = rows["hota_cove_stormbird"]["repair"]
        self.assertEqual(stormbird["processingState"], "candidate_reviewed")
        self.assertIn("zz-eagle-flyer-v1", stormbird["animationEvidence"]["repairReview"])
        couatl = rows["hota_factory_couatl"]["repair"]
        self.assertEqual(couatl["processingState"], "needs_geometry_work")
        self.assertIn("zz-eagle-flyer-v1", couatl["animationEvidence"]["repairReview"])
        crimson_couatl = rows["hota_factory_crimson_couatl"]["repair"]
        self.assertEqual(crimson_couatl["processingState"], "needs_geometry_work")
        self.assertIn("zz-eagle-flyer-v1", crimson_couatl["animationEvidence"]["repairReview"])
        fargazer = rows["h3_fargazer"]["repair"]
        self.assertEqual(fargazer["processingState"], "needs_geometry_work")
        self.assertIn("zz-mixamo-person-v1", fargazer["animationEvidence"]["repairReview"])
        infernal_troglodyte = rows["h3_infernal_troglodyte"]["repair"]
        self.assertEqual(infernal_troglodyte["processingState"], "candidate_reviewed")
        self.assertIn("zz-mixamo-person-v1", infernal_troglodyte["animationEvidence"]["repairReview"])
        kobold = rows["hota_bulwark_kobold"]["repair"]
        self.assertEqual(kobold["processingState"], "candidate_reviewed")
        self.assertIn("zz-mixamo-person-v1", kobold["animationEvidence"]["repairReview"])
        frost_elemental = rows["h3_frost_elemental"]["repair"]
        self.assertEqual(frost_elemental["processingState"], "needs_geometry_work")
        self.assertIn("zz-mixamo-person-v1", frost_elemental["animationEvidence"]["repairReview"])
        ice_elemental = rows["h3_ice_elemental"]["repair"]
        self.assertEqual(ice_elemental["processingState"], "needs_geometry_work")
        self.assertIn("zz-mixamo-person-v1", ice_elemental["animationEvidence"]["repairReview"])
        magic_elemental = rows["h3_magic_elemental"]["repair"]
        self.assertEqual(magic_elemental["processingState"], "candidate_reviewed")
        self.assertIn("zz-mixamo-person-v1", magic_elemental["animationEvidence"]["repairReview"])
        water_elemental = rows["h3_water_elemental"]["repair"]
        self.assertEqual(water_elemental["processingState"], "needs_geometry_work")
        self.assertIn("zz-mixamo-person-v1", water_elemental["animationEvidence"]["repairReview"])
        nereid = rows["hota_cove_nereid"]["repair"]
        self.assertEqual(nereid["processingState"], "needs_geometry_work")
        self.assertIn("zz-mixamo-person-v1", nereid["animationEvidence"]["repairReview"])
        nix_praetorian = rows["hota_cove_nix_praetorian"]["repair"]
        self.assertEqual(nix_praetorian["processingState"], "candidate_reviewed")
        self.assertIn("zz-mixamo-person-v1", nix_praetorian["animationEvidence"]["repairReview"])
        nix_warrior = rows["hota_cove_nix_warrior"]["repair"]
        self.assertEqual(nix_warrior["processingState"], "candidate_reviewed")
        self.assertIn("zz-mixamo-person-v1", nix_warrior["animationEvidence"]["repairReview"])
        nymph = rows["hota_cove_nymph"]["repair"]
        self.assertEqual(nymph["processingState"], "candidate_reviewed")
        self.assertIn("zz-mixamo-person-v1", nymph["animationEvidence"]["repairReview"])
        oceanid = rows["hota_cove_oceanid"]["repair"]
        self.assertEqual(oceanid["processingState"], "candidate_reviewed")
        self.assertIn("zz-mixamo-person-v1", oceanid["animationEvidence"]["repairReview"])
        for unit in ("hota_cove_nereid", "hota_cove_nix_praetorian", "hota_cove_nix_warrior", "hota_cove_nymph", "hota_cove_oceanid"):
            review = rows[unit]["repair"]["animationEvidence"]["repairReview"]
            self.assertIn("mixamo-person-v1", review)
        corsair = rows["hota_cove_corsair"]["repair"]
        self.assertEqual(corsair["processingState"], "needs_source")
        self.assertIn("toes point along its hip-to-hip axis", corsair["animationEvidence"]["repairCandidateError"])
        self.assertGreaterEqual(ledger["counts"]["reviewedAnimationCandidates"], 6)
        self.assertEqual(rows["h3_champion"]["repair"]["processingState"], "candidate_reviewed")
        self.assertEqual(ledger["counts"]["reviewedAnimationCandidates"], 183)
        self.assertEqual(ledger["counts"]["reviewedAdapterEvidence"], 76)
        dread = rows["h3_dread_knight"]["repair"]
        self.assertEqual(dread["processingState"], "needs_geometry_work")
        self.assertIn(
            "mounted-authored-source-space-v1/review.json",
            dread["animationEvidence"]["repairReview"],
        )
        self.assertEqual(rows["h3_amalek"]["repair"]["processingState"], "candidate_reviewed")
        self.assertEqual(rows["h3_astral_elemental"]["repair"]["processingState"], "candidate_reviewed")
        self.assertEqual(rows["h3_black_knight"]["repair"]["processingState"], "candidate_reviewed")
        self.assertEqual(rows["h3_ancient_behemoth"]["repair"]["processingState"], "candidate_reviewed")
        self.assertEqual(
            rows["h3_ancient_behemoth"]["repair"]["animationEvidence"]["sharedAdapterEvidence"]["route"],
            "existing_zoo_quadruped",
        )
        self.assertEqual(rows["h3_black_dragon"]["repair"]["processingState"], "candidate_reviewed")
        self.assertEqual(rows["h3_couatl_upg_alt"]["repair"]["processingState"], "candidate_reviewed")
        self.assertEqual(rows["h3_dreadnought_upg_alt"]["repair"]["processingState"], "candidate_reviewed")
        self.assertEqual(rows["h3_diamond_dragon"]["repair"]["processingState"], "candidate_reviewed")
        self.assertEqual(rows["h3_firebird"]["repair"]["processingState"], "candidate_reviewed")
        self.assertEqual(rows["h3_ghost_dragon"]["repair"]["processingState"], "candidate_reviewed")
        self.assertEqual(rows["h3_giant_upg"]["repair"]["processingState"], "candidate_reviewed")
        self.assertEqual(rows["h3_gold_dragon"]["repair"]["processingState"], "candidate_reviewed")
        self.assertEqual(rows["h3_gold_pegasus"]["repair"]["processingState"], "rejected_needs_shared_adapter")
        self.assertEqual(rows["h3_greater_basilisk"]["repair"]["processingState"], "rejected_needs_shared_adapter")
        self.assertEqual(rows["h3_mechanic_upg_alt"]["identity"]["status"], "verified_correct")
        self.assertEqual(rows["h3_mechanic_upg_alt"]["repair"]["processingState"], "candidate_reviewed")
        self.assertEqual(rows["h3_paokai"]["repair"]["processingState"], "needs_geometry_work")
        self.assertIn("zzzzzz-paokai-wing-body-counterfactual-review-v1", rows["h3_paokai"]["repair"]["animationEvidence"]["repairReview"])
        self.assertTrue(
            rows["h3_paokai"]["repair"]["animationEvidence"]["repairDetailReel"].endswith(
                "h3_paokai_region_counterfactual/current_replay_4x_v2/detail_reel.gif"
            )
        )
        self.assertEqual(rows["h3_medusa"]["repair"]["processingState"], "needs_geometry_work")
        self.assertEqual(rows["h3_paokai"]["identity"]["status"], "verified_correct")
        self.assertEqual(rows["h3_pit_lord"]["repair"]["processingState"], "candidate_reviewed")
        self.assertEqual(rows["h3_shadow_dragon"]["repair"]["processingState"], "candidate_reviewed")
        self.assertEqual(
            rows["h3_dwarf_battlerager"]["repair"]["animationEvidence"]["repairReviewStatus"],
            "candidate_reviewed",
        )
        self.assertEqual(rows["h3_grand_elf"]["repair"]["processingState"], "candidate_reviewed")
        self.assertEqual(rows["h3_genie"]["repair"]["processingState"], "needs_source")
        self.assertEqual(rows["h3_efreet_sufi"]["repair"]["processingState"], "needs_shared_adapter")
        self.assertEqual(rows["h3_dwarf_battlerager"]["repair"]["processingState"], "needs_source")
        self.assertEqual(rows["h3_gremlin_upg"]["repair"]["processingState"], "needs_source")
        self.assertEqual(rows["h3_skeleton"]["repair"]["processingState"], "needs_geometry_work")
        for unit in ("h3_grand_elf", "h3_lich", "h3_ogre_mage"):
            self.assertEqual(rows[unit]["repair"]["processingState"], "candidate_reviewed")
            self.assertEqual(
                rows[unit]["repair"]["animationEvidence"]["repairReviewStatus"],
                "candidate_reviewed",
            )
        for unit in ("h3_dwarf_battlerager", "h3_genie", "h3_gremlin_upg"):
            self.assertIn(
                "toes point along its hip-to-hip axis",
                rows[unit]["repair"]["animationEvidence"]["repairCandidateError"],
            )
        satyr = rows["h3_satyr"]
        self.assertEqual(satyr["identity"]["status"], "unresolved_provenance")
        self.assertTrue(satyr["identity"]["sourceHashMatchesSelectedImage"])
        self.assertIn("semantic identity review", satyr["identity"]["evidence"])
        battle_griffin = rows["h3_battle_griffin"]
        self.assertEqual(battle_griffin["repair"]["processingState"], "rejected_needs_shared_adapter")
        self.assertEqual(
            battle_griffin["repair"]["animationEvidence"]["sharedAdapterEvidence"]["route"],
            "existing_eagle_flyer",
        )
        pegasus = rows["h3_pegasus"]
        self.assertEqual(pegasus["identity"]["status"], "verified_correct")
        self.assertEqual(pegasus["repair"]["processingState"], "needs_shared_adapter")
        wolf_raider = rows["h3_wolf_raider"]
        self.assertEqual(wolf_raider["repair"]["processingState"], "needs_geometry_work")
        self.assertIn("zzzz-wolf-raider-mounted-review-v1", wolf_raider["repair"]["animationEvidence"]["repairReview"])
        wolf_rider = rows["h3_wolf_rider"]
        self.assertEqual(wolf_rider["repair"]["processingState"], "needs_geometry_work")
        self.assertIn("zzzz-wolf-rider-identity-review-v1", wolf_rider["repair"]["animationEvidence"]["repairReview"])
        boar_rider = rows["toa_boar_rider"]
        self.assertEqual(boar_rider["repair"]["processingState"], "needs_source")
        self.assertIn("zzzz-boar-rider-source-blocker-v1", boar_rider["repair"]["animationEvidence"]["repairReview"])
        banshee = rows["h3_banshee"]
        self.assertEqual(banshee["repair"]["processingState"], "needs_source")
        self.assertIn(
            "zzzz-meshy-source-recovery-review-v1",
            banshee["repair"]["animationEvidence"]["repairReview"],
        )
        fury = rows["h3_fury"]
        self.assertEqual(fury["repair"]["processingState"], "needs_geometry_work")
        self.assertIn("zzzzzzz-fury-meshy-eagle-adapter-review-v1", fury["repair"]["animationEvidence"]["repairReview"])
        self.assertTrue(
            fury["repair"]["animationEvidence"]["repairDetailReel"].endswith(
                "diagnostics/h3_fury_eagle_full_replay_yaw90_8x/detail_reel.gif"
            )
        )
        armadillo = rows["hota_factory_armadillo"]
        self.assertEqual(armadillo["repair"]["processingState"], "needs_geometry_work")
        self.assertEqual(
            armadillo["repair"]["animationEvidence"]["sharedAdapterEvidence"]["route"],
            "existing_zoo_turtle_quadruped",
        )
        centaur = rows["h3_centaur"]
        centaur_captain = rows["h3_centaur_captain"]
        centaur_ranger = rows["h3_centaur_ranger"]
        dreadtaur = rows["h3_dreadtaur"]
        for row in (centaur, centaur_captain, centaur_ranger, dreadtaur):
            self.assertEqual(row["repair"]["processingState"], "candidate_reviewed")
            self.assertEqual(
                row["repair"]["animationEvidence"]["sharedAdapterEvidence"]["route"],
                "existing_centauroid_rider",
            )


if __name__ == "__main__":
    unittest.main()
