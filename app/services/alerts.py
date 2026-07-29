from app.models.embedded import Alert, AlertSeverity, AlertType

# Exact list per CLAUDE.md's Alert Trigger Rules — aspirin is deliberately
# absent, so aspirin-only medication lists never trigger this alert.
_ANTICOAGULANTS = (
    "warfarin",
    "apixaban",
    "rivaroxaban",
    "dabigatran",
    "edoxaban",
    "clopidogrel",
)

_SEVERE_ALLERGY_KEYWORDS = (
    "anaphylaxis",
    "difficulty breathing",
    "throat swelling",
    "hospitalization",
)

_DIFFICULT_AIRWAY_KEYWORD = "difficult airway"


def generate_alerts(
    medications: list[str],
    allergy_notes: str,
    stop_bang_score: int,
    mallampati_class: int | None,
    airway_history_notes: str,
) -> list[Alert]:
    """Construct Alert objects per CLAUDE.md's Alert Trigger Rules.

    Pure function: builds and returns Alert instances ready to attach to a
    Patient's `alerts` list — it never saves anything.
    """
    alerts: list[Alert] = []

    matched_anticoagulants = sorted(
        {
            drug.capitalize()
            for drug in _ANTICOAGULANTS
            for medication in medications
            if drug in medication.lower()
        }
    )
    if matched_anticoagulants:
        alerts.append(
            Alert(
                alert_type=AlertType.ANTICOAGULANT,
                message=(
                    "Patient is on anticoagulant medication: "
                    f"{', '.join(matched_anticoagulants)}"
                ),
                severity=AlertSeverity.CRITICAL,
            )
        )

    allergy_notes_lower = allergy_notes.lower()
    if any(keyword in allergy_notes_lower for keyword in _SEVERE_ALLERGY_KEYWORDS):
        alerts.append(
            Alert(
                alert_type=AlertType.SEVERE_ALLERGY,
                message=(
                    "Allergy history indicates a severe reaction (anaphylaxis, "
                    "difficulty breathing, throat swelling, or hospitalization)"
                ),
                severity=AlertSeverity.CRITICAL,
            )
        )

    if stop_bang_score >= 5:
        alerts.append(
            Alert(
                alert_type=AlertType.OSA,
                message=f"STOP-Bang score of {stop_bang_score} indicates high risk of OSA",
                severity=AlertSeverity.CRITICAL,
            )
        )

    if mallampati_class in (3, 4) or _DIFFICULT_AIRWAY_KEYWORD in airway_history_notes.lower():
        alerts.append(
            Alert(
                alert_type=AlertType.AIRWAY_CONCERN,
                message=("Airway concern: Mallampati class 3/4 or history of difficult airway"),
                severity=AlertSeverity.CRITICAL,
            )
        )

    return alerts


def merge_alerts(existing: list[Alert], newly_generated: list[Alert]) -> list[Alert]:
    """Merge freshly generated alerts with a patient's existing ones.

    Acknowledgment is an audit-trail record of a real action someone took —
    recalculating risk must not silently discard it. Alerts are matched by
    alert_type (not exact message, since wording can shift between
    calculations for the same underlying condition). For each newly
    generated alert: if an alert of the same type already exists and is
    acknowledged, keep its acknowledged/acknowledged_by/acknowledged_at but
    refresh the message text; otherwise use the new alert as-is. Alert
    types no longer triggered are dropped.
    """
    existing_by_type = {alert.alert_type: alert for alert in existing}
    merged: list[Alert] = []

    for new_alert in newly_generated:
        prior = existing_by_type.get(new_alert.alert_type)
        if prior is not None and prior.acknowledged:
            merged.append(prior.model_copy(update={"message": new_alert.message}))
        else:
            merged.append(new_alert)

    return merged
