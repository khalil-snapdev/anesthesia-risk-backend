from datetime import UTC, datetime

from app.models.embedded import ActorSnapshot, Alert, AlertSeverity, AlertType, RiskLevel
from app.services.alerts import generate_alerts, merge_alerts
from app.services.recommendations import generate_recommended_tests


class TestGenerateAlertsAnticoagulant:
    def test_warfarin_triggers_critical_anticoagulant_alert(self) -> None:
        alerts = generate_alerts(
            medications=["Warfarin 5mg daily"],
            allergy_notes="",
            stop_bang_score=0,
            mallampati_class=None,
            airway_history_notes="",
        )
        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.ANTICOAGULANT
        assert alerts[0].severity == AlertSeverity.CRITICAL

    def test_each_listed_anticoagulant_triggers(self) -> None:
        for drug in (
            "Warfarin",
            "Apixaban",
            "Rivaroxaban",
            "Dabigatran",
            "Edoxaban",
            "Clopidogrel",
        ):
            alerts = generate_alerts(
                medications=[drug],
                allergy_notes="",
                stop_bang_score=0,
                mallampati_class=None,
                airway_history_notes="",
            )
            assert any(a.alert_type == AlertType.ANTICOAGULANT for a in alerts), drug

    def test_multiple_anticoagulants_produce_single_alert(self) -> None:
        alerts = generate_alerts(
            medications=["Warfarin 5mg", "Clopidogrel 75mg"],
            allergy_notes="",
            stop_bang_score=0,
            mallampati_class=None,
            airway_history_notes="",
        )
        anticoagulant_alerts = [a for a in alerts if a.alert_type == AlertType.ANTICOAGULANT]
        assert len(anticoagulant_alerts) == 1
        assert "Warfarin" in anticoagulant_alerts[0].message
        assert "Clopidogrel" in anticoagulant_alerts[0].message

    def test_aspirin_only_does_not_trigger_anticoagulant_alert(self) -> None:
        alerts = generate_alerts(
            medications=["Aspirin 81mg"],
            allergy_notes="",
            stop_bang_score=0,
            mallampati_class=None,
            airway_history_notes="",
        )
        assert not any(a.alert_type == AlertType.ANTICOAGULANT for a in alerts)

    def test_no_medications_triggers_no_anticoagulant_alert(self) -> None:
        alerts = generate_alerts(
            medications=[],
            allergy_notes="",
            stop_bang_score=0,
            mallampati_class=None,
            airway_history_notes="",
        )
        assert not any(a.alert_type == AlertType.ANTICOAGULANT for a in alerts)


class TestGenerateAlertsSevereAllergy:
    def test_anaphylaxis_triggers_alert(self) -> None:
        alerts = generate_alerts(
            medications=[],
            allergy_notes="History of anaphylaxis to penicillin",
            stop_bang_score=0,
            mallampati_class=None,
            airway_history_notes="",
        )
        assert any(a.alert_type == AlertType.SEVERE_ALLERGY for a in alerts)

    def test_difficulty_breathing_triggers_alert(self) -> None:
        alerts = generate_alerts(
            medications=[],
            allergy_notes="Patient reported difficulty breathing after exposure",
            stop_bang_score=0,
            mallampati_class=None,
            airway_history_notes="",
        )
        assert any(a.alert_type == AlertType.SEVERE_ALLERGY for a in alerts)

    def test_throat_swelling_triggers_alert(self) -> None:
        alerts = generate_alerts(
            medications=[],
            allergy_notes="Throat swelling noted on prior reaction",
            stop_bang_score=0,
            mallampati_class=None,
            airway_history_notes="",
        )
        assert any(a.alert_type == AlertType.SEVERE_ALLERGY for a in alerts)

    def test_hospitalization_triggers_alert(self) -> None:
        alerts = generate_alerts(
            medications=[],
            allergy_notes="Required hospitalization after reaction",
            stop_bang_score=0,
            mallampati_class=None,
            airway_history_notes="",
        )
        assert any(a.alert_type == AlertType.SEVERE_ALLERGY for a in alerts)

    def test_severe_allergy_alert_is_critical(self) -> None:
        alerts = generate_alerts(
            medications=[],
            allergy_notes="anaphylaxis",
            stop_bang_score=0,
            mallampati_class=None,
            airway_history_notes="",
        )
        severe_allergy_alerts = [a for a in alerts if a.alert_type == AlertType.SEVERE_ALLERGY]
        assert severe_allergy_alerts[0].severity == AlertSeverity.CRITICAL

    def test_mild_reaction_does_not_trigger_alert(self) -> None:
        alerts = generate_alerts(
            medications=[],
            allergy_notes="Mild rash with penicillin",
            stop_bang_score=0,
            mallampati_class=None,
            airway_history_notes="",
        )
        assert not any(a.alert_type == AlertType.SEVERE_ALLERGY for a in alerts)

    def test_no_allergy_notes_triggers_no_alert(self) -> None:
        alerts = generate_alerts(
            medications=[],
            allergy_notes="",
            stop_bang_score=0,
            mallampati_class=None,
            airway_history_notes="",
        )
        assert not any(a.alert_type == AlertType.SEVERE_ALLERGY for a in alerts)


class TestGenerateAlertsOsa:
    def test_stop_bang_five_triggers_osa_alert(self) -> None:
        alerts = generate_alerts(
            medications=[],
            allergy_notes="",
            stop_bang_score=5,
            mallampati_class=None,
            airway_history_notes="",
        )
        assert any(a.alert_type == AlertType.OSA for a in alerts)

    def test_stop_bang_four_does_not_trigger_osa_alert(self) -> None:
        alerts = generate_alerts(
            medications=[],
            allergy_notes="",
            stop_bang_score=4,
            mallampati_class=None,
            airway_history_notes="",
        )
        assert not any(a.alert_type == AlertType.OSA for a in alerts)

    def test_osa_alert_is_critical(self) -> None:
        alerts = generate_alerts(
            medications=[],
            allergy_notes="",
            stop_bang_score=8,
            mallampati_class=None,
            airway_history_notes="",
        )
        osa_alerts = [a for a in alerts if a.alert_type == AlertType.OSA]
        assert osa_alerts[0].severity == AlertSeverity.CRITICAL


class TestGenerateAlertsAirwayConcern:
    def test_mallampati_three_triggers_airway_concern(self) -> None:
        alerts = generate_alerts(
            medications=[],
            allergy_notes="",
            stop_bang_score=0,
            mallampati_class=3,
            airway_history_notes="",
        )
        assert any(a.alert_type == AlertType.AIRWAY_CONCERN for a in alerts)

    def test_mallampati_four_triggers_airway_concern(self) -> None:
        alerts = generate_alerts(
            medications=[],
            allergy_notes="",
            stop_bang_score=0,
            mallampati_class=4,
            airway_history_notes="",
        )
        assert any(a.alert_type == AlertType.AIRWAY_CONCERN for a in alerts)

    def test_mallampati_two_does_not_trigger(self) -> None:
        alerts = generate_alerts(
            medications=[],
            allergy_notes="",
            stop_bang_score=0,
            mallampati_class=2,
            airway_history_notes="",
        )
        assert not any(a.alert_type == AlertType.AIRWAY_CONCERN for a in alerts)

    def test_mallampati_none_with_no_history_does_not_trigger(self) -> None:
        alerts = generate_alerts(
            medications=[],
            allergy_notes="",
            stop_bang_score=0,
            mallampati_class=None,
            airway_history_notes="",
        )
        assert not any(a.alert_type == AlertType.AIRWAY_CONCERN for a in alerts)

    def test_difficult_airway_history_triggers_even_without_mallampati(self) -> None:
        alerts = generate_alerts(
            medications=[],
            allergy_notes="",
            stop_bang_score=0,
            mallampati_class=None,
            airway_history_notes="Documented difficult airway in prior surgery",
        )
        assert any(a.alert_type == AlertType.AIRWAY_CONCERN for a in alerts)

    def test_airway_concern_alert_is_critical(self) -> None:
        alerts = generate_alerts(
            medications=[],
            allergy_notes="",
            stop_bang_score=0,
            mallampati_class=4,
            airway_history_notes="",
        )
        airway_alerts = [a for a in alerts if a.alert_type == AlertType.AIRWAY_CONCERN]
        assert airway_alerts[0].severity == AlertSeverity.CRITICAL


class TestGenerateAlertsCombinations:
    def test_no_triggers_returns_empty_list(self) -> None:
        alerts = generate_alerts(
            medications=["Aspirin"],
            allergy_notes="Mild rash",
            stop_bang_score=2,
            mallampati_class=2,
            airway_history_notes="No concerns noted",
        )
        assert alerts == []

    def test_all_triggers_fire_together(self) -> None:
        alerts = generate_alerts(
            medications=["Warfarin"],
            allergy_notes="History of anaphylaxis",
            stop_bang_score=6,
            mallampati_class=3,
            airway_history_notes="",
        )
        alert_types = {a.alert_type for a in alerts}
        assert alert_types == {
            AlertType.ANTICOAGULANT,
            AlertType.SEVERE_ALLERGY,
            AlertType.OSA,
            AlertType.AIRWAY_CONCERN,
        }
        assert len(alerts) == 4


class TestMergeAlerts:
    def test_no_existing_alerts_returns_new_alerts_as_is(self) -> None:
        new_alert = Alert(
            alert_type=AlertType.OSA,
            message="STOP-Bang score 6",
            severity=AlertSeverity.CRITICAL,
        )
        merged = merge_alerts([], [new_alert])
        assert merged == [new_alert]

    def test_alert_type_no_longer_triggered_is_dropped(self) -> None:
        stale_alert = Alert(
            alert_type=AlertType.OSA,
            message="STOP-Bang score 6",
            severity=AlertSeverity.CRITICAL,
        )
        merged = merge_alerts([stale_alert], [])
        assert merged == []

    def test_unacknowledged_existing_alert_is_replaced_by_new_one(self) -> None:
        old_alert = Alert(
            alert_type=AlertType.OSA,
            message="STOP-Bang score 5",
            severity=AlertSeverity.CRITICAL,
        )
        new_alert = Alert(
            alert_type=AlertType.OSA,
            message="STOP-Bang score 7",
            severity=AlertSeverity.CRITICAL,
        )
        merged = merge_alerts([old_alert], [new_alert])
        assert len(merged) == 1
        assert merged[0].id == new_alert.id
        assert merged[0].message == "STOP-Bang score 7"

    def test_acknowledged_alert_of_same_type_preserves_acknowledgment_and_updates_message(
        self,
    ) -> None:
        acknowledged_by = ActorSnapshot(user_id="user-1", full_name="Nora Nurse", role="nurse")
        acknowledged_at = datetime.now(UTC)
        old_alert = Alert(
            alert_type=AlertType.OSA,
            message="STOP-Bang score 6 — high risk of OSA",
            severity=AlertSeverity.CRITICAL,
            acknowledged=True,
            acknowledged_by=acknowledged_by,
            acknowledged_at=acknowledged_at,
        )
        new_alert = Alert(
            alert_type=AlertType.OSA,
            message="STOP-Bang score 7 — high risk of OSA",
            severity=AlertSeverity.CRITICAL,
        )

        merged = merge_alerts([old_alert], [new_alert])

        assert len(merged) == 1
        result = merged[0]
        assert result.id == old_alert.id
        assert result.acknowledged is True
        assert result.acknowledged_by == acknowledged_by
        assert result.acknowledged_at == acknowledged_at
        assert result.message == "STOP-Bang score 7 — high risk of OSA"

    def test_new_alert_type_is_added_fresh(self) -> None:
        existing_alert = Alert(
            alert_type=AlertType.OSA,
            message="STOP-Bang score 6",
            severity=AlertSeverity.CRITICAL,
            acknowledged=True,
            acknowledged_by=ActorSnapshot(user_id="user-1", full_name="Nora Nurse", role="nurse"),
            acknowledged_at=datetime.now(UTC),
        )
        new_airway_alert = Alert(
            alert_type=AlertType.AIRWAY_CONCERN,
            message="Mallampati class 4",
            severity=AlertSeverity.CRITICAL,
        )

        merged = merge_alerts([existing_alert], [existing_alert, new_airway_alert])

        assert len(merged) == 2
        merged_types = {a.alert_type for a in merged}
        assert merged_types == {AlertType.OSA, AlertType.AIRWAY_CONCERN}
        osa_alert = next(a for a in merged if a.alert_type == AlertType.OSA)
        assert osa_alert.acknowledged is True


class TestGenerateRecommendedTests:
    def _baseline_kwargs(self) -> dict[str, object]:
        return {
            "on_anticoagulant": False,
            "is_diabetic": False,
            "stop_bang_level": RiskLevel.LOW,
            "has_osa_diagnosis": False,
            "asa_level": RiskLevel.LOW,
            "rcri_level": RiskLevel.LOW,
            "rcri_score": 0,
            "is_pregnant": False,
        }

    def test_baseline_returns_no_tests(self) -> None:
        assert generate_recommended_tests(**self._baseline_kwargs()) == []  # type: ignore[arg-type]

    def test_on_anticoagulant_recommends_inr(self) -> None:
        kwargs = self._baseline_kwargs()
        kwargs["on_anticoagulant"] = True
        assert "INR" in generate_recommended_tests(**kwargs)  # type: ignore[arg-type]

    def test_diabetic_recommends_hba1c(self) -> None:
        kwargs = self._baseline_kwargs()
        kwargs["is_diabetic"] = True
        assert "HbA1c" in generate_recommended_tests(**kwargs)  # type: ignore[arg-type]

    def test_high_stop_bang_recommends_sleep_study(self) -> None:
        kwargs = self._baseline_kwargs()
        kwargs["stop_bang_level"] = RiskLevel.HIGH
        assert "Sleep Study" in generate_recommended_tests(**kwargs)  # type: ignore[arg-type]

    def test_existing_osa_diagnosis_recommends_sleep_study_even_if_stop_bang_low(self) -> None:
        kwargs = self._baseline_kwargs()
        kwargs["has_osa_diagnosis"] = True
        assert "Sleep Study" in generate_recommended_tests(**kwargs)  # type: ignore[arg-type]

    def test_moderate_stop_bang_does_not_recommend_sleep_study_alone(self) -> None:
        kwargs = self._baseline_kwargs()
        kwargs["stop_bang_level"] = RiskLevel.MODERATE
        assert "Sleep Study" not in generate_recommended_tests(**kwargs)  # type: ignore[arg-type]

    def test_asa_moderate_recommends_ekg(self) -> None:
        kwargs = self._baseline_kwargs()
        kwargs["asa_level"] = RiskLevel.MODERATE
        assert "EKG" in generate_recommended_tests(**kwargs)  # type: ignore[arg-type]

    def test_asa_high_recommends_ekg(self) -> None:
        kwargs = self._baseline_kwargs()
        kwargs["asa_level"] = RiskLevel.HIGH
        assert "EKG" in generate_recommended_tests(**kwargs)  # type: ignore[arg-type]

    def test_rcri_at_least_one_recommends_ekg(self) -> None:
        kwargs = self._baseline_kwargs()
        kwargs["rcri_level"] = RiskLevel.MODERATE
        kwargs["rcri_score"] = 1
        assert "EKG" in generate_recommended_tests(**kwargs)  # type: ignore[arg-type]

    def test_asa_low_and_rcri_low_does_not_recommend_ekg(self) -> None:
        assert "EKG" not in generate_recommended_tests(**self._baseline_kwargs())  # type: ignore[arg-type]

    def test_rcri_two_or_more_recommends_cbc_and_cmp(self) -> None:
        kwargs = self._baseline_kwargs()
        kwargs["rcri_level"] = RiskLevel.HIGH
        kwargs["rcri_score"] = 2
        tests = generate_recommended_tests(**kwargs)  # type: ignore[arg-type]
        assert "CBC" in tests
        assert "CMP" in tests

    def test_rcri_one_does_not_recommend_cbc_or_cmp(self) -> None:
        kwargs = self._baseline_kwargs()
        kwargs["rcri_level"] = RiskLevel.MODERATE
        kwargs["rcri_score"] = 1
        tests = generate_recommended_tests(**kwargs)  # type: ignore[arg-type]
        assert "CBC" not in tests
        assert "CMP" not in tests

    def test_pregnant_recommends_ob_clearance(self) -> None:
        kwargs = self._baseline_kwargs()
        kwargs["is_pregnant"] = True
        assert "OB clearance" in generate_recommended_tests(**kwargs)  # type: ignore[arg-type]

    def test_all_triggers_combine_without_duplicates(self) -> None:
        tests = generate_recommended_tests(
            on_anticoagulant=True,
            is_diabetic=True,
            stop_bang_level=RiskLevel.HIGH,
            has_osa_diagnosis=True,
            asa_level=RiskLevel.HIGH,
            rcri_level=RiskLevel.HIGH,
            rcri_score=3,
            is_pregnant=True,
        )
        assert tests == ["INR", "HbA1c", "Sleep Study", "EKG", "CBC", "CMP", "OB clearance"]
